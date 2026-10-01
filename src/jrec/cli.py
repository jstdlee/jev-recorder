"""jrec command line.

  jrec devices                       recorders currently mounted
  jrec scan   [MOUNT]                preview files (reads listing + headers only)
  jrec import [MOUNT] [--pick 1,3-5] [--yes]
                                     preview, ask, then copy new files into the archive
  jrec sources                       archived recordings with start times and flags
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
        flags = ",".join(st.flags) if st and st.flags else ""
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
    a = ap.parse_args(argv)
    cfg = config.load(a.config)
    {"devices": cmd_devices, "scan": cmd_scan, "import": cmd_import, "sources": cmd_sources}[a.cmd](cfg, a)


if __name__ == "__main__":
    main()
