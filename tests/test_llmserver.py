"""On-demand LLM server: cold boot when needed, stop when idle or before speech work."""
import pytest

from jrec import llmserver
from jrec.llm import LLMError


def _fake(monkeypatch, up_after=None):
    state = {"up": False, "calls": []}

    def reachable(profile, timeout=3):
        return state["up"]

    def run(cmd, log):
        state["calls"].append(cmd)
        state["up"] = cmd.startswith("start")
    monkeypatch.setattr(llmserver, "reachable", reachable)
    monkeypatch.setattr(llmserver, "_run", run)
    monkeypatch.setattr(llmserver.time, "sleep", lambda s: None)
    return state


PROF = {"base_url": "http://x/v1", "start_cmd": "start srv", "stop_cmd": "stop srv", "memory_gib": 1}


def test_cold_boot_then_stop(monkeypatch):
    st = _fake(monkeypatch)
    monkeypatch.setattr(llmserver, "available_gib", lambda: (50.0, 121.0))
    assert llmserver.ensure_up(PROF, log=lambda m: None) is True
    assert st["up"] and st["calls"] == ["start srv"]
    assert llmserver.ensure_up(PROF, log=lambda m: None) is False          # already up: no second start
    assert llmserver.ensure_down(PROF, log=lambda m: None) is True
    assert not st["up"] and st["calls"][-1] == "stop srv"


def test_not_enough_memory_refuses(monkeypatch):
    st = _fake(monkeypatch)
    monkeypatch.setattr(llmserver, "available_gib", lambda: (5.0, 121.0))
    with pytest.raises(LLMError, match="Not enough free memory"):
        llmserver.ensure_up({**PROF, "memory_gib": 88}, log=lambda m: None)
    assert st["calls"] == []


def test_unmanaged_server_is_never_started_or_stopped(monkeypatch):
    st = _fake(monkeypatch)
    plain = {"base_url": "http://x/v1"}
    with pytest.raises(LLMError, match="not found"):
        llmserver.ensure_up(plain, log=lambda m: None)
    st["up"] = True
    assert llmserver.ensure_down(plain, log=lambda m: None) is False
    assert st["calls"] == []


def test_ui_keeps_server_between_tasks(monkeypatch):
    st = _fake(monkeypatch)
    st["up"] = True
    monkeypatch.setenv("JREC_LLM_KEEP", "1")
    llmserver.after_task(PROF, started=True, log=lambda m: None)
    assert st["up"]                                                         # the UI's idle timer stops it
    monkeypatch.delenv("JREC_LLM_KEEP")
    llmserver.after_task(PROF, started=True, log=lambda m: None)
    assert not st["up"]
