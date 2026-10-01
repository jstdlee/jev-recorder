"""Qwen3-ASR throughput on vLLM (native Qwen3ASRForConditionalGeneration), run in .venv-vllm.

Uses the same 30 s chunks as longform_bench.py qwen (taken from results/long/qwen/*.json),
so speed and CER compare directly with the Transformers backend.
Memory: gpu_memory_utilization=0.15, about 18 GiB of 121 GiB (project limit 20 GB, global cap 80 %).

usage: vllm_bench.py [1.7B|0.6B]
"""
import json, sys, time
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).parent
EVAL = ROOT / "data" / "diar_eval"
SR = 16000


def main():
    size = sys.argv[1] if len(sys.argv) > 1 else "1.7B"
    from vllm import LLM, SamplingParams
    t0 = time.time()
    llm = LLM(model=f"Qwen/Qwen3-ASR-{size}", gpu_memory_utilization=0.15, max_model_len=4096,
              max_num_seqs=128, limit_mm_per_prompt={"audio": 1})
    print(f"load {time.time()-t0:.0f}s", flush=True)
    prompt = "<|im_start|>user\n<|audio_start|><|audio_pad|><|audio_end|><|im_end|>\n<|im_start|>assistant\n"
    sp = SamplingParams(temperature=0.0, max_tokens=512)
    reqs, index, total = [], [], 0.0
    for j in sorted((ROOT / "results" / "long" / "qwen").glob("*.json")):
        a, sr = sf.read(EVAL / f"{j.stem}.wav", dtype="float32")
        total += len(a) / sr
        for k, seg in enumerate(json.loads(j.read_text())):
            piece = a[int(seg["start"] * sr):int(seg["end"] * sr)]
            reqs.append({"prompt": prompt, "multi_modal_data": {"audio": (piece, sr)}})
            index.append((j.stem, k, seg["start"], seg["end"]))
    t = time.time()
    outs = llm.generate(reqs, sp)
    el = time.time() - t
    print(f"vLLM Qwen3-ASR-{size}: {len(reqs)} chunks, {total/60:.0f} min audio in {el:.1f}s = x{total/el:.0f} realtime",
          flush=True)
    out = ROOT / "results" / "long" / f"vllm-{size}"; out.mkdir(parents=True, exist_ok=True)
    by = {}
    for (stem, k, s, e), o in zip(index, outs):
        raw = o.outputs[0].text
        lang, _, text = raw.partition("<asr_text>")
        by.setdefault(stem, []).append({"start": s, "end": e, "speaker": None, "text": text.strip(),
                                        "lang": lang.removeprefix("language ").strip()})
    for stem, segs in by.items():
        (out / f"{stem}.json").write_text(json.dumps(segs, ensure_ascii=False))


if __name__ == "__main__":
    main()
