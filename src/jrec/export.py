"""Export an A–B excerpt as verifiable evidence: byte ranges of the archived originals + a manifest.

The excerpt is cut from the archive (never re-encoded), so its bytes can be checked against the
original with the shell command written next to each part. Nothing in the library is modified.
"""
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

from . import mp3frames, wavfile
from .cutter import verify_cmd


def export_range(manifest, archive, out_root, a, b, label=""):
    """a, b: seconds from the clip start. Returns the export folder."""
    clip_start = datetime.fromisoformat(manifest["window"]["start"])
    t_a, t_b = clip_start + timedelta(seconds=a), clip_start + timedelta(seconds=b)
    out = Path(out_root) / f"{manifest['conversation']}_{t_a:%H%M%S}-{t_b:%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)
    parts, acc = [], 0.0
    for p in manifest["parts"]:
        dur = p["t_end"] - p["t_start"]
        lo, hi = max(a, acc), min(b, acc + dur)       # clip time covered by this part
        if hi > lo:
            ext = p["file"].rsplit(".", 1)[1]
            src = Path(archive) / f"{p['source_sha256']}.{ext}"
            s0 = p["t_start"] + (lo - acc)                # time inside the archived original
            s1 = p["t_start"] + (hi - acc)
            name = f"excerpt_{len(parts) + 1:02d}.{ext}"
            info = (mp3frames.cut if ext == "mp3" else wavfile.cut)(src, out / name, s0, s1)
            start_abs = datetime.fromisoformat(p["abs_start"]) + timedelta(seconds=info["t_start"] - p["t_start"])
            parts.append({"file": name, "sha256": hashlib.sha256((out / name).read_bytes()).hexdigest(),
                          "source_sha256": p["source_sha256"], "source_orig_path": p["source_orig_path"],
                          "byte_start": info["byte_start"], "byte_end": info["byte_end"],
                          **({"header_bytes": info["header_bytes"]} if "header_bytes" in info else {}),
                          "abs_start": start_abs.isoformat(),
                          "abs_end": (start_abs + timedelta(seconds=info["t_end"] - info["t_start"])).isoformat(),
                          "verify": verify_cmd(f"{p['source_sha256']}.{ext}", info)})
        acc += dur
    m = {"version": 1, "kind": "excerpt", "from_conversation": manifest["conversation"], "label": label,
         "requested": [t_a.isoformat(), t_b.isoformat()], "parts": parts,
         "note": "Byte-exact ranges of the archived original recording(s); not re-encoded. "
                 "Run each 'verify' command in the library folder: its hash must equal 'sha256'.",
         "created": datetime.now().astimezone().isoformat(timespec="seconds")}
    (out / "manifest.json").write_text(json.dumps(m, indent=1, ensure_ascii=False))
    return out
