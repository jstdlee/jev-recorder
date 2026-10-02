"""What the UI shows about one conversation. Read-only towards audio files: notes, translations,
speaker names and summaries come from the database."""
import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from .. import db

PEAK_HZ = 50                      # waveform bins per second


class Conversation:
    def __init__(self, folder, row):
        self.folder = Path(folder)
        self.name = self.folder.name
        self.status = row["status"]
        self.speech_start = datetime.fromisoformat(row["speech_start"])
        self.manifest = json.loads((self.folder / "manifest.json").read_text())
        w = self.manifest["window"]
        self.start = datetime.fromisoformat(w["start"])
        self.end = datetime.fromisoformat(w["end"])
        self.duration = (self.end - self.start).total_seconds()
        self.sp0 = (datetime.fromisoformat(w["speech_start"]) - self.start).total_seconds()
        self.sp1 = (datetime.fromisoformat(w["speech_end"]) - self.start).total_seconds()
        self.segments, self.summary, self.title = [], None, None
        self.notes, self.names, self.translations = [], {}, {}   # translations: {lang: {seg: text}}
        self.row_names, self.moments = {}, []
        self.insight = None
        self.peaks, self.gain, self.verified = None, 1.0, None

    def reload(self, con):
        t = self.folder / "transcript.json"
        if t.exists():
            self.segments = json.loads(t.read_text())["segments"]
            for s in self.segments:
                s["_t0"] = (datetime.fromisoformat(s["abs_start"]) - self.start).total_seconds()
                s["_t1"] = (datetime.fromisoformat(s["abs_end"]) - self.start).total_seconds()
        self.summary = db.get_summary(con, self.name)
        if self.summary is None and (self.folder / "summary.json").exists():
            self.summary = json.loads((self.folder / "summary.json").read_text())
        self.title = (self.summary or {}).get("title") or (self.segments[0]["text"][:60] if self.segments else None)
        self.notes = db.notes(con, self.name)
        self.names = db.speaker_names(con, self.name)
        self.row_names = db.row_speakers(con, self.name)
        self.moments = db.moments(con, self.name)
        self.insight = db.get_insight(con, self.name)
        self.translations = {lang: db.translations(con, self.name, lang, self.segments)
                             for lang in db.translated_langs(con, self.name)}

    @staticmethod
    def default_name(k):
        """S1 -> 'Char 1' until the user names the voice."""
        return f"Char {k[1:]}" if k and k[0] == "S" and k[1:].isdigit() else (k or "")

    def speaker(self, s, i=None):
        """Name shown for row i: the row's own name, else the voice's name, else Char N."""
        if i is None:
            i = next((j for j, x in enumerate(self.segments) if x is s), None)
        if i is not None and i in self.row_names:
            return self.row_names[i]
        k = s.get("speaker")
        return self.names.get(k) or self.default_name(k)

    def voice_rows(self, k):
        return [i for i, s in enumerate(self.segments) if s.get("speaker") == k]

    def load_peaks(self):
        cache = self.folder / "peaks.npy"
        if cache.exists():
            self.peaks = np.load(cache)
        else:
            chunks = []
            for p in self.manifest["parts"]:
                raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(self.folder / p["file"]), "-ac", "1",
                                      "-ar", "8000", "-f", "s16le", "-"], capture_output=True, check=True).stdout
                chunks.append(np.frombuffer(raw, np.int16))
            a = np.concatenate(chunks).astype(np.float32) / 32768.0
            n = 8000 // PEAK_HZ
            a = a[: len(a) // n * n].reshape(-1, n)
            self.peaks = np.stack([a.min(1), a.max(1)])
            np.save(cache, self.peaks)
        top = float(np.percentile(np.abs(self.peaks), 99.5)) if self.peaks.size else 0.0
        self.gain = min(30.0, 0.9 / top) if top > 1e-4 else 1.0

    def abs_at(self, t):
        return self.start + timedelta(seconds=t)

    def t_of_abs(self, dt):
        return (dt - self.start).total_seconds()

    def seg_at(self, t):
        return next((i for i, s in enumerate(self.segments) if s["_t0"] <= t < s["_t1"]), None)

    def speech_spans(self):
        """Transcript segments when available, else VAD regions (clip seconds), merged across < 1 s gaps."""
        raw = [(s["_t0"], s["_t1"]) for s in self.segments] or [tuple(r) for r in self.manifest["vad"]["regions_sec"]]
        out = []
        for a, b in sorted(raw):
            if out and a - out[-1][1] < 1.0:
                out[-1] = (out[-1][0], max(out[-1][1], b))
            else:
                out.append((a, b))
        return out

    def next_speech(self, t, direction=1):
        spans = self.speech_spans()
        if direction > 0:
            return next((a for a, _ in spans if a > t + 0.5), None)
        return next((a for a, _ in reversed(spans) if a < t - 1.0), None)

    def notes_in(self, t0, t1):
        return [n for n in self.notes if t0 <= n["t"] < t1]

    def matches(self, query, lang=None):
        """Segment indices whose shown text (original, or translation in `lang`) contains query."""
        q = query.strip().lower()
        if not q:
            return []
        tr = self.translations.get(lang, {}) if lang else {}
        return [i for i, s in enumerate(self.segments)
                if q in s["text"].lower() or q in tr.get(i, "").lower() or q in self.speaker(s, i).lower()]
