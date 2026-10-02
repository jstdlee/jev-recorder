"""Conversation summary via any OpenAI-compatible chat endpoint (config profiles).

Every key point / action item cites transcript line numbers, turned into clock times, so
each claim points back to the audio. Long transcripts are cut into chunks of
profile["chunk_chars"] (default 256k characters) that overlap by profile["overlap_chars"]
(default 8k), so nothing at a chunk boundary loses its context; the chunk notes are then
merged. Stored in the database (summary table) and as summary.json/.md in the folder.
"""
import json
from datetime import datetime
from pathlib import Path

from . import db
from .llm import ask as _ask, chat, parse_json as _parse_json  # noqa: F401 (re-exported for callers/tests)

CHUNK_CHARS = 256_000
OVERLAP_CHARS = 8_000

SCHEMA_HINT = """Return ONLY one JSON object, no prose, with exactly these keys:
{"title": str (max 12 words),
 "summary": str (3-6 sentences),
 "key_points": [{"text": str, "refs": [line numbers]}],
 "action_items": [{"text": str, "owner": str or null, "due": str or null, "refs": [line numbers]}],
 "people": [str], "places": [str],
 "language": str}
Use the conversation's main language for title/summary/points. Every key point and action
item must cite the [line numbers] it comes from. Do not invent facts that are not in the lines."""

NOTES_HINT = """This is one part of a longer conversation. Return ONLY one JSON object:
{"notes": [{"text": str, "refs": [line numbers]}], "people": [str], "places": [str]}
Cover every topic, decision, number, date and commitment. Cite [line numbers]."""


def _lines(segs):
    return [f"[{i}] {s['abs_start'][11:19]} {s.get('speaker') or '?'}: {s['text']}" for i, s in enumerate(segs)]


def chunk_lines(lines, size, overlap):
    """Split lines into chunks of <= size characters; each chunk starts with the last
    `overlap` characters' worth of lines from the previous chunk (context, not new work)."""
    chunks, cur, n = [], [], 0
    for ln in lines:
        if cur and n + len(ln) + 1 > size:
            chunks.append(cur)
            keep, k = [], 0
            for prev in reversed(cur):
                if k + len(prev) + 1 > overlap:
                    break
                keep.insert(0, prev)
                k += len(prev) + 1
            cur, n = keep, k
        cur.append(ln)
        n += len(ln) + 1
    if cur:
        chunks.append(cur)
    return chunks


def summarize_segments(segs, profile, progress=None):
    lines = _lines(segs)
    sys_msg = "You summarize transcribed conversations from a voice recorder, faithfully and concisely."
    size = int(profile.get("chunk_chars", CHUNK_CHARS))
    overlap = int(profile.get("overlap_chars", OVERLAP_CHARS))
    text = "\n".join(lines)
    if len(text) <= size:
        return _ask(profile, sys_msg, f"{SCHEMA_HINT}\n\nTranscript:\n{text}", ["title", "summary", "key_points"])
    notes = []
    parts = chunk_lines(lines, size, overlap)
    for k, part in enumerate(parts):
        if progress:
            progress("summary", k, len(parts) + 1)
        head = ("Lines before the first new line are repeated from the previous part for context only.\n"
                if k else "")
        d = _ask(profile, sys_msg, f"{NOTES_HINT}\n{head}\nTranscript part {k + 1} of {len(parts)}:\n" + "\n".join(part),
                 ["notes"])
        notes += d["notes"]
    merged = "\n".join(f"- {n['text']} {n.get('refs', [])}" for n in notes)
    return _ask(profile, sys_msg, f"{SCHEMA_HINT}\n\nNotes from all parts of the conversation (refs are line numbers):\n"
                                  f"{merged}", ["title", "summary", "key_points"])


def _cite(refs, segs):
    out = []
    for r in refs or []:
        try:
            out.append(segs[int(r)]["abs_start"][11:19])
        except (ValueError, IndexError, TypeError):
            pass
    return out


def summarize_folder(folder, profile, con=None, progress=None):
    folder = Path(folder)
    t = json.loads((folder / "transcript.json").read_text())
    segs = t["segments"]
    d = summarize_segments(segs, profile, progress)
    for k in ("key_points", "action_items"):
        for item in d.get(k, []):
            item["times"] = _cite(item.get("refs"), segs)
    d["_meta"] = {"model": profile["model"], "endpoint": profile["base_url"],
                  "created": datetime.now().astimezone().isoformat(timespec="seconds")}
    (folder / "summary.json").write_text(json.dumps(d, ensure_ascii=False, indent=1))
    if con is not None:
        db.save_summary(con, folder.name, d, profile["model"])
    md = [f"# {d['title']}", "", d["summary"], "", "## Key points"]
    md += [f"- {p['text']} ({', '.join(p['times'])})" for p in d.get("key_points", [])]
    if d.get("action_items"):
        md += ["", "## Action items"]
        md += [f"- [ ] {a['text']}" + (f" — {a['owner']}" if a.get("owner") else "") +
               (f" (due {a['due']})" if a.get("due") else "") + f" ({', '.join(a['times'])})" for a in d["action_items"]]
    md += ["", f"_Summarised by {profile['model']}; times link to transcript lines._"]
    (folder / "summary.md").write_text("\n".join(md) + "\n")
    return d
