"""Parse "go to" positions typed by the user. Returns seconds from the clip start, or None.

  14:15:30 / 14:15     clock time (the clip's date; past midnight rolls over)
  +30  +1:30  -0:10    relative to the playhead
  @5:00  @90           from the start of the clip
  2:30  90             also from the start of the clip
"""
import re
from datetime import datetime, timedelta


def _secs(txt):
    parts = txt.split(":")
    if not all(re.fullmatch(r"\d+(\.\d+)?", p) for p in parts) or len(parts) > 3:
        return None
    v = 0.0
    for p in parts:
        v = v * 60 + float(p)
    return v


def parse(text, clip_start, playhead, duration):
    s = text.strip().replace(" ", "")
    if not s:
        return None
    if s[0] in "+-":
        v = _secs(s[1:])
        t = None if v is None else playhead + (v if s[0] == "+" else -v)
    elif s[0] == "@":
        t = _secs(s[1:])
    elif re.fullmatch(r"\d{1,2}:\d{2}(:\d{2}(\.\d+)?)?", s) and int(s.split(":")[0]) < 24 and \
            (len(s.split(":")) == 3 or int(s.split(":")[0]) >= 1 and _clock_plausible(s, clip_start, duration)):
        hh, mm, *ss = s.split(":")
        dt = clip_start.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0) + \
            timedelta(seconds=float(ss[0]) if ss else 0)
        if dt < clip_start - timedelta(hours=12):
            dt += timedelta(days=1)
        t = (dt - clip_start).total_seconds()
    else:
        t = _secs(s)
    if t is None:
        return None
    return max(0.0, min(duration, t))


def _clock_plausible(s, clip_start, duration):
    """'14:15' is a clock time when it falls within the clip; otherwise mm:ss from the start."""
    hh, mm = (int(x) for x in s.split(":")[:2])
    dt = clip_start.replace(hour=hh, minute=mm, second=0, microsecond=0)
    for d in (dt, dt + timedelta(days=1)):
        off = (d - clip_start).total_seconds()
        if -60 <= off <= duration + 60:
            return True
    return False
