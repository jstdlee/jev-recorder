"""One window per library: a second launch brings the open window to the front, then exits.

Linux/macOS: a Unix socket in the cache folder; Windows: a named pipe. The address depends on the
library path, so the demo library and the real one can be open at the same time.
"""
import hashlib
import os
import sys
import threading
from multiprocessing.connection import Client, Listener

from ..paths import cache_dir

_KEY = b"jev-recorder"


def _address(library):
    h = hashlib.sha1(str(library).encode()).hexdigest()[:12]
    if sys.platform == "win32":
        return rf"\\.\pipe\jrec-{h}", "AF_PIPE"
    d = cache_dir()
    d.mkdir(parents=True, exist_ok=True)
    return str(d / f"ui-{h}.sock"), "AF_UNIX"


def claim(library, on_focus):
    """True if this process is the only window for `library` (and now listens for later launches).
    False if another window is open; it has been asked to come to the front."""
    addr, family = _address(library)
    try:
        with Client(addr, family=family, authkey=_KEY) as c:
            c.send("focus")
        return False
    except (FileNotFoundError, ConnectionRefusedError, OSError):
        pass
    if family == "AF_UNIX" and os.path.exists(addr):
        os.unlink(addr)                     # left over from a crash
    try:
        listener = Listener(addr, family=family, authkey=_KEY)
    except OSError:
        return True                         # cannot listen: still run, just without the single-window check

    def serve():
        while True:
            try:
                with listener.accept() as conn:
                    if conn.recv() == "focus":
                        on_focus()
            except Exception:
                continue
    threading.Thread(target=serve, daemon=True).start()
    return True
