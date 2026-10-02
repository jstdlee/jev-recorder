"""Conversation folder -> transcript with speakers, word times and absolute clock times.

ASR: Qwen3-ASR-1.7B on raw audio (M0: denoised input hurts). Every second of the speech
span is transcribed (contiguous chunks cut in silences); in the padding, only chunks that
VAD marks as speech. The conversation language is detected from the first chunks and
forced only when one language clearly dominates, so code-switching is not suppressed.
Word times: Qwen3-ForcedAligner where supported, MMS CTC aligner otherwise.
"""
import json
import re
import subprocess
import tempfile
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from . import diarize, segment

SR = 16000
ASR_MODEL = "Qwen/Qwen3-ASR-1.7B"
ALIGNER_MODEL = "Qwen/Qwen3-ForcedAligner-0.6B"
QWEN_ALIGN = {"Chinese", "Cantonese", "English", "Japanese", "Korean", "German", "Spanish", "French",
              "Italian", "Portuguese", "Russian"}
MMS_ISO = {"Malay": "msa", "Indonesian": "ind", "Thai": "tha", "Vietnamese": "vie", "Filipino": "tgl",
           "Hindi": "hin", "Arabic": "ara", "Turkish": "tur", "Dutch": "nld", "Persian": "fas"}
NO_SPACE = {"Chinese", "Cantonese", "Japanese", "Thai"}
LANG_DOMINANCE = 0.7
LANG_PROBE_CHUNKS = 6


# ---------- audio ----------
def load_clip(folder, manifest):
    """Decode all parts, concatenated. Returns (audio, parts) with parts = [(clip_t0, clip_t1, abs_start)]."""
    pieces, parts, t = [], [], 0.0
    for p in manifest["parts"]:
        raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(Path(folder) / p["file"]), "-ac", "1",
                              "-ar", str(SR), "-f", "f32le", "-"], capture_output=True, check=True).stdout
        a = np.frombuffer(raw, np.float32)
        pieces.append(a)
        parts.append((t, t + len(a) / SR, datetime.fromisoformat(p["abs_start"])))
        t += len(a) / SR
    return np.concatenate(pieces), parts


def clip_to_abs(t, parts):
    for t0, t1, abs0 in parts:
        if t < t1 or (t0, t1, abs0) == parts[-1]:
            return abs0 + timedelta(seconds=max(0.0, t - t0))


def pick_chunks(regions, total, speech_start, speech_end, max_len=30.0):
    """Contiguous chunks over the clip; keep all inside the speech span, VAD-speech ones in the padding."""
    keep = []
    for a, b in segment.chunks(regions, 0.0, total, max_len=max_len):
        inside = b > speech_start - 1.0 and a < speech_end + 1.0
        if inside or any(e > a and s < b for s, e in regions):
            keep.append((a, b))
    return keep


# ---------- models ----------
class Engine:
    def __init__(self, device="cuda:0"):
        import torch
        from qwen_asr import Qwen3ASRModel
        self.asr = Qwen3ASRModel.from_pretrained(
            ASR_MODEL, dtype=torch.bfloat16, device_map=device, max_inference_batch_size=16, max_new_tokens=1024,
            forced_aligner=ALIGNER_MODEL, forced_aligner_kwargs={"dtype": torch.bfloat16, "device_map": device})
        self.device = device
        self._mms = None

    def transcribe(self, pieces, language=None):
        return self.asr.transcribe(audio=[(p, SR) for p in pieces],
                                   language=[language] * len(pieces) if language else None)

    def align_qwen(self, pieces, texts, langs):
        return self.asr.forced_aligner.align(audio=[(p, SR) for p in pieces], text=texts, language=langs)

    def align_mms(self, piece, text, lang):
        import torch
        from ctc_forced_aligner import (generate_emissions, get_alignments, get_spans, load_alignment_model,
                                        postprocess_results, preprocess_text)
        if self._mms is None:
            self._mms = load_alignment_model(self.device.split(":")[0], dtype=torch.float16)
        model, tok = self._mms
        wav = torch.from_numpy(piece).to(model.dtype).to(model.device)
        em, stride = generate_emissions(model, wav, batch_size=4)
        tt, txt = preprocess_text(text, romanize=True, language=MMS_ISO[lang])
        segs, scores, blank = get_alignments(em, tt, tok)
        return [(w["text"], w["start"], w["end"]) for w in postprocess_results(txt, get_spans(tt, segs, blank), stride, scores)]


def conversation_language(results):
    langs = [r.language.split(",")[0] for r in results if r.text.strip() and r.language]
    if not langs:
        return None, {}
    counts = Counter(langs)
    top, n = counts.most_common(1)[0]
    return (top if n / len(langs) >= LANG_DOMINANCE else None), dict(counts)


# ---------- assembly ----------
_PUNCT = re.compile(r"[\s]*[,.!?;:，。！？；：、…」』）)\]\"'”’]*")


def _spans(text, tokens):
    """Locate each aligner token in the ASR text, in order. Returns [(i0, i1) | None]."""
    out, cur, low = [], 0, text.lower()
    for t in tokens:
        i = low.find(t.lower(), cur) if t else -1
        if i < 0 or i - cur > 40:  # not found nearby: keep cursor, mark missing
            out.append(None)
            continue
        out.append((i, i + len(t)))
        cur = i + len(t)
    return out


def _seg_text(words, texts, lang):
    """Segment text from the original chunk text (keeps punctuation), token join as fallback."""
    parts, group = [], []
    for w in words + [None]:
        if group and (w is None or w.get("c") != group[0].get("c") or w.get("span") is None):
            spans = [g["span"] for g in group if g.get("span")]
            if spans and group[0].get("c") is not None:
                t = texts[group[0]["c"]]
                i0, i1 = spans[0][0], spans[-1][1]
                i1 += len(_PUNCT.match(t, i1).group(0).rstrip())
                parts.append(t[i0:i1])
            else:
                parts.append(_join([g["w"] for g in group], lang))
            group = []
        if w is not None:
            if w.get("span") is None:
                parts.append(w["w"])
            else:
                group.append(w)
    return _join([p for p in parts if p], lang)


def _join(tokens, lang):
    out = ""
    for t in tokens:
        if out and (lang not in NO_SPACE or (out[-1].isascii() and out[-1].isalnum() and t[:1].isascii() and t[:1].isalnum())):
            out += " "
        out += t
    return out


def _speaker_at(s, e, diar):
    best, best_ov = None, 0.0
    for d in diar:
        ov = min(e, d["end"]) - max(s, d["start"])
        if ov > best_ov:
            best, best_ov = d["speaker"], ov
    if best is None and diar:  # nearest segment for words in diarization gaps
        best = min(diar, key=lambda d: min(abs(d["start"] - e), abs(d["end"] - s)))["speaker"]
    return best


def build_segments(words, diar, max_gap=1.0, max_len=25.0, texts=None):
    for w in words:
        w["speaker"] = _speaker_at(w["s"], w["e"], diar) if diar else None
    segs = []
    for w in words:
        cur = segs[-1] if segs else None
        if cur and w["speaker"] == cur["speaker"] and w["lang"] == cur["lang"] and w["s"] - cur["end"] <= max_gap \
                and w["e"] - cur["start"] <= max_len:
            cur["words"].append(w); cur["end"] = w["e"]
        else:
            segs.append({"start": w["s"], "end": w["e"], "speaker": w["speaker"], "lang": w["lang"], "words": [w]})
    for s in segs:
        s["text"] = _seg_text(s["words"], texts or {}, s["lang"])
        for w in s["words"]:
            w.pop("span", None); w.pop("c", None)
    return segs


def _ts(t, sep=","):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d}{sep}{ms % 1000:03d}"


def write_outputs(folder, segs, parts, meta):
    folder = Path(folder)
    for s in segs:
        s["abs_start"] = clip_to_abs(s["start"], parts).isoformat(timespec="milliseconds")
        s["abs_end"] = clip_to_abs(s["end"], parts).isoformat(timespec="milliseconds")
        for w in s["words"]:
            w["abs"] = clip_to_abs(w["s"], parts).isoformat(timespec="milliseconds")
    (folder / "transcript.json").write_text(json.dumps({**meta, "segments": segs}, ensure_ascii=False, indent=1))
    spk = lambda s: f"[{s['speaker']}] " if s["speaker"] else ""
    with open(folder / "transcript.srt", "w") as f:
        for i, s in enumerate(segs, 1):
            f.write(f"{i}\n{_ts(s['start'])} --> {_ts(s['end'])}\n{spk(s)}{s['text']}\n\n")
    with open(folder / "transcript.vtt", "w") as f:
        f.write("WEBVTT\n\n")
        for s in segs:
            f.write(f"{_ts(s['start'], '.')} --> {_ts(s['end'], '.')}\n{spk(s)}{s['text']}\n\n")
    with open(folder / "labels.txt", "w") as f:  # Audacity label track
        for s in segs:
            f.write(f"{s['start']:.3f}\t{s['end']:.3f}\t{spk(s)}{s['text'][:80]}\n")
    with open(folder / "transcript.md", "w") as f:
        f.write(f"# {folder.name}\n\nlanguage: {meta['language'] or 'mixed'} {meta['language_counts']}\n\n")
        for s in segs:
            f.write(f"**{s['abs_start'][11:19]}** {spk(s)}{s['text']}\n\n")


def _nemotron(audio):
    import soundfile as sf
    with tempfile.TemporaryDirectory() as td:
        sf.write(Path(td) / "a.wav", audio, SR)
        return diarize.run(Path(td) / "a.wav", Path(td) / "d.json")


ASR_BATCH = 16


def transcribe_folder(folder, engine, use_diarization=True, log=print, diarizer=None, progress=None):
    """diarizer(audio16k) -> [{start, end, speaker}]; defaults to Nemotron in its own venv.
    progress(stage, done, total) is called as work advances (stages: asr, align, speakers)."""
    progress = progress or (lambda *a: None)
    folder = Path(folder)
    m = json.loads((folder / "manifest.json").read_text())
    audio, parts = load_clip(folder, m)
    total = len(audio) / SR
    w0 = datetime.fromisoformat(m["window"]["start"])
    sp0 = (datetime.fromisoformat(m["window"]["speech_start"]) - w0).total_seconds()
    sp1 = (datetime.fromisoformat(m["window"]["speech_end"]) - w0).total_seconds()
    regions = [tuple(r) for r in m["vad"]["regions_sec"]]
    chunks = pick_chunks(regions, total, sp0, sp1)
    pieces = [audio[int(a * SR):int(b * SR)] for a, b in chunks]
    # language: probe the first speech chunks, force only a clearly dominant language
    n = len(pieces)
    progress("asr", 0, n)
    probe = engine.transcribe(pieces[:LANG_PROBE_CHUNKS])
    lang, counts = conversation_language(probe)
    log(f"  {len(chunks)} chunks ({sum(b - a for a, b in chunks):.0f}s of {total:.0f}s), language {lang or 'mixed'} {counts}")
    res = list(probe if lang is None else engine.transcribe(pieces[:LANG_PROBE_CHUNKS], lang))
    progress("asr", len(res), n)
    for k in range(LANG_PROBE_CHUNKS, n, ASR_BATCH):
        res += list(engine.transcribe(pieces[k:k + ASR_BATCH], lang))
        progress("asr", len(res), n)
    # word times
    words = []
    q = [i for i, r in enumerate(res) if r.text.strip() and r.language.split(",")[0] in QWEN_ALIGN]
    progress("align", 0, n)
    if q:
        al = engine.align_qwen([pieces[i] for i in q], [res[i].text for i in q], [res[i].language.split(",")[0] for i in q])
        for i, a in zip(q, al):
            items = list(a)
            for it, sp in zip(items, _spans(res[i].text, [it.text for it in items])):
                words.append({"w": it.text, "s": chunks[i][0] + it.start_time, "e": chunks[i][0] + it.end_time,
                              "lang": res[i].language.split(",")[0], "c": i, "span": sp})
    for i, r in enumerate(res):
        lg = r.language.split(",")[0] if r.language else ""
        if not r.text.strip() or i in q:
            continue
        if lg in MMS_ISO:
            al = engine.align_mms(pieces[i], r.text, lg)
            for (t, s0, e0), sp in zip(al, _spans(r.text, [t for t, _, _ in al])):
                words.append({"w": t, "s": chunks[i][0] + s0, "e": chunks[i][0] + e0, "lang": lg, "c": i, "span": sp})
        else:  # no aligner: one item spanning the chunk, flagged
            words.append({"w": r.text, "s": chunks[i][0], "e": chunks[i][1], "lang": lg or "unknown", "unaligned": True})
    words.sort(key=lambda w: w["s"])
    progress("align", n, n)
    if use_diarization:
        progress("speakers", 0, 1)
    diar = (diarizer or _nemotron)(audio) if use_diarization else []
    progress("speakers", 1, 1)
    segs = build_segments(words, diar, texts={i: r.text for i, r in enumerate(res)})
    meta = {"conversation": m["conversation"], "asr": ASR_MODEL, "aligners": [ALIGNER_MODEL, "MMS ctc-forced-aligner"],
            "diarization": diarize.MODEL if use_diarization else None, "language": lang, "language_counts": counts,
            "chunks": [[round(a, 2), round(b, 2)] for a, b in chunks],
            "created": datetime.now().astimezone().isoformat(timespec="seconds")}
    write_outputs(folder, segs, parts, meta)
    return segs
