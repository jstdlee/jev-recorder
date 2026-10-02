"""Task queue: every long job (transcribe, summarize, translate, analyze, cleaned copy) is a Task.

One task runs at a time (GPU and thermal rule); the rest wait in order. Each task is a `jrec`
child process in its own process group, printing PROGRESS lines that drive its progress bar.

States: queued -> running -> (paused) -> done | failed | canceled | stopped
  Pause / Resume  only for resumable tasks ("process" picks up the conversations still to do)
  Stop            end it now; finished conversations are kept, the current one stays as it was
  Cancel          drop a waiting task, or end a running one and mark it canceled
  Retry           run a failed, canceled or stopped task again
The queue is saved to tasks.json next to the library database; after a restart, resumable tasks
come back paused, others that were running come back failed with Retry.
"""
import json
import os
import shlex
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

STAGE_WEIGHT = {"asr": (0.0, 0.8), "align": (0.8, 0.1), "speakers": (0.9, 0.1), "summary": (0.0, 1.0),
                "translate": (0.0, 1.0)}
RESUMABLE = {"process"}
ACTIVE = ("queued", "running", "paused")
FINISHED = ("done", "failed", "canceled", "stopped")


def kill_tree(proc, hard=False):
    """End a child and everything it started (Linux/macOS: its process group; Windows: taskkill /T)."""
    if proc is None or proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T"] + (["/F"] if hard else []),
                           capture_output=True, timeout=10)
        else:
            import signal
            os.killpg(proc.pid, signal.SIGKILL if hard else signal.SIGTERM)
    except (ProcessLookupError, OSError, subprocess.SubprocessError):
        pass


class Task:
    _ids = iter(range(1, 1 << 30))

    def __init__(self, args, label, files=None, state="queued", tid=None, **kw):
        self.id = tid or f"t{int(time.time() * 1000)}{next(Task._ids)}"
        self.args, self.label, self.files = list(args), label, list(files or [])
        self.state = state
        self.resumable = args[:1] and args[0] in RESUMABLE
        self.log = kw.get("log", [])
        self.error = kw.get("error", "")
        self.created = kw.get("created") or datetime.now().isoformat(timespec="seconds")
        self.t0 = self.t1 = 0.0
        self.exit = None
        self.proc = None
        self.file = None      # (i, n, name) from PROGRESS file lines
        self.step = None      # (stage, done, total) from PROGRESS step lines
        self.wanted = None    # what the user asked for while running: paused / stopped / canceled

    # ---------------------------------------------------------- progress
    def file_frac(self):
        stage, d, t = self.step or ("", 0, 1)
        a, w = STAGE_WEIGHT.get(stage, (0.0, 0.0))
        return a + w * (d / max(1, t))

    def progress(self):
        """0..1, or None when the total is not known yet (models loading)."""
        if self.state == "done":
            return 1.0
        if self.state != "running":
            return 0.0 if not self.file else self._frac()
        if not self.file or self.file[2] == "loading-models":
            return None
        return self._frac()

    def _frac(self):
        i, n, _ = self.file
        return ((i - 1) + self.file_frac()) / max(1, n)

    def stage_label(self, T):
        stage, d, t = self.step or ("", 0, 1)
        return {"asr": T("Speech to text  ·  part {d} of {t}", d=d, t=t), "align": T("Word timings"),
                "speakers": T("Who spoke when"), "summary": T("Summarising  ·  part {d} of {t}", d=d + 1, t=t),
                "translate": T("Translating  ·  {d} of {t} rows", d=d, t=t)}.get(stage, T("Preparing"))

    def elapsed(self):
        if not self.t0:
            return 0.0
        return (self.t1 or time.monotonic()) - self.t0

    def eta(self):
        p = self.progress()
        if self.state != "running" or not p or p < 0.02:
            return None
        return self.elapsed() * (1 - p) / p

    def to_json(self):
        return {"id": self.id, "args": self.args, "label": self.label, "files": self.files, "state": self.state,
                "log": self.log[-80:], "error": self.error, "created": self.created}


class TaskQueue:
    def __init__(self, cfg, cfg_path, on_finish=None, on_log=None):
        self.cfg, self.cfg_path = cfg, cfg_path
        self.on_finish = on_finish or (lambda t: None)
        self.on_log = on_log or (lambda level, msg: None)
        self.tasks = []
        self.lock = threading.Lock()
        self.path = Path(cfg.db_path).parent / "tasks.json"
        self.paused_all = False
        self.closing = False
        self._load()

    # ---------------------------------------------------------- persistence
    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for d in data.get("tasks", []):
            t = Task(d["args"], d["label"], d.get("files"), d.get("state", "failed"), d.get("id"),
                     log=d.get("log", []), error=d.get("error", ""), created=d.get("created"))
            if t.state == "running":
                if t.resumable:
                    t.state = "paused"
                else:
                    t.state, t.error = "failed", "The app closed while this was running"
            self.tasks.append(t)

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            keep = [t for t in self.tasks if t.state in ACTIVE] + [t for t in self.tasks if t.state in FINISHED][-30:]
            self.path.write_text(json.dumps({"tasks": [t.to_json() for t in keep]}, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass

    # ---------------------------------------------------------- queries
    @property
    def running(self):
        return next((t for t in self.tasks if t.state == "running"), None)

    def active(self):
        return [t for t in self.tasks if t.state in ACTIVE]

    def last(self):
        return self.running or (self.tasks[-1] if self.tasks else None)

    def overall(self):
        """(fraction 0..1 weighted by files, done count, total count) over the active batch."""
        batch = [t for t in self.tasks if t.state in ACTIVE] + \
                [t for t in self.tasks if t.state == "done" and t.t1 and time.monotonic() - t.t1 < 30]
        if not batch:
            return 1.0, 0, 0
        weights = [max(1, len(t.files)) for t in batch]
        frac = sum(w * (t.progress() or 0.0) for w, t in zip(weights, batch)) / sum(weights)
        return frac, sum(t.state == "done" for t in batch), len(batch)

    def eta(self):
        t = self.running
        e = t.eta() if t else None
        return e

    # ---------------------------------------------------------- actions
    def add(self, args, label, files=None):
        """Queue a job; the same job already waiting or running is not added twice."""
        for t in self.tasks:
            if t.args == list(args) and t.state in ("queued", "running"):
                return t
        t = Task(args, label, files)
        self.tasks.append(t)
        self.on_log("info", f"Queued: {label}")
        self.save()
        return t

    def pump(self):
        """Call every frame: start the next waiting task when nothing runs."""
        if self.running or self.paused_all:
            return
        t = next((t for t in self.tasks if t.state == "queued"), None)
        if t:
            self._start(t)

    def _start(self, t):
        cmd = [sys.executable, "-m", "jrec.cli"] + (["--config", str(self.cfg_path)] if self.cfg_path else []) + t.args
        kw = {"start_new_session": True} if sys.platform != "win32" else \
            {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        try:
            t.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                      encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL, close_fds=True,
                                      cwd=str(Path.home()), env={**os.environ, "PYTHONIOENCODING": "utf-8"}, **kw)
        except OSError as e:
            t.state, t.error = "failed", str(e)
            self.on_log("error", f"{t.label}: {e}")
            self.save()
            return
        t.state, t.t0, t.t1, t.exit, t.wanted, t.error = "running", time.monotonic(), 0.0, None, None, ""
        t.file = t.step = None
        t.log = [f"$ jrec {shlex.join(t.args)}"]
        self.on_log("info", f"Started: {t.label}")
        self.save()
        threading.Thread(target=self._pump_log, args=(t,), daemon=True).start()

    def _pump_log(self, t):
        for line in t.proc.stdout:
            if line.startswith("PROGRESS "):
                f = line.split()
                try:
                    if f[1] == "file":
                        t.file, t.step = (int(f[2]), int(f[3]), " ".join(f[4:])), None
                        name = " ".join(f[4:])
                        if name != "loading-models" and name not in t.files:
                            t.files.append(name)
                    elif f[1] == "step":
                        t.step = (f[2], int(f[3]), int(f[4]))
                except (IndexError, ValueError):
                    pass
                continue
            low = line.lower()
            if "it/s]" in low or "loading" in low:
                continue
            t.log.append(line.rstrip())
            t.log = t.log[-300:]
            if "error" in low or "traceback" in low:
                self.on_log("error", f"{t.label}: {line.strip()}")
            elif "warn" in low:
                self.on_log("warning", f"{t.label}: {line.strip()}")
        t.exit = t.proc.wait()
        t.t1 = time.monotonic()
        if self.closing:          # saved as running: comes back paused (resumable) or failed
            return
        if t.wanted:
            t.state = t.wanted
            t.log.append({"paused": "paused; Resume continues with what is left",
                          "stopped": "stopped; finished conversations are kept, the current one is unchanged",
                          "canceled": "canceled"}[t.wanted])
            self.on_log("info", f"{t.wanted.capitalize()}: {t.label}")
        elif t.exit:
            t.state = "failed"
            t.error = next((ln for ln in reversed(t.log) if ln.strip()), f"exit {t.exit}")
            self.on_log("error", f"Failed: {t.label} ({t.error})")
        else:
            t.state = "done"
            self.on_log("info", f"Done: {t.label}")
        self.save()
        self.on_finish(t)

    def _end(self, t, state):
        if t.state == "running":
            t.wanted = state
            kill_tree(t.proc)

            def reap(p=t.proc):
                try:
                    p.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    kill_tree(p, hard=True)
            threading.Thread(target=reap, daemon=True).start()
        elif t.state in ("queued", "paused"):
            t.state = state if state != "paused" else "paused"
            self.save()

    def pause(self, t):
        if t.resumable and t.state in ("running", "queued"):
            self._end(t, "paused")

    def resume(self, t):
        if t.state == "paused":
            t.state = "queued"
            self.save()

    def stop(self, t):
        if t.state == "running":
            self._end(t, "stopped")

    def cancel(self, t):
        if t.state in ACTIVE:
            self._end(t, "canceled")

    def retry(self, t):
        if t.state in ("failed", "canceled", "stopped"):
            t.state, t.error = "queued", ""
            self.tasks.remove(t)
            self.tasks.append(t)
            self.save()

    def remove(self, t):
        if t.state not in ("running",):
            self.tasks.remove(t)
            self.save()

    def move(self, t, d):
        q = [x for x in self.tasks if x.state == "queued"]
        if t not in q:
            return
        k = q.index(t) + d
        if 0 <= k < len(q):
            i, j = self.tasks.index(t), self.tasks.index(q[k])
            self.tasks[i], self.tasks[j] = self.tasks[j], self.tasks[i]
            self.save()

    def pause_all(self):
        self.paused_all = True
        for t in list(self.tasks):
            if t.resumable and t.state in ("running", "queued"):
                self.pause(t)

    def resume_all(self):
        self.paused_all = False
        for t in self.tasks:
            if t.state == "paused":
                t.state = "queued"
        self.save()

    def cancel_all(self):
        for t in list(self.tasks):
            self.cancel(t)

    def clear_done(self):
        self.tasks = [t for t in self.tasks if t.state not in FINISHED]
        self.save()

    def shutdown(self):
        """App closing: end the running child (it comes back paused or failed on the next start)."""
        self.closing = True
        self.save()
        t = self.running
        if t:
            kill_tree(t.proc)
