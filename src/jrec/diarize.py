"""Nemotron 3 Diarization, run as a subprocess in its own venv (needs transformers >= 5.x,
while qwen-asr pins 4.57).

  python -m jrec.diarize IN.wav OUT.json     -> [{"start", "end", "speaker"}] in seconds
"""
import json
import os
import subprocess
import sys
from pathlib import Path

MODEL = "nvidia/Nemotron-3-Diarization"


def python_for_diarization():
    return os.environ.get("JREC_DIAR_PYTHON",
                          str(Path(__file__).resolve().parents[2] / ".venv-nemo" / "bin" / "python"))


def run(wav_path, out_json):
    """Called from the main process: diarize wav_path in the diarization venv."""
    subprocess.run([python_for_diarization(), "-m", "jrec.diarize", str(wav_path), str(out_json)], check=True,
                   env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1])))
    return json.loads(Path(out_json).read_text(encoding="utf-8"))


def _main(wav, out):
    import soundfile as sf
    import torch
    from transformers import AutoModelForAudioFrameClassification, AutoProcessor
    proc = AutoProcessor.from_pretrained(MODEL)
    model = AutoModelForAudioFrameClassification.from_pretrained(MODEL, device_map="cuda")
    audio, sr = sf.read(wav, dtype="float32")
    inputs = proc(audio, sampling_rate=sr).to(model.device, dtype=model.dtype)
    with torch.inference_mode():
        logits = model(**inputs).logits
    segs = proc.extract_speaker_dict(logits, inputs.attention_mask)[0]
    Path(out).write_text(json.dumps([{"start": float(s["Start"]), "end": float(s["End"]),
                                      "speaker": f"S{int(s['Speaker']) + 1}"} for s in segs]), encoding="utf-8")


if __name__ == "__main__":
    _main(sys.argv[1], sys.argv[2])
