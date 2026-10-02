"""Build a demo library from public test audio (FLEURS, AMI, AliMeeting in spike/data).

  .venv/bin/python scripts/make_demo.py [~/jrec-demo]
  .venv/bin/jrec --config ~/jrec-demo/config.toml ui

Writes a fake TX660 card (REC_FILE/FOLDER01/YYMMDD_HHMM.mp3, FAT-style mtimes) with room
tone around real speech, then imports it (no prompt) and cuts conversations (CPU only).
Kept separate from the real library so demo audio never mixes with evidence.
"""
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "spike" / "data"
SR = 16000
TZ = ZoneInfo("Asia/Singapore")
sys.path.insert(0, str(ROOT / "spike"))
from asr_bench import load_set, pink, read16k  # noqa: E402


def room_tone(seconds, rng):
    n = int(seconds * SR)
    x = pink(n, rng).astype(np.float32) * 10 ** (-55 / 20) * 3
    return x + (0.0015 * np.sin(2 * np.pi * 50 * np.arange(n) / SR)).astype(np.float32)


def fleurs_talk(lang, seconds, rng, seed):
    parts, total = [], 0
    for fn, _ in load_set(lang, 200, seed=seed):
        a = read16k(DATA / "fleurs" / lang / "test" / fn)
        gap = np.zeros(int(rng.uniform(0.4, 2.0) * SR), np.float32)
        parts += [a, gap]
        total += len(a) + len(gap)
        if total > seconds * SR:
            break
    return np.concatenate(parts)


def recording(path, start, pieces, rng):
    """pieces: [(seconds_of_room_tone_before, speech_array_or_None, gain_db)]"""
    x = []
    for pre, speech, gain in pieces:
        x.append(room_tone(pre, rng))
        if speech is not None:
            seg = speech * 10 ** (gain / 20)
            x.append(seg + room_tone(len(seg) / SR, rng))
    a = np.clip(np.concatenate(x), -1, 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    wav = path.with_suffix(".tmp.wav")
    sf.write(wav, a, SR)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(wav), "-ac", "2", "-ar", "44100", "-b:a", "192k",
                    str(path)], check=True)
    wav.unlink()
    end = start.timestamp() + len(a) / SR + 1.0  # FAT mtime = closed ~1 s after the last frame
    os.utime(path, (end, end))
    print(f"  {path.name}: {len(a) / SR / 60:.0f} min")


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "~/jrec-demo").expanduser()
    card = out / "card" / "IC RECORDER" / "REC_FILE" / "FOLDER01"
    rng = np.random.default_rng(11)
    print(f"demo card in {card.parent.parent}")
    big = DATA / "recorder" / "REC_FILE" / "FOLDER01" / "251001_0900.mp3"
    if big.exists() and not (card / big.name).exists():
        card.mkdir(parents=True, exist_ok=True)
        os.link(big, card / big.name) if big.stat().st_dev == card.stat().st_dev else \
            subprocess.run(["cp", "-p", str(big), str(card / big.name)], check=True)
        print(f"  {big.name}: 120 min (English meeting + quieter Malay talk)")
    ali = DATA / "diar_eval" / "ali_R8003.wav"
    if ali.exists() and not (card / "251002_1400.mp3").exists():
        meet = read16k(ali)[60 * SR: 7 * 60 * SR]  # 6 min of a 4-person Mandarin table-mic meeting
        recording(card / "251002_1400.mp3", datetime(2025, 10, 2, 14, 0, 12, tzinfo=TZ),
                  [(12 * 60, meet, 6), (22 * 60, None, 0)], rng)
    if not (card / "251003_1930.mp3").exists():
        recording(card / "251003_1930.mp3", datetime(2025, 10, 3, 19, 30, 40, tzinfo=TZ),
                  [(14 * 60, fleurs_talk("yue_hant_hk", 240, rng, 5), 0), (17 * 60, None, 0)], rng)
    cfg = out / "config.toml"
    sys.path.insert(0, str(ROOT / "src"))
    from jrec import config
    cfg.write_text(config.DEFAULT.replace('library = "~/jrec-library"', f'library = "{out / "lib"}"'))
    jrec = [sys.executable, "-m", "jrec.cli", "--config", str(cfg)]
    subprocess.run(jrec + ["import", str(card.parent.parent), "--yes"], check=True)
    subprocess.run(jrec + ["cut"], check=True)
    print(f"\ndemo ready:  {ROOT}/.venv/bin/jrec --config {cfg} ui")


if __name__ == "__main__":
    main()
