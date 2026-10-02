"""Archive -> conversation folders with byte-exact raw clips and a verifiable manifest.

Sources from the same device whose times line up (end of one ~ start of the next, the
TX660 1 GB auto-split) are stitched into one stream. A window keeps >= PAD of raw audio on
each side (segment.windows) and can span several source files; each part is a byte range
of one archived original. Seams between stitched files are recorded as possible gaps.
"""
import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from . import mp3frames, segment, wavfile

STITCH_TOL = 5.0      # seconds between one file's end and the next file's start
VAD_BLOCK = 1800      # seconds of audio per VAD block (bounded memory on 12 h files)
SR = 16000


@dataclass
class Src:
    sha256: str
    ext: str
    path: Path
    start: datetime
    duration: float
    orig_path: str
    device: str
    meta: dict


def streams(sources):
    """Group sources (sorted by start) into contiguous streams: [[Src, ...], ...]."""
    out = []
    for s in sorted(sources, key=lambda s: s.start):
        if out:
            last = out[-1][-1]
            gap = (s.start - last.start).total_seconds() - last.duration
            if s.device == last.device and -STITCH_TOL <= gap <= STITCH_TOL:
                out[-1].append(s)
                continue
        out.append([s])
    return out


def speech_regions_file(path, offset=0.0):
    """Silero VAD over a whole file, decoded by ffmpeg in VAD_BLOCK pieces."""
    proc = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-i", str(path), "-ac", "1", "-ar", str(SR),
                             "-f", "s16le", "-"], stdout=subprocess.PIPE)
    regs, t = [], 0.0
    while True:
        buf = proc.stdout.read(VAD_BLOCK * SR * 2)
        if not buf:
            break
        a = np.frombuffer(buf, np.int16).astype(np.float32) / 32768.0
        regs += [(offset + t + s, offset + t + e) for s, e in segment.speech_regions(a)]
        t += len(a) / SR
    proc.wait()
    return regs


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 22):
            h.update(chunk)
    return h.hexdigest()


def _cut(src, dst, t0, t1):
    if src.ext == "mp3":
        return mp3frames.cut(src.path, dst, t0, t1)
    if src.ext == "wav":
        return wavfile.cut(src.path, dst, t0, t1)
    raise NotImplementedError(f"byte-exact cut not supported for .{src.ext}")


def verify_cmd(archive_name, info):
    n = info["byte_end"] - info["byte_start"]
    return f"tail -c +{info['byte_start'] + 1} archive/{archive_name} | head -c {n} | sha256sum"


def cut_stream(stream, out_root, pad=segment.PAD, gap=segment.GAP, min_speech=segment.MIN_SPEECH,
               regions=None):
    """Cut every conversation in one stream. Returns [manifest dict]. `regions` (stream
    seconds) can be passed to skip VAD (tests)."""
    t0 = stream[0].start
    offsets, total = [], 0.0
    for s in stream:  # stream time of each file = seconds since the first file's start
        offsets.append((s.start - t0).total_seconds())
        total = offsets[-1] + s.duration
    if regions is None:
        regions = []
        for s, off in zip(stream, offsets):
            regions += speech_regions_file(s.path, off)
    manifests = []
    for w in segment.windows(regions, total, gap=gap, min_speech=min_speech, pad=pad):
        sp_abs = t0 + timedelta(seconds=w.speech_start)
        folder = out_root / f"{sp_abs:%Y-%m-%d_%H%M%S}_{stream[0].sha256[:8]}"
        folder.mkdir(parents=True, exist_ok=True)
        parts, seams = [], []
        for k, (s, off) in enumerate(zip(stream, offsets)):
            a, b = max(w.start, off), min(w.end, off + s.duration)
            if b <= a:
                continue
            name = f"raw_{len(parts) + 1:02d}.{s.ext}"
            info = _cut(s, folder / name, a - off, b - off)
            if parts:
                seams.append({"after_part": len(parts), "at": (s.start + timedelta(seconds=info["t_start"])).isoformat(),
                              "note": "file boundary (recorder auto-split): audio may be missing here"})
            parts.append({
                "file": name, "sha256": _sha256(folder / name),
                "source_sha256": s.sha256, "source_orig_path": s.orig_path, "source_start": s.meta,
                **{k2: info[k2] for k2 in ("byte_start", "byte_end", "t_start", "t_end")},
                **({"header_bytes": info["header_bytes"]} if "header_bytes" in info else {}),
                "abs_start": (s.start + timedelta(seconds=info["t_start"])).isoformat(),
                "abs_end": (s.start + timedelta(seconds=info["t_end"])).isoformat(),
                "verify": verify_cmd(f"{s.sha256}.{s.ext}", info),
            })
        abs_ = lambda x: (t0 + timedelta(seconds=x)).isoformat()
        # the clip starts/ends on whole frames: report the audio actually covered, and give
        # VAD regions relative to that real start
        c0 = (offsets[stream.index(next(s for s in stream if s.sha256 == parts[0]["source_sha256"]))]
              + parts[0]["t_start"])
        c1 = (offsets[stream.index(next(s for s in stream if s.sha256 == parts[-1]["source_sha256"]))]
              + parts[-1]["t_end"])
        m = {
            "version": 1, "conversation": folder.name,
            "window": {"start": parts[0]["abs_start"], "end": parts[-1]["abs_end"],
                       "speech_start": abs_(w.speech_start), "speech_end": abs_(w.speech_end),
                       "speech_sec": round(w.speech_sec, 2), "requested": [abs_(w.start), abs_(w.end)]},
            "rules": {"pad_sec": pad, "gap_sec": gap, "min_speech_sec": min_speech,
                      "padding": "kept on both sides, clamped only at the stream's own start/end"},
            "parts": parts, "seams": seams,
            "vad": {"model": "silero-vad", "regions_sec": [[round(a - c0, 3), round(b - c0, 3)]
                                                          for a, b in regions if b > c0 and a < c1]},
            "created": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        (folder / "manifest.json").write_text(json.dumps(m, indent=1, ensure_ascii=False), encoding="utf-8")
        manifests.append(m)
    return manifests


def verify_folder(folder, archive):
    """Re-check every part: clip hash, and the clip bytes against the archived original."""
    m = json.loads((Path(folder) / "manifest.json").read_text(encoding="utf-8"))
    problems = []
    for p in m["parts"]:
        clip = (Path(folder) / p["file"]).read_bytes()
        if hashlib.sha256(clip).hexdigest() != p["sha256"]:
            problems.append(f"{p['file']}: clip hash changed")
        src = Path(archive) / f"{p['source_sha256']}.{p['file'].rsplit('.', 1)[1]}"
        with open(src, "rb") as f:
            f.seek(p["byte_start"])
            orig = f.read(p["byte_end"] - p["byte_start"])
        if clip[p.get("header_bytes", 0):] != orig:
            problems.append(f"{p['file']}: bytes differ from archived original")
        if _sha256(src) != p["source_sha256"]:
            problems.append(f"{src.name}: archived original changed")
    return problems
