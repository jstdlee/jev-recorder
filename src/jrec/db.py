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
