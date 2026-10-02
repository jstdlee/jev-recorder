"""Conversation summary via any OpenAI-compatible chat endpoint (config profiles).

Every key point / action item cites transcript line numbers, turned into clock times, so
each claim points back to the audio. Long transcripts: chunk -> notes -> merged summary.
Written for small models: plain JSON schema in the prompt, validated, retried.
"""
import json
import os
import re
import urllib.request
from datetime import datetime
from pathlib import Path

CHUNK_CHARS = 24000

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


def chat(profile, system, user):
    body = {"model": profile["model"], "messages": [{"role": "system", "content": system},
                                                    {"role": "user", "content": user}],
            "temperature": 0.2, "max_tokens": profile.get("max_tokens", 4096), **profile.get("extra_body", {})}
    req = urllib.request.Request(profile["base_url"].rstrip("/") + "/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    key = os.environ.get(profile["api_key_env"]) if profile.get("api_key_env") else profile.get("api_key")
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    with urllib.request.urlopen(req, timeout=profile.get("timeout", 600)) as r:
        msg = json.loads(r.read())["choices"][0]["message"]
    return msg.get("content") or ""


def _parse_json(text):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        raise ValueError("no JSON object in reply")
    return json.loads(m.group(0))


def _ask(profile, system, user, required, tries=3):
    last = None
    for _ in range(tries):
        try:
            d = _parse_json(chat(profile, system, user))
            missing = [k for k in required if k not in d]
            if not missing:
                return d
            last = f"missing keys {missing}"
        except (ValueError, json.JSONDecodeError) as e:
            last = str(e)
        user += f"\n\n(Your previous reply was invalid: {last}. Reply with the JSON object only.)"
    raise RuntimeError(f"LLM did not return valid JSON after {tries} tries: {last}")


def summarize_segments(segs, profile):
    lines = _lines(segs)
    sys_msg = "You summarize transcribed conversations from a voice recorder, faithfully and concisely."
    text = "\n".join(lines)
    if len(text) <= CHUNK_CHARS:
        return _ask(profile, sys_msg, f"{SCHEMA_HINT}\n\nTranscript:\n{text}", ["title", "summary", "key_points"])
    notes, buf = [], []
    for ln in lines + [None]:
        if buf and (ln is None or sum(map(len, buf)) + len(ln) > CHUNK_CHARS):
            d = _ask(profile, sys_msg, f"{NOTES_HINT}\n\nTranscript part:\n" + "\n".join(buf), ["notes"])
            notes += d["notes"]
            buf = []
        if ln is not None:
            buf.append(ln)
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


def summarize_folder(folder, profile):
    folder = Path(folder)
    t = json.loads((folder / "transcript.json").read_text())
    segs = t["segments"]
    d = summarize_segments(segs, profile)
    for k in ("key_points", "action_items"):
        for item in d.get(k, []):
            item["times"] = _cite(item.get("refs"), segs)
    d["_meta"] = {"model": profile["model"], "endpoint": profile["base_url"],
                  "created": datetime.now().astimezone().isoformat(timespec="seconds")}
    (folder / "summary.json").write_text(json.dumps(d, ensure_ascii=False, indent=1))
    md = [f"# {d['title']}", "", d["summary"], "", "## Key points"]
    md += [f"- {p['text']} ({', '.join(p['times'])})" for p in d.get("key_points", [])]
    if d.get("action_items"):
        md += ["", "## Action items"]
        md += [f"- [ ] {a['text']}" + (f" — {a['owner']}" if a.get("owner") else "") +
               (f" (due {a['due']})" if a.get("due") else "") + f" ({', '.join(a['times'])})" for a in d["action_items"]]
    md += ["", f"_Summarised by {profile['model']}; times link to transcript lines._"]
    (folder / "summary.md").write_text("\n".join(md) + "\n")
    return d
