"""M0 ASR benchmark on FLEURS test (Asian languages + English).

Each model transcribes N utterances per language, with no language hint (so language
ID is tested too), under three conditions: clean, noisy (babble + pink noise at 5 dB SNR,
like a pocket recorder) and enhanced (the noisy audio after the selected enhancer, if
there is a cache for it).
Writes results/asr_<model>.jsonl and prints a CER/WER table.

usage: asr_bench.py MODEL [--n 60] [--langs ...] [--conds clean,noisy]
"""
import argparse, csv, json, random, re, sys, time, unicodedata
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).parent
DATA = ROOT / "data"
RES = ROOT / "results"
LANGS = ["yue_hant_hk", "cmn_hans_cn", "en_us", "ms_my", "id_id", "ta_in", "th_th", "vi_vn"]
CHAR_LANGS = {"yue_hant_hk", "cmn_hans_cn", "th_th"}  # scored by CER
WHISPER_LANG = {"yue_hant_hk": "yue", "cmn_hans_cn": "zh", "en_us": "en", "ms_my": "ms",
                "id_id": "id", "ta_in": "ta", "th_th": "th", "vi_vn": "vi"}
SR = 16000


def load_set(lang, n, seed=0):
    rows = list(csv.reader(open(DATA / "fleurs" / lang / "test.tsv"), delimiter="\t",
                           quoting=csv.QUOTE_NONE))
    seen, uniq = set(), []
    for r in rows:  # one recording per sentence id
        if r[0] not in seen:
            seen.add(r[0]); uniq.append(r)
    random.Random(seed).shuffle(uniq)
    return [(r[1], r[2]) for r in uniq[:n]]


def read16k(path):
    a, sr = sf.read(path, dtype="float32", always_2d=True)
    a = a.mean(1)
    if sr != SR:
        import librosa
        a = librosa.resample(a, orig_sr=sr, target_sr=SR)
    return a


def pink(n, rng):
    w = np.fft.rfft(rng.standard_normal(n))
    f = np.arange(len(w)); f[0] = 1
    x = np.fft.irfft(w / np.sqrt(f), n)
    return x / (np.abs(x).max() + 1e-9)


_babble_pool = None


def add_noise(clean, key, snr_db=5.0):
    """Deterministic babble (3 talkers from other languages) + pink noise at snr_db."""
    global _babble_pool
    if _babble_pool is None:
        _babble_pool = [read16k(DATA / "fleurs" / l / "test" / f)
                        for l in LANGS for f, _ in load_set(l, 4, seed=99)]
    rng = np.random.default_rng(abs(hash(key)) % 2**32)
    n = len(clean)
    bab = np.zeros(n, np.float32)
    for i in rng.choice(len(_babble_pool), 3, replace=False):
        b = np.resize(_babble_pool[i], n)
        bab += np.roll(b, rng.integers(n)) / 3
    noise = 0.6 * bab / (np.std(bab) + 1e-9) + 0.4 * pink(n, rng).astype(np.float32) / 0.3
    p_s, p_n = np.mean(clean**2), np.mean(noise**2)
    noise *= np.sqrt(p_s / (p_n * 10 ** (snr_db / 10)))
    y = clean + noise
    return (y / max(1.0, np.abs(y).max())).astype(np.float32)


def load_audio(lang, fname, cond):
    clean = read16k(DATA / "fleurs" / lang / "test" / fname)
    if cond == "clean":
        return clean
    noisy = add_noise(clean, f"{lang}/{fname}")
    if cond == "noisy":
        return noisy
    enh = DATA / "enhanced" / cond / lang / fname  # produced by enhance_bench.py
    if not enh.exists():
        raise FileNotFoundError(enh)
    return read16k(enh)


# ---------- scoring ----------
_cc = None


def norm(text, lang):
    global _cc
    t = unicodedata.normalize("NFKC", text).lower()
    if lang in ("yue_hant_hk", "cmn_hans_cn"):
        if _cc is None:
            import opencc
            _cc = opencc.OpenCC("t2s")
        t = _cc.convert(t)
    t = "".join(ch if not unicodedata.category(ch).startswith(("P", "S")) else " " for ch in t)
    if lang in CHAR_LANGS:
        return "".join(t.split())
    return " ".join(t.split())


def score(rows):
    import jiwer
    by = {}
    for r in rows:
        by.setdefault((r["lang"], r["cond"]), []).append(r)
    out = {}
    for (lang, cond), rs in by.items():
        refs = [norm(r["ref"], lang) for r in rs]
        hyps = [norm(r["hyp"], lang) for r in rs]
        if lang in CHAR_LANGS:
            e = jiwer.cer(refs, [h or "∅" for h in hyps])
        else:
            e = jiwer.wer(refs, [h or "∅" for h in hyps])
        out[(lang, cond)] = e
    return out


# ---------- models ----------
class QwenASR:
    def __init__(self, size):
        import torch
        from qwen_asr import Qwen3ASRModel
        self.m = Qwen3ASRModel.from_pretrained(
            f"Qwen/Qwen3-ASR-{size}", dtype=torch.bfloat16, device_map="cuda:0",
            max_inference_batch_size=16, max_new_tokens=512)

    def run(self, audios, lang):
        res = self.m.transcribe(audio=[(a, SR) for a in audios])
        return [(r.text, r.language) for r in res]


class Whisper:
    def __init__(self, name):
        import torch
        from transformers import pipeline
        self.p = pipeline("automatic-speech-recognition", model=f"openai/{name}",
                          dtype=torch.bfloat16, device="cuda:0")

    def run(self, audios, lang):
        out = self.p([{"raw": a, "sampling_rate": SR} for a in audios], batch_size=16,
                     generate_kwargs={"task": "transcribe"}, return_language=True)
        return [(o["text"], (o.get("chunks") or [{}])[0].get("language", "")) for o in out]


MODELS = {
    "qwen3-asr-1.7b": lambda: QwenASR("1.7B"),
    "qwen3-asr-0.6b": lambda: QwenASR("0.6B"),
    "whisper-large-v3": lambda: Whisper("whisper-large-v3"),
    "whisper-large-v3-turbo": lambda: Whisper("whisper-large-v3-turbo"),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model", choices=MODELS)
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--langs", default=",".join(LANGS))
    ap.add_argument("--conds", default="clean,noisy")
    a = ap.parse_args()
    RES.mkdir(exist_ok=True)
    out_path = RES / f"asr_{a.model}.jsonl"
    done = set()
    if out_path.exists():
        for line in open(out_path):
            r = json.loads(line); done.add((r["lang"], r["cond"]))
    t0 = time.time(); model = MODELS[a.model](); print(f"load {time.time()-t0:.1f}s", flush=True)
    with open(out_path, "a") as f:
        for lang in a.langs.split(","):
            items = load_set(lang, a.n)
            for cond in a.conds.split(","):
                if (lang, cond) in done:
                    continue
                try:
                    audios = [load_audio(lang, fn, cond) for fn, _ in items]
                except FileNotFoundError as e:
                    print("skip (no enhanced audio)", lang, cond, e); continue
                dur = sum(len(x) for x in audios) / SR
                t = time.time(); hyps = model.run(audios, lang); el = time.time() - t
                for (fn, ref), (hyp, lid) in zip(items, hyps):
                    f.write(json.dumps({"model": a.model, "lang": lang, "cond": cond, "file": fn,
                                        "ref": ref, "hyp": hyp, "lid": lid,
                                        "rtf": el / dur}, ensure_ascii=False) + "\n")
                f.flush()
                print(f"{lang:12s} {cond:8s} {dur:6.0f}s audio in {el:5.1f}s (x{dur/el:.0f} realtime)",
                      flush=True)
    rows = [json.loads(l) for l in open(out_path)]
    for (lang, cond), e in sorted(score(rows).items()):
        print(f"  {lang:12s} {cond:10s} {'CER' if lang in CHAR_LANGS else 'WER'} {e*100:5.1f}%")


if __name__ == "__main__":
    main()
