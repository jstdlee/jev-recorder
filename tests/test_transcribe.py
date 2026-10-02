"""transcribe_folder with a fake ASR engine and diarizer: no models, no GPU."""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace as NS

from conftest import TZ, make_audio

from jrec import cutter, mp3frames, transcribe


class FakeEngine:
    """Every chunk says the same sentence; chunk k's language comes from `langs`."""
    def __init__(self, langs):
        self.langs, self.calls = langs, []

    def transcribe(self, pieces, language=None):
        self.calls.append((len(pieces), language))
        out = []
        for _ in pieces:
            lg = language or self.langs[len(out) % len(self.langs)]
            out.append(NS(text="Selamat pagi, semua." if lg == "Malay" else "Hello there, team.", language=lg))
        return out

    def align_qwen(self, pieces, texts, langs):
        return [[NS(text=w, start_time=1.0 + k, end_time=1.5 + k) for k, w in enumerate(t.replace(",", "").rstrip(".").split())]
                for t in texts]

    def align_mms(self, piece, text, lang):
        return [(w, 2.0 + k, 2.4 + k) for k, w in enumerate(text.replace(",", "").rstrip(".").split())]


def _conversation(tmp_path, seconds=90):
    t0 = datetime(2025, 10, 1, 9, 0, 0, tzinfo=TZ)
    a = make_audio(tmp_path / "a.mp3", seconds)
    src = cutter.Src("e" * 64, "mp3", a, t0, mp3frames.index(a).duration, "251001_0900.mp3", "sony-tx660", {})
    (m,) = cutter.cut_stream([src], tmp_path / "out", pad=20, gap=5, min_speech=5, regions=[(30, 60)])
    return tmp_path / "out" / m["conversation"], t0


def test_dominant_language_is_forced_and_outputs_written(tmp_path):
    folder, t0 = _conversation(tmp_path)
    eng = FakeEngine(["English"])
    diar = lambda audio: [{"start": 0, "end": 1000, "speaker": "S1"}]
    segs = transcribe.transcribe_folder(folder, eng, diarizer=diar, log=lambda *a: None)
    assert eng.calls[1][1] == "English"  # second pass forced
    assert segs and all(s["speaker"] == "S1" for s in segs)
    assert segs[0]["text"].startswith("Hello there, team.")  # punctuation kept from ASR text
    # absolute time = window start + clip offset
    w0 = datetime.fromisoformat(json.loads((folder / "manifest.json").read_text())["window"]["start"])
    first = json.loads((folder / "transcript.json").read_text())["chunks"][0]
    got = (datetime.fromisoformat(segs[0]["abs_start"]) - w0).total_seconds()
    assert abs(got - (first[0] + 1.0)) < 0.002  # ISO output has ms resolution
    for name in ("transcript.json", "transcript.srt", "transcript.vtt", "transcript.md", "labels.txt"):
        assert (folder / name).stat().st_size > 0
    assert "[S1] Hello there, team." in (folder / "transcript.srt").read_text()


def test_mixed_languages_are_not_forced_and_malay_uses_mms(tmp_path):
    folder, _ = _conversation(tmp_path)
    eng = FakeEngine(["English", "Malay"])
    segs = transcribe.transcribe_folder(folder, eng, use_diarization=False, log=lambda *a: None)
    assert all(lang is None for _, lang in eng.calls)
    langs = {s["lang"] for s in segs}
    assert langs == {"English", "Malay"}
    malay = next(s for s in segs if s["lang"] == "Malay")
    assert malay["text"] == "Selamat pagi, semua." and malay["speaker"] is None
    meta = json.loads((folder / "transcript.json").read_text())
    assert meta["language"] is None and meta["language_counts"] == {"English": 2, "Malay": 1} or meta["language_counts"]


def test_pick_chunks_covers_speech_span_and_skips_silent_padding():
    cs = transcribe.pick_chunks([(600, 650), (700, 760)], 1960, 600, 760)
    assert cs[0][0] < 600 + 1 and cs[-1][1] >= 760
    assert all(b - a <= 30 for a, b in cs)
    assert all(b > 599 and a < 761 for a, b in cs)  # no chunks in the silent 10 min pads


def test_listen_track_is_separate_and_manifest_untouched(tmp_path):
    import pytest
    from jrec import enhance
    if enhance.deep_filter_bin() is None:
        pytest.skip("deep-filter binary not installed")
    folder, _ = _conversation(tmp_path, seconds=40)
    before = (folder / "manifest.json").read_bytes()
    out = enhance.make_listen_track(folder)
    assert out.stat().st_size > 0 and (folder / "manifest.json").read_bytes() == before
    info = json.loads((folder / "listen.json").read_text())
    assert info["from_parts"] == ["raw_01.mp3"] and "listening only" in info["purpose"]
