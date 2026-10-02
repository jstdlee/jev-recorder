"""cut -> transcribe -> enhance -> summarize for everything new, one heavy step at a time."""
import json
import urllib.request

from . import db, thermal


def llm_reachable(profile, timeout=3):
    try:
        urllib.request.urlopen(profile["base_url"].rstrip("/") + "/models", timeout=timeout)
        return True
    except Exception:
        return False


def process_all(cfg, diarization=True, log=print):
    from . import cutter
    from .cli import _sources
    con = db.connect(cfg.db_path)
    out = cfg.library / "conversations"
    # 1. cut new sources
    srcs = list(_sources(cfg, con))
    for stream in cutter.streams(srcs):
        thermal.wait_cool(log=log)
        for m in cutter.cut_stream(stream, out):
            w = m["window"]
            con.execute("INSERT OR REPLACE INTO conversation (folder, start, end, speech_start, speech_end, speech_sec,"
                        " manifest) VALUES (?,?,?,?,?,?,?)", (m["conversation"], w["start"], w["end"], w["speech_start"],
                                                             w["speech_end"], w["speech_sec"], json.dumps(m)))
            con.commit()
            log(f"cut {m['conversation']}")
    # 2. transcribe (GPU), newest conversations first so recent talk is searchable soonest
    todo = [r["folder"] for r in con.execute("SELECT folder FROM conversation WHERE status='cut' ORDER BY speech_start DESC")]
    if todo:
        with thermal.gpu_lock(cfg.library, log=log):
            _transcribe_all(cfg, con, out, todo, diarization, log)
    _post(cfg, con, out, log)


def _transcribe_all(cfg, con, out, todo, diarization, log):
    from . import search, transcribe
    engine = transcribe.Engine()
    for name in todo:
        thermal.wait_cool(log=log)
        f = out / name
        transcribe.transcribe_folder(f, engine, use_diarization=diarization, log=log)
        search.index_transcript(con, f)
        con.execute("UPDATE conversation SET status='transcribed' WHERE folder=?", (name,))
        con.commit()
        log(f"transcribed {name}")


def _post(cfg, con, out, log):
    from . import enhance, summarize
    # 3. listening tracks (CPU)
    if enhance.deep_filter_bin():
        for f in sorted(out.glob("*/")):
            if not (f / "listen.opus").exists():
                thermal.wait_cool(log=log)
                enhance.make_listen_track(f)
    # 4. summaries, if the LLM endpoint is up (otherwise they stay 'transcribed' for later)
    prof = cfg.llm_profile()
    pending = [r["folder"] for r in con.execute("SELECT folder FROM conversation WHERE status='transcribed'")]
    if pending and llm_reachable(prof):
        for name in pending:
            d = summarize.summarize_folder(out / name, prof)
            con.execute("UPDATE conversation SET status='summarized' WHERE folder=?", (name,))
            con.commit()
            log(f"summarized {name}: {d['title']}")
    elif pending:
        log(f"LLM endpoint {prof['base_url']} not reachable: {len(pending)} summary(ies) left for later")
