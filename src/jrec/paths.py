"""Per-OS locations: config (prefs, LLM overrides, task queue) and cache (logs).
Windows: %APPDATA%\\jrec, %LOCALAPPDATA%\\jrec ; Linux/BSD: $XDG_CONFIG_HOME/jrec, $XDG_CACHE_HOME/jrec ;
macOS: ~/Library/Application Support/jrec, ~/Library/Caches/jrec."""
import os
import sys
from pathlib import Path


def config_dir():
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "jrec"


def cache_dir():
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "jrec"
