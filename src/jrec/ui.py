"""jev-recorder desktop UI (Dear ImGui via imgui-bundle).

  jrec ui [--ui-script "open:0,wait:2.5,shot:/tmp/a.png"]     (wait is in seconds)

Left: search + conversations. Main: waveform timeline on an absolute clock (padding shaded,
speaker lanes, playhead; click = seek/play, wheel = zoom, drag = pan), synced transcript,
summary. A recorder plug-in opens the Import dialog; nothing is copied until "Import".
Heavy work runs in a separate `jrec process` process (GPU never in the UI process).
"""
import json
import os
import shlex
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from imgui_bundle import hello_imgui, imgui

from . import config, db, ingest, search
from . import theme as th
from .theme import C, U

PEAK_HZ = 50                      # waveform bins per second
SPEAKER_COLORS = [(0.35, 0.62, 0.95), (0.95, 0.55, 0.30), (0.45, 0.80, 0.45), (0.85, 0.45, 0.80),
                  (0.95, 0.85, 0.35), (0.40, 0.80, 0.85), (0.75, 0.75, 0.75), (0.95, 0.45, 0.50)]
FONT_CANDIDATES = ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                   "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc",
                   "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"]
THAI_FONTS = ["/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf",
              "/usr/share/fonts/opentype/noto/NotoSansThai-Regular.otf"]


def col(rgb, a=1.0):
    return imgui.IM_COL32(int(rgb[0] * 255), int(rgb[1] * 255), int(rgb[2] * 255), int(a * 255))


def fmt_clock(dt):
    return dt.strftime("%H:%M:%S")


# ---------------------------------------------------------------- data
class Conversation:
    def __init__(self, folder, row):
        self.folder = Path(folder)
        self.name = self.folder.name
        self.status = row["status"]
        self.speech_start = datetime.fromisoformat(row["speech_start"])
        self.manifest = json.loads((self.folder / "manifest.json").read_text())
        w = self.manifest["window"]
        self.start = datetime.fromisoformat(w["start"])
        self.end = datetime.fromisoformat(w["end"])
        self.duration = (self.end - self.start).total_seconds()
        self.sp0 = (datetime.fromisoformat(w["speech_start"]) - self.start).total_seconds()
        self.sp1 = (datetime.fromisoformat(w["speech_end"]) - self.start).total_seconds()
        self.segments, self.summary, self.title = [], None, None
        self.reload_text()
        self.peaks = None                 # (mins, maxs) at PEAK_HZ, filled by a thread
        self.gain = 1.0
        self.verified = None              # None | [] | [problems]

    def reload_text(self):
        t = self.folder / "transcript.json"
        if t.exists():
            self.segments = json.loads(t.read_text())["segments"]
            for s in self.segments:
                s["_t0"] = (datetime.fromisoformat(s["abs_start"]) - self.start).total_seconds()
                s["_t1"] = (datetime.fromisoformat(s["abs_end"]) - self.start).total_seconds()
        sm = self.folder / "summary.json"
        if sm.exists():
            self.summary = json.loads(sm.read_text())
            self.title = self.summary.get("title")
        if not self.title and self.segments:
            self.title = self.segments[0]["text"][:60]

    def load_peaks(self):
        cache = self.folder / "peaks.npy"
        if cache.exists():
            self.peaks = np.load(cache)
            self._set_gain()
            return
        chunks = []
        for p in self.manifest["parts"]:
            raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(self.folder / p["file"]), "-ac", "1",
                                  "-ar", "8000", "-f", "s16le", "-"], capture_output=True, check=True).stdout
            chunks.append(np.frombuffer(raw, np.int16))
        a = np.concatenate(chunks).astype(np.float32) / 32768.0
        n = 8000 // PEAK_HZ
        a = a[: len(a) // n * n].reshape(-1, n)
        peaks = np.stack([a.min(1), a.max(1)])
        np.save(cache, peaks)
        self.peaks = peaks
        self._set_gain()

    def _set_gain(self):
        top = float(np.percentile(np.abs(self.peaks), 99.5)) if self.peaks.size else 0.0
        self.gain = min(30.0, 0.9 / top) if top > 1e-4 else 1.0

    def abs_at(self, t):
        return self.start + timedelta(seconds=t)

    def speech_spans(self):
        """Transcript segments when available, else VAD regions (clip seconds), merged across < 1 s gaps."""
        raw = [(s["_t0"], s["_t1"]) for s in self.segments] or [tuple(r) for r in self.manifest["vad"]["regions_sec"]]
        out = []
        for a, b in sorted(raw):
            if out and a - out[-1][1] < 1.0:
                out[-1] = (out[-1][0], max(out[-1][1], b))
            else:
                out.append((a, b))
        return out

    def next_speech(self, t, direction=1):
        spans = self.speech_spans()
        if direction > 0:
            return next((a for a, _ in spans if a > t + 0.5), None)
        return next((a for a, _ in reversed(spans) if a < t - 1.0), None)


class Player:
    """ffplay in a child process; playhead = start offset + elapsed wall time."""
    def __init__(self):
        self.proc, self.t0, self.wall0, self.conv = None, 0.0, 0.0, None
        self.speed = 1.0

    def play(self, conv, t, speed=None):
        self.stop()
        self.speed = speed or self.speed
        listen = conv.folder / "listen.opus"
        src, off = (listen, t) if listen.exists() else self._raw_at(conv, t)
        af = ["-af", f"atempo={self.speed}"] if self.speed != 1.0 else []  # pitch-preserving speed
        self.proc = subprocess.Popen(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "-ss", f"{off:.2f}",
                                      *af, str(src)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, close_fds=True)
        self.t0, self.wall0, self.conv = t, time.monotonic(), conv

    @staticmethod
    def _raw_at(conv, t):
        acc = 0.0
        for p in conv.manifest["parts"]:
            d = p["t_end"] - p["t_start"]
            if t < acc + d:
                return conv.folder / p["file"], t - acc
            acc += d
        p = conv.manifest["parts"][-1]
        return conv.folder / p["file"], 0.0

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
        self.proc = None

    @property
    def playing(self):
        return self.proc is not None and self.proc.poll() is None

    def position(self):
        return self.t0 + (time.monotonic() - self.wall0) * self.speed if self.playing else None


# ---------------------------------------------------------------- app
class App:
    def __init__(self, cfg, script=None):
        self.cfg = cfg
        self.con = db.connect(cfg.db_path)
        search.ensure(self.con)
        self.convs, self.sel = [], None
        self.query, self.hits = "", None
        self.player = Player()
        self.player.speed = float(th.load_prefs()["speed"])
        self.view = (0.0, 1.0)            # visible [t0, t1] seconds of the selected conversation
        self.follow = True
        self.cursor = 0.0
        self.drag_from = None
        self.scroll_to_cursor = False
        # import dialog
        self.recorders_seen, self.pending_import = set(), None
        self.import_msg, self.importing = "", False
        # background processing
        self.proc, self.proc_log = None, []
        self.job_label, self.job_t0 = "", 0.0
        self.job_file, self.job_step = None, None   # (i, n, name), (stage, done, total)
        self.prefs = th.load_prefs()
        self.skip_silence = self.prefs["skip_silence"]
        self.follow = self.prefs["follow"]
        self.show_settings = False
        self.job_exit = None
        self.cfg_path = os.environ.get("JREC_CONFIG_PATH")
        self.script = [s.strip() for s in script.split(",")] if script else []
        self.script_wait = 0
        self.quit = False
        self.need_reload = False
        self.reload()
        threading.Thread(target=self._watch_recorders, daemon=True).start()

    # ---- data
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
            c.reload_text()
            out.append(c)
        self.convs = out

    def select(self, conv, t=None):
        if conv is not self.sel:
            self.player.stop()
            self.sel = conv
            self.view = (0.0, conv.duration)
            if conv.peaks is None:
                threading.Thread(target=conv.load_peaks, daemon=True).start()
        if t is not None:
            self.cursor = t
            self.scroll_to_cursor = True
            span = self.view[1] - self.view[0]
            if not (self.view[0] <= t <= self.view[1]):
                self.view = (max(0.0, t - span / 2), min(conv.duration, t + span / 2))

    # ---- recorder detection -> import dialog
    def _watch_recorders(self):
        from .watch import remount_readonly
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

    def _do_import(self, items, d, serial):
        self.importing = True
        con = db.connect(self.cfg.db_path)
        try:
            for i, c in enumerate(items, 1):
                self.import_msg = f"importing {i}/{len(items)}: {c.rel}"
                ingest.import_one(c, d, serial, self.cfg, con)
            self.import_msg = f"imported {len(items)} file(s). The recorder was not modified; safe to eject."
            self.need_reload = True
        except Exception as e:
            self.import_msg = f"import failed: {e}"
        self.importing = False

    def start_job(self, args, label):
        """Run a jrec subcommand in a child process (GPU work never runs in the UI process)."""
        if self.job_busy:
            return
        cmd = [sys.executable, "-m", "jrec.cli"] + (["--config", str(self.cfg_path)] if self.cfg_path else []) + args
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                     stdin=subprocess.DEVNULL, close_fds=True, cwd=str(Path.home()))
        self.job_label, self.job_t0 = label, time.monotonic()
        self.proc_log = [f"$ jrec {shlex.join(args)}"]
        self.job_file, self.job_step, self.job_exit = None, None, None
        threading.Thread(target=self._pump_log, daemon=True).start()

    def start_processing(self):
        self.start_job(["process"], "Transcribing all new conversations")

    @property
    def job_busy(self):
        return self.proc is not None and self.proc.poll() is None

    def _pump_log(self):
        for line in self.proc.stdout:
            if line.startswith("PROGRESS "):
                f = line.split()
                if f[1] == "file":
                    self.job_file, self.job_step = (int(f[2]), int(f[3]), " ".join(f[4:])), None
                elif f[1] == "step":
                    self.job_step = (f[2], int(f[3]), int(f[4]))
                continue
            low = line.lower()
            if "warn" not in low and "it/s]" not in low and "loading" not in low:
                self.proc_log.append(line.rstrip())
                self.proc_log = self.proc_log[-200:]
        self.job_exit = self.proc.wait()
        if self.job_exit:
            self.proc_log.append(f"failed (exit {self.job_exit}); see the lines above")
        self.need_reload = True  # the SQLite connection belongs to the UI thread: reload there

    # ---- prefs
    def set_pref(self, key, value):
        self.prefs[key] = value
        th.save_prefs(self.prefs)
        if key in ("theme", "text_size"):
            th.apply(self.prefs["theme"], self.prefs["text_size"])

    def apply_theme(self):
        th.apply(self.prefs["theme"], self.prefs["text_size"])

    # ---- frame
    def gui(self):
        if self.need_reload:
            self.need_reload = False
            self.reload()
        self._run_script()
        self.global_keys()
        vp = imgui.get_main_viewport()
        imgui.set_next_window_pos(vp.work_pos)
        imgui.set_next_window_size(vp.work_size)
        flags = (imgui.WindowFlags_.no_decoration | imgui.WindowFlags_.no_move | imgui.WindowFlags_.no_saved_settings
                 | imgui.WindowFlags_.no_bring_to_front_on_focus)
        imgui.begin("main", None, flags)
        side_w = 320 * self.prefs["text_size"]
        with th.card("side", imgui.ImVec2(side_w, 0), padding=(10, 10)):
            self.left_panel()
        imgui.same_line(0, 14)
        imgui.push_style_color(imgui.Col_.child_bg, C("bg", 0.0))
        imgui.push_style_var(imgui.StyleVar_.child_border_size, 0)
        imgui.begin_child("main_area", imgui.ImVec2(0, 0))
        imgui.pop_style_var()
        imgui.pop_style_color()
        self.job_bar()
        if self.sel:
            self.conversation_view(self.sel)
        else:
            imgui.dummy(imgui.ImVec2(0, 40))
            imgui.text_colored(C("text_dim"), "Pick a conversation on the left, or plug in the recorder.")
        imgui.end_child()
        self.settings_popup()
        self.import_dialog()
        imgui.end()
        if self.quit:
            hello_imgui.get_runner_params().app_shall_exit = True

    def global_keys(self):
        io = imgui.get_io()
        ctrl = io.key_ctrl or io.key_super
        K = imgui.Key
        if ctrl and imgui.is_key_pressed(K.comma, False):
            self.show_settings = True
        sizes = [0.9, 1.0, 1.1, 1.25, 1.5]
        cur = min(range(len(sizes)), key=lambda i: abs(sizes[i] - self.prefs["text_size"]))
        if ctrl and (imgui.is_key_pressed(K.equal, False) or imgui.is_key_pressed(K.keypad_add, False)):
            self.set_pref("text_size", sizes[min(len(sizes) - 1, cur + 1)])
        elif ctrl and (imgui.is_key_pressed(K.minus, False) or imgui.is_key_pressed(K.keypad_subtract, False)):
            self.set_pref("text_size", sizes[max(0, cur - 1)])
        elif ctrl and imgui.is_key_pressed(K._0, False):
            self.set_pref("text_size", 1.0)

    def left_panel(self):
        imgui.set_next_item_width(-1)
        changed, self.query = imgui.input_text_with_hint("##q", "Search transcripts", self.query)
        if changed:
            self.hits = search.search(self.con, self.query) if self.query.strip() else None
        n_new = sum(c.status == "cut" for c in self.convs)
        if th.button(f"Transcribe all new ({n_new})" if n_new else "Transcribe all new", disabled=self.job_busy or not n_new,
                     why="A job is already running" if self.job_busy else "Everything is transcribed"):
            self.start_processing()
        imgui.same_line()
        if th.button("Settings", help_="Appearance, text size, playback (Ctrl+,)"):
            self.show_settings = True
        imgui.dummy(imgui.ImVec2(0, 2))
        imgui.begin_child("list", imgui.ImVec2(0, 0), 0)
        if self.hits is not None:
            th.section(f"{len(self.hits)} results")
            for i, h in enumerate(self.hits):
                if self.list_row(f"hit{i}", h["text"], f"{h['abs_start'][:10]}  {h['abs_start'][11:19]}"
                                 + (f"  ·  {h['speaker']}" if h.get("speaker") else ""), False):
                    conv = next((c for c in self.convs if c.name == h["folder"]), None)
                    if conv:
                        self.select(conv, (datetime.fromisoformat(h["abs_start"]) - conv.start).total_seconds())
            if not self.hits:
                imgui.text_colored(C("text_dim"), "No transcript contains that.")
            imgui.end_child()
            return
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
            mins = (c.sp1 - c.sp0) / 60
            status = {"cut": "not transcribed", "transcribed": "transcribed", "summarized": "summarized"}.get(c.status, c.status)
            title = c.title or f"Conversation at {c.speech_start:%H:%M}"
            if self.list_row(c.name, title, f"{c.speech_start:%H:%M}  ·  {mins:.0f} min  ·  {status}", c is self.sel):
                self.select(c)
        imgui.end_child()

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

    def job_bar(self):
        if not self.proc_log:
            return
        busy = self.job_busy
        with th.card("job", imgui.ImVec2(0, 0), flags=imgui.ChildFlags_.auto_resize_y):
            last = next((l for l in reversed(self.proc_log) if l.strip()), "")
            if busy:
                dots = "." * (1 + int(time.monotonic() * 2) % 3)
                imgui.text(f"{self.job_label}{dots}")
                imgui.same_line()
                th.small(f"{time.monotonic() - self.job_t0:.0f} s")
            elif self.job_exit:
                imgui.text_colored(C("danger"), f"{self.job_label}: failed")
            else:
                imgui.text_colored(C("ok"), f"{self.job_label}: done")
            if not busy:
                imgui.same_line(imgui.get_content_region_avail().x + imgui.get_cursor_pos_x() - 70)
                if th.button("Dismiss"):
                    self.proc_log = []
            if busy and self.job_file:
                i, n, name = self.job_file
                stage, d, t = self.job_step or ("", 0, 1)
                weight = {"asr": (0.0, 0.8), "align": (0.8, 0.1), "speakers": (0.9, 0.1)}.get(stage, (0.0, 0.0))
                frac_file = weight[0] + weight[1] * (d / max(1, t))
                if name == "loading-models":
                    imgui.progress_bar(-1.0 * time.monotonic(), imgui.ImVec2(-1, 0), "Loading models (first run takes 1-2 min)")
                else:
                    overall = ((i - 1) + frac_file) / max(1, n)
                    imgui.progress_bar(overall, imgui.ImVec2(-1, 0), f"Conversation {i} of {n}  ·  {overall*100:.0f}%")
                    label = {"asr": f"Speech to text  ·  chunk {d} of {t}", "align": "Word timings",
                             "speakers": "Who spoke when"}.get(stage, "Preparing")
                    imgui.progress_bar(frac_file, imgui.ImVec2(-1, 0), label)
            th.small(last[-160:], "danger" if self.job_exit else "text_dim")
        imgui.dummy(imgui.ImVec2(0, 4))

    def conversation_view(self, c):
        # header
        imgui.push_font(None, imgui.get_style().font_size_base * 1.3)
        imgui.text(c.title or f"Conversation at {c.speech_start:%H:%M}")
        imgui.pop_font()
        mins = (c.sp1 - c.sp0) / 60
        parts = len(c.manifest["parts"])
        th.small(f"{c.speech_start:%a %-d %b %Y}  ·  talk {fmt_clock(c.abs_at(c.sp0))}–{fmt_clock(c.abs_at(c.sp1))} "
                 f"({mins:.0f} min)  ·  kept {fmt_clock(c.start)}–{fmt_clock(c.end)} with 10 min either side"
                 + (f"  ·  {parts} files" if parts > 1 else ""))
        from .cli import human_flag
        flags = sorted({human_flag(f) for p in c.manifest["parts"] for f in p["source_start"].get("flags", [])})
        confs = {p["source_start"].get("confidence") for p in c.manifest["parts"]} - {None}
        if flags or (confs and "high" not in confs):
            th.small(f"Clock time is {', '.join(sorted(confs))} confidence" + (f": {', '.join(flags)}" if flags else ""), "warn")
        if c.manifest["seams"]:
            th.small(f"{len(c.manifest['seams'])} file boundary(ies) from the recorder's auto-split: a moment of audio may be missing there", "warn")
        imgui.dummy(imgui.ImVec2(0, 2))
        # actions: one primary
        if c.status == "cut":
            if th.primary_button("Transcribe", disabled=self.job_busy, why="Another job is running; it starts when that one ends"):
                self.start_job(["transcribe", str(c.folder)], f"Transcribing {c.speech_start:%H:%M}")
            imgui.same_line()
            imgui.align_text_to_frame_padding()
            th.small("Speech to text, word timings and speakers, on the GPU (about 11 GB, ~1 min per 10 min of talk)")
        elif c.status == "transcribed":
            prof = self.cfg.llm_profile()
            if th.button("Summarize", disabled=self.job_busy, why="Another job is running"):
                self.start_job(["summarize", str(c.folder)], f"Summarizing {c.speech_start:%H:%M}")
            imgui.same_line()
            imgui.align_text_to_frame_padding()
            th.small(f"Uses the LLM at {prof['base_url']}")
        if c.status != "cut":
            imgui.same_line()
        if th.button("Verify clips", help_="Re-check every clip byte for byte against the archived original"):
            from .cutter import verify_folder
            c.verified = verify_folder(c.folder, self.cfg.archive)
        if c.verified is not None:
            imgui.same_line()
            imgui.align_text_to_frame_padding()
            if c.verified:
                th.small("Verification failed: " + "; ".join(c.verified), "danger")
            else:
                th.small("Clips match the archived originals", "ok")
        imgui.dummy(imgui.ImVec2(0, 2))
        # player card: controls + timeline
        with th.card("player", imgui.ImVec2(0, 0), flags=imgui.ChildFlags_.auto_resize_y):
            self.player_controls(c)
            self.timeline(c)
        imgui.dummy(imgui.ImVec2(0, 2))
        # transcript + summary
        avail = imgui.get_content_region_avail()
        sum_w = max(300.0, avail.x * 0.30) if c.summary else 0
        imgui.begin_group()
        th.section("Transcript")
        with th.card("transcript", imgui.ImVec2(avail.x - sum_w - (14 if sum_w else 0), 0), padding=(10, 8)):
            self.transcript(c)
        imgui.end_group()
        if c.summary:
            imgui.same_line(0, 14)
            imgui.begin_group()
            th.section("Summary")
            with th.card("summary", imgui.ImVec2(0, 0)):
                self.summary_panel(c)
            imgui.end_group()

    @staticmethod
    def _next_group(label, labels, gap=18):
        """Continue on this line if the next labelled segmented group fits, else start a new line."""
        need = imgui.calc_text_size(label).x + 6 + th.seg_width(labels)
        imgui.same_line(0, gap)
        if imgui.get_content_region_avail().x < need:
            imgui.new_line()

    def player_controls(self, c):
        playing = self.player.playing and self.player.conv is c
        imgui.push_style_var(imgui.StyleVar_.button_text_align, imgui.ImVec2(0.5, 0.5))
        if imgui.button("Pause" if playing else "Play", imgui.ImVec2(70 * self.prefs["text_size"], 0)):
            self.toggle_play(c)
        imgui.pop_style_var()
        th.tip("Space")
        imgui.same_line()
        if imgui.button("◀"):
            self.jump_speech(c, -1)
        th.tip("Previous speech (P)")
        imgui.same_line(0, 4)
        if imgui.button("▶"):
            self.jump_speech(c, 1)
        th.tip("Next speech (N)  ·  ← → move 5 s")
        imgui.same_line()
        pos = self.player.position() if playing else self.cursor
        imgui.align_text_to_frame_padding()
        imgui.text(fmt_clock(c.abs_at(pos or 0.0)))
        self._next_group("Speed", ["1×", "1.25×", "1.5×", "2×", "3×"])
        ch, sp = th.labeled_seg("Speed", "speed", self.player.speed, [1.0, 1.25, 1.5, 2.0, 3.0],
                                ["1×", "1.25×", "1.5×", "2×", "3×"])
        if ch:
            self.player.speed = sp
            self.set_pref("speed", sp)
            if playing:
                self.player.play(c, self.player.position() or self.cursor, sp)
        self._next_group("Skip silence", ["Off", "On"])
        ch, v = th.labeled_seg("Skip silence", "skip", self.skip_silence, [False, True], ["Off", "On"],
                               ["Play every second", "Jump over quiet gaps longer than 3 s while playing"])
        if ch:
            self.skip_silence = v
            self.set_pref("skip_silence", v)
        self._next_group("Follow", ["Off", "On"])
        ch, v = th.labeled_seg("Follow", "follow", self.follow, [False, True], ["Off", "On"],
                               ["Keep the view still", "Scroll timeline and transcript with playback"])
        if ch:
            self.follow = v
            self.set_pref("follow", v)
        imgui.dummy(imgui.ImVec2(0, 2))

    def settings_popup(self):
        if self.show_settings and not imgui.is_popup_open("Settings"):
            imgui.open_popup("Settings")
        vp = imgui.get_main_viewport()
        imgui.set_next_window_pos(imgui.ImVec2(vp.work_pos.x + vp.work_size.x / 2, vp.work_pos.y + vp.work_size.y / 3),
                                  imgui.Cond_.appearing, imgui.ImVec2(0.5, 0.5))
        imgui.set_next_window_size(imgui.ImVec2(620 * self.prefs["text_size"], 0))
        imgui.push_style_color(imgui.Col_.popup_bg, C("bg"))
        opened, keep = imgui.begin_popup_modal("Settings", True, imgui.WindowFlags_.no_saved_settings | imgui.WindowFlags_.no_title_bar)
        imgui.pop_style_color()
        if not opened:
            self.show_settings = False
            return
        if imgui.is_key_pressed(imgui.Key.escape, False):
            imgui.close_current_popup()
            self.show_settings = False
        th.section("Appearance")
        with th.card("set_look", imgui.ImVec2(0, 0), flags=imgui.ChildFlags_.auto_resize_y):
            ch, v = self.setting_row("Theme", "Dark or light; applies at once", "theme", self.prefs["theme"],
                                     ["Dark", "Light"])
            if ch:
                self.set_pref("theme", v)
            imgui.separator()
            ch, v = self.setting_row("Text size", "Everything in the window; Ctrl+ Ctrl– Ctrl+0 too", "size",
                                     self.prefs["text_size"], [1.0, 1.1, 1.25, 1.5], ["100%", "110%", "125%", "150%"])
            if ch:
                self.set_pref("text_size", v)
        th.section("Playback")
        with th.card("set_play", imgui.ImVec2(0, 0), flags=imgui.ChildFlags_.auto_resize_y):
            ch, v = self.setting_row("Speed", "Pitch stays natural at every speed", "dspeed", self.player.speed,
                                     [1.0, 1.25, 1.5, 2.0, 3.0], ["1×", "1.25×", "1.5×", "2×", "3×"])
            if ch:
                self.player.speed = v
                self.set_pref("speed", v)
            imgui.separator()
            ch, v = self.setting_row("Skip silence", "Jump over quiet gaps longer than 3 s while playing", "dskip",
                                     self.skip_silence, [False, True], ["Off", "On"])
            if ch:
                self.skip_silence = v
                self.set_pref("skip_silence", v)
        th.section("Library")
        with th.card("set_lib", imgui.ImVec2(0, 0), flags=imgui.ChildFlags_.auto_resize_y):
            imgui.text("Folder")
            th.small(str(self.cfg.library))
            imgui.separator()
            imgui.text("Summaries")
            prof = self.cfg.llm_profile()
            th.small(f"{prof['base_url']}  ·  model {prof['model']}  ·  edit [llm.profiles] in the config file")
        th.small("Changes are saved as you make them.")
        imgui.dummy(imgui.ImVec2(0, 2))
        if th.button("Done"):
            imgui.close_current_popup()
            self.show_settings = False
        imgui.end_popup()

    def setting_row(self, title, desc, id_, value, options, labels=None):
        """Magpie row: title + one grey line on the left, segmented control on the right."""
        labels = labels or [str(o) for o in options]
        y0 = imgui.get_cursor_pos_y()
        imgui.text(title)
        th.small(desc)
        y1 = imgui.get_cursor_pos_y()
        w = th.seg_width(labels)
        imgui.set_cursor_pos(imgui.ImVec2(imgui.get_window_width() - w - 14,
                                          y0 + (y1 - y0 - imgui.get_frame_height()) / 2 - 2))
        ch, v = th.seg(id_, value, options, labels)
        imgui.set_cursor_pos(imgui.ImVec2(imgui.get_style().window_padding.x, y1))
        imgui.dummy(imgui.ImVec2(0, 0))  # an item, so ImGui accepts the cursor move
        return ch, v

    def toggle_play(self, c):
        if self.player.playing and self.player.conv is c:
            self.cursor = self.player.position() or self.cursor
            self.player.stop()
        else:
            self.player.play(c, self.cursor)

    def jump_speech(self, c, direction):
        here = self.player.position() if self.player.conv is c and self.player.playing else self.cursor
        t = c.next_speech(here, direction)
        if t is None:
            return
        self.select(c, max(0.0, t - 0.3))
        if self.player.playing:
            self.player.play(c, self.cursor)

    def keys(self, c):
        io = imgui.get_io()
        if io.want_text_input:
            return
        K = imgui.Key
        if imgui.is_key_pressed(K.space, False):
            self.toggle_play(c)
        elif imgui.is_key_pressed(K.n, False):
            self.jump_speech(c, 1)
        elif imgui.is_key_pressed(K.p, False):
            self.jump_speech(c, -1)
        elif imgui.is_key_pressed(K.right_arrow) or imgui.is_key_pressed(K.left_arrow):
            d = 5.0 if imgui.is_key_pressed(K.right_arrow) else -5.0
            here = self.player.position() if self.player.playing and self.player.conv is c else self.cursor
            self.cursor = max(0.0, min(c.duration, here + d))
            if self.player.playing:
                self.player.play(c, self.cursor)

    def timeline(self, c):
        self.keys(c)
        w = imgui.get_content_region_avail().x
        h_wave, h_lanes, h_axis = 104, 30, 20 * self.prefs["text_size"]
        h = h_wave + h_lanes + h_axis
        p0 = imgui.get_cursor_screen_pos()
        imgui.invisible_button("timeline", imgui.ImVec2(w, h))
        hovered = imgui.is_item_hovered()
        dl = imgui.get_window_draw_list()
        v0, v1 = self.view
        span = max(1e-3, v1 - v0)
        x_of = lambda t: p0.x + (t - v0) / span * w
        t_of = lambda x: v0 + (x - p0.x) / w * span
        dl.add_rect_filled(p0, imgui.ImVec2(p0.x + w, p0.y + h_wave), U("track"), 6.0)
        # padding (outside the speech span) shaded, speech span marked
        for a, b in ((0.0, c.sp0), (c.sp1, c.duration)):
            if b > v0 and a < v1:
                dl.add_rect_filled(imgui.ImVec2(max(p0.x, x_of(a)), p0.y), imgui.ImVec2(min(p0.x + w, x_of(b)), p0.y + h_wave),
                                   U("pad_shade", 0.85))
        # waveform
        if c.peaks is not None:
            mins, maxs = c.peaks
            mid, amp = p0.y + h_wave / 2, (h_wave / 2 - 4) * c.gain
            wave = U("wave")
            for px in range(int(w)):
                a, b = int((v0 + px / w * span) * PEAK_HZ), int((v0 + (px + 1) / w * span) * PEAK_HZ) + 1
                if a >= len(mins):
                    break
                lo, hi = max(-1.0, float(mins[a:b].min()) * c.gain) / c.gain, min(1.0, float(maxs[a:b].max()) * c.gain) / c.gain
                dl.add_line(imgui.ImVec2(p0.x + px, mid - hi * amp), imgui.ImVec2(p0.x + px, mid - lo * amp + 1),
                            wave)
        else:
            dl.add_text(imgui.ImVec2(p0.x + 10, p0.y + 8), U("text_dim"), "Drawing the waveform…")
        # speaker lanes
        ly = p0.y + h_wave + 4
        spk = sorted({s.get("speaker") for s in c.segments if s.get("speaker")})
        lane_h = (h_lanes - 6) / max(1, len(spk))
        for s in c.segments:
            if s["_t1"] < v0 or s["_t0"] > v1:
                continue
            i = spk.index(s["speaker"]) if s.get("speaker") in spk else 0
            rgb = SPEAKER_COLORS[i % len(SPEAKER_COLORS)]
            y = ly + i * lane_h
            dl.add_rect_filled(imgui.ImVec2(max(p0.x, x_of(s["_t0"])), y),
                               imgui.ImVec2(min(p0.x + w, max(x_of(s["_t1"]), x_of(s["_t0"]) + 1)), y + lane_h - 1), col(rgb, 0.9))
        # clock axis: absolute times, tick step chosen for ~8 labels
        ay = p0.y + h_wave + h_lanes
        step = next(s for s in (1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200) if span / s <= 9)
        first = c.start + timedelta(seconds=v0)
        k = (first.timestamp() // step + 1) * step
        while (tt := k - c.start.timestamp()) <= v1:
            x = x_of(tt)
            dl.add_line(imgui.ImVec2(x, ay), imgui.ImVec2(x, ay + 5), U("text_dim"))
            label = datetime.fromtimestamp(k, c.start.tzinfo).strftime("%H:%M:%S" if step < 60 else "%H:%M")
            if x + 3 + imgui.calc_text_size(label).x <= p0.x + w:
                dl.add_text(imgui.ImVec2(x + 3, ay + 4), U("text_dim"), label)
            k += step
        # playhead + cursor
        pos = self.player.position() if self.player.conv is c else None
        if pos is not None and pos > c.duration:
            self.player.stop(); pos = None
        if pos is not None and self.skip_silence:
            spans = c.speech_spans()
            inside = any(a - 0.5 <= pos <= b + 1.5 for a, b in spans)
            nxt = c.next_speech(pos, 1)
            if not inside and nxt is not None and nxt - pos > 3.0:
                self.player.play(c, nxt - 0.3)   # jump over the silent stretch
                pos = nxt - 0.3
        if pos is not None:
            self.cursor = pos
            if self.follow and not (v0 <= pos <= v1):
                self.view = (pos, min(c.duration, pos + span)) if pos + span <= c.duration else (c.duration - span, c.duration)
        cx = x_of(self.cursor)
        if p0.x <= cx <= p0.x + w:
            dl.add_line(imgui.ImVec2(cx, p0.y), imgui.ImVec2(cx, ay), U("playhead"), 2)
        # interaction: click = seek (+ play if playing), wheel = zoom at mouse, drag = pan
        io = imgui.get_io()
        if hovered:
            mx = io.mouse_pos.x
            t_m = t_of(mx)
            imgui.set_tooltip(fmt_clock(c.abs_at(t_m)))
            if io.mouse_wheel:
                f = 0.8 if io.mouse_wheel > 0 else 1.25
                ns = min(c.duration, max(5.0, span * f))
                a = t_m - (mx - p0.x) / w * ns
                a = max(0.0, min(c.duration - ns, a))
                self.view = (a, a + ns)
            if imgui.is_mouse_clicked(0):
                self.drag_from = (mx, self.view)
        if self.drag_from and imgui.is_mouse_down(0):
            x_start, (a, b) = self.drag_from
            dt = (io.mouse_pos.x - x_start) / w * (b - a)
            if abs(io.mouse_pos.x - x_start) > 3:
                ns = b - a
                na = max(0.0, min(c.duration - ns, a - dt))
                self.view = (na, na + ns)
        if self.drag_from and imgui.is_mouse_released(0):
            x_start, _ = self.drag_from
            if abs(io.mouse_pos.x - x_start) <= 3 and hovered:
                self.cursor = max(0.0, min(c.duration, t_of(io.mouse_pos.x)))
                if self.player.playing:
                    self.player.play(c, self.cursor)
            self.drag_from = None
        imgui.spacing()

    def transcript(self, c):
        if not c.segments:
            imgui.text_colored(C("text_dim"), "Not transcribed yet. Press Transcribe above.")
            return
        spk = sorted({s.get("speaker") for s in c.segments if s.get("speaker")})
        cur = self.player.position() if self.player.conv is c else None
        flags = imgui.TableFlags_.row_bg | imgui.TableFlags_.sizing_stretch_prop
        ts = self.prefs["text_size"]
        if imgui.begin_table("tr", 3, flags):
            imgui.table_setup_column("time", imgui.TableColumnFlags_.width_fixed, 66 * ts)
            imgui.table_setup_column("who", imgui.TableColumnFlags_.width_fixed, 30 * ts)
            imgui.table_setup_column("text", imgui.TableColumnFlags_.width_stretch)
            for i, s in enumerate(c.segments):
                imgui.table_next_row()
                active = cur is not None and s["_t0"] <= cur < s["_t1"]
                if active:
                    imgui.table_set_bg_color(imgui.TableBgTarget_.row_bg1, U("playhead", 0.16))
                imgui.table_next_column()
                imgui.push_style_color(imgui.Col_.text, C("text_dim"))
                clicked = imgui.selectable(f"{s['abs_start'][11:19]}##s{i}", False)[0]
                imgui.pop_style_color()
                th.tip("Play from here")
                if clicked:
                    self.cursor = s["_t0"]
                    self.select(c, s["_t0"])
                    self.player.play(c, s["_t0"])
                imgui.table_next_column()
                if s.get("speaker"):
                    rgb = SPEAKER_COLORS[spk.index(s["speaker"]) % len(SPEAKER_COLORS)]
                    imgui.text_colored(imgui.ImVec4(*rgb, 1), s["speaker"])
                imgui.table_next_column()
                imgui.text_wrapped(s["text"])
                if (active and self.follow) or (self.scroll_to_cursor and s["_t0"] <= self.cursor < s["_t1"] + 2):
                    imgui.set_scroll_here_y(0.4)
                    if self.scroll_to_cursor and not active:
                        imgui.table_set_bg_color(imgui.TableBgTarget_.row_bg1, U("accent", 0.16))
                        self.scroll_to_cursor = False
            imgui.end_table()

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
                            self.select(c, seg["_t0"]); self.player.play(c, seg["_t0"])
                    th.tip("Play the moment this comes from")
        imgui.dummy(imgui.ImVec2(0, 6))
        th.small(f"Written by {sm.get('_meta', {}).get('model', 'the LLM')}; check it against the audio.")
        imgui.pop_text_wrap_pos()

    def import_dialog(self):
        pi = self.pending_import
        if pi and pi["open"] and not imgui.is_popup_open("Recorder connected"):
            imgui.open_popup("Recorder connected")
        vp = imgui.get_main_viewport()
        imgui.set_next_window_size(imgui.ImVec2(min(1000, vp.work_size.x - 80), 0), imgui.Cond_.appearing)
        imgui.set_next_window_pos(imgui.ImVec2(vp.work_pos.x + vp.work_size.x / 2, vp.work_pos.y + vp.work_size.y / 3),
                                  imgui.Cond_.appearing, imgui.ImVec2(0.5, 0.5))
        imgui.push_style_color(imgui.Col_.popup_bg, C("card"))  # opaque: no text bleeding through
        opened, _ = imgui.begin_popup_modal("Recorder connected", None, imgui.WindowFlags_.no_saved_settings)
        imgui.pop_style_color()
        if not opened:
            return
        if pi:
            imgui.push_font(None, imgui.get_style().font_size_base * 1.2)
            imgui.text(f"{len(pi['cands'])} new recording{'s' if len(pi['cands']) != 1 else ''} on the {pi['device'].name}")
            imgui.pop_font()
            th.small(f"{pi['mount']}  ·  mounted read-only. Nothing is copied until you press Import.")
            imgui.dummy(imgui.ImVec2(0, 2))
            # columns stretch to fill the dialog width exactly
            tflags = (imgui.TableFlags_.sizing_stretch_prop | imgui.TableFlags_.borders_inner_h | imgui.TableFlags_.row_bg
                      | imgui.TableFlags_.scroll_y)
            rows_h = min(420, 44 * (len(pi["cands"]) + 1) + 6)
            if imgui.begin_table("cands", 6, tflags, imgui.ImVec2(-1, rows_h)):
                for name, weight in (("", 0.4), ("file", 3.0), ("size", 1.0), ("length", 1.0), ("start", 2.4), ("flags", 1.6)):
                    imgui.table_setup_column(name, imgui.TableColumnFlags_.width_stretch, weight)
                imgui.table_setup_scroll_freeze(0, 1)
                imgui.table_headers_row()
                from .cli import _fmt_dur, _fmt_size, human_flag
                for i, c in enumerate(pi["cands"]):
                    imgui.table_next_row()
                    imgui.table_next_column()
                    _, pi["checked"][i] = imgui.checkbox(f"##c{i}", pi["checked"][i])
                    st = c.start
                    for v in (c.rel.split("/")[-1], _fmt_size(c.size), _fmt_dur(c.duration),
                              f"{st.start:%Y-%m-%d %H:%M:%S} ({st.confidence})" if st else "?",
                              ", ".join(human_flag(f) for f in st.flags) if st and st.flags else ""):
                        imgui.table_next_column(); imgui.text_wrapped(v)  # wrap: never clip in narrow columns
                imgui.end_table()
            n = sum(pi["checked"])
            size = sum(c.size for c, k in zip(pi["cands"], pi["checked"]) if k)
            from .cli import _fmt_size
            imgui.dummy(imgui.ImVec2(0, 4))
            if not pi.get("done"):
                if th.primary_button(f"Import {n} recording{'s' if n != 1 else ''} ({_fmt_size(size)})",
                                     disabled=self.importing or n == 0, why="Tick at least one recording"):
                    items = [c for c, k in zip(pi["cands"], pi["checked"]) if k]
                    threading.Thread(target=self._do_import, args=(items, pi["device"], pi["serial"]), daemon=True).start()
                    pi["done"] = True
                imgui.same_line()
                if th.button("Skip"):
                    self.pending_import = None
                    imgui.close_current_popup()
            else:
                if th.primary_button("Transcribe now", disabled=self.importing, why="Still copying"):
                    self.start_processing()
                    self.pending_import = None
                    imgui.close_current_popup()
                imgui.same_line()
                if th.button("Close"):
                    self.pending_import = None
                    imgui.close_current_popup()
            if self.import_msg:
                th.small(self.import_msg, "danger" if "failed" in self.import_msg else "text_dim")
        imgui.end_popup()

    # ---- scripted runs for headless tests (never XTest)
    def _run_script(self):
        if not self.script:
            return
        if time.monotonic() < self.script_wait:
            return
        step = self.script.pop(0)
        cmd, _, arg = step.partition(":")
        if cmd == "wait":
            self.script_wait = time.monotonic() + float(arg or 1)
        elif cmd == "open" and self.convs:
            self.select(self.convs[int(arg or 0)])
        elif cmd == "seek" and self.sel:
            self.select(self.sel, float(arg))
        elif cmd == "search":
            self.query = arg
            self.hits = search.search(self.con, arg)
        elif cmd == "zoom" and self.sel:
            a, b = (float(x) for x in arg.split("-"))
            self.view = (a, b)
        elif cmd == "importdlg":
            d = self.cfg.devices[0]
            cands = [c for c in ingest.scan(d, Path(arg), "script", db.connect(self.cfg.db_path)) if c.status == "new"]
            self.pending_import = {"device": d, "mount": Path(arg), "serial": "script", "cands": cands,
                                   "checked": [True] * len(cands), "open": True}
        elif cmd == "fakejob":  # render the job bar with a given progress state (UI tests only)
            i, n, stage, d, t = arg.split("/")
            self.proc = subprocess.Popen(["sleep", "30"])
            self.job_label, self.job_t0 = "Transcribing all new conversations", time.monotonic() - 42
            self.proc_log = ["[2/4] 2025-10-02_141213_19966260"]
            self.job_file, self.job_step = (int(i), int(n), "2025-10-02_141213_19966260"), (stage, int(d), int(t))
        elif cmd == "theme":
            self.prefs["theme"] = arg
            th.apply(arg, self.prefs["text_size"])
        elif cmd == "size":
            self.prefs["text_size"] = float(arg)
            th.apply(self.prefs["theme"], float(arg))
        elif cmd == "settings":
            self.show_settings = True
        elif cmd == "shot":
            self.shot_path = arg
            self.quit = True
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
    app.shot_path = None
    params = hello_imgui.RunnerParams()
    params.app_window_params.window_title = "jev-recorder"
    params.app_window_params.window_geometry.size = (1500, 950)
    params.imgui_window_params.background_color = th.C("bg")
    params.imgui_window_params.default_imgui_window_type = hello_imgui.DefaultImGuiWindowType.no_default_window
    params.callbacks.show_gui = app.gui
    params.callbacks.setup_imgui_style = app.apply_theme
    params.callbacks.load_additional_fonts = _load_fonts
    params.fps_idling.enable_idling = True
    params.ini_disable = True
    # no MSAA: ImGui anti-aliases its own shapes, and Xvfb/Mesa (tests) has no multisample configs
    gl = hello_imgui.OpenGlOptions()
    gl.anti_aliasing_samples = 0
    params.renderer_backend_options.open_gl_options = gl
    hello_imgui.run(params)
    app.player.stop()
    if app.shot_path:
        from PIL import Image
        img = hello_imgui.final_app_window_screenshot()
        Image.fromarray(img).save(app.shot_path)
