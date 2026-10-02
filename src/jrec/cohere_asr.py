"""Cohere Transcribe (CohereLabs/cohere-transcribe-03-2026), run as a long-lived worker in the
diarization venv (needs transformers >= 5.4, while qwen-asr pins 4.57).

The model has no language detection and no timestamps: the caller gives the language
(ISO code) and gets text only. Word times come from the aligners in jrec.transcribe.

Protocol: one JSON request per stdin line {"npz": PATH, "lang": "en"}; PATH holds arrays
a0, a1, ... (float32, 16 kHz). One reply line per request: '@@JREC {"texts": [...]}'.
Other stdout lines (library chatter) are ignored by the caller.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

MODEL = "CohereLabs/cohere-transcribe-03-2026"
SR = 16000
TAG = "@@JREC "
BATCH = 8
# the 14 trained languages: ISO code <-> the language names jrec uses (Qwen3-ASR style)
LANGS = {"ar": "Arabic", "de": "German", "el": "Greek", "en": "English", "es": "Spanish", "fr": "French",
         "it": "Italian", "ja": "Japanese", "ko": "Korean", "nl": "Dutch", "pl": "Polish", "pt": "Portuguese",
         "vi": "Vietnamese", "zh": "Chinese"}
ISO = {v: k for k, v in LANGS.items()} | {"Cantonese": "zh"}


class Worker:
    """Main-process handle: starts the worker once, then sends batches to it."""
    def __init__(self, python=None):
        from .diarize import python_for_diarization
        self.proc = subprocess.Popen(
            [python or python_for_diarization(), "-m", "jrec.cohere_asr"], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, text=True, bufsize=1,
            env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1])))

    def transcribe(self, pieces, iso):
        import tempfile
        import numpy as np
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "in.npz"
            np.savez(p, **{f"a{i}": x for i, x in enumerate(pieces)})
            self.proc.stdin.write(json.dumps({"npz": str(p), "lang": iso}) + "\n")
            self.proc.stdin.flush()
            for line in self.proc.stdout:
                if line.startswith(TAG):
                    r = json.loads(line[len(TAG):])
                    if "error" in r:
                        raise RuntimeError(f"Cohere Transcribe: {r['error']}")
                    return r["texts"]
        raise RuntimeError(f"Cohere Transcribe worker stopped (exit {self.proc.wait()})")

    def close(self):
        if self.proc.poll() is None:
            self.proc.stdin.close()
            self.proc.wait(timeout=30)


def _main():
    import numpy as np
    import torch
    from transformers import AutoProcessor, CohereAsrForConditionalGeneration
    proc = AutoProcessor.from_pretrained(MODEL)
    model = CohereAsrForConditionalGeneration.from_pretrained(MODEL, dtype=torch.bfloat16, device_map="cuda")
    for line in sys.stdin:
        try:
            req = json.loads(line)
            z = np.load(req["npz"])
            pieces = [z[f"a{i}"] for i in range(len(z.files))]
            texts = []
            for k in range(0, len(pieces), BATCH):
                inputs = proc(pieces[k:k + BATCH], sampling_rate=SR, return_tensors="pt", language=req["lang"])
                idx = inputs.get("audio_chunk_index")
                inputs.to(model.device, dtype=model.dtype)
                with torch.inference_mode():
                    out = model.generate(**inputs, max_new_tokens=448)
                dec = proc.decode(out, skip_special_tokens=True, audio_chunk_index=idx, language=req["lang"])
                texts += [dec] if isinstance(dec, str) else list(dec)
            reply = {"texts": [t.strip() for t in texts]}
        except Exception as e:  # keep the worker alive; the caller raises
            reply = {"error": f"{type(e).__name__}: {e}"}
        print(TAG + json.dumps(reply, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    _main()
