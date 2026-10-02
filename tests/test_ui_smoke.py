"""Headless UI smoke test. Opt-in: needs a private X display (never the user's desktop).
    JREC_UI_TEST_DISPLAY=:99 pytest tests/test_ui_smoke.py
(start one with jev-photos/scripts/test-display.sh; run scripts/fix-imgui-gl.sh once after install)"""
import os
import subprocess
import sys

import pytest

from jrec.cli import human_flag

DISPLAY = os.environ.get("JREC_UI_TEST_DISPLAY")


def test_human_flag():
    assert human_flag("timeline_gap:31489923s") == "timeline gap 364d"
    assert human_flag("mtime_tz_shift:+8h") == "mtime tz shift +8h"
    assert human_flag("minute_precision") == "minute precision"


@pytest.mark.skipif(not DISPLAY, reason="set JREC_UI_TEST_DISPLAY to a private X display")
def test_ui_renders_import_dialog(card, cfg, tmp_path):
    shot = tmp_path / "ui.png"
    env = dict(os.environ, DISPLAY=DISPLAY, __GLX_VENDOR_LIBRARY_NAME="mesa", LIBGL_ALWAYS_SOFTWARE="1")
    cfgfile = tmp_path / "config.toml"
    r = subprocess.run([sys.executable, "-m", "jrec.cli", "--config", str(cfgfile), "ui", "--ui-script",
                        f"importdlg:{card},wait:1,shot:{shot}"], env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    assert shot.stat().st_size > 10_000
