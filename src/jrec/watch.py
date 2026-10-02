"""Watch for recorders. On plug-in: remount read-only, scan, and ask with a desktop
notification (Import / Skip). Nothing is copied without a click, unless the device profile
sets auto_import = true. After an import, the processing pipeline runs (one job at a time)."""
import shutil
import subprocess
import time

from . import db, ingest

POLL_SEC = 3


def remount_readonly(mount, blockdev, log=print):
    """Best effort: udisks unmount + mount -o ro. We never write anyway; this makes it physical."""
    opts = next((l.split()[3] for l in open("/proc/mounts") if l.split()[1].replace("\\040", " ") == str(mount)), "")
    if "ro" in opts.split(","):
        return str(mount)
    if not shutil.which("udisksctl"):
        return str(mount)
    try:
        subprocess.run(["udisksctl", "unmount", "-b", blockdev], check=True, capture_output=True, timeout=30)
        out = subprocess.run(["udisksctl", "mount", "-b", blockdev, "-o", "ro"], check=True, capture_output=True,
                             text=True, timeout=30).stdout
        new = out.strip().split(" at ", 1)[-1].rstrip(".")
        log(f"remounted {blockdev} read-only at {new}")
        return new
    except (subprocess.SubprocessError, OSError) as e:
        log(f"read-only remount failed ({e}); continuing read-only by policy")
        return str(mount)


def ask(title, body, timeout_s=600):
    """Desktop notification with buttons. Returns 'import', 'skip' or None (dismissed / no desktop)."""
    if not shutil.which("notify-send"):
        return None
    try:
        r = subprocess.run(["notify-send", "--app-name=jev-recorder", "--urgency=normal", "--wait",
                            "-A", "import=Import", "-A", "skip=Skip", title, body],
                           capture_output=True, text=True, timeout=timeout_s)
        return r.stdout.strip() or None
    except subprocess.TimeoutExpired:
        return None


def notify(title, body):
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "--app-name=jev-recorder", title, body], check=False)


def new_mounts(prev, now):
    return [m for m in now if m not in prev]


def run(cfg, process_after=True, log=print):
    from .cli import _fmt_size  # shared formatting
    seen = set()
    log("watching for recorders … (Ctrl+C to stop)")
    while True:
        recs = {str(m): (d, m, s) for d, m, s in ingest.find_recorders(cfg)}
        for key in new_mounts(seen, recs):
            d, mnt, serial = recs[key]
            dev = ingest.mount_points().get(str(mnt))
            mnt = remount_readonly(mnt, dev, log) if dev and dev.startswith("/dev/") else str(mnt)
            con = db.connect(cfg.db_path)
            cands = [c for c in ingest.scan(d, mnt, serial, con) if c.status == "new"]
            log(f"{d.name} at {mnt}: {len(cands)} new recording(s)")
            if not cands:
                notify("Recorder connected", f"{d.name}: nothing new")
                continue
            size = _fmt_size(sum(c.size for c in cands))
            choice = "import" if d.auto_import else ask(
                f"Recorder connected: {len(cands)} new recording(s)", f"{d.name}, {size}. Import into the archive?")
            if choice != "import":
                log("not imported (skipped or no answer)")
                continue
            for c in cands:
                ingest.import_one(c, d, serial, cfg, con)
            notify("Import done", f"{len(cands)} file(s), {size}. Safe to eject.")
            if process_after:
                from .pipeline import process_all
                process_all(cfg, log=log)
        seen = set(recs)
        time.sleep(POLL_SEC)
