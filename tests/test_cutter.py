import hashlib
from datetime import datetime, timedelta

from conftest import TZ, make_audio

from jrec import cutter, mp3frames


def _src(path, start, name, sha):
    return cutter.Src(sha, "mp3", path, start, mp3frames.index(path).duration, name, "sony-tx660", {})


def test_split_files_are_stitched_and_window_spans_both_with_padding(tmp_path):
    t0 = datetime(2025, 10, 1, 9, 0, 0, tzinfo=TZ)
    a = make_audio(tmp_path / "a.mp3", 60)
    b = make_audio(tmp_path / "b.mp3", 60)
    ha, hb = (hashlib.sha256(p.read_bytes()).hexdigest() for p in (a, b))
    sa = _src(a, t0, "251001_0900.mp3", ha)
    sb = _src(b, t0 + timedelta(seconds=sa.duration + 1.0), "251001_0901.mp3", hb)
    other = _src(a, t0 + timedelta(hours=3), "251001_1200.mp3", "c" * 64)
    groups = cutter.streams([other, sb, sa])
    assert [[s.orig_path for s in g] for g in groups] == [["251001_0900.mp3", "251001_0901.mp3"], ["251001_1200.mp3"]]
    # speech 50-70 s in stream time crosses the file boundary; pad 20 s each side
    (m,) = cutter.cut_stream(groups[0], tmp_path / "out", pad=20, gap=5, min_speech=10, regions=[(50, 70)])
    assert len(m["parts"]) == 2 and len(m["seams"]) == 1
    p1, p2 = m["parts"]
    assert p1["t_start"] <= 30.0 and p1["t_end"] == sa.duration  # runs to the end of file a
    assert p2["t_start"] == 0.0 and p2["t_end"] >= 90.0 - sa.duration - 1.0
    # archive names in verify commands, and bytes match the originals
    archive = tmp_path / "arch"
    archive.mkdir()
    (archive / f"{ha}.mp3").write_bytes(a.read_bytes())
    (archive / f"{hb}.mp3").write_bytes(b.read_bytes())
    folder = tmp_path / "out" / m["conversation"]
    assert cutter.verify_folder(folder, archive) == []
    # tampering is detected
    clip = folder / "raw_01.mp3"
    data = bytearray(clip.read_bytes()); data[500] ^= 1; clip.write_bytes(bytes(data))
    assert any("hash changed" in p for p in cutter.verify_folder(folder, archive))


def test_padding_clamped_at_stream_start(tmp_path):
    t0 = datetime(2025, 10, 1, 9, 0, 0, tzinfo=TZ)
    a = make_audio(tmp_path / "a.mp3", 40)
    (m,) = cutter.cut_stream([_src(a, t0, "x.mp3", "d" * 64)], tmp_path / "o", pad=600, regions=[(5, 30)])
    assert m["parts"][0]["t_start"] == 0.0 and m["window"]["start"] == t0.isoformat()
