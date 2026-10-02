"""CohereEngine routing and the [asr] config section, with fake models: no GPU."""
from types import SimpleNamespace as NS

import numpy as np

from jrec import config, transcribe


class FakeWorker:
    def __init__(self):
        self.calls = []

    def transcribe(self, pieces, iso):
        self.calls.append((len(pieces), iso))
        return [f"cohere-{iso}"] * len(pieces)


class FakeQwen:
    def __init__(self, langs):
        self.langs = langs

    def transcribe(self, audio, language=None):
        return [NS(text="qwen", language=(language or self.langs)[i]) for i in range(len(audio))]


def _engine(language, langs=None):
    e = transcribe.CohereEngine.__new__(transcribe.CohereEngine)
    e.language, e.worker, e._lid = language, FakeWorker(), FakeQwen(langs or [])
    return e


def test_auto_groups_by_detected_language_and_keeps_qwen_for_others():
    e = _engine("auto", ["English", "Malay", "Chinese,English", "English"])
    out = e.transcribe([np.zeros(10, np.float32)] * 4)
    assert [(r.text, r.language) for r in out] == [("cohere-en", "English"), ("qwen", "Malay"),
                                                  ("cohere-zh", "Chinese"), ("cohere-en", "English")]
    assert sorted(e.worker.calls) == [(1, "zh"), (2, "en")]


def test_fixed_language_skips_detection_and_forced_language_maps_to_iso():
    e = _engine("ja")
    assert [r.language for r in e.transcribe([np.zeros(10, np.float32)])] == ["Japanese"]
    assert e.transcribe([np.zeros(10, np.float32)], "Korean")[0].text == "cohere-ko"
    assert e.worker.calls == [(1, "ja"), (1, "ko")]


def test_asr_section_defaults_and_app_override(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('library = "%s"\n' % tmp_path)
    cfg = config.load(p)
    assert cfg.asr == {"engine": "qwen", "language": "auto"}
    cfg.save_section("asr", {"engine": "cohere"})
    assert config.load(p).asr["engine"] == "cohere"
