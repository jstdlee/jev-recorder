"""Full-text search over transcript segments.

FTS5 with the trigram tokenizer: substring search that works for CJK/Thai (no word
spaces) as well as spaced languages. Queries under 3 characters fall back to LIKE.
"""
import json
from pathlib import Path

SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS seg_fts USING fts5(
  text, folder UNINDEXED, abs_start UNINDEXED, speaker UNINDEXED, lang UNINDEXED,
  tokenize = 'trigram case_sensitive 0'
);
"""


def ensure(con):
    con.executescript(SCHEMA)


def index_transcript(con, folder):
    ensure(con)
    folder = Path(folder)
    t = json.loads((folder / "transcript.json").read_text())
    con.execute("DELETE FROM seg_fts WHERE folder = ?", (folder.name,))
    con.executemany("INSERT INTO seg_fts (text, folder, abs_start, speaker, lang) VALUES (?,?,?,?,?)",
                    [(s["text"], folder.name, s["abs_start"], s.get("speaker"), s.get("lang")) for s in t["segments"]])
    con.commit()


def search(con, q, limit=50):
    ensure(con)
    q = q.strip()
    if not q:
        return []
    if len(q) >= 3:
        rows = con.execute("SELECT folder, abs_start, speaker, text FROM seg_fts WHERE seg_fts MATCH ? "
                           "ORDER BY abs_start LIMIT ?", ('"' + q.replace('"', '""') + '"', limit)).fetchall()
    else:
        rows = con.execute("SELECT folder, abs_start, speaker, text FROM seg_fts WHERE text LIKE ? "
                           "ORDER BY abs_start LIMIT ?", (f"%{q}%", limit)).fetchall()
    return [dict(r) for r in rows]
