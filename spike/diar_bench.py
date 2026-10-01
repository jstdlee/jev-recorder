"""M0 diarization benchmark.

prep:   build data/diar_eval/<id>.wav (16 kHz mono) + <id>.rttm references from
        AMI (Mix-Headset) and AliMeeting Eval far-field (channel 0 = one table mic).
run:    diar_bench.py run nemotron|pyannote   (call with the matching venv python)
score:  diar_bench.py score                   (needs pyannote.metrics -> .venv-enh)
"""
import re, sys, time
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"
EVAL = DATA / "diar_eval"
OUT = ROOT / "results" / "diar"


def textgrid_to_rttm(tg_path, rec_id):
    """AliMeeting TextGrid: one tier per speaker, intervals with non-empty text = speech."""
    txt = tg_path.read_text(encoding="utf-8", errors="ignore")
    lines = []
    for tier in re.split(r'item \[\d+\]:', txt)[1:]:
        name = re.search(r'name = "([^"]*)"', tier).group(1)
        for xmin, xmax, text in re.findall(
                r'xmin = ([\d.]+)\s*xmax = ([\d.]+)\s*text = "([^"]*)"', tier):
            if text.strip():
                s, e = float(xmin), float(xmax)
                lines.append(f"SPEAKER {rec_id} 1 {s:.3f} {e-s:.3f} <NA> <NA> {name} <NA> <NA>")
    return "\n".join(lines) + "\n"


def prep():
    import numpy as np, soundfile as sf, librosa
    EVAL.mkdir(parents=True, exist_ok=True)
    for m in ["ES2004a", "IS1009a"]:
        a, sr = sf.read(DATA / "ami" / f"{m}.Mix-Headset.wav", dtype="float32", always_2d=True)
        sf.write(EVAL / f"ami_{m}.wav", librosa.resample(a.mean(1), orig_sr=sr, target_sr=16000), 16000)
        ref = (DATA / "ami" / f"{m}.rttm").read_text().replace(f" {m} ", f" ami_{m} ")
        (EVAL / f"ami_{m}.rttm").write_text(ref)
    far = next((DATA / "alimeeting").rglob("Eval_Ali_far"), None)
    if far is None:
        print("AliMeeting not extracted yet; AMI only"); return
    wavs = sorted((far / "audio_dir").glob("*.wav"))[:4]  # 4 meetings is enough for M0
    for w in wavs:
        rid = "ali_" + w.stem.split("_")[0]
        tg = next((far / "textgrid_dir").glob(w.stem.split("_")[0] + "*.TextGrid"))
        a, sr = sf.read(w, dtype="float32", always_2d=True)
        sf.write(EVAL / f"{rid}.wav", librosa.resample(a[:, 0], orig_sr=sr, target_sr=16000), 16000)
        (EVAL / f"{rid}.rttm").write_text(textgrid_to_rttm(tg, rid))
    print("prepared", sorted(p.stem for p in EVAL.glob("*.wav")))


def run(model):
    out = OUT / model; out.mkdir(parents=True, exist_ok=True)
    wavs = sorted(EVAL.glob("*.wav"))
    if model == "nemotron":
        from nemo.collections.asr.models import SortformerEncLabelModel
        m = SortformerEncLabelModel.from_pretrained("nvidia/Nemotron-3-Diarization").eval().cuda()
        sm = m.sortformer_modules  # offline-ish settings from the model card
        sm.chunk_len, sm.chunk_right_context, sm.fifo_len, sm.spkcache_update_period = 340, 40, 40, 300
        m._check_streaming_parameters()
        for w in wavs:
            t = time.time(); segs = m.diarize(audio=[str(w)], batch_size=1)[0]
            with open(out / f"{w.stem}.rttm", "w") as f:
                for s in segs:
                    st, en, spk = s.split()[:3]
                    f.write(f"SPEAKER {w.stem} 1 {float(st):.3f} {float(en)-float(st):.3f} <NA> <NA> {spk} <NA> <NA>\n")
            print(f"nemotron {w.stem} {time.time()-t:.1f}s", flush=True)
    elif model == "pyannote":
        import torch
        from pyannote.audio import Pipeline
        p = Pipeline.from_pretrained("pyannote/speaker-diarization-community-1").to(torch.device("cuda"))
        for w in wavs:
            t = time.time(); d = p(str(w))
            ann = getattr(d, "speaker_diarization", d)
            with open(out / f"{w.stem}.rttm", "w") as f:
                for seg, _, spk in ann.itertracks(yield_label=True):
                    f.write(f"SPEAKER {w.stem} 1 {seg.start:.3f} {seg.duration:.3f} <NA> <NA> {spk} <NA> <NA>\n")
            print(f"pyannote {w.stem} {time.time()-t:.1f}s", flush=True)


def score():
    from pyannote.database.util import load_rttm
    from pyannote.metrics.diarization import DiarizationErrorRate
    for model in sorted(p.name for p in OUT.iterdir()):
        der = DiarizationErrorRate(collar=0.25, skip_overlap=False)
        rows = []
        for ref_p in sorted(EVAL.glob("*.rttm")):
            hyp_p = OUT / model / ref_p.name
            if not hyp_p.exists():
                continue
            ref = load_rttm(ref_p)[ref_p.stem]; hyp = load_rttm(hyp_p).get(ref_p.stem)
            if hyp is None:
                from pyannote.core import Annotation; hyp = Annotation()
            rows.append(f"{ref_p.stem}={der(ref, hyp)*100:.1f}%")
        print(f"{model:10s} DER {abs(der)*100:5.1f}%  " + " ".join(rows))


if __name__ == "__main__":
    {"prep": prep, "run": lambda: run(sys.argv[2]), "score": score}[sys.argv[1]]()
