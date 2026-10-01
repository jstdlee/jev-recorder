"""MP3 frame index and byte-exact cuts.

A clip is the exact byte range original[frame_i_start : frame_j_start], so anyone can
verify it with dd + sha256sum. Frame k starts at sample k * samples_per_frame, which gives
exact times for every cut. A leading Xing/Info/VBRI tag frame holds no audio and is skipped.
"""
import mmap
from dataclasses import dataclass
from pathlib import Path

_BR_V1_L3 = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]
_BR_V2_L3 = [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0]
_SR = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}  # by version bits


@dataclass(frozen=True)
class FrameIndex:
    offsets: list          # byte offset of each audio frame, plus one final entry = end of audio data
    sample_rate: int
    samples_per_frame: int
    channels: int

    @property
    def n_frames(self):
        return len(self.offsets) - 1

    @property
    def duration(self):
        return self.n_frames * self.samples_per_frame / self.sample_rate

    def frame_at(self, t):
        """Index of the frame containing time t (clamped)."""
        k = int(t * self.sample_rate // self.samples_per_frame)
        return max(0, min(self.n_frames, k))

    def time_of(self, k):
        return k * self.samples_per_frame / self.sample_rate


def _header(b):
    """Parse a 4-byte MPEG audio Layer III header. Returns (length, sr, spf, channels) or None."""
    if len(b) < 4 or b[0] != 0xFF or (b[1] & 0xE0) != 0xE0:
        return None
    ver = (b[1] >> 3) & 3          # 3 = MPEG1, 2 = MPEG2, 0 = MPEG2.5, 1 reserved
    layer = (b[1] >> 1) & 3        # 1 = Layer III
    bri, sri, pad = b[2] >> 4, (b[2] >> 2) & 3, (b[2] >> 1) & 1
    if ver == 1 or layer != 1 or bri in (0, 15) or sri == 3:
        return None
    sr = _SR[ver][sri]
    if ver == 3:
        br, spf, coef = _BR_V1_L3[bri], 1152, 144
    else:
        br, spf, coef = _BR_V2_L3[bri], 576, 72
    channels = 1 if (b[3] >> 6) == 3 else 2
    return coef * br * 1000 // sr + pad, sr, spf, channels


def _id3v2_size(m):
    if m[:3] == b"ID3" and len(m) >= 10:
        s = m[6:10]
        size = (s[0] << 21) | (s[1] << 14) | (s[2] << 7) | s[3]
        return 10 + size + (10 if m[5] & 0x10 else 0)  # footer flag
    return 0


def _is_tag_frame(m, off, length):
    head = m[off:off + min(length, 64)]
    return b"Xing" in head or b"Info" in head or b"VBRI" in head


def index(path):
    path = Path(path)
    with open(path, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:
        n = len(m)
        off = _id3v2_size(m)
        end = n - 128 if n >= 128 and m[n - 128:n - 125] == b"TAG" else n  # ID3v1 at the end
        offsets, fmt = [], None
        while off + 4 <= end:
            h = _header(m[off:off + 4])
            if h is None or (fmt and (h[1], h[2]) != fmt[:2]):
                # lost sync (junk or a mid-file tag): scan forward for the next valid header
                nxt = m.find(b"\xff", off + 1, end)
                if nxt < 0:
                    break
                off = nxt
                continue
            length, sr, spf, ch = h
            if off + length > end:
                break  # truncated last frame: not playable, so not counted
            if fmt is None:
                fmt = (sr, spf, ch)
                if _is_tag_frame(m, off, length):
                    off += length
                    continue
            offsets.append(off)
            off += length
        if not offsets:
            raise ValueError(f"no MP3 frames in {path}")
        offsets.append(off)
    return FrameIndex(offsets, fmt[0], fmt[1], fmt[2])


def cut(src, dst, t0, t1, idx=None):
    """Copy the frames covering [t0, t1) from src to dst, byte for byte.

    Returns {byte_start, byte_end, frame_start, frame_end, t_start, t_end} with the exact
    times of the copied range (which can be a few ms wider than asked, to whole frames).
    """
    idx = idx or index(src)
    i = idx.frame_at(t0)
    j = min(idx.n_frames, max(i + 1, -(-int(t1 * idx.sample_rate) // idx.samples_per_frame)))
    b0, b1 = idx.offsets[i], idx.offsets[j]
    with open(src, "rb") as f, open(dst, "wb") as g:
        f.seek(b0)
        left = b1 - b0
        while left:
            chunk = f.read(min(left, 1 << 22))
            g.write(chunk)
            left -= len(chunk)
    return {"byte_start": b0, "byte_end": b1, "frame_start": i, "frame_end": j,
            "t_start": idx.time_of(i), "t_end": idx.time_of(j)}
