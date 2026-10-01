import hashlib
import json
import os
import stat
from datetime import datetime

from conftest import TZ

from jrec import db, ingest

SERIAL = "TEST-SERIAL"


def test_scan_lists_recordings_only_and_reads_nothing_into_archive(card, cfg):
    con = db.connect(cfg.db_path)
    d = cfg.devices[0]
    cands = ingest.scan(d, card, SERIAL, con)
    assert [c.rel for c in cands] == ["REC_FILE/FOLDER01/251001_0900.mp3",
                                      "REC_FILE/FOLDER01/Important_251001_1430.mp3",
                                      "REC_FILE/FOLDER02/251002_0815.wav"]  # MUSIC ignored
    assert all(c.status == "new" for c in cands)
    assert not cfg.archive.exists()


def test_import_archives_readonly_by_hash_and_dedupes(card, cfg):
    con = db.connect(cfg.db_path)
    d = cfg.devices[0]
    before = {p: (p.stat().st_mtime, p.read_bytes()) for p in card.rglob("*") if p.is_file()}
    cands = ingest.scan(d, card, SERIAL, con)
    for c in cands:
        sha, new = ingest.import_one(c, d, SERIAL, cfg, con)
        arch = cfg.archive / f"{sha}.{c.path.suffix[1:]}"
        assert new and arch.read_bytes() == c.path.read_bytes()
        assert sha == hashlib.sha256(c.path.read_bytes()).hexdigest()
        assert not arch.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
    # device untouched
    assert before == {p: (p.stat().st_mtime, p.read_bytes()) for p in card.rglob("*") if p.is_file()}
    # rescan: everything is recognised without reading audio
    assert all(c.status == "imported" for c in ingest.scan(d, card, SERIAL, con))
    # same content under another name/device is stored once
    sha2, new2 = ingest.import_one(cands[0], d, "OTHER", cfg, con)
    assert not new2 and len(list(cfg.archive.iterdir())) == 3


def test_import_records_second_precision_start(card, cfg):
    con = db.connect(cfg.db_path)
    d = cfg.devices[0]
    for c in ingest.scan(d, card, SERIAL, con):
        ingest.import_one(c, d, SERIAL, cfg, con)
    rows = {r["orig_path"]: r for r in con.execute("SELECT * FROM source")}
    r = rows["REC_FILE/FOLDER01/251001_0900.mp3"]
    start = datetime.fromisoformat(r["start"])
    want = datetime(2025, 10, 1, 9, 0, 17, tzinfo=TZ)
    # mtime has 1 s close lag and the MP3 frame count rounds to 26 ms frames
    assert abs((start - want).total_seconds() - 1.0) < 0.1
    assert r["start_conf"] == "high" and json.loads(r["flags"]) == []
    assert abs(r["duration"] - 20.0) < 0.1
    w = rows["REC_FILE/FOLDER02/251002_0815.wav"]
    assert w["start"].startswith("2025-10-02T08:15:4") and w["start_conf"] == "high"
