"""Translate transcript segments with the configured LLM; results are stored only in the database.

Batches of ~profile["translate_chars"] characters (default 6000); every batch gets the two
previous lines as context (not re-translated), so meaning carries across batch boundaries.
"""
import json
from pathlib import Path

from . import db
from .llm import ask

LANGS = ["English", "Chinese", "Cantonese", "Malay", "Indonesian", "Thai", "Vietnamese", "Japanese", "Korean", "Tamil"]
BATCH_CHARS = 6000
CONTEXT_LINES = 2

PROMPT = """Translate each numbered line into {to}. Keep names, numbers and times exact; keep the
speaker's tone; do not merge or split lines; do not add explanations. Lines under CONTEXT are only
for understanding and must not be translated. Return ONLY JSON: {{"t": [{{"i": number, "text": str}}]}}
"""


def batches(indices, segs, size):
    out, cur, n = [], [], 0
    for i in indices:
        L = len(segs[i]["text"])
        if cur and n + L > size:
            out.append(cur)
            cur, n = [], 0
        cur.append(i)
        n += L
    if cur:
        out.append(cur)
    return out


def translate_folder(folder, to, profile, con, rows=None, progress=None):
    folder = Path(folder)
    segs = json.loads((folder / "transcript.json").read_text(encoding="utf-8"))["segments"]
    have = db.translations(con, folder.name, to, segs)
    todo = [i for i in (rows if rows is not None else range(len(segs))) if i not in have and segs[i]["text"].strip()]
    groups = batches(todo, segs, int(profile.get("translate_chars", BATCH_CHARS)))
    done = 0
    for g in groups:
        if progress:
            progress("translate", done, len(todo))
        ctx = [segs[j]["text"] for j in range(max(0, g[0] - CONTEXT_LINES), g[0])]
        body = (("CONTEXT:\n" + "\n".join(ctx) + "\n\n") if ctx else "") + "LINES:\n" + \
            "\n".join(f"[{i}] {segs[i]['text']}" for i in g)
        d = ask(profile, "You are a careful, faithful translator.", PROMPT.format(to=to) + "\n" + body, ["t"])
        got = {int(x["i"]): x["text"] for x in d["t"] if "i" in x and "text" in x}
        db.save_translations(con, folder.name, to, [(i, segs[i]["text"], got[i]) for i in g if i in got], profile["model"])
        done += len(g)
    if progress:
        progress("translate", len(todo), len(todo))
    return db.translations(con, folder.name, to, segs)
