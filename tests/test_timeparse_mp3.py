import hashlib
import subprocess
from datetime import datetime

from conftest import TZ, make_audio

from jrec import mp3frames
from jrec.config import DEFAULT, load
from jrec.timeparse import recording_start

PAT = r'(?:^|_)(\d{6})_(\d{4})\.(?:mp3|wav)$'
T0 = datetime(2025, 10, 1, 9, 0, 0, tzinfo=TZ)


def _mtime(start_s, dur, tz_shift_h=0):
    return T0.timestamp() + start_s + dur + tz_shift_h * 3600


def test_filename_and_mtime_agree_gives_seconds():
    st = recording_start("251001_0900.mp3", _mtime(42.5, 600), 600, "Asia/Singapore", PAT)
    assert st.confidence == "high" and st.flags == []
    assert st.start == datetime(2025, 10, 1, 9, 0, 42, 500000, tzinfo=TZ)


def test_prefixed_name_still_parses():
    st = recording_start("Important_251001_0900.mp3", _mtime(5, 60), 60, "Asia/Singapore", PAT)
    assert st.start.second == 5 and st.confidence == "high"


def test_mtime_off_by_whole_hours_is_corrected_and_flagged():
    st = recording_start("251001_0900.mp3", _mtime(10, 300, tz_shift_h=-8), 300, "Asia/Singapore", PAT)
    assert st.start.second == 10 and st.flags == ["mtime_tz_shift:-8h"]


def test_file_shorter_than_elapsed_time_flags_gap():
    # 30 min of audio, but closed 2 h after start: VOR pauses or lost audio
    st = recording_start("251001_0900.mp3", T0.timestamp() + 7200, 1800, "Asia/Singapore", PAT)
    assert st.start == T0 and st.confidence == "medium"
    assert any(f.startswith("timeline_gap") for f in st.flags)


def test_no_filename_falls_back_to_mtime_low_confidence():
    st = recording_start("REC0001.mp3", _mtime(0, 100), 100, "Asia/Singapore", PAT)
    assert st.confidence == "low" and st.start == T0


def test_default_config_has_tx660():
    d = load("/nonexistent").devices[0]
    assert d.label == "IC RECORDER" and d.roots == ["REC_FILE"] and "MUSIC" in d.ignore


def test_mp3_index_matches_ffprobe_and_cut_is_exact_byte_range(tmp_path):
    src = make_audio(tmp_path / "a.mp3", 30)
    idx = mp3frames.index(src)
    probe = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                  str(src)], capture_output=True, text=True).stdout)
    assert abs(idx.duration - probe) < 0.06 and idx.sample_rate == 44100 and idx.samples_per_frame == 1152
    info = mp3frames.cut(src, tmp_path / "clip.mp3", 10.0, 20.0, idx)
    data = src.read_bytes()
    clip = (tmp_path / "clip.mp3").read_bytes()
    assert clip == data[info["byte_start"]:info["byte_end"]]
    assert info["t_start"] <= 10.0 < info["t_start"] + 0.027 and info["t_end"] >= 20.0
    # the clip decodes to the expected length
    d = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                              str(tmp_path / "clip.mp3")], capture_output=True, text=True).stdout)
    assert abs(d - (info["t_end"] - info["t_start"])) < 0.06


def test_wav_cut_payload_is_exact_byte_range(tmp_path):
    from jrec import wavfile
    src = make_audio(tmp_path / "a.wav", 6, fmt="wav")
    idx = wavfile.index(src)
    assert abs(idx.duration - 6.0) < 1e-3
    info = wavfile.cut(src, tmp_path / "c.wav", 1.5, 4.0, idx)
    assert (tmp_path / "c.wav").read_bytes()[44:] == src.read_bytes()[info["byte_start"]:info["byte_end"]]
    assert wavfile.index(tmp_path / "c.wav").duration == 2.5
