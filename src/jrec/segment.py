"""Conversation windows: speech regions -> padded, merged clip windows.

Rule: a window keeps at least `pad` seconds of raw audio before its first and after its
last speech, clamped only by the stream's own start and end. Windows whose padding
overlaps are merged, so the padding is never cut short to separate two windows.
"""
from dataclasses import dataclass

GAP = 180.0          # speech closer than this belongs to the same conversation
MIN_SPEECH = 20.0    # windows with less total speech are dropped
PAD = 600.0          # 10 min of raw audio kept on each side


@dataclass(frozen=True)
class Window:
    start: float         # clip start (padded)
    end: float           # clip end (padded)
    speech_start: float  # first speech
    speech_end: float    # last speech
    speech_sec: float    # total detected speech inside


def windows(regions, total, gap=GAP, min_speech=MIN_SPEECH, pad=PAD):
    """regions: sorted [(start, end)] speech seconds; total: stream length in seconds."""
    convs = []  # [first, last, speech_sec]
    for s, e in sorted(regions):
        if convs and s - convs[-1][1] <= gap:
            c = convs[-1]; c[1] = max(c[1], e); c[2] += e - s
        else:
            convs.append([s, e, e - s])
    convs = [c for c in convs if c[2] >= min_speech]
    out = []
    for first, last, sp in convs:
        w = [max(0.0, first - pad), min(total, last + pad), first, last, sp]
        if out and w[0] <= out[-1][1]:
            o = out[-1]; o[1] = max(o[1], w[1]); o[3] = max(o[3], last); o[4] += sp
        else:
            out.append(w)
    return [Window(*w) for w in out]


def chunks(regions, start, end, max_len=30.0, min_len=10.0):
    """Cover [start, end] with contiguous ASR chunks of at most max_len seconds.

    Nothing is dropped: VAD only chooses where to cut. Each cut lands in the middle of
    the widest VAD silence that falls between min_len and max_len into the chunk, or
    falls back to a hard cut at max_len.
    """
    gaps = []  # (gap_start, gap_end) between consecutive speech regions
    regs = sorted(r for r in regions if r[1] > start and r[0] < end)
    for (_, e1), (s2, _) in zip(regs, regs[1:]):
        if s2 > e1:
            gaps.append((e1, s2))
    out, t = [], start
    while end - t > max_len:
        lo, hi = t + min_len, t + max_len
        cands = [(min(g1, hi) - max(g0, lo), g0, g1) for g0, g1 in gaps if g1 > lo and g0 < hi]
        if cands:
            _, g0, g1 = max(cands)
            cut = (max(g0, lo) + min(g1, hi)) / 2
        else:
            cut = hi
        out.append((t, cut)); t = cut
    out.append((t, end))
    return out


def speech_regions(audio16k, threshold=0.5, min_silence_ms=500):
    """Silero VAD over a 16 kHz mono float array -> [(start, end)] seconds."""
    import torch
    from silero_vad import get_speech_timestamps, load_silero_vad
    model = load_silero_vad()
    ts = get_speech_timestamps(torch.from_numpy(audio16k), model, threshold=threshold,
                               min_silence_duration_ms=min_silence_ms, return_seconds=True)
    return [(t["start"], t["end"]) for t in ts]
