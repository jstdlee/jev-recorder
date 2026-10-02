"""Notes, translation, chunking, LLM settings — and the evidence rule: none of it touches audio files."""
import hashlib
import json
from datetime import datetime

from conftest import TZ, make_audio
from test_search_summary import _Fake, _server

from jrec import config, cutter, db, mp3frames, summarize, translate


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_chunk_lines_overlap_and_size():
    lines = [f"[{i}] line {i} " + "x" * 30 for i in range(40)]
    chunks = summarize.chunk_lines(lines, 400, 120)
    assert all(sum(len(l) + 1 for l in c) <= 400 + 60 for c in chunks)
    for a, b in zip(chunks, chunks[1:]):
        assert b[0] in a and b[0] != a[0]            # the next chunk restarts inside the previous one
    assert set(sum(chunks, [])) == set(lines)        # nothing lost


def test_notes_crud(tmp_path):
    con = db.connect(tmp_path / "j.sqlite")
    nid = db.add_note(con, "f1", 12.5, "2025-10-01T09:00:12+08:00", "contractor promises roof fix")
    db.add_note(con, "f1", 3.0, "2025-10-01T09:00:03+08:00", "first")
    assert [n["text"] for n in db.notes(con, "f1")] == ["first", "contractor promises roof fix"]
    db.update_note(con, nid, "roof fix by Friday")
    assert db.notes(con, "f1")[1]["text"] == "roof fix by Friday"
    db.delete_note(con, nid)
    assert len(db.notes(con, "f1")) == 1


def test_llm_settings_saved_by_app_override_file(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(config.DEFAULT)
    cfg = config.load(p)
    cfg.save_llm("local", {"base_url": "http://127.0.0.1:9999/v1", "model": "qwen3.8", "chunk_chars": 128000})
    again = config.load(p)
    prof = again.llm_profile()
    assert prof["base_url"] == "http://127.0.0.1:9999/v1" and prof["chunk_chars"] == 128000
    assert "chunk_chars = 256000" in p.read_text()   # the TOML file itself is not rewritten


def _conv(tmp_path):
    t0 = datetime(2025, 10, 1, 9, 0, 0, tzinfo=TZ)
    a = make_audio(tmp_path / "a.mp3", 60)
    arch = tmp_path / "archive"; arch.mkdir()
    sha = _sha(a)
    (arch / f"{sha}.mp3").write_bytes(a.read_bytes())
    src = cutter.Src(sha, "mp3", arch / f"{sha}.mp3", t0, mp3frames.index(a).duration, "251001_0900.mp3", "x", {})
    (m,) = cutter.cut_stream([src], tmp_path / "conv", pad=10, gap=5, min_speech=5, regions=[(20, 40)])
    folder = tmp_path / "conv" / m["conversation"]
    segs = [{"start": 10 + i, "end": 11 + i, "abs_start": f"2025-10-01T09:00:{20 + i:02d}.000+08:00",
             "abs_end": f"2025-10-01T09:00:{21 + i:02d}.000+08:00", "speaker": "S1", "lang": "Chinese",
             "text": f"第{i}句话。", "words": []} for i in range(5)]
    (folder / "transcript.json").write_text(json.dumps({"segments": segs}, ensure_ascii=False))
    return folder, arch


def test_translate_batches_with_context_and_staleness(tmp_path):
    folder, _ = _conv(tmp_path)
    con = db.connect(tmp_path / "j.sqlite")

    def reply(body):
        user = body["messages"][1]["content"]
        idx = [int(x.split("]")[0]) for x in user.split("LINES:\n")[1].split("[")[1:]]
        return json.dumps({"t": [{"i": i, "text": f"Sentence {i}."} for i in idx]})
    _Fake.replies, _Fake.seen = reply, []
    srv = _server()
    prof = {"base_url": f"http://127.0.0.1:{srv.server_port}/v1", "model": "m", "translate_chars": 12}
    out = translate.translate_folder(folder, "English", prof, con)
    srv.shutdown()
    assert out == {i: f"Sentence {i}." for i in range(5)}
    assert len(_Fake.seen) >= 2 and "CONTEXT:" in _Fake.seen[1][1]["messages"][1]["content"]
    # re-transcribed row: its old translation is no longer returned
    segs = json.loads((folder / "transcript.json").read_text())["segments"]
    segs[2]["text"] = "改了。"
    assert 2 not in db.translations(con, folder.name, "English", segs)


def test_nothing_touches_the_evidence(tmp_path):
    folder, arch = _conv(tmp_path)
    con = db.connect(tmp_path / "j.sqlite")
    before = {p.name: _sha(p) for p in list(arch.iterdir()) + [x for x in folder.iterdir() if x.name.startswith("raw_")]}
    manifest_before = (folder / "manifest.json").read_bytes()
    good = json.dumps({"title": "t", "summary": "s", "key_points": [{"text": "k", "refs": [0]}], "action_items": [],
                       "people": [], "places": [], "language": "Chinese"})
    _Fake.replies = lambda body: good if "summarize" in body["messages"][0]["content"] else \
        json.dumps({"t": [{"i": i, "text": "x"} for i in range(5)]})
    srv = _server()
    prof = {"base_url": f"http://127.0.0.1:{srv.server_port}/v1", "model": "m"}
    summarize.summarize_folder(folder, prof, con)
    translate.translate_folder(folder, "English", prof, con)
    srv.shutdown()
    db.add_note(con, folder.name, 5.0, "2025-10-01T09:00:05+08:00", "note")
    db.set_speaker_name(con, folder.name, "S1", "Mum")
    after = {p.name: _sha(p) for p in list(arch.iterdir()) + [x for x in folder.iterdir() if x.name.startswith("raw_")]}
    assert before == after and (folder / "manifest.json").read_bytes() == manifest_before
    assert cutter.verify_folder(folder, arch) == []
    assert db.get_summary(con, folder.name)["title"] == "t"


def test_export_excerpt_is_byte_exact_and_library_untouched(tmp_path):
    from jrec import export
    folder, arch = _conv(tmp_path)
    m = json.loads((folder / "manifest.json").read_text())
    before = {p.name: _sha(p) for p in list(arch.iterdir()) + list(folder.iterdir()) if p.is_file()}
    out = export.export_range(m, arch, tmp_path / "exports", 5.0, 12.0, "promise")
    em = json.loads((out / "manifest.json").read_text())
    (p,) = em["parts"]
    data = (arch / f"{p['source_sha256']}.mp3").read_bytes()
    assert (out / p["file"]).read_bytes() == data[p["byte_start"]:p["byte_end"]]
    assert em["kind"] == "excerpt" and em["label"] == "promise"
    after = {p.name: _sha(p) for p in list(arch.iterdir()) + list(folder.iterdir()) if p.is_file()}
    assert before == after


def test_speaker_names_row_override_people_and_moments(tmp_path):
    con = db.connect(tmp_path / "j.sqlite")
    db.set_speaker_name(con, "f1", "S1", "Mum")
    db.set_row_speaker(con, "f1", 4, "Dad")          # only row 4
    db.set_speaker_name(con, "f2", "S2", "Mum")
    assert db.row_speakers(con, "f1") == {4: "Dad"}
    assert db.people(con) == {"Mum": {"f1": 1, "f2": 1}, "Dad": {"f1": 1}}
    db.set_row_speaker(con, "f1", 4, "")             # empty = back to the voice's name
    assert db.row_speakers(con, "f1") == {}
    mid = db.add_moment(con, "f1", 10.0, 20.0, "2025-10-01T09:00:10+08:00", "2025-10-01T09:00:20+08:00", "roof")
    assert [m["label"] for m in db.moments(con)] == ["roof"]
    db.delete_moment(con, mid)
    assert db.moments(con, "f1") == []
