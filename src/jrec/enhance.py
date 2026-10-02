"""Listening track: DeepFilterNet3 (gentle, -a 12) + EBU R128 loudness -> listen.opus.

For listening only. Transcripts use the raw clip (M0: denoised input hurts ASR), and the
raw clip stays the evidence. listen.json records exactly how the track was made.
"""
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

ATTEN_DB = 12          # mix back some noise: natural sound, no ASR-hurting artifacts
LOUDNORM = "loudnorm=I=-19:TP=-2:LRA=11"


def deep_filter_bin():
    cands = [os.environ.get("JREC_DEEP_FILTER"), shutil.which("deep-filter"),
             str(Path(__file__).resolve().parents[2] / "spike" / "bin" / "deep-filter")]
    for c in cands:
        if c and Path(c).is_file() and os.access(c, os.X_OK):
            return c
    return None


def make_listen_track(folder, atten_db=ATTEN_DB, bitrate="32k"):
    folder = Path(folder)
    m = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    df = deep_filter_bin()
    if df is None:
        raise FileNotFoundError("deep-filter binary not found (set JREC_DEEP_FILTER)")
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        concat = td / "list.txt"
        concat.write_text("".join(f"file '{(folder / p['file']).resolve()}'\n" for p in m["parts"]), encoding="utf-8")
        src = td / "in.wav"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat),
                        "-ac", "1", "-ar", "48000", str(src)], check=True)
        subprocess.run([df, "-D", "-a", str(atten_db), "-o", str(td / "out"), str(src)], check=True,
                       capture_output=True)
        out = folder / "listen.opus"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(td / "out" / "in.wav"), "-af", LOUDNORM,
                        "-ac", "1", "-ar", "48000", "-c:a", "libopus", "-b:a", bitrate, str(out)], check=True)
    info = {"file": "listen.opus", "purpose": "listening only; evidence is raw_*.{mp3,wav}",
            "from_parts": [p["file"] for p in m["parts"]],
            "steps": [f"DeepFilterNet3 deep-filter -D -a {atten_db}", f"ffmpeg {LOUDNORM}", f"libopus {bitrate} mono 48k"],
            "created": datetime.now().astimezone().isoformat(timespec="seconds")}
    (folder / "listen.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    return out
