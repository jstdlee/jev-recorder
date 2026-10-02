"""Find recorders, preview their files (read-only: listing + headers), import on confirmation.

Import = copy to staging while hashing, fsync, move to archive/<sha256>.<ext>, chmod 0444.
Nothing on the device is ever written or deleted.
"""
import getpass
import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import db, mp3frames, wavfile
from .timeparse import recording_start


@dataclass
class Candidate:
    path: Path        # absolute path on the device
    rel: str          # path relative to the mount
    size: int
    mtime: float
    duration: float | None
    start: object     # StartTime
    status: str       # new | imported


def mount_points():
    """Mounted filesystems as {mountpoint: device}, from /proc/mounts."""
    out = {}
    for line in Path("/proc/mounts").read_text(encoding="utf-8").splitlines():
        dev, mnt = line.split()[:2]
        out[mnt.replace("\\040", " ")] = dev
    return out


def device_serial(blockdev, fallback):
    try:
        props = subprocess.run(["udevadm", "info", "--query=property", f"--name={blockdev}"],
                               capture_output=True, text=True, timeout=5).stdout
        kv = dict(l.split("=", 1) for l in props.splitlines() if "=" in l)
        return kv.get("ID_SERIAL_SHORT") or kv.get("ID_SERIAL") or fallback
    except (OSError, subprocess.SubprocessError):
        return fallback


def find_recorders(cfg):
    """[(device_profile, mountpoint, serial)] for mounted volumes that match a profile."""
    user = getpass.getuser()
    found = []
    for mnt, dev in mount_points().items():
        p = Path(mnt)
        if not (mnt.startswith((f"/media/{user}/", f"/run/media/{user}/", "/mnt/"))):
            continue
        for d in cfg.devices:
            if p.name == d.label or all((p / r).is_dir() for r in d.roots):
                found.append((d, p, device_serial(dev, f"{d.name}:{p.name}")))
                break
    return found


def _duration(path):
    """Header-level duration for the preview (cheap); exact frame count is taken at import."""
    if str(path).lower().endswith(".wav"):
        try:
            return wavfile.index(path).duration
        except (OSError, ValueError):
            return None
    try:
        import mutagen
        f = mutagen.File(path)
        return f.info.length if f else None
    except Exception:
        return None


def scan(profile, mount, serial, con):
    """Preview: list candidate recordings without reading their audio."""
    out = []
    for root in profile.roots:
        base = Path(mount) / root
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            rel = p.relative_to(mount).as_posix()      # same key on every OS
            if not p.is_file() or p.suffix.lower().lstrip(".") not in profile.extensions \
                    or any(part in profile.ignore for part in p.relative_to(mount).parts):
                continue
            st = p.stat()
            dur = _duration(p)
            start = recording_start(p.name, st.st_mtime, dur or 0.0, profile.timezone, profile.filename_time) \
                if dur is not None else None
            status = "imported" if db.is_seen(con, serial, rel, st.st_size, st.st_mtime) else "new"
            out.append(Candidate(p, rel, st.st_size, st.st_mtime, dur, start, status))
    return out


def _copy_hash(src, dst):
    h = hashlib.sha256()
    with open(src, "rb") as f, open(dst, "wb") as g:
        while chunk := f.read(1 << 22):
            h.update(chunk)
            g.write(chunk)
        g.flush()
        os.fsync(g.fileno())
    return h.hexdigest()


def import_one(cand, profile, serial, cfg, con):
    """Copy one candidate into the archive. Returns (sha256, was_new)."""
    staging = cfg.library / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    cfg.archive.mkdir(parents=True, exist_ok=True)
    ext = cand.path.suffix.lower().lstrip(".")
    tmp = staging / f"{os.getpid()}-{cand.path.name}"
    sha = _copy_hash(cand.path, tmp)
    if tmp.stat().st_size != cand.size:
        tmp.unlink()
        raise IOError(f"size changed while copying {cand.rel}")
    dst = cfg.archive / f"{sha}.{ext}"
    new = not dst.exists()
    if new:
        os.chmod(tmp, 0o444)
        os.replace(tmp, dst)
    else:
        tmp.unlink()
    duration = exact_duration(dst)
    st = recording_start(cand.path.name, cand.mtime, duration, profile.timezone, profile.filename_time)
    db.add_source(con, {
        "sha256": sha, "ext": ext, "size": cand.size, "device": profile.name, "device_serial": serial,
        "orig_path": cand.rel, "orig_mtime": cand.mtime, "duration": duration,
        "start": st.start.isoformat(), "start_source": st.source, "start_conf": st.confidence,
        "flags": st.flags, "imported_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    return sha, new


def exact_duration(path):
    ext = str(path).lower().rsplit(".", 1)[-1]
    if ext == "mp3":
        return mp3frames.index(path).duration
    if ext == "wav":
        return wavfile.index(path).duration
    return _duration(path)


def free_space_ok(cfg, cands):
    need = sum(c.size for c in cands)
    cfg.library.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(cfg.library).free > need * 1.1, need
