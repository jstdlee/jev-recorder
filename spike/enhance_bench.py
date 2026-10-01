"""M0 enhancement benchmark.

Writes the noisy FLEURS sets that asr_bench.py uses (5 dB SNR babble + pink noise), then
enhances them with:
  dfn3      DeepFilterNet3 (deep-filter binary, CPU), full suppression
  dfn3a12   DeepFilterNet3 with --atten-lim-db 12, a gentle mix that leaves some noise
  mf2       ClearerVoice MossFormer2_SE_48K (GPU, run in .venv-enh)
Output goes to data/enhanced/<cond>/<lang>/<file> at 16 kHz, where asr_bench.py picks it up.
It also prints SI-SDR against the clean audio, as a sanity check on enhancement quality.
"""
import subprocess, sys, time
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).parent))
from asr_bench import DATA, LANGS, SR, add_noise, load_set, read16k  # noqa: E402

ROOT = Path(__file__).parent
N = 60
NOISY48 = DATA / "noisy48"


def si_sdr(ref, est):
    n = min(len(ref), len(est)); ref, est = ref[:n], est[:n]
    a = np.dot(est, ref) / (np.dot(ref, ref) + 1e-9)
    t = a * ref
    return 10 * np.log10(np.sum(t**2) / (np.sum((est - t) ** 2) + 1e-9))


def write_noisy():
    for lang in LANGS:
        d = NOISY48 / lang; d.mkdir(parents=True, exist_ok=True)
        for fn, _ in load_set(lang, N):
            if (d / fn).exists():
                continue
            noisy = add_noise(read16k(DATA / "fleurs" / lang / "test" / fn), f"{lang}/{fn}")
            sf.write(d / fn, librosa.resample(noisy, orig_sr=SR, target_sr=48000), 48000)


def to16k_dir(src, dst):
    dst.mkdir(parents=True, exist_ok=True)
    for p in src.glob("*.wav"):
        a, sr = sf.read(p, dtype="float32", always_2d=True)
        sf.write(dst / p.name, librosa.resample(a.mean(1), orig_sr=sr, target_sr=SR), SR)


def run_dfn(cond, extra):
    for lang in LANGS:
        out = DATA / "enhanced" / cond / lang
        if out.exists() and len(list(out.glob("*.wav"))) >= N:
            continue
        tmp = DATA / "tmp48" / cond / lang
        files = sorted(str(p) for p in (NOISY48 / lang).glob("*.wav"))
        t = time.time()
        subprocess.run([str(ROOT / "bin" / "deep-filter"), "-D", *extra, "-o", str(tmp), *files],
                       check=True, capture_output=True)
        print(f"{cond} {lang} {time.time()-t:.1f}s", flush=True)
        to16k_dir(tmp, out)


MF2 = r'''
import sys, os
from clearvoice import ClearVoice
cv = ClearVoice(task="speech_enhancement", model_names=["MossFormer2_SE_48K"])
cv(input_path=sys.argv[1], online_write=True, output_path=sys.argv[2])
'''


def run_mf2():
    for lang in LANGS:
        out = DATA / "enhanced" / "mf2" / lang
        if out.exists() and len(list(out.glob("*.wav"))) >= N:
            continue
        tmp = DATA / "tmp48" / "mf2" / lang
        t = time.time()
        subprocess.run([str(ROOT.parent / ".venv-enh" / "bin" / "python"), "-c", MF2,
                        str(NOISY48 / lang), str(tmp)], check=True, cwd=DATA)
        print(f"mf2 {lang} {time.time()-t:.1f}s", flush=True)
        src = next((p.parent for p in tmp.rglob("*.wav")), tmp)  # clearvoice nests a model dir
        to16k_dir(src, out)


def report():
    for cond in ["noisy", "dfn3", "dfn3a12", "mf2"]:
        vals = []
        for lang in LANGS:
            for fn, _ in load_set(lang, N):
                clean = read16k(DATA / "fleurs" / lang / "test" / fn)
                if cond == "noisy":
                    est = add_noise(clean, f"{lang}/{fn}")
                else:
                    p = DATA / "enhanced" / cond / lang / fn
                    if not p.exists():
                        continue
                    est = read16k(p)
                vals.append(si_sdr(clean, est))
        if vals:
            print(f"SI-SDR {cond:8s} {np.mean(vals):6.2f} dB  (n={len(vals)})")


if __name__ == "__main__":
    write_noisy()
    run_dfn("dfn3", [])
    run_dfn("dfn3a12", ["-a", "12"])
    run_mf2()
    report()
