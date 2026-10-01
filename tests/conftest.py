import os
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from jrec import config

TZ = ZoneInfo("Asia/Singapore")


def make_audio(path, seconds, fmt="mp3"):
    path.parent.mkdir(parents=True, exist_ok=True)
    args = ["-ac", "2", "-ar", "44100"] + (["-b:a", "192k"] if fmt == "mp3" else ["-c:a", "pcm_s16le"])
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"sine=frequency=440:duration={seconds}", *args, str(path)], check=True)
    return path


def set_closed_at(path, start_local, seconds, lag=1.0):
    """FAT-style mtime: the file was closed `lag` s after start + duration."""
    t = start_local.timestamp() + seconds + lag
    os.utime(path, (t, t))


@pytest.fixture
def card(tmp_path):
    """A fake TX660 volume: two MP3 recordings, one WAV, and a MUSIC file to ignore."""
    root = tmp_path / "IC RECORDER"
    f1 = make_audio(root / "REC_FILE/FOLDER01/251001_0900.mp3", 20)
    set_closed_at(f1, datetime(2025, 10, 1, 9, 0, 17, tzinfo=TZ), 20.0)
    f2 = make_audio(root / "REC_FILE/FOLDER01/Important_251001_1430.mp3", 8)
    set_closed_at(f2, datetime(2025, 10, 1, 14, 30, 5, tzinfo=TZ), 8.0)
    f3 = make_audio(root / "REC_FILE/FOLDER02/251002_0815.wav", 5, fmt="wav")
    set_closed_at(f3, datetime(2025, 10, 2, 8, 15, 40, tzinfo=TZ), 5.0)
    make_audio(root / "MUSIC/song.mp3", 3)
    return root


@pytest.fixture
def cfg(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(config.DEFAULT.replace('library = "~/jrec-library"', f'library = "{tmp_path / "lib"}"'))
    return config.load(p)
