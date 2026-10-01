"""M0 long-form benchmark on whole meetings (data/diar_eval/*.wav, 14-34 min each).

  qwen        Qwen3-ASR-1.7B on VAD chunks plus Qwen3-ForcedAligner timestamps (main .venv)
  vibevoice   VibeVoice-ASR-HF, one pass with speakers and timestamps (.venv-nemo, transformers git)
Writes results/long/<model>/<id>.json = [{start, end, speaker, text}].
score: CER on AliMeeting (reference text = all TextGrid intervals in time order), plus DER
       for models that output speakers. Run with .venv-enh.
"""
import json, re, sys, time
from pathlib import Path

ROOT = Path(__file__).parent
EVAL = ROOT / "data" / "diar_eval"
OUT = ROOT / "results" / "long"


def run_qwen():
    import numpy as np, soundfile as sf, torch
    sys.path.insert(0, str(ROOT.parent / "src"))
    from jrec.segment import chunks, speech_regions
    ALIGN_LANGS = {'Chinese', 'Cantonese', 'English', 'Japanese', 'Korean'}
    from qwen_asr import Qwen3ASRModel
    m = Qwen3ASRModel.from_pretrained("Qwen/Qwen3-ASR-1.7B", dtype=torch.bfloat16, device_map="cuda:0",
                                      forced_aligner="Qwen/Qwen3-ForcedAligner-0.6B",
                                      forced_aligner_kwargs={"dtype": torch.bfloat16, "device_map": "cuda:0"},
                                      max_inference_batch_size=16, max_new_tokens=1024)
    out = OUT / "qwen"; out.mkdir(parents=True, exist_ok=True)
    for w in sorted(EVAL.glob("*.wav")):
        if (out / f"{w.stem}.json").exists():
            continue
        a, sr = sf.read(w, dtype="float32")
        t = time.time()
        # the whole file is one conversation: contiguous 30 s chunks, cut in VAD silences
        cs = chunks(speech_regions(a), 0.0, len(a) / sr, max_len=30.0)
        pieces = [(a[int(s * sr):int(e * sr)], sr) for s, e in cs]
        t_vad = time.time() - t
        res = m.transcribe(audio=pieces)
        t_asr = time.time() - t - t_vad
        al = {}
        for i, r in enumerate(res):
            if r.text.strip() and r.language.split(",")[0] in ALIGN_LANGS:
                al[i] = r
        ts = m.forced_aligner.align(audio=[pieces[i] for i in al], text=[r.text for r in al.values()],
                                    language=[r.language.split(",")[0] for r in al.values()]) if al else []
        ts = dict(zip(al, ts))
        t_al = time.time() - t - t_vad - t_asr
        segs = []
        for i, ((s, e), r) in enumerate(zip(cs, res)):
            items = list(ts[i]) if i in ts else []
            segs.append({"start": s, "end": e, "speaker": None, "text": r.text, "lang": r.language,
                         "words": [{"w": x.text, "s": s + x.start_time, "e": s + x.end_time} for x in items]})
        chunks_n = len(cs)
        (out / f"{w.stem}.json").write_text(json.dumps(segs, ensure_ascii=False))
        print(f"qwen {w.stem} {len(a)/sr/60:.0f} min in {time.time()-t:.1f}s (vad {t_vad:.0f} asr {t_asr:.0f} align {t_al:.0f}), {chunks_n} chunks", flush=True)


def run_vibevoice():
    # dropped from M0: ~25 GiB at runtime, over the 20 GB model limit set for this project
    print("vibevoice skipped (over 20 GB limit)"); return
    import soundfile as sf, torch
    from transformers import AutoProcessor, VibeVoiceAsrForConditionalGeneration
    mid = "microsoft/VibeVoice-ASR-HF"
    proc = AutoProcessor.from_pretrained(mid)
    m = VibeVoiceAsrForConditionalGeneration.from_pretrained(mid, device_map="cuda", dtype=torch.bfloat16)
    out = OUT / "vibevoice"; out.mkdir(parents=True, exist_ok=True)
    for w in sorted(EVAL.glob("*.wav")):
        if (out / f"{w.stem}.json").exists():
            continue
        a, sr = sf.read(w, dtype="float32")
        t = time.time()
        inputs = proc.apply_transcription_request(audio=a, sampling_rate=sr).to(m.device, m.dtype)
        with torch.inference_mode():
            ids = m.generate(**inputs, max_new_tokens=32768)
        parsed = proc.decode(ids[:, inputs["input_ids"].shape[1]:], return_format="parsed")[0]
        segs = [{"start": float(p["Start"]), "end": float(p["End"]), "speaker": f"spk{p.get('Speaker')}",
                 "text": p.get("Content", "")} for p in parsed]
        (out / f"{w.stem}.json").write_text(json.dumps(segs, ensure_ascii=False))
        print(f"vibevoice {w.stem} {len(a)/sr/60:.0f} min in {time.time()-t:.1f}s, {len(segs)} segs", flush=True)


def ref_text(rid):
    tg = next((ROOT / "data" / "alimeeting").rglob(rid.removeprefix("ali_") + "*.TextGrid"))
    txt = tg.read_text(encoding="utf-8", errors="ignore")
    ivs = [(float(s), t) for s, _, t in re.findall(r'xmin = ([\d.]+)\s*xmax = ([\d.]+)\s*text = "([^"]*)"', txt) if t.strip()]
    return "".join(t for _, t in sorted(ivs))


def score():
    import jiwer
    from pyannote.core import Annotation, Segment
    from pyannote.database.util import load_rttm
    from pyannote.metrics.diarization import DiarizationErrorRate
    sys.path.insert(0, str(ROOT))
    from asr_bench import norm
    for model in sorted(p.name for p in OUT.iterdir()):
        der = DiarizationErrorRate(collar=0.25); cers = []; has_spk = False
        for j in sorted((OUT / model).glob("*.json")):
            segs = json.loads(j.read_text())
            if j.stem.startswith("ali_"):
                hyp = "".join(s["text"] for s in sorted(segs, key=lambda s: s["start"]))
                cers.append(f"{j.stem}={jiwer.cer(norm(ref_text(j.stem), 'cmn_hans_cn'), norm(hyp, 'cmn_hans_cn') or '∅')*100:.1f}%")
            if segs and segs[0].get("speaker"):
                has_spk = True
                ann = Annotation()
                for i, s in enumerate(segs):
                    if s["end"] > s["start"]:
                        ann[Segment(s["start"], s["end"]), i] = s["speaker"]
                der(load_rttm(EVAL / f"{j.stem}.rttm")[j.stem], ann)
        print(f"{model:10s} CER {' '.join(cers)}" + (f"  | DER {abs(der)*100:.1f}%" if has_spk else ""))


if __name__ == "__main__":
    {"qwen": run_qwen, "vibevoice": run_vibevoice, "score": score}[sys.argv[1]]()
