"""Recording start time from filename + file mtime (+ duration).

The TX660 names files YYMMDD_HHMM (start, local time, minute precision), and the FAT mtime
is the moment the file was closed, so start = mtime - duration. When the two agree within
the filename's minute, we get second precision with high confidence. Disagreements are
kept and flagged, never silently resolved:
  mtime_tz_shift    mtime is off by whole hours (FAT has no timezone), corrected
  timeline_gap      the file is shorter than the wall time that passed (VOR / pause)
  mtime_mismatch    mtime does not fit the filename at all; the filename wins
"""
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TOL = 3.0  # seconds: FAT 2 s mtime resolution + close latency


@dataclass
class StartTime:
    start: datetime          # timezone-aware
    source: str              # filename+mtime | filename | mtime
    confidence: str          # high | medium | low
    flags: list = field(default_factory=list)

    def as_dict(self):
        return {"start": self.start.isoformat(), "source": self.source,
                "confidence": self.confidence, "flags": self.flags}


def filename_minute(name, pattern, tz):
    m = re.search(pattern, name)
    if not m:
        return None
    d, hm = m.group(1), m.group(2)
    return datetime(2000 + int(d[:2]), int(d[2:4]), int(d[4:6]), int(hm[:2]), int(hm[2:]),
                    tzinfo=ZoneInfo(tz))


def recording_start(name, mtime, duration, tz, pattern):
    """name: file name; mtime: epoch seconds (as read from the mounted device);
    duration: seconds of audio; tz: IANA zone of the device clock; pattern: filename regex."""
    fn = filename_minute(name, pattern, tz)
    est = datetime.fromtimestamp(mtime - duration, tz=timezone.utc).astimezone(ZoneInfo(tz)) \
        if mtime is not None else None
    if fn is None:
        if est is None:
            raise ValueError(f"no time source for {name}")
        return StartTime(est, "mtime", "low", ["no_filename_time"])
    if est is None:
        return StartTime(fn, "filename", "medium", ["minute_precision"])
    d = (est - fn).total_seconds()
    if -TOL <= d < 60 + TOL:
        return StartTime(fn + timedelta(seconds=min(max(d, 0.0), 59.999)), "filename+mtime", "high")
    k = round(d / 3600)
    r = d - k * 3600
    if k and abs(k) <= 14 and -TOL <= r < 60 + TOL:
        return StartTime(fn + timedelta(seconds=min(max(r, 0.0), 59.999)), "filename+mtime", "high",
                         [f"mtime_tz_shift:{k:+d}h"])
    if d >= 60 + TOL:
        # closed later than start + duration: the recording paused (VOR) or lost audio
        return StartTime(fn, "filename", "medium", ["minute_precision", f"timeline_gap:{d-60:.0f}s"])
    return StartTime(fn, "filename", "medium", ["minute_precision", f"mtime_mismatch:{d:.0f}s"])
