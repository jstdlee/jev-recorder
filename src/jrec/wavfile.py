"""WAV (RIFF/RF64-free) data-chunk index and sample-exact cuts.

A clip's audio payload is the exact byte range original[data_start + a : data_start + b],
with a fresh 44-byte header in front. The manifest records that range, so the payload can
be verified against the original with dd + sha256sum (skip the clip's 44-byte header).
"""
import struct
from dataclasses import dataclass


@dataclass(frozen=True)
class WavIndex:
    data_start: int
    data_size: int
    sample_rate: int
    channels: int
    block_align: int
    bits: int
    fmt_tag: int

    @property
    def n_frames(self):
        return self.data_size // self.block_align

    @property
    def duration(self):
        return self.n_frames / self.sample_rate


def index(path):
    with open(path, "rb") as f:
        riff, _, wave = struct.unpack("<4sI4s", f.read(12))
        if riff != b"RIFF" or wave != b"WAVE":
            raise ValueError(f"not a RIFF/WAVE file: {path}")
        fmt = None
        while True:
            h = f.read(8)
            if len(h) < 8:
                raise ValueError(f"no data chunk in {path}")
            cid, size = struct.unpack("<4sI", h)
            if cid == b"fmt ":
                tag, ch, sr, _, ba, bits = struct.unpack("<HHIIHH", f.read(16))
                f.seek(size - 16 + (size & 1), 1)
                fmt = (tag, ch, sr, ba, bits)
            elif cid == b"data":
                if fmt is None:
                    raise ValueError(f"data before fmt in {path}")
                start = f.tell()
                f.seek(0, 2)
                size = min(size, f.tell() - start)  # recorder may die before patching sizes
                tag, ch, sr, ba, bits = fmt
                return WavIndex(start, size - size % ba, sr, ch, ba, bits, tag)
            else:
                f.seek(size + (size & 1), 1)


def cut(src, dst, t0, t1, idx=None):
    idx = idx or index(src)
    a = max(0, min(idx.n_frames, int(t0 * idx.sample_rate)))
    b = max(a, min(idx.n_frames, int(-(-t1 * idx.sample_rate // 1))))
    b0, b1 = idx.data_start + a * idx.block_align, idx.data_start + b * idx.block_align
    n = b1 - b0
    with open(src, "rb") as f, open(dst, "wb") as g:
        g.write(struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + n, b"WAVE", b"fmt ", 16, idx.fmt_tag,
                            idx.channels, idx.sample_rate, idx.sample_rate * idx.block_align,
                            idx.block_align, idx.bits, b"data", n))
        f.seek(b0)
        left = n
        while left:
            chunk = f.read(min(left, 1 << 22))
            g.write(chunk)
            left -= len(chunk)
    return {"byte_start": b0, "byte_end": b1, "frame_start": a, "frame_end": b,
            "t_start": a / idx.sample_rate, "t_end": b / idx.sample_rate, "header_bytes": 44}
