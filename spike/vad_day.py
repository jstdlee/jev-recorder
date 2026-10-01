"""Decode the synthetic recorder file, run Silero VAD + windows(), compare to truth."""
import json, subprocess, sys, time
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from jrec.segment import speech_regions, windows

D = Path(__file__).parent / "data" / "recorder"
mp3 = D / "REC_FILE" / "FOLDER01" / "251001_0900.mp3"
raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(mp3), "-ac", "1", "-ar", "16000",
                      "-f", "f32le", "-"], capture_output=True, check=True).stdout
a = np.frombuffer(raw, np.float32).copy()
t = time.time(); regs = speech_regions(a); el = time.time() - t
hms = lambda s: f"{int(s//3600):02d}:{int(s%3600//60):02d}:{int(s%60):02d}"
print(f"VAD {len(a)/16000/60:.0f} min in {el:.1f}s, {len(regs)} regions, {sum(e-s for s,e in regs):.0f}s speech")
for w in windows(regs, len(a) / 16000):
    print(f"window {hms(w.start)}-{hms(w.end)}  speech {hms(w.speech_start)}-{hms(w.speech_end)}  ({w.speech_sec:.0f}s)")
print("truth:", [(t["label"], hms(t["start"]), hms(t["end"])) for t in json.load(open(D / "truth.json"))])
