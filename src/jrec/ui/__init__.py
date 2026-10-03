"""Desktop UI. `run(cfg, script)` opens the window."""
from .app import run  # noqa: F401
FOCUS_REQUESTS = []   # filled by the single-window listener (instance.py); the UI focuses itself
