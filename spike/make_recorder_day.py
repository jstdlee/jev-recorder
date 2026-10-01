"""Synthetic TX660-style recording to exercise VAD -> windows -> padding.

Writes data/recorder/REC_FILE/FOLDER01/251001_0900.mp3 (2 h, MP3 192k stereo 44.1k, as
the TX660 records). Its mtime is set to the end time, the way FAT stores it. A
ground-truth json is written next to it.
  00:25:00  AMI ES2004a first 8 min (English meeting, 4 speakers)
  00:50:00  single 3 s utterance (should be dropped: < 20 s speech)
  01:20:00  ~4 min Malay talk from FLEURS, at -12 dB (speaker farther away)
  room tone: pink noise around -55 dBFS + a soft 50 Hz hum
"""
import json, os, subprocess, sys
from datetime import datetime
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).parent))
from asr_bench import DATA, load_set, pink, read16k  # noqa: E402

SR = 16000
TOTAL = 2 * 3600


def main():
    rng = np.random.default_rng(7)
    n = TOTAL * SR
    x = (pink(n, rng) * 10 ** (-55 / 20) * 3).astype(np.float32)
    x += (0.0015 * np.sin(2 * np.pi * 50 * np.arange(n) / SR)).astype(np.float32)
    truth = []

    def put(at, a, gain_db=0.0, label=""):
        s = int(at * SR); a = a * 10 ** (gain_db / 20)
        x[s:s + len(a)] += a[: n - s]
        truth.append({"label": label, "start": at, "end": at + len(a) / SR})

    ami = read16k(DATA / "diar_eval" / "ami_ES2004a.wav") if (DATA / "diar_eval" / "ami_ES2004a.wav").exists() \
        else read16k(DATA / "ami" / "ES2004a.Mix-Headset.wav")
    put(25 * 60, ami[: 8 * 60 * SR], 0, "ami_meeting_en")
    fn, _ = load_set("en_us", 1, seed=5)[0]
    put(50 * 60, read16k(DATA / "fleurs" / "en_us" / "test" / fn)[: 3 * SR], 0, "blip_3s")
    parts = []
    for fn, _ in load_set("ms_my", 40, seed=3):
        parts += [read16k(DATA / "fleurs" / "ms_my" / "test" / fn), np.zeros(int(rng.uniform(0.5, 2.5) * SR), np.float32)]
        if sum(len(p) for p in parts) > 240 * SR:
            break
    put(80 * 60, np.concatenate(parts), -12, "malay_talk")

    out = DATA / "recorder" / "REC_FILE" / "FOLDER01"; out.mkdir(parents=True, exist_ok=True)
    wav = DATA / "recorder" / "day.wav"; sf.write(wav, np.clip(x, -1, 1), SR)
    mp3 = out / "251001_0900.mp3"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-ac", "2", "-ar", "44100",
                    "-b:a", "192k", str(mp3)], check=True)
    end = datetime(2025, 10, 1, 9, 0, 0).timestamp() + TOTAL + 1  # file closed at stop
    os.utime(mp3, (end, end))
    (DATA / "recorder" / "truth.json").write_text(json.dumps(truth, indent=1))
    print(mp3, json.dumps(truth))


if __name__ == "__main__":
    main()
