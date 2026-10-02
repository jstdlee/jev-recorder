"""jev-recorder desktop app (Dear ImGui via imgui-bundle). Layout and behaviour follow the polish-ui
skill: soft page, rounded cards, small-caps sections, segmented pills, one accent action per screen.

  jrec ui [--ui-script "open:0,wait:2,shot:/tmp/a.png"]          (script waits are in seconds)

Heavy work (speech to text, summaries, translation, cleaned copies) runs as `jrec …` child
processes; the UI shows their progress. Audio files are only ever read.
"""
import json
import os
import shlex
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from imgui_bundle import hello_imgui, imgui

from .. import db, ingest, search
from .. import theme as th
from ..theme import C, U
from ..timeref import parse as parse_goto
from . import dialogs, timeline, transcript
from .data import Conversation
from .player import Player
from .timeline import clamp_view, fmt_offset

FONT_CANDIDATES = ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                   "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc",
                   "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"]
THAI_FONTS = ["/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf",
              "/usr/share/fonts/opentype/noto/NotoSansThai-Regular.otf"]
STAGE_WEIGHT = {"asr": (0.0, 0.8), "align": (0.8, 0.1), "speakers": (0.9, 0.1), "summary": (0.0, 1.0),
                "translate": (0.0, 1.0)}


def fmt_clock(dt):
    return dt.strftime("%H:%M:%S")


class App:
    def __init__(self, cfg, script=None):
        self.cfg = cfg
        self.cfg_path = os.environ.get("JREC_CONFIG_PATH")
        self.con = db.connect(cfg.db_path)
        search.ensure(self.con)
        self.prefs = th.load_prefs()
        self.player = Player()
        self.player.speed = float(self.prefs["speed"])
        self.player.sound = self.prefs["sound"]
        self.player.channel = self.prefs["channel"]
        self.skip_silence, self.follow = self.prefs["skip_silence"], self.prefs["follow"]
        self.convs, self.sel = [], None
        self.query, self.hits = "", None
        # per-conversation view state
        self.view, self.cursor, self.drag = (0.0, 1.0), 0.0, None
        self.range_ab, self.loop = None, False
        self.find, self.match_idx, self.match_pos = "", [], None
        self.goto_buf, self.goto_err = "", False
        self.view_lang, self.row_lang, self.sel_row = None, {}, None
        self.scroll_to_t = None
        self.ctx_t, self.ctx_note = 0.0, None
        # dialogs
        self.show_settings = self.show_progress = False
        self.row_view = self.note_edit = self.speaker_edit = self.moment_edit = None
        self.llm_edit, self.llm_test = {}, ""
        self.settings_query, self.settings_focus = "", False
        self.focus_find = self.focus_goto = False
        self.side_tab, self.person_open, self.rec_open = "conv", None, None
        # recorder import
        self.recorders_seen, self.pending_import = set(), None
        self.import_msg, self.importing = "", False
        # background job
        self.proc, self.proc_log = None, []
        self.job_label, self.job_t0, self.job_exit = "", 0.0, None
        self.job_file, self.job_step, self.job_files = None, None, []
        self.need_reload, self.flash = False, ""
        self.script = [s.strip() for s in script.split(",")] if script else []
        self.script_wait, self.quit, self.shot_path = 0.0, False, None
        self.reload()
        threading.Thread(target=self._watch_recorders, daemon=True).start()

    # ------------------------------------------------------------ data
    def reload(self):
        rows = self.con.execute("SELECT * FROM conversation ORDER BY speech_start DESC").fetchall()
        keep = {c.name: c for c in self.convs}
        out = []
        for r in rows:
            f = self.cfg.library / "conversations" / r["folder"]
            if not (f / "manifest.json").exists():
                continue
            c = keep.get(r["folder"]) or Conversation(f, r)
            c.status = r["status"]
            c.reload(self.con)
            out.append(c)
        self.convs = out
        if self.sel:
            self.sel = next((c for c in self.convs if c.name == self.sel.name), None)
            self.update_matches()

    def select(self, conv, t=None):
        if conv is not self.sel:
            self.player.stop()
            self.sel = conv
            self.view = (0.0, conv.duration)
            self.range_ab, self.loop, self.sel_row = None, False, None
            self.cursor = conv.sp0
            if conv.peaks is None:
                threading.Thread(target=conv.load_peaks, daemon=True).start()
            self.update_matches()
        if t is not None:
            self.cursor = t
            self.scroll_to_t = t
            a, b = self.view
            if not (a <= t <= b):
                span = b - a
                self.view = clamp_view(t - span / 3, t + span * 2 / 3, conv.duration)

    def seek(self, c, t, play=False):
        self.select(c, t)
        if play or self.player.playing:
            self.player.play(c, t)

    def conv_label(self, name):
        """'Fri 3 Oct · 19:44 · title' for a conversation folder name."""
        c = next((x for x in self.convs if x.name == name), None)
        if not c:
            return name
        return f"{c.speech_start:%a %-d %b}  ·  {c.speech_start:%H:%M}  ·  {c.title or 'not transcribed yet'}"

    def update_matches(self):
        c = self.sel
        self.match_idx = c.matches(self.find, self.view_lang) if c and self.find.strip() else []
        if self.match_pos is not None and self.match_pos >= len(self.match_idx):
            self.match_pos = None

    # ------------------------------------------------------------ playback helpers
    def on_playhead(self, c, pos):
        """Called each frame while playing: end of clip, A–B loop, skip silence. Returns the position."""
        if pos > c.duration:
            self.player.stop()
            return None
        if self.loop and self.range_ab:
            a, b = self.range_ab
            if pos >= b or pos < a - 1.0:
                self.player.play(c, a)
                return a
            return pos
        if self.skip_silence:
            spans = c.speech_spans()
            inside = any(a - 0.5 <= pos <= b + 1.5 for a, b in spans)
            nxt = c.next_speech(pos, 1)
            if not inside and nxt is not None and nxt - pos > 3.0:
                self.player.play(c, nxt - 0.3)
                return nxt - 0.3
        return pos

    def toggle_play(self, c):
        if self.player.playing and self.player.conv is c:
            self.cursor = self.player.position() or self.cursor
            self.player.stop()
        else:
            start = self.range_ab[0] if (self.loop and self.range_ab and not
                                         (self.range_ab[0] <= self.cursor < self.range_ab[1])) else self.cursor
            self.player.play(c, start)

    def here(self, c):
        return self.player.position() if self.player.playing and self.player.conv is c else self.cursor

    def jump_speech(self, c, direction):
        t = c.next_speech(self.here(c), direction)
        if t is not None:
            self.seek(c, max(0.0, t - 0.3))

    def set_speed(self, v):
        self.player.speed = v
        self.set_pref("speed", v)
        self.player.restart()

    def set_a(self, t):
        b = self.range_ab[1] if self.range_ab and self.range_ab[1] > t else min(self.sel.duration, t + 5)
        self.range_ab = (t, b)

    def set_b(self, t):
        a = self.range_ab[0] if self.range_ab and self.range_ab[0] < t else max(0.0, t - 5)
        self.range_ab = (a, t)

    def goto_match(self, step):
        if not self.match_idx:
            return
        here = self.here(self.sel)
        if self.match_pos is None:
            k = next((k for k, i in enumerate(self.match_idx) if self.sel.segments[i]["_t0"] > here), 0)
            self.match_pos = k if step > 0 else (k - 1) % len(self.match_idx)
        else:
            self.match_pos = (self.match_pos + step) % len(self.match_idx)
        s = self.sel.segments[self.match_idx[self.match_pos]]
        self.select(self.sel, s["_t0"])
        self.sel_row = (self.sel.name, self.match_idx[self.match_pos])

    # ------------------------------------------------------------ notes / rows / speakers / translation
    def new_note(self, c, t):
        self.note_edit = {"conv": c, "t": t, "text": "", "focus": True}

    def edit_note(self, c, n):
        self.note_edit = {"conv": c, "t": n["t"], "text": n["text"], "id": n["id"], "focus": True}

    def open_row(self, c, i):
        self.row_view = (c, i)

    def rename_speaker(self, c, spk, row=None):
        current = c.row_names.get(row) if row is not None and row in c.row_names else c.names.get(spk, "")
        self.speaker_edit = {"conv": c, "speaker": spk, "row": row, "name": current, "focus": True,
                             "scope": "row" if row is not None and row in c.row_names else "voice"}

    def toggle_row_lang(self, c, i):
        key = (c.name, i)
        cur = self.row_lang.get(key, self.view_lang)
        to = self.prefs["translate_to"]
        shown_tr = cur and i in c.translations.get(cur, {})
        if shown_tr:
            self.row_lang[key] = None                              # back to the original
        elif i in c.translations.get(to, {}):
            self.row_lang[key] = to
        else:
            self.translate(c, to, rows=[i])
            self.row_lang[key] = to

    def translate(self, c, to, rows=None):
        args = ["translate", str(c.folder), "--to", to] + (["--rows", ",".join(map(str, rows))] if rows else [])
        what = f"row {rows[0] + 1}" if rows and len(rows) == 1 else "the transcript"
        self.start_job(args, f"Translating {what} into {to}", [c.name])

    # ------------------------------------------------------------ prefs
    def set_pref(self, key, value):
        self.prefs[key] = value
        th.save_prefs(self.prefs)
        if key in ("theme", "text_size"):
            th.apply(self.prefs["theme"], self.prefs["text_size"])

    def apply_theme(self):
        th.apply(self.prefs["theme"], self.prefs["text_size"])

    # ------------------------------------------------------------ background jobs
    def start_job(self, args, label, files=None):
        """Run a jrec subcommand in a child process (GPU work never runs in the UI process)."""
        if self.job_busy:
            return
        cmd = [sys.executable, "-m", "jrec.cli"] + (["--config", str(self.cfg_path)] if self.cfg_path else []) + args
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                     stdin=subprocess.DEVNULL, close_fds=True, cwd=str(Path.home()))
        self.job_label, self.job_t0, self.job_exit = label, time.monotonic(), None
        self.proc_log = [f"$ jrec {shlex.join(args)}"]
        self.job_file, self.job_step, self.job_files = None, None, list(files or [])
        threading.Thread(target=self._pump_log, daemon=True).start()

    def start_processing(self):
        todo = [r["folder"] for r in self.con.execute(
            "SELECT folder FROM conversation WHERE status='cut' ORDER BY speech_start DESC")]
        self.start_job(["process"], "Transcribing new conversations", todo)

    @property
    def job_busy(self):
        return self.proc is not None and self.proc.poll() is None

    def job_elapsed(self):
        return time.monotonic() - self.job_t0

    def job_file_frac(self):
        stage, d, t = self.job_step or ("", 0, 1)
        a, w = STAGE_WEIGHT.get(stage, (0.0, 0.0))
        return a + w * (d / max(1, t))

    def job_stage_label(self):
        stage, d, t = self.job_step or ("", 0, 1)
        return {"asr": f"Speech to text  ·  part {d} of {t}", "align": "Word timings", "speakers": "Who spoke when",
                "summary": f"Summarising  ·  part {d + 1} of {t}", "translate": f"Translating  ·  {d} of {t} rows"
                }.get(stage, "Preparing")

    def job_overall(self):
        if not self.job_busy:
            return 1.0 if not self.job_exit else 0.0
        if not self.job_file or self.job_file[2] == "loading-models":
            return 0.0
        i, n, _ = self.job_file
        return ((i - 1) + self.job_file_frac()) / max(1, n)

    def _pump_log(self):
        for line in self.proc.stdout:
            if line.startswith("PROGRESS "):
                f = line.split()
                if f[1] == "file":
                    self.job_file, self.job_step = (int(f[2]), int(f[3]), " ".join(f[4:])), None
                    name = " ".join(f[4:])
                    if name != "loading-models" and name not in self.job_files:
                        self.job_files.append(name)
                elif f[1] == "step":
                    self.job_step = (f[2], int(f[3]), int(f[4]))
                continue
            low = line.lower()
            if "warn" not in low and "it/s]" not in low and "loading" not in low:
                self.proc_log.append(line.rstrip())
                self.proc_log = self.proc_log[-300:]
        self.job_exit = self.proc.wait()
        if self.job_exit:
            self.proc_log.append(f"failed (exit {self.job_exit}); see the lines above")
        self.need_reload = True  # the SQLite connection belongs to the UI thread: reload there

    # ------------------------------------------------------------ recorder import
    def _watch_recorders(self):
        from ..watch import remount_readonly
        while True:
            try:
                recs = ingest.find_recorders(self.cfg)
                now = {str(m) for _, m, _ in recs}
                for d, mnt, serial in recs:
                    if str(mnt) in self.recorders_seen or self.pending_import:
                        continue
                    dev = ingest.mount_points().get(str(mnt))
                    mnt = remount_readonly(mnt, dev, log=lambda *a: None) if dev and dev.startswith("/dev/") else mnt
                    con = db.connect(self.cfg.db_path)
                    cands = [c for c in ingest.scan(d, mnt, serial, con) if c.status == "new"]
                    if cands:
                        self.pending_import = {"device": d, "mount": mnt, "serial": serial, "cands": cands,
                                               "checked": [True] * len(cands), "open": True}
                self.recorders_seen = now if not self.pending_import else self.recorders_seen | now
            except Exception as e:  # never kill the UI over a flaky mount
                self.import_msg = f"recorder scan error: {e}"
            time.sleep(2)

    def do_import(self, items, d, serial):
        self.importing = True
        con = db.connect(self.cfg.db_path)
        try:
            for i, c in enumerate(items, 1):
                self.import_msg = f"Copying {i} of {len(items)}: {c.rel}"
                ingest.import_one(c, d, serial, self.cfg, con)
            self.import_msg = f"Imported {len(items)}. The recorder was not changed; it is safe to eject."
            self.need_reload = True
        except Exception as e:
            self.import_msg = f"Import failed: {e}"
        self.importing = False

    # ------------------------------------------------------------ frame
    def gui(self):
        if self.need_reload:
            self.need_reload = False
            self.reload()
        self._run_script()
        self.global_keys()
        vp = imgui.get_main_viewport()
        imgui.set_next_window_pos(vp.work_pos)
        imgui.set_next_window_size(vp.work_size)
        imgui.begin("main", None, imgui.WindowFlags_.no_decoration | imgui.WindowFlags_.no_move
                    | imgui.WindowFlags_.no_saved_settings | imgui.WindowFlags_.no_bring_to_front_on_focus)
        ts = self.prefs["text_size"]
        with th.card("side", imgui.ImVec2(310 * ts, 0), padding=(10, 10)):
            self.sidebar()
        imgui.same_line(0, 14)
        imgui.push_style_color(imgui.Col_.child_bg, C("bg", 0.0))
        imgui.push_style_var(imgui.StyleVar_.child_border_size, 0)
        imgui.begin_child("main_area", imgui.ImVec2(0, 0))
        imgui.pop_style_var()
        imgui.pop_style_color()
        if self.sel:
            self.conversation(self.sel)
        else:
            imgui.dummy(imgui.ImVec2(0, 40))
            imgui.text_colored(C("text_dim"), "Pick a conversation on the left, or plug in the recorder.")
        imgui.end_child()
        dialogs.import_dialog(self)
        dialogs.progress(self)
        dialogs.row_view(self)
        dialogs.note_editor(self)
        dialogs.speaker_editor(self)
        dialogs.moment_editor(self)
        imgui.end()
        dialogs.settings(self)   # its own window, drawn last: floats above the main window
        if self.quit:
            hello_imgui.get_runner_params().app_shall_exit = True

    def global_keys(self):
        io = imgui.get_io()
        K = imgui.Key
        ctrl = io.key_ctrl or io.key_super
        if ctrl and imgui.is_key_pressed(K.comma, False):
            self.show_settings = self.settings_focus = True
        sizes = [0.9, 1.0, 1.1, 1.25, 1.5]
        cur = min(range(len(sizes)), key=lambda i: abs(sizes[i] - self.prefs["text_size"]))
        if ctrl and (imgui.is_key_pressed(K.equal, False) or imgui.is_key_pressed(K.keypad_add, False)):
            self.set_pref("text_size", sizes[min(len(sizes) - 1, cur + 1)])
        elif ctrl and (imgui.is_key_pressed(K.minus, False) or imgui.is_key_pressed(K.keypad_subtract, False)):
            self.set_pref("text_size", sizes[max(0, cur - 1)])
        elif ctrl and imgui.is_key_pressed(K._0, False):
            self.set_pref("text_size", 1.0)
        elif ctrl and imgui.is_key_pressed(K.f, False):
            self.focus_find = True
        elif ctrl and imgui.is_key_pressed(K.g, False):
            self.focus_goto = True
        c = self.sel
        if c is None or io.want_text_input or ctrl or imgui.is_popup_open("", imgui.PopupFlags_.any_popup_id):
            return
        if imgui.is_key_pressed(K.space, False):
            self.toggle_play(c)
        elif imgui.is_key_pressed(K.n, False):
            self.jump_speech(c, 1)
        elif imgui.is_key_pressed(K.p, False):
            self.jump_speech(c, -1)
        elif imgui.is_key_pressed(K.m, False):
            self.new_note(c, self.here(c))
        elif imgui.is_key_pressed(K.left_bracket, False):
            self.set_a(self.here(c))
        elif imgui.is_key_pressed(K.right_bracket, False):
            self.set_b(self.here(c))
        elif imgui.is_key_pressed(K.l, False):
            self.loop = not self.loop and self.range_ab is not None
        elif imgui.is_key_pressed(K.escape, False):
            self.range_ab, self.loop = None, False
        elif imgui.is_key_pressed(K.equal, False) or imgui.is_key_pressed(K.minus, False):
            self.zoom(c, 0.6 if imgui.is_key_pressed(K.equal, False) else 1.6)
        elif imgui.is_key_pressed(K.enter, False) and self.sel_row and self.sel_row[0] == c.name:
            self.open_row(c, self.sel_row[1])
        elif imgui.is_key_pressed(K.right_arrow) or imgui.is_key_pressed(K.left_arrow):
            d = 1.0 if io.key_shift else (30.0 if io.key_alt else 5.0)
            self.seek(c, max(0.0, min(c.duration, self.here(c) + (d if imgui.is_key_pressed(K.right_arrow) else -d))))

    def zoom(self, c, f, center=None):
        a, b = self.view
        mid = center if center is not None else self.here(c)
        span = min(c.duration, max(4.0, (b - a) * f))
        self.view = clamp_view(mid - span / 2, mid + span / 2, c.duration)

    # ------------------------------------------------------------ sidebar
    def sidebar(self):
        if self.proc_log:
            self.job_indicator()
        imgui.set_next_item_width(-1)
        changed, self.query = imgui.input_text_with_hint("##q", "Search all transcripts", self.query)
        if changed:
            self.hits = search.search(self.con, self.query) if self.query.strip() else None
        n_new = sum(c.status == "cut" for c in self.convs)
        if th.button(f"Transcribe new ({n_new})" if n_new else "Transcribe new", disabled=self.job_busy or not n_new,
                     why="A job is already running" if self.job_busy else "Everything is transcribed"):
            self.start_processing()
        imgui.same_line()
        if th.button("Settings", help_="Appearance, playback, summaries and translation (Ctrl+,)"):
            self.show_settings = True
        imgui.dummy(imgui.ImVec2(0, 2))
        _, self.side_tab = th.seg("sidetab", self.side_tab, ["conv", "people", "rec", "moments"],
                                  ["Talks", "People", "Recordings", "Moments"],
                                  ["Conversations, newest first", "Everyone you have named, and where they speak",
                                   "Original recordings from the recorder (read-only archive)",
                                   "Your notes and saved A–B stretches"])
        imgui.dummy(imgui.ImVec2(0, 2))
        imgui.begin_child("list", imgui.ImVec2(0, 0), 0)
        if self.hits is not None:
            self.side_hits()
        elif self.side_tab == "people":
            self.side_people()
        elif self.side_tab == "rec":
            self.side_recordings()
        elif self.side_tab == "moments":
            self.side_moments()
        else:
            self.side_conversations()
        imgui.end_child()

    def side_hits(self):
        th.section(f"{len(self.hits)} result{'s' if len(self.hits) != 1 else ''}")
        for i, h in enumerate(self.hits):
            if self.list_row(f"hit{i}", h["text"], f"{h['abs_start'][:10]}  {h['abs_start'][11:19]}"
                             + (f"  ·  {h['speaker']}" if h.get("speaker") else ""), False):
                conv = next((c for c in self.convs if c.name == h["folder"]), None)
                if conv:
                    self.find = self.query
                    self.select(conv, conv.t_of_abs(datetime.fromisoformat(h["abs_start"])))
                    self.update_matches()
        if not self.hits:
            imgui.text_colored(C("text_dim"), "No transcript contains that.")

    def side_conversations(self):
        if not self.convs:
            th.section("Library is empty")
            imgui.push_text_wrap_pos(0)
            imgui.text_colored(C("text_dim"), "Plug in the recorder: the import dialog opens here. "
                                              "A copied folder can be imported with  jrec import <folder>.")
            imgui.pop_text_wrap_pos()
        day = None
        for c in self.convs:
            d = c.speech_start.strftime("%a %-d %b %Y")
            if d != day:
                imgui.dummy(imgui.ImVec2(0, 4 if day else 0))
                th.section(d)
                day = d
            status = {"cut": "not transcribed", "transcribed": "transcribed",
                      "summarized": "summarized"}.get(c.status, c.status)
            extra = f"  ·  {len(c.notes)} note{'s' if len(c.notes) != 1 else ''}" if c.notes else ""
            if self.list_row(c.name, c.title or f"Conversation at {c.speech_start:%H:%M}",
                             f"{c.speech_start:%H:%M}  ·  {(c.sp1 - c.sp0) / 60:.0f} min  ·  {status}{extra}",
                             c is self.sel):
                self.select(c)

    def side_people(self):
        people = db.people(self.con)
        if not people:
            th.section("No names yet")
            imgui.push_text_wrap_pos(0)
            imgui.text_colored(C("text_dim"), "Voices show as Char 1, Char 2… Click a name in the By column of a "
                                              "transcript to say who it is.")
            imgui.pop_text_wrap_pos()
            return
        for name in sorted(people):
            where = people[name]
            open_ = self.person_open == name
            if self.list_row(f"p_{name}", name, f"{len(where)} conversation{'s' if len(where) != 1 else ''}", open_):
                self.person_open = None if open_ else name
            if open_:
                imgui.indent(10)
                for c in self.convs:
                    if c.name not in where:
                        continue
                    rows = [i for i, s in enumerate(c.segments) if c.speaker(s, i) == name]
                    th.section(f"{c.speech_start:%a %-d %b  %H:%M}  ·  {len(rows)} rows")
                    for i in rows[:40]:
                        s = c.segments[i]
                        if imgui.selectable(f"{s['abs_start'][11:19]}  {s['text'][:60]}##pr{c.name}{i}", False)[0]:
                            self.select(c, s["_t0"])
                            self.sel_row = (c.name, i)
                imgui.unindent(10)

    def side_recordings(self):
        rows = self.con.execute("SELECT * FROM source ORDER BY start DESC").fetchall()
        if not rows:
            th.section("No recordings imported")
            return
        th.section(f"{len(rows)} original recording{'s' if len(rows) != 1 else ''}  ·  read-only")
        from ..cli import _fmt_dur, _fmt_size, human_flag
        for r in rows:
            convs = [c for c in self.convs if any(p["source_sha256"] == r["sha256"] for p in c.manifest["parts"])]
            flags = json.loads(r["flags"])
            sub = (f"{r['start'][:16].replace('T', ' ')}  ·  {_fmt_dur(r['duration'])}  ·  {_fmt_size(r['size'])}  ·  "
                   f"{len(convs)} talk{'s' if len(convs) != 1 else ''}" + (f"  ·  {', '.join(human_flag(f) for f in flags)}"
                                                                          if flags else ""))
            open_ = self.rec_open == r["sha256"]
            if self.list_row(f"r_{r['sha256'][:12]}", r["orig_path"].split("/")[-1], sub, open_):
                self.rec_open = None if open_ else r["sha256"]
            th.tip(f"{r['device']}:{r['orig_path']}\nsha256 {r['sha256']}\nstart time: {r['start_source']} "
                   f"({r['start_conf']} confidence)")
            if open_:
                imgui.indent(10)
                for c in convs:
                    if imgui.selectable(f"{c.speech_start:%H:%M}  {c.title or 'Conversation'}##rc{c.name}",
                                        c is self.sel)[0]:
                        self.select(c)
                if not convs:
                    th.small("No conversation found in this recording (only silence or noise).")
                imgui.unindent(10)

    def side_moments(self):
        items = [("note", n) for n in db.all_notes(self.con)] + [("moment", m) for m in db.moments(self.con)]
        items.sort(key=lambda x: x[1]["abs"] if x[0] == "note" else x[1]["abs_a"], reverse=True)
        if not items:
            th.section("Nothing saved yet")
            imgui.push_text_wrap_pos(0)
            imgui.text_colored(C("text_dim"), "Add a note (M or ＋ Note) or mark A–B and press Save as moment.")
            imgui.pop_text_wrap_pos()
            return
        by_name = {c.name: c for c in self.convs}
        day = None
        for kind, it in items:
            when = it["abs"] if kind == "note" else it["abs_a"]
            d = when[:10]
            if d != day:
                th.section(datetime.fromisoformat(when).strftime("%a %-d %b %Y"))
                day = d
            c = by_name.get(it["folder"])
            if kind == "note":
                imgui.push_style_color(imgui.Col_.text, C("note"))
                clicked = imgui.selectable(f"◆ {when[11:19]}  {it['text']}##mn{it['id']}", False)[0]
                imgui.pop_style_color()
                th.tip("Your note")
                if clicked and c:
                    self.select(c, it["t"])
            else:
                clicked = imgui.selectable(f"▭ {when[11:19]}–{it['abs_b'][11:19]}  {it['label']}##mm{it['id']}",
                                           False)[0]
                th.tip("Saved stretch: opens with A–B set to repeat")
                if clicked and c:
                    self.select(c, it["a"])
                    self.range_ab, self.loop = (it["a"], it["b"]), True
                if imgui.begin_popup_context_item(f"mctx{it['id']}"):
                    if imgui.menu_item("Delete this moment", "", False)[0]:
                        db.delete_moment(self.con, it["id"])
                        if c:
                            c.moments = db.moments(self.con, c.name)
                    imgui.end_popup()

    def job_indicator(self):
        busy = self.job_busy
        p = imgui.get_cursor_screen_pos()
        w = imgui.get_content_region_avail().x
        h = imgui.get_font_size() * 2.6
        if imgui.invisible_button("job_ind", imgui.ImVec2(w, h)):
            self.show_progress = True
        th.tip("Show progress")
        dl = imgui.get_window_draw_list()
        dl.add_rect_filled(p, imgui.ImVec2(p.x + w, p.y + h), U("track"), 8.0)
        if busy:
            spin = "◐◓◑◒"[int(time.monotonic() * 4) % 4]
            label = f"{spin}  {self.job_label}"
            col = U("text")
        elif self.job_exit:
            label, col = f"✕  {self.job_label}: failed", U("danger")
        else:
            label, col = f"✓  {self.job_label}: done", U("ok")
        dl.push_clip_rect(p, imgui.ImVec2(p.x + w - 6, p.y + h), True)
        dl.add_text(imgui.ImVec2(p.x + 10, p.y + 5), col, label)
        dl.pop_clip_rect()
        frac = self.job_overall()
        by = p.y + h - 10
        dl.add_rect_filled(imgui.ImVec2(p.x + 10, by), imgui.ImVec2(p.x + w - 10, by + 4), U("pill_border"), 2.0)
        dl.add_rect_filled(imgui.ImVec2(p.x + 10, by), imgui.ImVec2(p.x + 10 + (w - 20) * frac, by + 4),
                           U("danger" if self.job_exit else "accent"), 2.0)
        imgui.dummy(imgui.ImVec2(0, 2))

    def list_row(self, id_, title, sub, selected):
        """Two-line list row: title in text colour, details in grey; accent wash when selected."""
        fs = imgui.get_font_size()
        h = fs * 2.35 + 8
        p = imgui.get_cursor_screen_pos()
        w = imgui.get_content_region_avail().x
        clicked = imgui.selectable(f"##{id_}", selected, 0, imgui.ImVec2(0, h))[0]
        dl = imgui.get_window_draw_list()
        dl.push_clip_rect(p, imgui.ImVec2(p.x + w - 4, p.y + h), True)
        dl.add_text(imgui.ImVec2(p.x + 6, p.y + 4), U("text"), title)
        dl.add_text(imgui.get_font(), fs * 0.86, imgui.ImVec2(p.x + 6, p.y + 6 + fs), U("text_dim"), sub)
        dl.pop_clip_rect()
        if imgui.calc_text_size(title).x > w - 10:
            th.tip(title)
        return clicked

    # ------------------------------------------------------------ conversation
    def conversation(self, c):
        ts = self.prefs["text_size"]
        imgui.push_font(None, imgui.get_style().font_size_base * 1.3)
        imgui.text(c.title or f"Conversation at {c.speech_start:%H:%M}")
        imgui.pop_font()
        parts = len(c.manifest["parts"])
        th.small(f"{c.speech_start:%a %-d %b %Y}  ·  talk {fmt_clock(c.abs_at(c.sp0))}–{fmt_clock(c.abs_at(c.sp1))} "
                 f"({(c.sp1 - c.sp0) / 60:.0f} min)  ·  kept {fmt_clock(c.start)}–{fmt_clock(c.end)} "
                 f"with 10 min either side" + (f"  ·  {parts} files" if parts > 1 else ""))
        from ..cli import human_flag
        flags = sorted({human_flag(f) for p in c.manifest["parts"] for f in p["source_start"].get("flags", [])})
        confs = {p["source_start"].get("confidence") for p in c.manifest["parts"]} - {None}
        if flags or (confs and "high" not in confs):
            th.small(f"Clock time is {', '.join(sorted(confs))} confidence" + (f": {', '.join(flags)}" if flags else ""),
                     "warn")
        if c.manifest["seams"]:
            th.small(f"{len(c.manifest['seams'])} recorder file boundary(ies): a moment of audio may be missing there",
                     "warn")
        imgui.dummy(imgui.ImVec2(0, 2))
        self.actions(c)
        imgui.dummy(imgui.ImVec2(0, 2))
        with th.card("player", flags=imgui.ChildFlags_.auto_resize_y):
            self.transport(c)
            self.options(c)
            self.find_bar(c)
            timeline.draw(self, c)
        imgui.dummy(imgui.ImVec2(0, 2))
        avail = imgui.get_content_region_avail()
        sum_w = max(300.0 * ts, avail.x * 0.28) if c.summary else 0
        imgui.begin_group()
        self.transcript_header(c, avail.x - sum_w - (14 if sum_w else 0))
        with th.card("transcript", imgui.ImVec2(avail.x - sum_w - (14 if sum_w else 0), 0), padding=(8, 6)):
            transcript.draw(self, c)
        imgui.end_group()
        if c.summary:
            imgui.same_line(0, 14)
            imgui.begin_group()
            th.section("Summary")
            imgui.dummy(imgui.ImVec2(0, imgui.get_frame_height() - imgui.get_font_size() * 0.8 - 8))
            with th.card("summary", imgui.ImVec2(0, 0)):
                self.summary_panel(c)
            imgui.end_group()

    def actions(self, c):
        busy = self.job_busy
        why = "Another job is running; see the indicator on the left"
        if c.status == "cut":
            if th.primary_button("Transcribe", disabled=busy, why=why):
                self.start_job(["transcribe", str(c.folder)], f"Transcribing {c.speech_start:%H:%M}", [c.name])
            imgui.same_line()
            imgui.align_text_to_frame_padding()
            th.small("Speech to text, word timings and speakers in the background (GPU, ~11 GB)")
        else:
            label = "Summarize" if c.status == "transcribed" else "Summarize again"
            draw = th.primary_button if c.status == "transcribed" else th.button
            if draw(label, disabled=busy, why=why):
                self.start_job(["summarize", str(c.folder)], f"Summarising {c.speech_start:%H:%M}", [c.name])
            th.tip(f"Uses {self.cfg.llm_profile()['base_url']}; long talks are summarised in overlapping parts")
            imgui.same_line()
            to = self.prefs["translate_to"]
            done = len(c.translations.get(to, {})) >= len([s for s in c.segments if s["text"].strip()])
            if th.button(f"Translate into {to}", disabled=busy or done,
                         why=why if busy else f"Already in {to}; change the language in Settings"):
                self.translate(c, to)
        imgui.same_line()
        if th.button("Verify clips", help_="Re-check every clip byte for byte against the archived original"):
            from ..cutter import verify_folder
            c.verified = verify_folder(c.folder, self.cfg.archive)
        if self.range_ab:
            imgui.same_line()
            a, b = self.range_ab
            if th.button(f"Export A–B ({b - a:.0f} s)",
                         help_="Save this stretch as a byte-exact excerpt with its own proof (manifest)"):
                from ..export import export_range
                out = export_range(c.manifest, self.cfg.archive, self.cfg.library / "exports", a, b)
                self.flash = f"Excerpt saved: {out}"
        if c.verified is not None:
            imgui.same_line()
            imgui.align_text_to_frame_padding()
            th.small("Verification failed: " + "; ".join(c.verified) if c.verified
                     else "Clips match the archived originals", "danger" if c.verified else "ok")
        if self.flash:
            th.small(self.flash, "ok")

    @staticmethod
    def _fit(width, gap=14):
        """Continue on this line if `width` more pixels fit, else start a new line."""
        imgui.same_line(0, gap)
        if imgui.get_content_region_avail().x < width:
            imgui.new_line()

    def transport(self, c):
        playing = self.player.playing and self.player.conv is c
        ts = self.prefs["text_size"]
        imgui.push_style_var(imgui.StyleVar_.button_text_align, imgui.ImVec2(0.5, 0.5))
        if imgui.button("Pause" if playing else "Play", imgui.ImVec2(72 * ts, 0)):
            self.toggle_play(c)
        imgui.pop_style_var()
        th.tip("Space")
        for label, fn, tip_ in (("|◀", lambda: self.seek(c, c.sp0), "Back to where the talk starts"),
                                ("◀", lambda: self.jump_speech(c, -1), "Previous speech (P)"),
                                ("▶", lambda: self.jump_speech(c, 1), "Next speech (N)")):
            imgui.same_line(0, 4)
            if imgui.button(label):
                fn()
            th.tip(tip_)
        imgui.same_line(0, 14)
        here = self.here(c)
        imgui.align_text_to_frame_padding()
        imgui.text(fmt_clock(c.abs_at(here)))
        imgui.same_line(0, 6)
        imgui.align_text_to_frame_padding()
        th.small(f"{fmt_offset(here)} / {fmt_offset(c.duration)}")
        imgui.same_line(0, 14)
        if self.focus_goto:
            imgui.set_keyboard_focus_here()
            self.focus_goto = False
        imgui.set_next_item_width(150 * ts)
        if self.goto_err:
            imgui.push_style_color(imgui.Col_.frame_bg, C("danger", 0.25))
        enter, self.goto_buf = imgui.input_text_with_hint("##goto", "Go to 14:15:30, +30, @5:00", self.goto_buf,
                                                          imgui.InputTextFlags_.enter_returns_true)
        if self.goto_err:
            imgui.pop_style_color()
        th.tip("Clock time (14:15:30), from the playhead (+30, -1:00) or from the start (@5:00). Ctrl+G")
        if enter:
            t = parse_goto(self.goto_buf, c.start, here, c.duration)
            self.goto_err = t is None
            if t is not None:
                self.seek(c, t)
                self.zoom(c, 1.0, t)
        # notes and A–B (wrapping onto a new line when the window is narrow)
        self._fit(imgui.calc_text_size("＋ Note").x + 24)
        imgui.push_style_color(imgui.Col_.button, C("note", 0.22))
        imgui.push_style_color(imgui.Col_.button_hovered, C("note", 0.35))
        if imgui.button("＋ Note"):
            self.new_note(c, here)
        imgui.pop_style_color(2)
        th.tip("Add a note at the playhead (M)")
        self._fit(imgui.calc_text_size("Set ASet B").x + 50)
        if imgui.button("Set A"):
            self.set_a(here)
        th.tip("Start of the stretch to repeat, at the playhead ([)")
        imgui.same_line(0, 4)
        if imgui.button("Set B"):
            self.set_b(here)
        th.tip("End of the stretch, at the playhead (])")
        if self.range_ab:
            a, b = self.range_ab
            label = f"{fmt_clock(c.abs_at(a))}–{fmt_clock(c.abs_at(b))} ({b - a:.1f} s)"
            self._fit(imgui.calc_text_size(label + "ClearSave as moment").x + th.seg_width(["Once", "Repeat"]) + 60, 10)
            ch, v = th.labeled_seg(label, "loop",
                                   self.loop, [False, True], ["Once", "Repeat"],
                                   ["Play through", "Repeat A–B until stopped (L)"])
            if ch:
                self.loop = v
                if v and playing:
                    self.player.play(c, a)
            imgui.same_line(0, 4)
            if imgui.button("Clear"):
                self.range_ab, self.loop = None, False
            th.tip("Remove the A–B range (Esc)")
            if self.range_ab:
                imgui.same_line(0, 4)
                if imgui.button("Save as moment"):
                    self.moment_edit = {"conv": c, "a": a, "b": b, "label": "", "focus": True}
                th.tip("Keep this stretch in Moments (left), with a label")
        else:
            self._fit(imgui.calc_text_size("or Shift+drag on the timeline").x, 8)
            imgui.align_text_to_frame_padding()
            th.small("or Shift+drag on the timeline")

    def options(self, c):
        labels = ["1×", "1.25×", "1.5×", "2×", "3×"]
        ch, v = th.labeled_seg("Speed", "speed", self.player.speed, [1.0, 1.25, 1.5, 2.0, 3.0], labels)
        if ch:
            self.set_speed(v)
        groups = (("Sound", "sound", self.player.sound, ["original", "clearer", "cleaned"], ["Original", "Clearer", "Cleaned"],
                   ["Exactly as recorded", "Live noise filter, for listening", "DeepFilterNet copy (made once)"]),
                  ("Channel", "chan", self.player.channel, ["both", "left", "right"], ["Both", "Left", "Right"],
                   ["Both microphones", "Left microphone only", "Right microphone only"]),
                  ("Skip silence", "skip", self.skip_silence, [False, True], ["Off", "On"],
                   ["Play every second", "Jump over quiet gaps longer than 3 s"]),
                  ("Follow", "follow", self.follow, [False, True], ["Off", "On"],
                   ["Keep the view still", "Scroll timeline and transcript with playback"]))
        for label, id_, val, opts, labs, tips in groups:
            need = imgui.calc_text_size(label).x + 6 + th.seg_width(labs)
            imgui.same_line(0, 16)
            if imgui.get_content_region_avail().x < need:
                imgui.new_line()
            ch, v = th.labeled_seg(label, id_, val, opts, labs, tips)
            if not ch:
                continue
            if id_ == "sound":
                if v == "cleaned" and not (c.folder / "listen.opus").exists():
                    self.start_job(["enhance", str(c.folder)], "Making the cleaned copy", [c.name])
                self.player.sound = v
                self.set_pref("sound", v)
                self.player.restart()
            elif id_ == "chan":
                self.player.channel = v
                self.set_pref("channel", v)
                self.player.restart()
            elif id_ == "skip":
                self.skip_silence = v
                self.set_pref("skip_silence", v)
            elif id_ == "follow":
                self.follow = v
                self.set_pref("follow", v)

    def find_bar(self, c):
        ts = self.prefs["text_size"]
        if self.focus_find:
            imgui.set_keyboard_focus_here()
            self.focus_find = False
        imgui.set_next_item_width(220 * ts)
        enter, new = imgui.input_text_with_hint("##find", "Find in this conversation (Ctrl+F)", self.find,
                                                imgui.InputTextFlags_.enter_returns_true)
        if new != self.find:
            self.find, self.match_pos = new, None
            self.update_matches()
        if enter:
            self.goto_match(1)
        imgui.same_line()
        n = len(self.match_idx)
        imgui.align_text_to_frame_padding()
        th.small(f"{(self.match_pos or 0) + 1 if self.match_pos is not None else 0} of {n}" if self.find.strip()
                 else "matches show in yellow")
        if n:
            imgui.same_line()
            if imgui.button("‹"):
                self.goto_match(-1)
            th.tip("Previous match")
            imgui.same_line(0, 4)
            if imgui.button("›"):
                self.goto_match(1)
            th.tip("Next match (Enter)")
            if self.match_pos is not None:
                s = c.segments[self.match_idx[self.match_pos]]
                imgui.same_line()
                if imgui.button("Play nearby"):
                    self.seek(c, max(0.0, s["_t0"] - 3.0), play=True)
                th.tip("Start 3 s before the match, to hear it in context")
                imgui.same_line(0, 4)
                if imgui.button("Repeat"):
                    self.range_ab = (max(0.0, s["_t0"] - 1.0), min(c.duration, s["_t1"] + 1.0))
                    self.loop = True
                    self.seek(c, self.range_ab[0], play=True)
                th.tip("Loop this match until stopped")
        # zoom, right-aligned
        zw = imgui.calc_text_size("−+Fit talkWhole").x + 4 * 22
        imgui.same_line(max(imgui.get_cursor_pos_x() + 10, imgui.get_window_width() - zw - 20))
        for label, fn, tip_ in (("−", lambda: self.zoom(c, 1.6), "Zoom out (-)"),
                                ("+", lambda: self.zoom(c, 0.6), "Zoom in (=); the scroll wheel zooms at the pointer"),
                                ("Fit talk", lambda: setattr(self, "view", clamp_view(c.sp0 - 15, c.sp1 + 15, c.duration)),
                                 "Show just the conversation"),
                                ("Whole", lambda: setattr(self, "view", (0.0, c.duration)), "Show the whole clip")):
            if imgui.small_button(label):
                fn()
            th.tip(tip_)
            imgui.same_line(0, 4)
        imgui.new_line()

    def transcript_header(self, c, width):
        th.section("Transcript")
        if not c.segments:
            imgui.dummy(imgui.ImVec2(0, imgui.get_frame_height() - imgui.get_font_size() * 0.8 - 8))
            return
        langs = [None] + sorted(c.translations)
        labels = ["Original"] + sorted(c.translations)
        imgui.same_line(0, 12)
        ch, v = th.labeled_seg("Show", "vlang", self.view_lang, langs, labels,
                               ["As spoken"] + [f"Translated into {L}; untranslated rows stay original" for L in labels[1:]])
        if ch:
            self.view_lang = v
            self.row_lang = {k: x for k, x in self.row_lang.items() if k[0] != c.name}
            self.update_matches()
        imgui.same_line(0, 12)
        imgui.align_text_to_frame_padding()
        th.small("click a row to select, double-click to play, a flag to switch language, Open for the full row")

    def summary_panel(self, c):
        sm = c.summary
        imgui.push_text_wrap_pos(0)
        imgui.text(sm.get("title", ""))
        imgui.dummy(imgui.ImVec2(0, 2))
        imgui.text_colored(C("text_dim"), sm.get("summary", ""))
        for key, head in (("key_points", "Key points"), ("action_items", "Action items")):
            items = sm.get(key) or []
            if not items:
                continue
            imgui.dummy(imgui.ImVec2(0, 4))
            th.section(head)
            for j, it in enumerate(items):
                imgui.text_wrapped(("☐ " if key == "action_items" else "•  ") + it["text"]
                                   + (f"  — {it['owner']}" if it.get("owner") else "")
                                   + (f", due {it['due']}" if it.get("due") else ""))
                for k, tm in enumerate(it.get("times", [])):
                    if k:
                        imgui.same_line(0, 4)
                    if imgui.small_button(f"{tm}##{key}{j}_{k}"):
                        seg = next((s for s in c.segments if s["abs_start"][11:19] == tm), None)
                        if seg:
                            self.seek(c, seg["_t0"], play=True)
                    th.tip("Play the moment this comes from")
        imgui.dummy(imgui.ImVec2(0, 6))
        th.small(f"Written by {(sm.get('_meta') or {}).get('model', 'the LLM')}; check it against the audio.")
        imgui.pop_text_wrap_pos()

    # ------------------------------------------------------------ scripted runs for headless tests (never XTest)
    def _run_script(self):
        if not self.script or time.monotonic() < self.script_wait:
            return
        cmd, _, arg = self.script.pop(0).partition(":")
        c = self.sel
        if cmd == "wait":
            self.script_wait = time.monotonic() + float(arg or 1)
        elif cmd == "open" and self.convs:
            self.select(self.convs[int(arg or 0)])
        elif cmd == "seek" and c:
            self.select(c, float(arg))
        elif cmd == "search":
            self.query = arg
            self.hits = search.search(self.con, arg)
        elif cmd == "find" and c:
            self.find = arg
            self.update_matches()
            self.goto_match(1)
        elif cmd == "zoom" and c:
            a, b = (float(x) for x in arg.split("-"))
            self.view = (a, b)
        elif cmd == "ab" and c:
            a, b = (float(x) for x in arg.split("-"))
            self.range_ab, self.loop = (a, b), True
        elif cmd == "note" and c:
            t, _, text = arg.partition("/")
            db.add_note(self.con, c.name, float(t), c.abs_at(float(t)).isoformat(), text)
            c.notes = db.notes(self.con, c.name)
        elif cmd == "newnote" and c:          # same path as the M key / right-click menu
            self.new_note(c, float(arg))
        elif cmd == "notetext" and self.note_edit:
            self.note_edit["text"] = arg
        elif cmd == "row" and c:
            self.open_row(c, int(arg))
        elif cmd == "rowsel" and c:
            self.sel_row = (c.name, int(arg))
        elif cmd == "viewlang":
            self.view_lang = arg or None
        elif cmd == "importdlg":
            d = self.cfg.devices[0]
            cands = [x for x in ingest.scan(d, Path(arg), "script", db.connect(self.cfg.db_path)) if x.status == "new"]
            self.pending_import = {"device": d, "mount": Path(arg), "serial": "script", "cands": cands,
                                   "checked": [True] * len(cands), "open": True}
        elif cmd == "fakejob":  # job bar + progress window in a given state (UI tests only)
            i, n, stage, d, t = arg.split("/")
            self.proc = subprocess.Popen(["sleep", "30"])
            self.job_label, self.job_t0 = "Transcribing new conversations", time.monotonic() - 42
            self.job_files = [x.name for x in self.convs][: int(n)]
            self.proc_log = [f"[{i}/{n}] {self.job_files[int(i) - 1]}"]
            self.job_file, self.job_step = (int(i), int(n), self.job_files[int(i) - 1]), (stage, int(d), int(t))
        elif cmd == "progress":
            self.show_progress = True
        elif cmd == "theme":
            self.prefs["theme"] = arg
            th.apply(arg, self.prefs["text_size"])
        elif cmd == "size":
            self.prefs["text_size"] = float(arg)
            th.apply(self.prefs["theme"], float(arg))
        elif cmd == "tab":
            self.side_tab = arg
        elif cmd == "person":
            self.person_open = arg
        elif cmd == "speaker" and c:
            i = int(arg)
            self.rename_speaker(c, c.segments[i]["speaker"], i)
        elif cmd == "settings":
            self.show_settings = True
        elif cmd == "settingsq":
            self.settings_query = arg
        elif cmd == "shot":
            self.shot_path, self.quit = arg, True
        elif cmd == "quit":
            self.quit = True


def _load_fonts():
    path = next((p for p in FONT_CANDIDATES if Path(p).exists()), None)
    if path:
        hello_imgui.load_font(path, 15.0)
        thai = next((p for p in THAI_FONTS if Path(p).exists()), None)
        if thai:
            hello_imgui.load_font(thai, 15.0, hello_imgui.FontLoadingParams(merge_to_last_font=True))
    else:
        hello_imgui.imgui_default_settings.load_default_font_with_font_awesome_icons()


def run(cfg, script=None):
    app = App(cfg, script)
    params = hello_imgui.RunnerParams()
    params.app_window_params.window_title = "jev-recorder"
    params.app_window_params.window_geometry.size = (1500, 950)
    params.imgui_window_params.default_imgui_window_type = hello_imgui.DefaultImGuiWindowType.no_default_window
    params.callbacks.show_gui = app.gui
    params.callbacks.load_additional_fonts = _load_fonts
    params.callbacks.setup_imgui_style = app.apply_theme
    params.fps_idling.enable_idling = True
    params.ini_disable = True
    # no MSAA: ImGui anti-aliases its own shapes, and Xvfb/Mesa (tests) has no multisample configs
    gl = hello_imgui.OpenGlOptions()
    gl.anti_aliasing_samples = 0
    params.renderer_backend_options.open_gl_options = gl
    hello_imgui.run(params)
    app.player.stop()
    if app.proc and app.proc.poll() is None and app.proc.args[:1] == ["sleep"]:
        app.proc.terminate()
    if app.shot_path:
        from PIL import Image
        Image.fromarray(hello_imgui.final_app_window_screenshot()).save(app.shot_path)
