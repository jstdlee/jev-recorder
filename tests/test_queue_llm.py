"""Task queue: the LLM cold boot starts when an LLM task is placed, never ahead of a transcription."""
import threading
import time
from types import SimpleNamespace as NS

from jrec import llmserver
from jrec.ui import tasks


def _queue(tmp_path, monkeypatch):
    boots = []

    def ensure_up(prof, log=print):
        boots.append(prof)
        return True
    monkeypatch.setattr(llmserver, "managed", lambda prof: True)
    monkeypatch.setattr(llmserver, "ensure_up", ensure_up)
    cfg = NS(db_path=tmp_path / "jrec.sqlite", analysis={"engine": "rules"},
             llm_profile=lambda name=None: {"base_url": "http://x/v1", "idle_stop": 0})
    q = tasks.TaskQueue(cfg, None)
    q._start = lambda t: setattr(t, "state", "running")      # no child processes in tests
    return q, boots


def _settle(q):
    for _ in range(100):
        if not q.llm_booting:
            return
        time.sleep(0.01)


def test_boot_starts_when_task_is_placed(tmp_path, monkeypatch):
    q, boots = _queue(tmp_path, monkeypatch)
    q.add(["summarize", "/x"], "Summarising 10:00", ["x"])
    _settle(q)
    assert len(boots) == 1 and q.llm_started


def test_no_boot_for_rules_analysis(tmp_path, monkeypatch):
    q, boots = _queue(tmp_path, monkeypatch)
    q.add(["analyze", "/x", "--engine", "rules"], "Analysing 10:00", ["x"])
    _settle(q)
    assert boots == []


def test_transcription_ahead_holds_the_boot(tmp_path, monkeypatch):
    q, boots = _queue(tmp_path, monkeypatch)
    q.add(["transcribe", "/a"], "Transcribing 09:00", ["a"])
    q.add(["translate", "/a", "--to", "English"], "Translating the transcript into English", ["a"])
    _settle(q)
    assert boots == []                                   # speech first: it needs the memory
    q.tasks[0].state = "done"                            # the transcription finished
    q.pump()
    _settle(q)
    assert len(boots) == 1
