"""Search queries over transcript rows, notes and tags.

  roof price                 both words, any order, anywhere in the row (AND)
  roof OR 屋顶                either  (also: |)
  roof AND (price OR cost)   grouping with ( )  (AND / & optional between terms)
  NOT friday  -friday        exclude
  "next friday"              exact phrase
  /\\d{4}\\s?\\d{4}/             regular expression
  note:roof  tag:家庭  by:mum  lang:cantonese   search one field only
  time:14:00-15:30  date:2025-10-03  after:2025-10-01  before:2025-10-05
Matching ignores case and width, and treats Traditional and Simplified Chinese alike
(錄音 finds 录音). Fields of a row: text, translations, notes, tags, speaker, lang, time.
"""
import re
import unicodedata
from datetime import datetime, time as dtime

_cc = None


def fold(s):
    """Normalise for matching: NFKC (full/half width), case-fold, Traditional -> Simplified Chinese."""
    global _cc
    s = unicodedata.normalize("NFKC", str(s or "")).casefold()
    if any("一" <= ch <= "鿿" for ch in s):
        try:
            if _cc is None:
                import opencc
                _cc = opencc.OpenCC("t2s")
            s = _cc.convert(s)
        except Exception:
            pass
    return s


# ---------------------------------------------------------------- tokenizer
_TOKEN = re.compile(r'''\s*(?:(?P<lp>\()|(?P<rp>\))|(?P<re>/(?:\\.|[^/])+/)|(?P<field>[a-z]+):(?P<fval>"[^"]*"|[^\s()]+)
                     |(?P<phrase>"[^"]*")|(?P<op>\b(?:AND|OR|NOT)\b|&&|\|\||[&|])|(?P<neg>-)(?=\S)|(?P<word>[^\s()"|&]+))''',
                    re.X)


def tokenize(q):
    out, pos = [], 0
    while pos < len(q):
        m = _TOKEN.match(q, pos)
        if not m or m.end() == pos:
            pos += 1
            continue
        pos = m.end()
        k = m.lastgroup if m.lastgroup != "fval" else "field"
        if m.group("lp"):
            out.append(("(", None))
        elif m.group("rp"):
            out.append((")", None))
        elif m.group("re"):
            out.append(("term", ("re", None, m.group("re")[1:-1])))
        elif m.group("field"):
            v = m.group("fval")
            out.append(("term", ("field", m.group("field"), v.strip('"'))))
        elif m.group("phrase"):
            out.append(("term", ("text", None, m.group("phrase")[1:-1])))
        elif m.group("op"):
            o = m.group("op").upper()
            out.append(({"&": "AND", "&&": "AND", "|": "OR", "||": "OR"}.get(o, o), None))
        elif m.group("neg"):
            out.append(("NOT", None))
        else:
            out.append(("term", ("text", None, m.group("word"))))
    return out


# ---------------------------------------------------------------- parser (OR < AND < NOT < atom)
def parse(q):
    toks = tokenize(q)
    pos = [0]

    def peek():
        return toks[pos[0]][0] if pos[0] < len(toks) else None

    def take():
        pos[0] += 1
        return toks[pos[0] - 1]

    def p_or():
        node = p_and()
        while peek() == "OR":
            take()
            node = ("or", node, p_and())
        return node

    def p_and():
        node = p_not()
        while peek() in ("AND", "NOT", "term", "("):
            if peek() == "AND":
                take()
            nxt = p_not()
            if nxt is None:
                break
            node = ("and", node, nxt) if node is not None else nxt
        return node

    def p_not():
        if peek() == "NOT":
            take()
            inner = p_not()
            return ("not", inner) if inner is not None else None
        return p_atom()

    def p_atom():
        k = peek()
        if k == "(":
            take()
            node = p_or()
            if peek() == ")":
                take()
            return node
        if k == "term":
            return ("term",) + take()[1]
        if k == ")":
            take()
        return None

    node = p_or() if toks else None
    return node


# ---------------------------------------------------------------- evaluation
FIELDS = {"note": "notes", "notes": "notes", "tag": "tags", "tags": "tags", "by": "speaker", "speaker": "speaker",
          "who": "speaker", "lang": "lang", "text": "text", "tr": "translations"}


def _hay(row, field=None):
    if field:
        v = row.get(field, "")
        return fold(" ".join(v) if isinstance(v, (list, tuple)) else v)
    return fold(" ".join([row.get("text", ""), " ".join(row.get("translations", [])), " ".join(row.get("notes", [])),
                          " ".join(row.get("tags", [])), row.get("speaker", "")]))


def _time_ok(row, kind, val):
    t = row.get("time")
    if not isinstance(t, datetime):
        return False
    try:
        if kind == "date":
            return t.date().isoformat() == val
        if kind == "after":
            return t.date().isoformat() >= val[:10] if len(val) <= 10 else t.isoformat() >= val
        if kind == "before":
            return t.date().isoformat() <= val[:10] if len(val) <= 10 else t.isoformat() <= val
        if kind == "time":
            a, _, b = val.partition("-")
            ta = dtime.fromisoformat(a if a.count(":") else a + ":00")
            tb = dtime.fromisoformat(b if b.count(":") else b + ":00") if b else None
            tt = t.time().replace(tzinfo=None)
            return (ta <= tt <= tb) if tb else (tt.hour, tt.minute) == (ta.hour, ta.minute)
    except ValueError:
        return False
    return False


def match(node, row, _cache=None):
    if node is None:
        return True
    op = node[0]
    if op == "and":
        return match(node[1], row) and match(node[2], row)
    if op == "or":
        return match(node[1], row) or match(node[2], row)
    if op == "not":
        return not match(node[1], row)
    _, kind, field, val = node
    if kind == "re":
        try:
            return re.search(val, _hay(row), flags=re.I) is not None or \
                re.search(val, " ".join([row.get("text", "")] + row.get("translations", []) + row.get("notes", [])),
                          flags=re.I) is not None
        except re.error:
            return False
    if kind == "field":
        if field in ("time", "date", "after", "before"):
            return _time_ok(row, field, val)
        return fold(val) in _hay(row, FIELDS.get(field, field))
    return fold(val) in _hay(row)


def terms(node):
    """Plain words/phrases in a query (for highlighting), excluding NOT branches."""
    if node is None:
        return []
    if node[0] in ("and", "or"):
        return terms(node[1]) + terms(node[2])
    if node[0] == "not":
        return []
    _, kind, field, val = node
    return [val] if kind in ("text",) or (kind == "field" and field not in ("time", "date", "after", "before")) else []
