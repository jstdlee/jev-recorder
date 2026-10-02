"""Search the whole library with the query language (jrec.query): every transcript row (text,
translations, its notes, speaker name, the talk's and recording's tags) and every note."""
import bisect
from datetime import datetime, timedelta

from . import query


def rows_of(conv):
    """Searchable rows for one loaded conversation (jrec.ui.data.Conversation or compatible)."""
    starts = [s["_t0"] for s in conv.segments]
    notes_by_row = {}
    for n in conv.notes:
        notes_by_row.setdefault(max(0, bisect.bisect_right(starts, n["t"]) - 1), []).append(n["text"])
    tags = list(getattr(conv, "tags", []))
    for i, s in enumerate(conv.segments):
        yield i, {"text": s["text"], "translations": [tr[i] for tr in conv.translations.values() if i in tr],
                  "notes": notes_by_row.get(i, []), "tags": tags, "speaker": conv.speaker(s, i),
                  "lang": s.get("lang") or "", "time": datetime.fromisoformat(s["abs_start"])}


def search(convs, q, limit=500):
    """[(conv, row_index or None, kind, note or None)] — kind 'row' or 'note' (notes on untranscribed talks too)."""
    node = query.parse(q)
    if node is None:
        return []
    hits = []
    for c in convs:
        for i, row in rows_of(c):
            if query.match(node, row):
                hits.append((c, i, "row", None))
        if not c.segments:                      # notes on talks without a transcript yet
            for n in c.notes:
                row = {"text": "", "notes": [n["text"]], "tags": list(getattr(c, "tags", [])), "speaker": "",
                       "lang": "", "time": c.start + timedelta(seconds=n["t"]), "translations": []}
                if query.match(node, row):
                    hits.append((c, None, "note", n))
        if len(hits) >= limit:
            break
    return hits[:limit]
