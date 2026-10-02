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


class Player:
    """ffplay in a child process; playhead = start offset + elapsed wall time."""
    def __init__(self):
        self.proc, self.t0, self.wall0, self.conv = None, 0.0, 0.0, None

    def play(self, conv, t):
        self.stop()
        listen = conv.folder / "listen.opus"
        src, off = (listen, t) if listen.exists() else self._raw_at(conv, t)
        self.proc = subprocess.Popen(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "-ss", f"{off:.2f}",
                                      str(src)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
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
        return self.t0 + (time.monotonic() - self.wall0) if self.playing else None


# ---------------------------------------------------------------- app
class App:
    def __init__(self, cfg, script=None):
        self.cfg = cfg
        self.con = db.connect(cfg.db_path)
        search.ensure(self.con)
        self.convs, self.sel = [], None
        self.query, self.hits = "", None
        self.player = Player()
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

    def start_processing(self):
        if self.proc and self.proc.poll() is None:
            return
        cmd = [sys.executable, "-m", "jrec.cli"] + (["--config", os.environ["JREC_CONFIG"]]
                                                    if os.environ.get("JREC_CONFIG") else []) + ["process"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                     stdin=subprocess.DEVNULL, close_fds=True)
        self.proc_log = [f"$ {shlex.join(cmd[2:])}"]
        threading.Thread(target=self._pump_log, daemon=True).start()

    def _pump_log(self):
        for line in self.proc.stdout:
            if "warn" not in line.lower():
                self.proc_log.append(line.rstrip())
                self.proc_log = self.proc_log[-200:]
        self.proc_log.append(f"(finished, exit {self.proc.wait()})")
        self.need_reload = True  # the SQLite connection belongs to the UI thread: reload there

    # ---- frame
    def gui(self):
        if self.need_reload:
            self.need_reload = False
            self.reload()
        self._run_script()
        vp = imgui.get_main_viewport()
        imgui.set_next_window_pos(vp.work_pos)
        imgui.set_next_window_size(vp.work_size)
        flags = (imgui.WindowFlags_.no_decoration | imgui.WindowFlags_.no_move | imgui.WindowFlags_.no_saved_settings
                 | imgui.WindowFlags_.no_bring_to_front_on_focus)
        imgui.begin("main", None, flags)
        left_w = 330
        imgui.begin_child("left", imgui.ImVec2(left_w, 0), imgui.ChildFlags_.borders)
        self.left_panel()
        imgui.end_child()
        imgui.same_line()
        imgui.begin_child("right", imgui.ImVec2(0, 0))
        if self.sel:
            self.conversation_view(self.sel)
        else:
            imgui.text_disabled("No conversation selected. Plug in the recorder, or pick one on the left.")
        imgui.end_child()
        self.import_dialog()
        imgui.end()
        if self.quit:
            hello_imgui.get_runner_params().app_shall_exit = True

    def left_panel(self):
        imgui.set_next_item_width(-1)
        changed, self.query = imgui.input_text_with_hint("##q", "Search transcripts…", self.query)
        if changed:
            self.hits = search.search(self.con, self.query) if self.query.strip() else None
        busy = self.proc is not None and self.proc.poll() is None
        if imgui.button("Processing…" if busy else "Process new"):
            self.start_processing()
        imgui.same_line()
        if imgui.button("Reload"):
            self.reload()
        imgui.separator()
        if self.hits is not None:
            imgui.text_disabled(f"{len(self.hits)} hit(s)")
            for i, h in enumerate(self.hits):
                label = f"{h['abs_start'][5:16].replace('T', ' ')}  {h['text'][:80]}##hit{i}"
                if imgui.selectable(label, False)[0]:
                    conv = next((c for c in self.convs if c.name == h["folder"]), None)
                    if conv:
                        t = (datetime.fromisoformat(h["abs_start"]) - conv.start).total_seconds()
                        self.select(conv, t)
            return
        if not self.convs:
            imgui.spacing()
            imgui.text_wrapped("Library is empty.")
            imgui.text_disabled(str(self.cfg.library))
            imgui.spacing()
            imgui.text_wrapped("Plug in the recorder: an Import dialog opens here. "
                               "Or import a copied folder in a terminal:")
            imgui.text_disabled("jrec import <folder>")
        day = None
        for c in self.convs:
            d = c.speech_start.strftime("%a %d %b %Y")
            if d != day:
                imgui.spacing(); imgui.text_disabled(d); day = d
            mins = (c.sp1 - c.sp0) / 60
            badge = {"cut": "○", "transcribed": "◐", "summarized": "●"}.get(c.status, "?")
            title = c.title or "(not transcribed yet)"
            if imgui.selectable(f"{badge} {c.speech_start:%H:%M}  {mins:4.0f} min  {title[:34]}##{c.name}",
                                c is self.sel)[0]:
                self.select(c)
        if self.proc_log:
            imgui.separator()
            imgui.text_disabled("processing log")
            for line in self.proc_log[-8:]:
                imgui.text_wrapped(line)

    def conversation_view(self, c):
        imgui.text(c.title or c.name)
        imgui.text_disabled(f"{c.start:%Y-%m-%d}  clip {fmt_clock(c.start)}–{fmt_clock(c.end)}   "
                            f"speech {fmt_clock(c.abs_at(c.sp0))}–{fmt_clock(c.abs_at(c.sp1))}   "
                            f"{len(c.manifest['parts'])} part(s)   status: {c.status}")
        from .cli import human_flag
        flags = sorted({human_flag(f) for p in c.manifest["parts"] for f in p["source_start"].get("flags", [])})
        confs = {p["source_start"].get("confidence") for p in c.manifest["parts"]}
        if flags or "high" not in confs:
            imgui.text_colored(imgui.ImVec4(0.95, 0.7, 0.3, 1), f"time confidence {', '.join(c for c in confs if c)}"
                               + (f"  flags: {', '.join(flags)}" if flags else ""))
        if c.manifest["seams"]:
            imgui.text_colored(imgui.ImVec4(0.95, 0.7, 0.3, 1),
                               f"{len(c.manifest['seams'])} file seam(s): audio may be missing at the recorder's split point")
        playing = self.player.playing and self.player.conv is c
        if imgui.button("Stop" if playing else "Play"):
            self.player.stop() if playing else self.player.play(c, self.cursor)
        imgui.same_line()
        if imgui.button("Verify"):
            from .cutter import verify_folder
            c.verified = verify_folder(c.folder, self.cfg.archive)
        if c.verified is not None:
            imgui.same_line()
            if c.verified:
                imgui.text_colored(imgui.ImVec4(1, 0.3, 0.3, 1), "FAILED: " + "; ".join(c.verified))
            else:
                imgui.text_colored(imgui.ImVec4(0.4, 0.9, 0.4, 1), "verified: clips match the archived originals")
        imgui.same_line()
        _, self.follow = imgui.checkbox("follow playhead", self.follow)
        self.timeline(c)
        avail = imgui.get_content_region_avail()
        sum_w = 360 if c.summary else 0
        imgui.begin_child("transcript", imgui.ImVec2(avail.x - sum_w - (8 if sum_w else 0), 0), imgui.ChildFlags_.borders)
        self.transcript(c)
        imgui.end_child()
        if c.summary:
            imgui.same_line()
            imgui.begin_child("summary", imgui.ImVec2(0, 0), imgui.ChildFlags_.borders)
            self.summary_panel(c)
            imgui.end_child()

    def timeline(self, c):
        w = imgui.get_content_region_avail().x
        h_wave, h_lanes, h_axis = 110, 34, 22
        h = h_wave + h_lanes + h_axis
        p0 = imgui.get_cursor_screen_pos()
        imgui.invisible_button("timeline", imgui.ImVec2(w, h))
        hovered = imgui.is_item_hovered()
        dl = imgui.get_window_draw_list()
        v0, v1 = self.view
        span = max(1e-3, v1 - v0)
        x_of = lambda t: p0.x + (t - v0) / span * w
        t_of = lambda x: v0 + (x - p0.x) / w * span
        dl.add_rect_filled(p0, imgui.ImVec2(p0.x + w, p0.y + h_wave), imgui.IM_COL32(24, 26, 30, 255))
        # padding (outside the speech span) shaded, speech span marked
        for a, b in ((0.0, c.sp0), (c.sp1, c.duration)):
            if b > v0 and a < v1:
                dl.add_rect_filled(imgui.ImVec2(max(p0.x, x_of(a)), p0.y), imgui.ImVec2(min(p0.x + w, x_of(b)), p0.y + h_wave),
                                   imgui.IM_COL32(60, 60, 70, 110))
        # waveform
        if c.peaks is not None:
            mins, maxs = c.peaks
            mid, amp = p0.y + h_wave / 2, (h_wave / 2 - 4) * c.gain
            for px in range(int(w)):
                a, b = int((v0 + px / w * span) * PEAK_HZ), int((v0 + (px + 1) / w * span) * PEAK_HZ) + 1
                if a >= len(mins):
                    break
                lo, hi = max(-1.0, float(mins[a:b].min()) * c.gain) / c.gain, min(1.0, float(maxs[a:b].max()) * c.gain) / c.gain
                dl.add_line(imgui.ImVec2(p0.x + px, mid - hi * amp), imgui.ImVec2(p0.x + px, mid - lo * amp + 1),
                            imgui.IM_COL32(110, 170, 230, 255))
        else:
            dl.add_text(imgui.ImVec2(p0.x + 8, p0.y + 8), imgui.IM_COL32(150, 150, 150, 255), "loading waveform…")
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
            dl.add_line(imgui.ImVec2(x, ay), imgui.ImVec2(x, ay + 5), imgui.IM_COL32(160, 160, 160, 255))
            label = datetime.fromtimestamp(k, c.start.tzinfo).strftime("%H:%M:%S" if step < 60 else "%H:%M")
            if x + 3 + imgui.calc_text_size(label).x <= p0.x + w:
                dl.add_text(imgui.ImVec2(x + 3, ay + 4), imgui.IM_COL32(170, 170, 170, 255), label)
            k += step
        # playhead + cursor
        pos = self.player.position() if self.player.conv is c else None
        if pos is not None and pos > c.duration:
            self.player.stop(); pos = None
        if pos is not None:
            self.cursor = pos
            if self.follow and not (v0 <= pos <= v1):
                self.view = (pos, min(c.duration, pos + span)) if pos + span <= c.duration else (c.duration - span, c.duration)
        cx = x_of(self.cursor)
        if p0.x <= cx <= p0.x + w:
            dl.add_line(imgui.ImVec2(cx, p0.y), imgui.ImVec2(cx, ay), imgui.IM_COL32(255, 210, 80, 255), 2)
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
            imgui.text_disabled("Not transcribed yet. Use “Process new”.")
            return
        spk = sorted({s.get("speaker") for s in c.segments if s.get("speaker")})
        cur = self.player.position() if self.player.conv is c else None
        flags = imgui.TableFlags_.row_bg | imgui.TableFlags_.sizing_stretch_prop | imgui.TableFlags_.borders_inner_v
        if imgui.begin_table("tr", 3, flags):
            imgui.table_setup_column("time", imgui.TableColumnFlags_.width_fixed, 70)
            imgui.table_setup_column("who", imgui.TableColumnFlags_.width_fixed, 34)
            imgui.table_setup_column("text", imgui.TableColumnFlags_.width_stretch)
            for i, s in enumerate(c.segments):
                imgui.table_next_row()
                active = cur is not None and s["_t0"] <= cur < s["_t1"]
                if active:
                    imgui.table_set_bg_color(imgui.TableBgTarget_.row_bg1, imgui.IM_COL32(80, 70, 30, 160))
                imgui.table_next_column()
                if imgui.selectable(f"{s['abs_start'][11:19]}##s{i}", False)[0]:
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
                        imgui.table_set_bg_color(imgui.TableBgTarget_.row_bg1, imgui.IM_COL32(60, 70, 110, 160))
                        self.scroll_to_cursor = False
            imgui.end_table()

    def summary_panel(self, c):
        sm = c.summary
        imgui.push_text_wrap_pos(0)
        imgui.text(sm.get("title", ""))
        imgui.separator()
        imgui.text_wrapped(sm.get("summary", ""))
        for key, head in (("key_points", "Key points"), ("action_items", "Action items")):
            items = sm.get(key) or []
            if not items:
                continue
            imgui.spacing(); imgui.text_disabled(head)
            for j, it in enumerate(items):
                imgui.bullet()
                imgui.text_wrapped(it["text"] + (f" — {it['owner']}" if it.get("owner") else ""))
                for k, tm in enumerate(it.get("times", [])):
                    imgui.same_line()
                    if imgui.small_button(f"{tm}##{key}{j}_{k}"):
                        seg = next((s for s in c.segments if s["abs_start"][11:19] == tm), None)
                        if seg:
                            self.select(c, seg["_t0"]); self.player.play(c, seg["_t0"])
        imgui.pop_text_wrap_pos()

    def import_dialog(self):
        pi = self.pending_import
        if pi and pi["open"] and not imgui.is_popup_open("Recorder connected"):
            imgui.open_popup("Recorder connected")
        vp = imgui.get_main_viewport()
        imgui.set_next_window_size(imgui.ImVec2(min(1000, vp.work_size.x - 80), 0), imgui.Cond_.appearing)
        imgui.set_next_window_pos(imgui.ImVec2(vp.work_pos.x + vp.work_size.x / 2, vp.work_pos.y + vp.work_size.y / 3),
                                  imgui.Cond_.appearing, imgui.ImVec2(0.5, 0.5))
        bg = imgui.get_style().color_(imgui.Col_.window_bg)
        imgui.push_style_color(imgui.Col_.popup_bg, imgui.ImVec4(bg.x, bg.y, bg.z, 1.0))  # opaque: no text bleeding through
        opened, _ = imgui.begin_popup_modal("Recorder connected", None, imgui.WindowFlags_.no_saved_settings)
        imgui.pop_style_color()
        if not opened:
            return
        if pi:
            imgui.text(f"{pi['device'].name} at {pi['mount']}: {len(pi['cands'])} new recording(s)")
            imgui.text_disabled("Mounted read-only. Nothing is copied until you press Import.")
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
            imgui.begin_disabled(self.importing or n == 0)
            if imgui.button(f"Import {n} file(s) ({_fmt_size(size)})"):
                items = [c for c, k in zip(pi["cands"], pi["checked"]) if k]
                threading.Thread(target=self._do_import, args=(items, pi["device"], pi["serial"]), daemon=True).start()
                pi["done"] = True
            imgui.end_disabled()
            imgui.same_line()
            if imgui.button("Skip" if not pi.get("done") else "Close"):
                self.pending_import = None
                imgui.close_current_popup()
            if pi.get("done") and not self.importing:
                imgui.same_line()
                if imgui.button("Process now"):
                    self.start_processing()
                    self.pending_import = None
                    imgui.close_current_popup()
            if self.import_msg:
                imgui.text_wrapped(self.import_msg)
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
        elif cmd == "shot":
            self.shot_path = arg
            self.quit = True
        elif cmd == "quit":
            self.quit = True


def _load_fonts():
    path = next((p for p in FONT_CANDIDATES if Path(p).exists()), None)
    if path:
        hello_imgui.load_font(path, 17.0)
        thai = next((p for p in THAI_FONTS if Path(p).exists()), None)
        if thai:
            hello_imgui.load_font(thai, 17.0, hello_imgui.FontLoadingParams(merge_to_last_font=True))
    else:
        hello_imgui.imgui_default_settings.load_default_font_with_font_awesome_icons()


def run(cfg, script=None):
    app = App(cfg, script)
    app.shot_path = None
    params = hello_imgui.RunnerParams()
    params.app_window_params.window_title = "jev-recorder"
    params.app_window_params.window_geometry.size = (1500, 950)
    params.imgui_window_params.default_imgui_window_type = hello_imgui.DefaultImGuiWindowType.no_default_window
    params.callbacks.show_gui = app.gui
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
