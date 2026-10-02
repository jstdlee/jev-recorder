"""Conversation intelligence: who, where, when, how to reach them, what matters, and how the
speakers relate. Every item cites transcript rows, so it can be played back and checked.

Engines (pick in Settings or `jrec analyze --engine`):
  rules   offline, instant: phone numbers, emails, links, money, dates and times (en + zh)
  llm     the OpenAI-compatible LLM extracts people, places, contacts, times, important rows,
          speaker roles and relationships (chunked like summaries)
  jev     Julia-1 (/v1/systemone) scores fixed choices: the relationship of every speaker pair,
          and whether each row is important
  check   llm extraction, then jev rates how well each claim is supported by its cited rows
Results are stored in the database (insight table) and insights.json; audio is never touched.
"""
import json
import re
import urllib.request
from datetime import datetime
from itertools import combinations
from pathlib import Path

from . import db
from .llm import ask
from .summarize import chunk_lines

# ---------------------------------------------------------------- rules
_RULES = [
    ("phone", r"\+\d{1,3}[\s-]?\d{1,4}[\s-]?\d{3,4}[\s-]?\d{3,4}"),
    ("phone", r"(?<![\d.])(?:[689]\d{3}[\s-]?\d{4}|01\d[\s-]?\d{3,4}[\s-]?\d{4})(?![\d.])"),
    ("email", r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    ("link", r"https?://\S+|www\.\S+"),
    ("money", r"(?:S\$|HK\$|US\$|RM|\$|¥|￥|€|£)\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:k|K|million|mil|万|萬))?"),
    ("money", r"\d[\d,]*(?:\.\d+)?\s?(?:dollars?|ringgit|bucks|元|块|塊|蚊|萬|万元|万|千)"),
    ("money", r"[零一二三四五六七八九十百千万萬两兩]{2,}(?:块|塊|元|蚊|文)(?:钱|錢)?"),
    ("time", r"\b\d{1,2}(?::\d{2})?\s?(?:am|pm|a\.m\.|p\.m\.)"),
    ("time", r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b"),
    ("time", r"(?:上午|下午|晚上|早上|中午|凌晨)?[零一二三四五六七八九十两兩\d]{1,3}[点點](?:[半一二三四五六七八九十\d]{0,3}(?:分)?)?"),
    ("date", r"\b(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day\b|\b(?:next|this|last)\s+(?:week|month|year|"
             r"Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b|\btomorrow\b|\byesterday\b|\btonight\b"),
    ("date", r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?\b|"
             r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\b"),
    ("date", r"(?:下|上|这|這|本)?(?:个|個)?(?:星期|礼拜|禮拜|周|週)[一二三四五六日天]|"
             r"[\d一二三四五六七八九十]{1,3}月[\d一二三四五六七八九十]{1,3}[日号號]|明天|后天|後天|今天|昨天|"
             r"下(?:个|個)?(?:星期|礼拜|禮拜|周|週|月)|今晚|明晚"),
]


def rules_extract(segs):
    found = {}
    for i, s in enumerate(segs):
        for kind, pat in _RULES:
            for m in re.finditer(pat, s["text"], flags=re.I):
                txt = m.group(0).strip()
                if kind == "phone" and len(re.sub(r"\D", "", txt)) < 7:
                    continue
                key = (kind, txt.lower())
                found.setdefault(key, {"text": txt, "kind": kind, "refs": []})["refs"].append(i)
    out = {"contacts": [], "times": [], "money": []}
    for (kind, _), item in found.items():
        bucket = "contacts" if kind in ("phone", "email", "link") else "money" if kind == "money" else "times"
        out[bucket].append(item)
    return out


# ---------------------------------------------------------------- llm
INTEL_HINT = """From the transcript lines, extract intelligence. Return ONLY one JSON object:
{"people": [{"name": str, "role": str or null, "speaker": "S1"-style label if this person is a speaker else null, "refs": [line numbers]}],
 "places": [{"text": str, "refs": [line numbers]}],
 "contacts": [{"text": str, "kind": "phone|email|address|account|link|other", "refs": [line numbers]}],
 "times": [{"text": str, "meaning": str, "refs": [line numbers]}],
 "important": [{"ref": line number, "why": str}],
 "speaker_roles": [{"speaker": "S1", "guess": str, "refs": [line numbers]}],
 "relationships": [{"a": "S1", "b": "S2", "relation": str, "confidence": 0.0-1.0, "evidence": [line numbers]}]}
Speakers are labelled S1, S2, ... in the lines. People are named or described individuals (also people
mentioned but not speaking). Important = decisions, promises, amounts, dates, names, instructions, threats
or anything someone would need to find later. Only use what the lines say or clearly imply; cite lines."""


def _lines(segs):
    return [f"[{i}] {s['abs_start'][11:19]} {s.get('speaker') or '?'}: {s['text']}" for i, s in enumerate(segs)]


def _merge_lists(parts, key_fn):
    out, seen = [], {}
    for item in parts:
        k = key_fn(item)
        if k in seen:
            seen[k].setdefault("refs", [])
            seen[k]["refs"] = sorted(set(seen[k]["refs"]) | set(item.get("refs", [])))
        else:
            seen[k] = dict(item)
            out.append(seen[k])
    return out


def llm_extract(segs, profile, progress=None):
    lines = _lines(segs)
    size = int(profile.get("chunk_chars", 256000))
    parts = chunk_lines(lines, size, int(profile.get("overlap_chars", 8000)))
    acc = {k: [] for k in ("people", "places", "contacts", "times", "important", "speaker_roles", "relationships")}
    for k, part in enumerate(parts):
        if progress:
            progress("analyze", k, len(parts))
        d = ask(profile, "You extract facts from transcribed conversations, carefully and only from the text.",
                INTEL_HINT + f"\n\nTranscript part {k + 1} of {len(parts)}:\n" + "\n".join(part), ["people", "important"])
        for key in acc:
            acc[key] += [x for x in d.get(key, []) if isinstance(x, dict)]
    norm = lambda s: re.sub(r"\s+", " ", str(s)).strip().lower()
    acc["people"] = _merge_lists(acc["people"], lambda x: norm(x.get("name")))
    acc["places"] = _merge_lists(acc["places"], lambda x: norm(x.get("text")))
    acc["contacts"] = _merge_lists(acc["contacts"], lambda x: norm(x.get("text")))
    acc["times"] = _merge_lists(acc["times"], lambda x: norm(x.get("text")))
    acc["important"] = list({int(x["ref"]): x for x in acc["important"] if str(x.get("ref", "")).isdigit()}.values())
    acc["speaker_roles"] = _merge_lists(acc["speaker_roles"], lambda x: (x.get("speaker"), norm(x.get("guess"))))
    acc["relationships"] = _merge_lists(acc["relationships"], lambda x: tuple(sorted([str(x.get("a")), str(x.get("b"))])))
    return acc


# ---------------------------------------------------------------- jev (Julia-1 choice scoring)
RELATIONS = {
    "family": "They are family: parent and child, siblings or relatives",
    "couple": "They are a couple or married to each other",
    "friends": "They are friends",
    "colleagues": "They are colleagues at work",
    "boss_staff": "One is the other's boss or manager",
    "client_vendor": "One is a customer and the other sells something or provides a service",
    "official": "One speaks in an official role (police, doctor, lawyer, teacher, officer) to the other",
    "strangers": "They are strangers or meet for the first time",
    "broadcast": "This is a broadcast, lecture or reading, not a conversation between them",
}


def jev_ask(jev, questions, state, timeout=120):
    """questions: {id: (instructions, {option_id: text})} -> {id: {option_id: probability}}"""
    req = {"model": jev.get("model", "julia-1"), "state": state,
           "questions": {q: {"type": "choice", "instructions": ins, "criteria": crit} for q, (ins, crit) in questions.items()}}
    r = urllib.request.Request(jev["url"].rstrip("/") + "/v1/systemone", json.dumps(req, ensure_ascii=False).encode(),
                               {"Content-Type": "application/json"})
    if jev.get("key"):
        r.add_header("Authorization", f"Bearer {jev['key']}")
    with urllib.request.urlopen(r, timeout=jev.get("timeout", timeout)) as resp:
        answers = json.loads(resp.read())["answers"]
    return {q: {k: float(v) for k, v in (answers.get(q) or {}).get("probabilities", {}).items()} for q in questions}


def _speaker_lines(segs, spk, limit=1500):
    out, n = [], 0
    for s in segs:
        if s.get("speaker") == spk:
            out.append(s["text"])
            n += len(s["text"])
            if n > limit:
                break
    return " / ".join(out)


def jev_relationships(segs, jev):
    spks = sorted({s["speaker"] for s in segs if s.get("speaker")})
    pairs = list(combinations(spks, 2))[:15]
    if not pairs:
        return []
    excerpt = "\n".join(f"{s.get('speaker')}: {s['text']}" for s in segs)[:3000]
    out = []
    for a, b in pairs:
        state = {"conversation_excerpt": excerpt, "speaker_A": a, "speaker_A_lines": _speaker_lines(segs, a),
                 "speaker_B": b, "speaker_B_lines": _speaker_lines(segs, b)}
        p = jev_ask(jev, {"rel": (f"How are speaker A ({a}) and speaker B ({b}) most likely related?", RELATIONS)},
                    state)["rel"]
        ranked = sorted(p.items(), key=lambda kv: -kv[1])
        out.append({"a": a, "b": b, "relation": ranked[0][0] if ranked else "?",
                    "scores": dict(ranked), "source": "jev"})
    return out


def jev_importance(segs, jev, batch=16, threshold=0.6, progress=None):
    yes_no = {"yes": "Yes: it holds a decision, promise, amount, date, name, address, instruction or warning",
              "no": "No: small talk or filler"}
    out = []
    for k in range(0, len(segs), batch):
        if progress:
            progress("jev", k, len(segs))
        qs = {f"r{i}": ("Is this line important to remember later?", yes_no) for i in range(k, min(len(segs), k + batch))}
        state = {"lines": {f"r{i}": segs[i]["text"] for i in range(k, min(len(segs), k + batch))}}
        res = jev_ask(jev, qs, state)
        for q, p in res.items():
            if p.get("yes", 0) >= threshold:
                out.append({"ref": int(q[1:]), "why": f"jev: important ({p['yes']:.0%})", "jev": p["yes"]})
    return out


def jev_check(intel, segs, jev):
    """Lint the LLM's claims: probability that each claim is supported by the rows it cites."""
    claims = []
    for key, fmt in (("people", lambda x: f"{x.get('name')} is mentioned" + (f" as {x['role']}" if x.get("role") else "")),
                     ("places", lambda x: f"The place '{x.get('text')}' is mentioned"),
                     ("times", lambda x: f"'{x.get('text')}' refers to {x.get('meaning') or 'a time'}"),
                     ("speaker_roles", lambda x: f"Speaker {x.get('speaker')} is {x.get('guess')}"),
                     ("relationships", lambda x: f"Speakers {x.get('a')} and {x.get('b')} are {x.get('relation')}")):
        for item in intel.get(key, []):
            refs = item.get("refs") or item.get("evidence") or []
            claims.append((item, fmt(item), refs))
    for item in intel.get("important", []):
        claims.append((item, f"This line is important: {item.get('why')}", [item.get("ref")]))
    yes_no = {"yes": "Yes: the lines say it or clearly imply it", "no": "No: the lines do not support it"}
    for k in range(0, len(claims), 12):
        group = claims[k:k + 12]
        qs, state = {}, {}
        for j, (item, text, refs) in enumerate(group):
            lines = [segs[r]["text"] for r in refs if isinstance(r, int) and 0 <= r < len(segs)][:6]
            qs[f"c{j}"] = (f"Claim: {text}. Is it supported by its lines?", yes_no)
            state[f"c{j}_lines"] = " / ".join(lines) or "(no lines cited)"
        res = jev_ask(jev, qs, state)
        for j, (item, _, _) in enumerate(group):
            item["jev_support"] = round(res.get(f"c{j}", {}).get("yes", 0.0), 3)
    return intel


# ---------------------------------------------------------------- run
def analyze_folder(folder, engine, profile, jev, con, progress=None):
    folder = Path(folder)
    segs = json.loads((folder / "transcript.json").read_text())["segments"]
    intel = {"rules": rules_extract(segs)}
    if engine in ("llm", "check"):
        intel.update(llm_extract(segs, profile, progress))
    if engine == "jev":
        intel["relationships"] = jev_relationships(segs, jev)
        intel["important"] = jev_importance(segs, jev, progress=progress)
    if engine == "check":
        jev_check(intel, segs, jev)
        if len({s.get("speaker") for s in segs if s.get("speaker")}) > 1:
            intel["jev_relationships"] = jev_relationships(segs, jev)
    intel["_meta"] = {"engine": engine, "llm": profile.get("model") if engine in ("llm", "check") else None,
                      "jev": jev.get("model") if engine in ("jev", "check") else None,
                      "created": datetime.now().astimezone().isoformat(timespec="seconds")}
    (folder / "insights.json").write_text(json.dumps(intel, ensure_ascii=False, indent=1))
    db.save_insight(con, folder.name, intel, engine)
    return intel
