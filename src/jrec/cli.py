"""jrec command line.

  jrec devices                       recorders currently mounted
  jrec scan   [MOUNT]                preview files (reads listing + headers only)
  jrec import [MOUNT] [--pick 1,3-5] [--yes]
                                     preview, ask, then copy new files into the archive
  jrec sources                       archived recordings with start times and flags
  jrec cut                           find conversations in new archive files, cut verifiable clips
  jrec verify [FOLDER ...]           re-check clip hashes against the archived originals
  jrec transcribe [FOLDER ...] [--no-diarization]
                                     Qwen3-ASR-1.7B + word times + speakers -> transcript.{json,srt,vtt,md}
  jrec enhance [FOLDER ...]          listening track listen.opus (DeepFilterNet3, CPU)
  jrec summarize [FOLDER ...] [--llm PROFILE]
                                     title/summary/points/actions with clock-time citations
  jrec search QUERY                  full-text search over all transcripts
  jrec process [--no-diarization]    cut + transcribe + enhance + summarize everything new
  jrec watch                         on plug-in: read-only remount, scan, ask (Import/Skip), process
  jrec ui [--ui-script STEPS]        desktop app: timeline, transcript, summary, import dialog
"""
import argparse
import json
import sys
from pathlib import Path

from . import config, db, ingest


def _fmt_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024


def _fmt_dur(s):
    if s is None:
        return "?"
    s = int(s)
    return f"{s//3600}:{s%3600//60:02d}:{s%60:02d}"


def human_flag(f):
    """'timeline_gap:31489923s' -> 'timeline gap 364d' (stored flags stay machine-readable)."""
    name, _, val = f.partition(":")
    if val.endswith("s") and val[:-1].lstrip("-").replace(".", "").isdigit():
        v = abs(float(val[:-1]))
        val = f"{v/86400:.0f}d" if v >= 86400 else f"{v/3600:.1f}h" if v >= 3600 else f"{v/60:.0f}m" if v >= 60 else f"{v:.0f}s"
    return name.replace("_", " ") + (f" {val}" if val else "")


def _pick(spec, n):
    out = set()
    for part in spec.split(","):
        a, _, b = part.partition("-")
        out.update(range(int(a), int(b or a) + 1))
    return sorted(i for i in out if 1 <= i <= n)


def _recorder(cfg, mount):
    recs = ingest.find_recorders(cfg)
    if mount:
        m = Path(mount).resolve()
        for r in recs:
            if r[1] == m:
                return r
        # an explicit folder (e.g. a copy of the card): use the first profile whose roots exist
        for d in cfg.devices:
            if all((m / r).is_dir() for r in d.roots):
                return d, m, f"{d.name}:{m.name}"
        sys.exit(f"{mount}: no device profile matches (expected {[d.roots for d in cfg.devices]})")
    if not recs:
        sys.exit("no recorder mounted (plug it in, or pass the mount path)")
    if len(recs) > 1:
        sys.exit("several recorders mounted; pass the mount path: " + ", ".join(str(r[1]) for r in recs))
    return recs[0]


def _preview(cands):
    print(f"{'#':>3}  {'status':8} {'file':34} {'size':>9} {'length':>8}  start (confidence) flags")
    for i, c in enumerate(cands, 1):
        st = c.start
        when = f"{st.start:%Y-%m-%d %H:%M:%S%z} ({st.confidence})" if st else "?"
        flags = ", ".join(human_flag(f) for f in st.flags) if st and st.flags else ""
        print(f"{i:>3}  {c.status:8} {c.rel[-34:]:34} {_fmt_size(c.size):>9} {_fmt_dur(c.duration):>8}  {when} {flags}")


def cmd_devices(cfg, a):
    recs = ingest.find_recorders(cfg)
    for d, mnt, serial in recs:
        print(f"{d.name}\t{mnt}\tserial={serial}")
    if not recs:
        print("no recorder mounted")


def cmd_scan(cfg, a):
    d, mnt, serial = _recorder(cfg, a.mount)
    con = db.connect(cfg.db_path)
    cands = ingest.scan(d, mnt, serial, con)
    print(f"{d.name} at {mnt} (serial {serial}): {len(cands)} recordings, "
          f"{sum(c.status == 'new' for c in cands)} new")
    _preview(cands)
    return d, mnt, serial, con, cands


def cmd_import(cfg, a):
    d, mnt, serial, con, cands = cmd_scan(cfg, a)
    chosen = [cands[i - 1] for i in _pick(a.pick, len(cands))] if a.pick else \
        [c for c in cands if c.status == "new"]
    chosen = [c for c in chosen if c.status == "new"]
    if not chosen:
        print("nothing new to import")
        return
    ok, need = ingest.free_space_ok(cfg, chosen)
    if not ok:
        sys.exit(f"not enough free space in {cfg.library} for {_fmt_size(need)}")
    if not a.yes:
        ans = input(f"Import {len(chosen)} file(s), {_fmt_size(need)}, into {cfg.archive}? [y/N] ")
        if ans.strip().lower() not in ("y", "yes"):
            print("cancelled; nothing copied")
            return
    for i, c in enumerate(chosen, 1):
        sha, new = ingest.import_one(c, d, serial, cfg, con)
        print(f"[{i}/{len(chosen)}] {c.rel} -> {sha[:16]}… {'archived' if new else 'already in archive'}")
    print("done. The device was not modified; it is safe to eject.")


def cmd_sources(cfg, a):
    con = db.connect(cfg.db_path)
    for r in con.execute("SELECT * FROM source ORDER BY start"):
        flags = ",".join(json.loads(r["flags"]))
        print(f"{r['start']}  {_fmt_dur(r['duration'])}  {r['start_conf']:6} {r['sha256'][:12]}  "
              f"{r['device']}:{r['orig_path']}  {flags}")


def _sources(cfg, con, only_new=True):
    from datetime import datetime
    from .cutter import Src
    done = {r[0] for r in con.execute("SELECT DISTINCT json_extract(value, '$.source_sha256') FROM conversation, "
                                       "json_each(json_extract(manifest, '$.parts'))")}
    for r in con.execute("SELECT * FROM source ORDER BY start"):
        if only_new and r["sha256"] in done:
            continue
        yield Src(r["sha256"], r["ext"], cfg.archive / f"{r['sha256']}.{r['ext']}", datetime.fromisoformat(r["start"]),
                  r["duration"], r["orig_path"], r["device"],
                  {"start": r["start"], "source": r["start_source"], "confidence": r["start_conf"],
                   "flags": json.loads(r["flags"])})


def cmd_cut(cfg, a):
    from . import cutter
    con = db.connect(cfg.db_path)
    out = cfg.library / "conversations"
    srcs = list(_sources(cfg, con, only_new=not a.all))
    if not srcs:
        print("no new archive files to cut")
        return
    for stream in cutter.streams(srcs):
        names = " + ".join(s.orig_path.rsplit("/", 1)[-1] for s in stream)
        print(f"stream {names}: running VAD …", flush=True)
        for m in cutter.cut_stream(stream, out):
            w = m["window"]
            con.execute("INSERT OR REPLACE INTO conversation (folder, start, end, speech_start, speech_end, speech_sec,"
                        " manifest) VALUES (?,?,?,?,?,?,?)",
                        (m["conversation"], w["start"], w["end"], w["speech_start"], w["speech_end"], w["speech_sec"],
                         json.dumps(m)))
            con.commit()
            print(f"  {m['conversation']}: speech {w['speech_start'][11:19]}-{w['speech_end'][11:19]} "
                  f"({w['speech_sec']:.0f}s), clip {w['start'][11:19]}-{w['end'][11:19]}, {len(m['parts'])} part(s)")


def cmd_verify(cfg, a):
    from . import cutter
    folders = [Path(f) for f in a.folders] or sorted((cfg.library / "conversations").glob("*/"))
    bad = 0
    for f in folders:
        probs = cutter.verify_folder(f, cfg.archive)
        bad += bool(probs)
        print(f"{'OK  ' if not probs else 'FAIL'} {f.name}" + "".join(f"\n     {p}" for p in probs))
    sys.exit(1 if bad else 0)


def cmd_transcribe(cfg, a):
    from . import search, thermal, transcribe
    con = db.connect(cfg.db_path)
    if a.folders:
        folders = [Path(f) for f in a.folders]
    else:
        folders = [cfg.library / "conversations" / r["folder"]
                   for r in con.execute("SELECT folder FROM conversation WHERE status='cut' ORDER BY speech_start")]
    if not folders:
        print("nothing to transcribe")
        return
    with thermal.gpu_lock(cfg.library):
        _transcribe_folders(cfg, con, folders, a)


def _transcribe_folders(cfg, con, folders, a):
    from . import search, thermal, transcribe
    engine = transcribe.Engine()
    for i, f in enumerate(folders, 1):
        print(f"[{i}/{len(folders)}] {f.name}", flush=True)
        thermal.wait_cool()
        segs = transcribe.transcribe_folder(f, engine, use_diarization=not a.no_diarization)
        search.index_transcript(con, f)
        con.execute("UPDATE conversation SET status='transcribed' WHERE folder=?", (f.name,))
        con.commit()
        print(f"  {len(segs)} segments, {len({s['speaker'] for s in segs if s['speaker']})} speakers -> {f}/transcript.md")


def cmd_enhance(cfg, a):
    from . import enhance
    folders = [Path(f) for f in a.folders] or [f for f in sorted((cfg.library / "conversations").glob("*/"))
                                               if not (f / "listen.opus").exists()]
    for i, f in enumerate(folders, 1):
        print(f"[{i}/{len(folders)}] {f.name} -> {enhance.make_listen_track(f).name}", flush=True)
    if not folders:
        print("nothing to enhance")


def cmd_summarize(cfg, a):
    from . import summarize
    con = db.connect(cfg.db_path)
    prof = cfg.llm_profile(a.llm)
    folders = [Path(f) for f in a.folders] or [cfg.library / "conversations" / r["folder"] for r in
                                               con.execute("SELECT folder FROM conversation WHERE status='transcribed'")]
    for i, f in enumerate(folders, 1):
        d = summarize.summarize_folder(f, prof)
        con.execute("UPDATE conversation SET status='summarized' WHERE folder=?", (f.name,))
        con.commit()
        print(f"[{i}/{len(folders)}] {f.name}: {d['title']}")
    if not folders:
        print("nothing to summarize")


def cmd_search(cfg, a):
    from . import search
    con = db.connect(cfg.db_path)
    hits = search.search(con, a.query)
    for h in hits:
        print(f"{h['abs_start'][:19].replace('T', ' ')}  {h['folder']}  [{h['speaker'] or '?'}] {h['text']}")
    print(f"{len(hits)} hit(s)")


def cmd_process(cfg, a):
    from .pipeline import process_all
    process_all(cfg, diarization=not a.no_diarization)


def cmd_watch(cfg, a):
    from . import watch
    watch.run(cfg, process_after=not a.no_process)


def cmd_ui(cfg, a):
    import os
    from . import ui
    if a.config:  # child jobs started from the UI use the same config
        os.environ["JREC_CONFIG_PATH"] = str(Path(a.config).expanduser().resolve())
    ui.run(cfg, a.ui_script)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="jrec", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("devices")
    s = sub.add_parser("scan"); s.add_argument("mount", nargs="?")
    i = sub.add_parser("import"); i.add_argument("mount", nargs="?")
    i.add_argument("--pick", help="numbers from the preview, e.g. 1,3-5 (default: all new)")
    i.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    sub.add_parser("sources")
    c = sub.add_parser("cut"); c.add_argument("--all", action="store_true", help="re-cut already cut sources too")
    v = sub.add_parser("verify"); v.add_argument("folders", nargs="*")
    t = sub.add_parser("transcribe"); t.add_argument("folders", nargs="*")
    t.add_argument("--no-diarization", action="store_true")
    e = sub.add_parser("enhance"); e.add_argument("folders", nargs="*")
    sm = sub.add_parser("summarize"); sm.add_argument("folders", nargs="*"); sm.add_argument("--llm")
    q = sub.add_parser("search"); q.add_argument("query")
    pr = sub.add_parser("process"); pr.add_argument("--no-diarization", action="store_true")
    wa = sub.add_parser("watch"); wa.add_argument("--no-process", action="store_true")
    u = sub.add_parser("ui"); u.add_argument("--ui-script", help="e.g. open:0,wait:2.5,shot:/tmp/a.png (wait in seconds)")
    a = ap.parse_args(argv)
    cfg = config.load(a.config)
    {"devices": cmd_devices, "scan": cmd_scan, "import": cmd_import, "sources": cmd_sources,
     "cut": cmd_cut, "verify": cmd_verify, "transcribe": cmd_transcribe,
     "enhance": cmd_enhance, "summarize": cmd_summarize, "search": cmd_search,
     "process": cmd_process, "watch": cmd_watch, "ui": cmd_ui}[a.cmd](cfg, a)


if __name__ == "__main__":
    main()
