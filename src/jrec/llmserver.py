"""The LLM server on demand (cold boot): start it only when a task needs it, free its memory afterwards.

Configure in the LLM profile (Settings › Summaries and translation, or config.toml):

  [llm.profiles.local]
  start_cmd = "docker start qwen38-flash-next-tf"   # how to start the server
  stop_cmd  = "docker stop qwen38-flash-next-tf"    # how to stop it
  memory_gib = 88          # what it needs, for the memory check before a start
  idle_stop = 120          # seconds without LLM work before the app stops it (0 = right after the task)

With no start_cmd the server is not managed: the app only uses it when it is already running.

Speech work (transcribe, process, enhance) needs the GPU memory, so it stops a managed server first;
the next summary or translation starts it again (a cold boot takes about 2–4 minutes).
"""
import os
import shlex
import subprocess
import time

from .llm import LLMError, reachable

MAX_USE = 0.80          # never plan a start that pushes unified memory above 80 %


def managed(profile):
    return bool(profile.get("start_cmd") and profile.get("stop_cmd"))


def available_gib():
    """MemAvailable from /proc/meminfo (Linux; GB10 memory is shared by CPU and GPU)."""
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            info = {line.split(":")[0]: int(line.split()[1]) for line in f}
        return info["MemAvailable"] / 2**20, info["MemTotal"] / 2**20
    except (OSError, KeyError, ValueError):
        return None, None


def _run(cmd, log):
    log(f"  $ {cmd}")
    r = subprocess.run(cmd if os.name == "nt" else shlex.split(cmd), shell=os.name == "nt",
                       capture_output=True, text=True, timeout=300)
    if r.returncode:
        raise LLMError(f"Command failed ({r.returncode}): {cmd}\n{(r.stderr or r.stdout).strip()[:300]}")


def ensure_up(profile, log=print):
    """Make sure the server answers. Returns True if this call started it."""
    if reachable(profile, timeout=3):
        return False
    if not managed(profile):
        raise LLMError(f"LLM server not found at {profile['base_url']}. Start it, or set a start command "
                       "in Settings › Summaries and translation so the app can start it when needed.")
    need = float(profile.get("memory_gib", 0) or 0)
    avail, total = available_gib()
    if need and avail is not None:
        log(f"  LLM server needs ~{need:.0f} GiB; {avail:.0f} of {total:.0f} GiB available now")
        if need > avail:
            raise LLMError(f"Not enough free memory to start the LLM server: it needs ~{need:.0f} GiB and "
                           f"{avail:.0f} GiB are free. Close other models or apps and try again.")
    log("Starting LLM server (cold boot, about 2–4 minutes)")
    _run(profile["start_cmd"], log)
    t0, timeout = time.monotonic(), float(profile.get("start_timeout", 900))
    while time.monotonic() - t0 < timeout:
        if reachable(profile, timeout=3):
            log(f"  LLM server ready after {time.monotonic() - t0:.0f} s")
            return True
        time.sleep(3)
    raise LLMError(f"The LLM server did not answer within {timeout:.0f} s after: {profile['start_cmd']}")


def ensure_down(profile, log=print, reason="to free memory"):
    """Stop a managed server if it runs. Returns True if it was stopped."""
    if not managed(profile) or not reachable(profile, timeout=2):
        return False
    log(f"Stopping LLM server {reason}")
    _run(profile["stop_cmd"], log)
    for _ in range(60):
        if not reachable(profile, timeout=2):
            break
        time.sleep(1)
    time.sleep(3)                         # let the driver release the memory
    return True


def keep_running():
    """True when a UI task queue owns the idle timer (then the CLI child leaves the server up)."""
    return os.environ.get("JREC_LLM_KEEP") == "1"


def after_task(profile, started, log=print):
    """CLI: stop the server we started, unless the UI keeps it for the next task."""
    if started and not keep_running():
        ensure_down(profile, log, "(task done)")
