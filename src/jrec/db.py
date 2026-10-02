"""SQLite index. The archive folder plus manifests are the source of truth; this is the index over them."""
import json
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS source (
  sha256 TEXT PRIMARY KEY,
  ext TEXT NOT NULL,
  size INTEGER NOT NULL,
  device TEXT, device_serial TEXT,
  orig_path TEXT,            -- path relative to the device mount
  orig_mtime REAL,           -- epoch seconds as read from the mounted device
  duration REAL,             -- seconds of audio (exact frame count for MP3)
  start TEXT,                -- ISO 8601 with offset
  start_source TEXT, start_conf TEXT,
  flags TEXT,                -- JSON list
  imported_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS seen (   -- device files already imported, matched without reading audio
  device_serial TEXT, orig_path TEXT, size INTEGER, mtime REAL, sha256 TEXT,
  PRIMARY KEY (device_serial, orig_path, size, mtime)
);
CREATE TABLE IF NOT EXISTS conversation (
  id INTEGER PRIMARY KEY,
  folder TEXT UNIQUE,
  start TEXT, end TEXT, speech_start TEXT, speech_end TEXT,
  speech_sec REAL,
  manifest TEXT,             -- JSON copy of manifest.json
  status TEXT NOT NULL DEFAULT 'cut'
);
-- Everything below is the user's and the models' work ABOUT the audio. It lives only here:
-- archived originals and clips are never written to (no tags, no metadata, no audio edits).
CREATE TABLE IF NOT EXISTS note (
  id INTEGER PRIMARY KEY,
  folder TEXT NOT NULL,
  t REAL NOT NULL,           -- seconds from the clip start
  abs TEXT NOT NULL,         -- absolute time, ISO 8601
  text TEXT NOT NULL,
  created TEXT NOT NULL, updated TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS note_folder ON note(folder, t);
CREATE TABLE IF NOT EXISTS summary (
  folder TEXT PRIMARY KEY, json TEXT NOT NULL, model TEXT, created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS translation (
  folder TEXT NOT NULL, seg INTEGER NOT NULL, lang TEXT NOT NULL,
  src_hash TEXT NOT NULL,    -- hash of the source text: a re-transcription makes old rows stale
  text TEXT NOT NULL, model TEXT, created TEXT NOT NULL,
  PRIMARY KEY (folder, seg, lang)
);
CREATE TABLE IF NOT EXISTS speaker_name (
  folder TEXT NOT NULL, speaker TEXT NOT NULL, name TEXT NOT NULL, PRIMARY KEY (folder, speaker)
);
"""


def connect(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def is_seen(con, serial, rel, size, mtime):
    return con.execute("SELECT sha256 FROM seen WHERE device_serial=? AND orig_path=? AND size=? AND mtime=?",
                       (serial, rel, size, mtime)).fetchone()


def add_source(con, row):
    row = dict(row, flags=json.dumps(row.get("flags", [])))
    con.execute(f"INSERT OR IGNORE INTO source ({','.join(row)}) VALUES ({','.join('?' * len(row))})",
                list(row.values()))
    con.execute("INSERT OR IGNORE INTO seen VALUES (?,?,?,?,?)",
                (row["device_serial"], row["orig_path"], row["size"], row["orig_mtime"], row["sha256"]))
    con.commit()


def now():
    from datetime import datetime
    return datetime.now().astimezone().isoformat(timespec="seconds")


def text_hash(text):
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()[:16]


# ---- notes
def notes(con, folder):
    return [dict(r) for r in con.execute("SELECT * FROM note WHERE folder=? ORDER BY t", (folder,))]


def add_note(con, folder, t, abs_iso, text):
    cur = con.execute("INSERT INTO note (folder, t, abs, text, created, updated) VALUES (?,?,?,?,?,?)",
                      (folder, t, abs_iso, text, now(), now()))
    con.commit()
    return cur.lastrowid


def update_note(con, note_id, text):
    con.execute("UPDATE note SET text=?, updated=? WHERE id=?", (text, now(), note_id))
    con.commit()


def delete_note(con, note_id):
    con.execute("DELETE FROM note WHERE id=?", (note_id,))
    con.commit()


# ---- summaries
def save_summary(con, folder, d, model):
    con.execute("INSERT OR REPLACE INTO summary (folder, json, model, created) VALUES (?,?,?,?)",
                (folder, json.dumps(d, ensure_ascii=False), model, now()))
    con.commit()


def get_summary(con, folder):
    r = con.execute("SELECT json FROM summary WHERE folder=?", (folder,)).fetchone()
    return json.loads(r[0]) if r else None


# ---- translations
def save_translations(con, folder, lang, rows, model):
    """rows: [(seg_index, source_text, translated_text)]"""
    con.executemany("INSERT OR REPLACE INTO translation (folder, seg, lang, src_hash, text, model, created) "
                    "VALUES (?,?,?,?,?,?,?)",
                    [(folder, i, lang, text_hash(src), tr, model, now()) for i, src, tr in rows])
    con.commit()


def translations(con, folder, lang, segments):
    """{seg_index: text} for rows whose source text is unchanged since translation."""
    out = {}
    for r in con.execute("SELECT seg, src_hash, text FROM translation WHERE folder=? AND lang=?", (folder, lang)):
        i = r[0]
        if i < len(segments) and text_hash(segments[i]["text"]) == r[1]:
            out[i] = r[2]
    return out


def translated_langs(con, folder):
    return [r[0] for r in con.execute("SELECT DISTINCT lang FROM translation WHERE folder=?", (folder,))]


# ---- speaker names
def speaker_names(con, folder):
    return {r[0]: r[1] for r in con.execute("SELECT speaker, name FROM speaker_name WHERE folder=?", (folder,))}


def set_speaker_name(con, folder, speaker, name):
    if name.strip():
        con.execute("INSERT OR REPLACE INTO speaker_name VALUES (?,?,?)", (folder, speaker, name.strip()))
    else:
        con.execute("DELETE FROM speaker_name WHERE folder=? AND speaker=?", (folder, speaker))
    con.commit()
