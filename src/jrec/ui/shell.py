"""App shell (polish-app): command registry and keymap, command palette (Ctrl+P), the utility
cluster at the top right (search · tasks and logs · help · settings), the Tasks and logs panel
(Ctrl+J) and Help (F1). Menus, palette, tooltips and Help › Shortcuts all read COMMANDS."""
import subprocess
import sys
import time
from dataclasses import dataclass, field

from imgui_bundle import imgui

from .. import i18n
from .. import theme as th
from ..i18n import T
from ..query import fold
from ..theme import C, U
from . import anim, helptext


# ---------------------------------------------------------------- command registry
@dataclass
class Command:
    id: str
    label: str                       # English; shown through T()
    group: str                       # General, Navigation, Playback, Tasks, Conversation, View
    run: object = None               # fn(app) or None for keys handled elsewhere (listed in Help only)
    keys: str = ""                   # "Ctrl+P"; several with " / "
    icon: str = ""
    when: object = None              # fn(app) -> bool
    ctx: str = "global"              # global: works in text fields too; player: only with no text field focused
    aliases: list = field(default_factory=list)


def _has_conv(app):
    return app.sel is not None


def _done_conv(app):
    return app.sel is not None and app.sel.status != "cut"


def _sidebar(app, tab):
    app.show_sidebar = True
    app.side_tab = tab
    app.query, app.hits = "", None


COMMANDS = [
    # General
    Command("palette", "Search and commands", "General", lambda a: a.open_palette(), "Ctrl+P / Ctrl+K", th.ICON_SEARCH,
            aliases=["find anything", "command palette"]),
    Command("tasks", "Tasks and logs", "General", lambda a: a.toggle_tasks(), "Ctrl+J", th.ICON_LIST_CHECK,
            aliases=["queue", "progress", "log"]),
    Command("help", "Help", "General", lambda a: a.open_help("concepts"), "F1", th.ICON_HELP),
    Command("shortcuts", "Keyboard shortcuts", "General", lambda a: a.open_help("shortcuts"), "Ctrl+/", th.ICON_KEYBOARD),
    Command("settings", "Settings", "General", lambda a: a.open_settings(), "Ctrl+,", th.ICON_GEAR,
            aliases=["preferences", "options"]),
    Command("theme", "Switch theme", "View", lambda a: a.cycle_theme(), "Ctrl+Shift+T", th.ICON_THEME,
            aliases=["dark", "light", "tokyo night"]),
    Command("lang", "Switch language", "View", lambda a: a.cycle_lang(), "", th.ICON_LANG,
            aliases=["english", "中文", "日本語", "한국어"]),
    Command("sidebar", "Show or hide the sidebar", "View", lambda a: setattr(a, "show_sidebar", not a.show_sidebar),
            "Ctrl+B", th.ICON_TALKS),
    Command("zoomin", "Larger text", "View", lambda a: a.text_step(1), "Ctrl+=", th.ICON_TEXT),
    Command("zoomout", "Smaller text", "View", lambda a: a.text_step(-1), "Ctrl+-", th.ICON_TEXT),
    Command("zoom0", "Normal text size", "View", lambda a: a.set_pref("text_size", 1.0), "Ctrl+0", th.ICON_TEXT),
    Command("quit", "Quit", "General", lambda a: setattr(a, "quit", True), "Ctrl+Q", th.ICON_X),
    # Navigation
    Command("talks", "Show conversations", "Navigation", lambda a: _sidebar(a, "conv"), "", th.ICON_TALKS),
    Command("people", "Show people", "Navigation", lambda a: _sidebar(a, "people"), "", th.ICON_PEOPLE),
    Command("files", "Show recordings", "Navigation", lambda a: _sidebar(a, "rec"), "", th.ICON_FILES),
    Command("moments", "Show moments", "Navigation", lambda a: _sidebar(a, "moments"), "", th.ICON_MOMENTS),
    Command("tags", "Manage tags", "Navigation", lambda a: _sidebar(a, "tags"), "", th.ICON_TAGS),
    Command("find", "Find in this conversation", "Navigation", lambda a: setattr(a, "focus_find", True), "Ctrl+F",
            th.ICON_SEARCH, _has_conv),
    Command("goto", "Go to a time", "Navigation", lambda a: setattr(a, "focus_goto", True), "Ctrl+G", "", _has_conv,
            aliases=["jump", "seek"]),
    # Playback (single keys: only when no text field has focus)
    Command("play", "Play / pause", "Playback", lambda a: a.toggle_play(a.sel), "Space", th.ICON_PLAY, _has_conv, "player"),
    Command("next", "Next speech", "Playback", lambda a: a.jump_speech(a.sel, 1), "N", "", _has_conv, "player"),
    Command("prev", "Previous speech", "Playback", lambda a: a.jump_speech(a.sel, -1), "P", "", _has_conv, "player"),
    Command("note", "Add a note here", "Playback", lambda a: a.new_note(a.sel, a.here(a.sel)), "M", th.ICON_NOTE,
            _has_conv, "player"),
    Command("seta", "Set A", "Playback", lambda a: a.set_a(a.here(a.sel)), "[", "", _has_conv, "player"),
    Command("setb", "Set B", "Playback", lambda a: a.set_b(a.here(a.sel)), "]", "", _has_conv, "player"),
    Command("loop", "Repeat A–B on or off", "Playback", None, "L", "", _has_conv, "player"),
    Command("seek", "Back / forward 5 s (Shift 1 s, Alt 30 s)", "Playback", None, "Left / Right"),
    Command("zoomtl", "Zoom the timeline", "Playback", None, "= / -"),
    Command("openrow", "Open the selected row", "Playback", None, "Enter"),
    Command("clearab", "Clear A–B; close a dialog", "Playback", None, "Esc"),
    # Tasks
    Command("transcribe_new", "Transcribe new", "Tasks", lambda a: a.start_processing(), "", th.ICON_WAND,
            lambda a: any(c.status == "cut" for c in a.convs), aliases=["process", "asr", "speech to text"]),
    Command("pause_all", "Pause all", "Tasks", lambda a: a.tasks.pause_all(), "", th.ICON_PAUSE),
    Command("resume_all", "Resume all", "Tasks", lambda a: a.tasks.resume_all(), "", th.ICON_PLAY,
            lambda a: any(t.state == "paused" for t in a.tasks.tasks) or a.tasks.paused_all),
    Command("cancel_all", "Cancel all", "Tasks", lambda a: a.tasks.cancel_all(), "", th.ICON_X,
            lambda a: bool(a.tasks.active())),
    Command("clear_done", "Clear done", "Tasks", lambda a: a.tasks.clear_done(), "", th.ICON_TRASH),
    # Conversation
    Command("transcribe", "Transcribe this conversation", "Conversation",
            lambda a: a.start_job(["transcribe", str(a.sel.folder)], f"Transcribing {a.sel.speech_start:%H:%M}",
                                  [a.sel.name]), "", th.ICON_WAND, lambda a: a.sel is not None and a.sel.status == "cut"),
    Command("summarize", "Summarize", "Conversation",
            lambda a: a.start_job(["summarize", str(a.sel.folder)], f"Summarising {a.sel.speech_start:%H:%M}",
                                  [a.sel.name]), "", "", _done_conv),
    Command("translate", "Translate…", "Conversation", lambda a: setattr(a, "open_tr_menu", True), "", th.ICON_LANG,
            _done_conv),
    Command("analyze", "Analyze", "Conversation", lambda a: a.analyze(a.sel), "", th.ICON_EYE, _done_conv,
            aliases=["insights", "people", "relationships"]),
    Command("verify", "Verify clips", "Conversation", lambda a: a.verify(a.sel), "", th.ICON_CHECK, _has_conv,
            aliases=["evidence", "hash", "sha256"]),
]
CMD = {c.id: c for c in COMMANDS}

_KEYS = {",": "comma", "/": "slash", "=": "equal", "-": "minus", "[": "left_bracket", "]": "right_bracket",
         "Space": "space", "Enter": "enter", "Esc": "escape", "Left": "left_arrow", "Right": "right_arrow"}


def _parse(combo):
    parts = combo.split("+") if combo != "Ctrl+=" else ["Ctrl", "="]
    if combo.endswith("+-"):
        parts = combo[:-2].split("+") + ["-"]
    mods = {p for p in parts[:-1]}
    k = parts[-1]
    name = _KEYS.get(k) or (k.lower() if len(k) == 1 and k.isalpha() else f"_{k}" if k.isdigit() else k.lower())
    key = getattr(imgui.Key, name, None)
    return ("Ctrl" in mods, "Shift" in mods, "Alt" in mods, key)


_PARSED = {c.id: [_parse(k.strip()) for k in c.keys.split(" / ")] for c in COMMANDS
           if c.keys and c.run is not None}


def dispatch_keys(app):
    """Run the command whose shortcut was pressed this frame."""
    io = imgui.get_io()
    ctrl = io.key_ctrl or io.key_super
    typing = io.want_text_input
    popup = imgui.is_popup_open("", imgui.PopupFlags_.any_popup_id)
    for c in COMMANDS:
        for (want_ctrl, want_shift, want_alt, key) in _PARSED.get(c.id, []):
            if key is None or not imgui.is_key_pressed(key, False):
                continue
            if want_ctrl != ctrl or want_shift != io.key_shift or want_alt != io.key_alt:
                continue
            if c.ctx == "player" and (typing or popup or app.palette_open):
                continue
            if c.when and not c.when(app):
                continue
            c.run(app)
            return True
    return False


def keys_for(cid):
    c = CMD.get(cid)
    return c.keys.split(" / ")[0] if c and c.keys else ""


# ---------------------------------------------------------------- utility cluster (top right)
def icon_button(id_, icon, tip, keys="", size=28.0, active=False):
    imgui.push_style_color(imgui.Col_.button, C("track") if active else C("bg", 0.0))
    imgui.push_style_color(imgui.Col_.button_hovered, C("track"))
    imgui.push_style_color(imgui.Col_.text, C("accent") if active else C("text_dim"))
    pressed = imgui.button(f"{icon}##{id_}", imgui.ImVec2(size, size))
    if imgui.is_item_hovered():
        imgui.push_style_color(imgui.Col_.text, C("text"))
        imgui.pop_style_color()
    imgui.pop_style_color(3)
    th.tip(tip, keys)
    return pressed


def utility_cluster(app, x, y, size):
    """Search · tasks and logs · help · settings, in this order, 4 px apart. Returns the width used."""
    gap = 4
    imgui.set_cursor_screen_pos(imgui.ImVec2(x, y))
    if icon_button("u_search", th.ICON_SEARCH, "Search", keys_for("palette"), size, app.palette_open):
        app.open_palette()
    imgui.set_cursor_screen_pos(imgui.ImVec2(x + (size + gap), y))
    status_icon(app, size)
    imgui.set_cursor_screen_pos(imgui.ImVec2(x + 2 * (size + gap), y))
    if icon_button("u_help", th.ICON_HELP, "Help", keys_for("help"), size, app.show_help):
        app.open_help("concepts")
    imgui.set_cursor_screen_pos(imgui.ImVec2(x + 3 * (size + gap), y))
    if icon_button("u_settings", th.ICON_GEAR, "Settings", keys_for("settings"), size, app.show_settings):
        app.open_settings()
    return 4 * size + 3 * gap


def status_text(app):
    q = app.tasks
    t = q.running
    frac, done, total = q.overall()
    if t:
        eta = q.eta()
        left = f" · {_dur(eta)} {T('left')}" if eta else ""
        return T("{done} of {total} · {pct}%", done=done, total=total, pct=int(frac * 100)) + left + f"  ·  {T(t.label)}"
    if q.paused_all or any(x.state == "paused" for x in q.tasks):
        return T("Paused")
    return T("Ready")


def _dur(s):
    s = int(s)
    return f"{s // 3600} h {s % 3600 // 60} m" if s >= 3600 else f"{s // 60} m" if s >= 60 else f"{s} s"


def status_icon(app, size):
    """Idle: grey list-check. Busy: accent ring with real progress + count badge. Paused: warning ring.
    Failure: danger dot. New warning in the logs: warning dot."""
    q = app.tasks
    p = imgui.get_cursor_screen_pos()
    active = q.active()
    if icon_button("u_tasks", th.ICON_LIST_CHECK, T("Tasks and logs") + "\n" + status_text(app), keys_for("tasks"),
                   size, app.show_tasks):
        app.toggle_tasks()
    dl = imgui.get_window_draw_list()
    cx, cy, r = p.x + size / 2, p.y + size / 2, size / 2 - 1.5
    running = q.running
    paused = any(t.state == "paused" for t in q.tasks) or q.paused_all
    if active:
        dl.add_circle(imgui.ImVec2(cx, cy), r, U("track"), 32, 2.5)
        frac = app.job_overall_smooth()
        if running and running.progress() is None:       # total not known yet: a short arc that turns
            a0 = time.monotonic() * 4.0
            dl.path_arc_to(imgui.ImVec2(cx, cy), r, a0, a0 + 1.2, 16)
        else:
            a0 = -1.5708
            dl.path_arc_to(imgui.ImVec2(cx, cy), r, a0, a0 + 6.2832 * max(0.02, frac), 32)
        dl.path_stroke(U("accent" if running else "warn" if paused else "text_dim"), 2.5)
        n = len(active)
        badge = str(n) if n < 10 else "9+"
        fs = imgui.get_font_size() * 0.68
        bw = max(fs + 2, imgui.calc_text_size(badge).x * 0.68 + 6)
        bx, by = p.x + size - bw + 3, p.y - 2
        dl.add_rect_filled(imgui.ImVec2(bx, by), imgui.ImVec2(bx + bw, by + fs + 2), U("accent" if running else "warn"), 8.0)
        dl.add_text(imgui.get_font(), fs, imgui.ImVec2(bx + (bw - imgui.calc_text_size(badge).x * 0.68) / 2, by + 1),
                    imgui.get_color_u32(th.hexc("#ffffff")), badge)
    failed = any(t.state == "failed" for t in q.tasks[-10:]) and not getattr(app, "failed_seen", False)
    if failed or app.log_unseen:
        col = U("danger" if failed or app.log_unseen == "error" else "warn")
        dl.add_circle_filled(imgui.ImVec2(p.x + 4, p.y + size - 4), 3.5, col)


# ---------------------------------------------------------------- Tasks and logs panel (Ctrl+J)
STATE_ICON = {"queued": th.ICON_WAIT, "running": th.ICON_PLAY, "paused": th.ICON_PAUSE, "done": th.ICON_CHECK,
              "failed": th.ICON_ERROR, "canceled": th.ICON_X, "stopped": th.ICON_STOP}
STATE_COL = {"queued": "text_dim", "running": "accent", "paused": "warn", "done": "ok", "failed": "danger",
             "canceled": "text_dim", "stopped": "warn"}
STATE_NAME = {"queued": "Waiting", "running": "Running", "paused": "Paused", "done": "Done", "failed": "Failed",
              "canceled": "Canceled", "stopped": "Stopped"}


def tasks_window(app):
    if not app.show_tasks:
        anim.fade_in("Tasks and logs", False)
        return
    vp = imgui.get_main_viewport()
    ts = app.prefs["text_size"]
    w, h = min(520 * ts, vp.work_size.x - 40), min(560 * ts, vp.work_size.y - 80)
    imgui.set_next_window_size(imgui.ImVec2(w, h), imgui.Cond_.appearing)
    anchor = app.tasks_anchor or (vp.work_pos.x + vp.work_size.x - 300, vp.work_pos.y + 44)
    pos = app.prefs.get("dlg_pos", {}).get("tasks")
    if pos:
        imgui.set_next_window_pos(imgui.ImVec2(*pos), imgui.Cond_.appearing)
    else:
        imgui.set_next_window_pos(imgui.ImVec2(min(anchor[0] - w / 2, vp.work_pos.x + vp.work_size.x - w - 12),
                                               anchor[1]), imgui.Cond_.appearing)
    imgui.push_style_color(imgui.Col_.window_bg, C("bg"))
    imgui.push_style_color(imgui.Col_.title_bg, C("track"))
    imgui.push_style_color(imgui.Col_.title_bg_active, C("pill"))
    imgui.push_style_var(imgui.StyleVar_.window_rounding, 10.0)
    imgui.push_style_var(imgui.StyleVar_.window_border_size, 1.0)
    imgui.set_next_window_bg_alpha(anim.fade_in("Tasks and logs", True))
    visible, app.show_tasks = imgui.begin(f"{T('Tasks and logs')}###tasks", True,
                                          imgui.WindowFlags_.no_collapse | imgui.WindowFlags_.no_saved_settings)
    imgui.pop_style_var(2)
    imgui.pop_style_color(3)
    if not visible:
        imgui.end()
        return
    keep_inside(app, "tasks")
    if imgui.is_window_focused(imgui.FocusedFlags_.root_and_child_windows) and \
            imgui.is_key_pressed(imgui.Key.escape, False) and not imgui.get_io().want_text_input:
        app.show_tasks = False
    th.small(status_text(app))
    if imgui.begin_tab_bar("tasks_tabs"):
        if imgui.begin_tab_item(f"{th.ICON_LIST_CHECK}  {T('Tasks')}###t_tasks", None,
                                imgui.TabItemFlags_.set_selected if app.tasks_tab_set == "tasks" else 0)[0]:
            app.tasks_tab = "tasks"
            app.failed_seen = True
            _tasks_tab(app)
            imgui.end_tab_item()
        if imgui.begin_tab_item(f"{th.ICON_TERMINAL}  {T('Logs')}###t_logs", None,
                                imgui.TabItemFlags_.set_selected if app.tasks_tab_set == "logs" else 0)[0]:
            app.tasks_tab = "logs"
            app.log_unseen = None
            _logs_tab(app)
            imgui.end_tab_item()
        app.tasks_tab_set = None
        imgui.end_tab_bar()
    remember_pos(app, "tasks")
    imgui.end()


def _small_icon(id_, icon, tip, col="text_dim"):
    imgui.push_style_color(imgui.Col_.button, C("bg", 0.0))
    imgui.push_style_color(imgui.Col_.button_hovered, C("track"))
    imgui.push_style_color(imgui.Col_.text, C(col))
    pressed = imgui.small_button(f"{icon}##{id_}")
    imgui.pop_style_color(3)
    th.tip(tip)
    return pressed


def _tasks_tab(app):
    q = app.tasks
    if th.button(f"{th.ICON_PLAY}  {T('Resume all')}" if q.paused_all else f"{th.ICON_PAUSE}  {T('Pause all')}"):
        q.resume_all() if q.paused_all else q.pause_all()
    th.tip("Pauses transcription between conversations; finished ones are kept")
    imgui.same_line()
    if th.button(f"{th.ICON_X}  {T('Cancel all')}", disabled=not q.active()):
        q.cancel_all()
    imgui.same_line()
    if th.button(f"{th.ICON_TRASH}  {T('Clear done')}",
                 disabled=not any(t.state not in ("queued", "running", "paused") for t in q.tasks)):
        q.clear_done()
    imgui.push_style_color(imgui.Col_.child_bg, C("bg", 0.0))
    imgui.begin_child("task_list", imgui.ImVec2(0, 0))
    imgui.pop_style_color()
    if not q.tasks:
        imgui.dummy(imgui.ImVec2(0, 8))
        th.small("No tasks. Long jobs like transcription show here.")
    order = ["running", "queued", "paused", "failed", "stopped", "canceled", "done"]
    groups = [(st, [t for t in q.tasks if t.state == st]) for st in order]
    for st, items in groups:
        if not items:
            continue
        th.section(T(STATE_NAME[st]))
        with th.card(f"tg_{st}", flags=imgui.ChildFlags_.auto_resize_y, padding=(10, 8)):
            for k, t in enumerate(reversed(items) if st in ("done", "failed", "stopped", "canceled") else items):
                if k:
                    imgui.separator()
                _task_row(app, t)
    imgui.end_child()


def _task_row(app, t):
    q = app.tasks
    imgui.push_id(t.id)
    x_right = imgui.get_cursor_pos_x() + imgui.get_content_region_avail().x
    imgui.text_colored(C(STATE_COL[t.state]), STATE_ICON[t.state])
    imgui.same_line()
    # actions on the right; Pause only where the task can resume
    acts = []
    if t.state == "running":
        if t.resumable:
            acts.append(("pause", th.ICON_PAUSE, "Pause: ends after a clean point; Resume continues with what is left",
                         lambda: q.pause(t), "text_dim"))
        acts.append(("stop", th.ICON_STOP, "Stop: finished conversations are kept; the current one stays as it was",
                     lambda: q.stop(t), "danger"))
    if t.state == "queued":
        acts += [("up", th.ICON_UP, "Move up", lambda: q.move(t, -1), "text_dim"),
                 ("down", th.ICON_DOWN, "Move down", lambda: q.move(t, 1), "text_dim")]
        if t.resumable:
            acts.append(("pause", th.ICON_PAUSE, "Pause", lambda: q.pause(t), "text_dim"))
    if t.state == "paused":
        acts.append(("resume", th.ICON_PLAY, "Resume", lambda: q.resume(t), "accent"))
    if t.state in ("queued", "paused"):
        acts.append(("cancel", th.ICON_X, "Cancel", lambda: q.cancel(t), "text_dim"))
    if t.state in ("failed", "canceled", "stopped"):
        acts.append(("retry", th.ICON_RETRY, "Retry", lambda: q.retry(t), "accent"))
    if t.state not in ("running",):
        acts.append(("remove", th.ICON_TRASH, "Remove from the list", lambda: q.remove(t), "text_dim"))
    aw = len(acts) * (imgui.get_frame_height() + 2)
    avail = imgui.get_content_region_avail().x - aw - 8
    label = T(t.label)
    imgui.push_clip_rect(imgui.get_cursor_screen_pos(),
                         imgui.ImVec2(imgui.get_cursor_screen_pos().x + avail, imgui.get_cursor_screen_pos().y + 40), True)
    imgui.text(label)
    imgui.pop_clip_rect()
    if imgui.calc_text_size(label).x > avail and imgui.is_item_hovered():
        imgui.set_tooltip(label)
    run = None
    for k, (aid, icon, tip, fn, col) in enumerate(acts):
        imgui.same_line(x_right - aw + k * (imgui.get_frame_height() + 2))
        if _small_icon(aid, icon, tip, col):
            run = fn
    p = t.progress()
    if t.state in ("running", "paused", "queued") or t.state == "done":
        frac = (app.job_overall_smooth() if False else p) if p is not None else None
        if frac is None:
            imgui.progress_bar(-1.0 * time.monotonic(), imgui.ImVec2(-1, 0), T("Loading models (the first run takes 1-2 minutes)…"))
        else:
            n = max(1, len(t.files))
            done_n = (t.file[0] - 1) if t.file else (n if t.state == "done" else 0)
            imgui.progress_bar(frac, imgui.ImVec2(-1, 0), f"{done_n} / {n}  ·  {frac * 100:.0f}%")
    if t.state == "running":
        eta = t.eta()
        cur = app.conv_label(t.file[2]) if t.file and t.file[2] != "loading-models" else ""
        th.small(f"{t.stage_label(T)}" + (f"  ·  {cur}" if cur else "") + (f"  ·  {_dur(eta)} {T('left')}" if eta else ""))
    elif t.state == "failed" and t.error:
        th.small(t.error[:110], "danger")
        if imgui.is_item_hovered():
            imgui.set_tooltip("\n".join(t.log[-25:]))
    elif t.state == "done" and t.t1:
        th.small(T("Done in {s}", s=_dur(t.elapsed())))
    if imgui.tree_node_ex(T("Output") + "##out", imgui.TreeNodeFlags_.span_avail_width):
        for line in t.log[-40:]:
            th.small(line, "danger" if "rror" in line or "failed" in line else "text_dim")
        imgui.tree_pop()
    imgui.pop_id()
    if run:
        run()


LEVELS = [("error", th.ICON_ERROR, "danger", "Error"), ("warning", th.ICON_WARN, "warn", "Warning"),
          ("info", th.ICON_INFO, "text_dim", "Info")]


def _logs_tab(app):
    for lv, icon, col, name in LEVELS:
        on = lv in app.log_levels
        imgui.push_style_color(imgui.Col_.button, C("pill") if on else C("track"))
        imgui.push_style_color(imgui.Col_.text, C(col) if on else C("text_dim"))
        if imgui.small_button(f"{icon} {T(name)}##lv{lv}"):
            app.log_levels ^= {lv}
        imgui.pop_style_color(2)
        imgui.same_line()
    imgui.set_next_item_width(max(80.0, imgui.get_content_region_avail().x - 70))
    _, app.log_query = imgui.input_text_with_hint("##logq", T("Search"), app.log_query)
    imgui.same_line()
    if _small_icon("copylog", th.ICON_COPY, "Copy"):
        imgui.set_clipboard_text("\n".join(f"{t} {lv} {m}" for t, lv, m in app.logs))
    imgui.same_line()
    if _small_icon("logdir", th.ICON_FOLDER, "Open log folder"):
        open_folder(app.log_dir)
    q = fold(app.log_query)
    rows = [r for r in reversed(app.logs) if r[1] in app.log_levels and (not q or q in fold(r[2]))]
    imgui.push_style_color(imgui.Col_.child_bg, C("bg", 0.0))
    imgui.begin_child("log_list", imgui.ImVec2(0, 0))
    imgui.pop_style_color()
    if not rows:
        th.small("Nothing to show.")
    icon_of = {lv: (icon, col) for lv, icon, col, _ in LEVELS}
    for k, (t, lv, msg) in enumerate(rows[:400]):
        icon, col = icon_of.get(lv, (th.ICON_INFO, "text_dim"))
        imgui.text_colored(C("text_dim"), t)
        imgui.same_line()
        imgui.text_colored(C(col), icon)
        imgui.same_line()
        imgui.push_text_wrap_pos(0)
        imgui.text(msg)
        imgui.pop_text_wrap_pos()
    imgui.end_child()


def open_folder(path):
    try:
        path.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            import os
            os.startfile(str(path))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


# ---------------------------------------------------------------- movable dialogs
def keep_inside(app, key, min_visible=48.0):
    """Push the current window back so at least its header stays inside the app window."""
    vp = imgui.get_main_viewport()
    p, s = imgui.get_window_pos(), imgui.get_window_size()
    x = min(max(p.x, vp.work_pos.x - s.x + min_visible), vp.work_pos.x + vp.work_size.x - min_visible)
    y = min(max(p.y, vp.work_pos.y), vp.work_pos.y + vp.work_size.y - min_visible)
    if (x, y) != (p.x, p.y) and not imgui.is_mouse_dragging(0):
        imgui.set_window_pos(imgui.ImVec2(x, y))


def remember_pos(app, key):
    p = imgui.get_window_pos()
    pos = app.prefs.setdefault("dlg_pos", {})
    if pos.get(key) != [p.x, p.y]:
        pos[key] = [p.x, p.y]
        if imgui.is_mouse_released(0):
            th.save_prefs(app.prefs)


# ---------------------------------------------------------------- command palette (Ctrl+P)
def _score(q_tokens, hay):
    if not q_tokens:
        return 1
    score = 0
    for tk in q_tokens:
        k = hay.find(tk)
        if k < 0:
            # loose: the letters in order (typing "trnew" finds "transcribe new")
            it = iter(hay)
            if len(tk) >= 3 and all(ch in it for ch in tk):
                score += 1
                continue
            return 0
        score += 10 if k == 0 or hay[k - 1] in " ·/" else 5
    return score


def palette_items(app, q):
    """[(group, icon, label, sub, keys, action)] ranked; groups: Commands, Settings, Help, Talks, Transcript."""
    from .dialogs import _settings_rows
    toks = fold(q).split()
    out = []
    for c in COMMANDS:
        if c.run is None or (c.when and not c.when(app)):
            continue
        hay = fold(" ".join([T(c.label), c.label] + c.aliases))
        s = _score(toks, hay)
        if s:
            out.append((s + 3, "Commands", c.icon or th.ICON_BULB, T(c.label), "", keys_for(c.id),
                        (lambda cc=c: cc.run(app))))
    if toks:
        for sec, title, desc, _ in _settings_rows(app):
            hay = fold(" ".join([T(title), title, T(sec), sec, T(desc)]))
            s = _score(toks, hay)
            if s:
                out.append((s, "Settings", th.ICON_GEAR, T(title), T(sec) + "  ·  " + T(desc), "",
                            (lambda t=title: app.open_settings(T(t)))))
        for kind, entries in (("concepts", helptext.concepts()), ("glossary", helptext.glossary())):
            for e in entries:
                hay = fold(" ".join([e["term"], e.get("en", ""), e["text"]]))
                s = _score(toks, hay)
                if s:
                    out.append((s - 1, "Help", th.ICON_BOOK, e["term"], e["text"][:90], "",
                                (lambda k=kind, t=e["term"]: app.open_help(k, t))))
        for c in app.convs:
            hay = fold(" ".join([c.title or "", f"{c.speech_start:%Y-%m-%d %a %b %H:%M}", " ".join(c.tags or [])]))
            s = _score(toks, hay)
            if s:
                out.append((s - 2, "Talks", th.ICON_TALKS, c.title or T("not transcribed"),
                            f"{c.speech_start:%a %-d %b  %H:%M}", "", (lambda cc=c: app.select(cc))))
        if len(q.strip()) >= 2:
            try:
                from .. import libsearch
                hits = [h for h in libsearch.search(app.convs, q, limit=60) if h[2] == "row"][:8]
            except Exception:
                hits = []
            for c, i, _, _ in hits:
                seg = c.segments[i]
                out.append((1, "Transcript", th.ICON_TEXT, seg["text"][:90],
                            f"{seg['abs_start'][:16].replace('T', '  ')}  ·  {c.speaker(seg, i)}", "",
                            (lambda cc=c, ii=i, t=seg["_t0"]: app.goto_row(cc, ii, t, q))))
    else:
        recent = [CMD[r] for r in app.recent_cmds if r in CMD]
        out = [(100 - k, "Recent", c.icon or th.ICON_BULB, T(c.label), "", keys_for(c.id), (lambda cc=c: cc.run(app)))
               for k, c in enumerate(recent)] + [o for o in out if o[3] not in {T(c.label) for c in recent}]
    order = {"Recent": 0, "Commands": 1, "Talks": 2, "Transcript": 3, "Settings": 4, "Help": 5}
    out.sort(key=lambda o: (order[o[1]], -o[0]))
    per = {}
    res = []
    for o in out:
        per[o[1]] = per.get(o[1], 0) + 1
        if per[o[1]] <= (12 if o[1] == "Commands" else 8):
            res.append(o[1:])
    return res


def palette(app):
    if not app.palette_open:
        return
    vp = imgui.get_main_viewport()
    w = min(680 * app.prefs["text_size"], vp.work_size.x - 40)
    imgui.set_next_window_pos(imgui.ImVec2(vp.work_pos.x + (vp.work_size.x - w) / 2, vp.work_pos.y + 56))
    imgui.set_next_window_size(imgui.ImVec2(w, 0))
    imgui.set_next_window_size_constraints(imgui.ImVec2(w, 0), imgui.ImVec2(w, vp.work_size.y * 0.7))
    imgui.push_style_color(imgui.Col_.window_bg, C("card"))
    imgui.push_style_color(imgui.Col_.border, C("card_border"))
    imgui.push_style_var(imgui.StyleVar_.window_rounding, 10.0)
    imgui.push_style_var(imgui.StyleVar_.window_border_size, 1.0)
    imgui.push_style_var(imgui.StyleVar_.window_padding, imgui.ImVec2(10, 10))
    imgui.begin("##palette", None, imgui.WindowFlags_.no_decoration | imgui.WindowFlags_.no_saved_settings
                | imgui.WindowFlags_.always_auto_resize | imgui.WindowFlags_.no_move)
    imgui.pop_style_var(3)
    imgui.pop_style_color(2)
    if app.palette_focus:
        imgui.set_window_focus()
        imgui.set_keyboard_focus_here()
        app.palette_focus = False
    imgui.text_colored(C("text_dim"), th.ICON_SEARCH)
    imgui.same_line()
    imgui.set_next_item_width(-1)
    changed, app.palette_q = imgui.input_text_with_hint(
        "##pq", T("Type a command, setting, help topic or words from a transcript"), app.palette_q)
    if changed:
        app.palette_sel = 0
        app.palette_cache = None
    if app.palette_cache is None:
        app.palette_cache = palette_items(app, app.palette_q)
    items = app.palette_cache
    K = imgui.Key
    if imgui.is_key_pressed(K.down_arrow):
        app.palette_sel = min(len(items) - 1, app.palette_sel + 1)
        app.palette_scroll = True
    if imgui.is_key_pressed(K.up_arrow):
        app.palette_sel = max(0, app.palette_sel - 1)
        app.palette_scroll = True
    if imgui.is_key_pressed(K.tab, False) and items:      # next group
        g = items[app.palette_sel][0]
        nxt = next((k for k in range(app.palette_sel + 1, len(items)) if items[k][0] != g), 0)
        app.palette_sel, app.palette_scroll = nxt, True
    run = None
    if imgui.is_key_pressed(K.enter, False) or imgui.is_key_pressed(K.keypad_enter, False):
        if items:
            run = items[app.palette_sel]
        elif app.palette_q.strip():
            run = ("Help", "", "", "", "", lambda: app.open_help("glossary", app.palette_q))
    close = imgui.is_key_pressed(K.escape, False)
    imgui.dummy(imgui.ImVec2(0, 2))
    if not items:
        imgui.text_colored(C("text_dim"), T("No results for “{q}”", q=app.palette_q))
        if imgui.selectable(f"{th.ICON_BOOK}  {T('Search help')}", True)[0]:
            run = ("Help", "", "", "", "", lambda: app.open_help("glossary", app.palette_q))
    fs = imgui.get_font_size()
    list_h = min(len(items) * (fs * 1.9) + 30 * len({i[0] for i in items}), vp.work_size.y * 0.6)
    if items:
        imgui.push_style_color(imgui.Col_.child_bg, C("card", 0.0))
        imgui.begin_child("pal_list", imgui.ImVec2(0, list_h))
        imgui.pop_style_color()
        last = None
        for k, (grp, icon, label, sub, keys, act) in enumerate(items):
            if grp != last:
                if last is not None:
                    imgui.dummy(imgui.ImVec2(0, 2))
                th.small(grp.upper() if T(grp).isascii() else T(grp))
                last = grp
            selected = k == app.palette_sel
            p = imgui.get_cursor_screen_pos()
            rw = imgui.get_content_region_avail().x
            h = fs * 1.75
            if imgui.selectable(f"##pi{k}", selected, 0, imgui.ImVec2(0, h))[0]:
                run = items[k]
            if imgui.is_item_hovered() and imgui.get_io().mouse_delta.x != 0:
                app.palette_sel = k
            if selected and app.palette_scroll:
                imgui.set_scroll_here_y()
                app.palette_scroll = False
            dl = imgui.get_window_draw_list()
            ty = p.y + (h - fs) / 2
            dl.add_text(imgui.ImVec2(p.x + 6, ty), U("accent" if selected else "text_dim"), icon or "")
            kw = th.chips_width(keys) if keys else 0
            dl.push_clip_rect(p, imgui.ImVec2(p.x + rw - kw - 12, p.y + h), True)
            dl.add_text(imgui.ImVec2(p.x + 30, ty), U("text"), label)
            if sub:
                lw = imgui.calc_text_size(label).x
                dl.add_text(imgui.get_font(), fs * 0.86, imgui.ImVec2(p.x + 30 + lw + 12, ty + fs * 0.08), U("text_dim"), sub)
            dl.pop_clip_rect()
            if keys:
                th.key_chip(dl, imgui.ImVec2(p.x + rw - kw - 4, ty - 1), keys)
        imgui.end_child()
    focused = imgui.is_window_focused(imgui.FocusedFlags_.root_and_child_windows)
    imgui.end()
    if run:
        app.palette_open = False
        if run[0] in ("Commands", "Recent"):
            cid = next((c.id for c in COMMANDS if T(c.label) == run[2]), None)
            if cid:
                app.recent_cmds = [cid] + [r for r in app.recent_cmds if r != cid][:5]
                app.prefs["recent_cmds"] = app.recent_cmds
                th.save_prefs(app.prefs)
        run[-1]()
    elif close or (not focused and not app.palette_focus and app.palette_age > 2):
        app.palette_open = False
    app.palette_age += 1


# ---------------------------------------------------------------- Help (F1)
def help_window(app):
    if not app.show_help:
        anim.fade_in("Help", False)
        return
    vp = imgui.get_main_viewport()
    ts = app.prefs["text_size"]
    w, h = min(760 * ts, vp.work_size.x - 40), vp.work_size.y * 0.78
    pos = app.prefs.get("dlg_pos", {}).get("help")
    imgui.set_next_window_size(imgui.ImVec2(w, h), imgui.Cond_.appearing)
    if pos:
        imgui.set_next_window_pos(imgui.ImVec2(*pos), imgui.Cond_.appearing)
    else:
        imgui.set_next_window_pos(imgui.ImVec2(vp.work_pos.x + vp.work_size.x / 2, vp.work_pos.y + vp.work_size.y / 2),
                                  imgui.Cond_.appearing, imgui.ImVec2(0.5, 0.5))
    imgui.push_style_color(imgui.Col_.window_bg, C("bg"))
    imgui.push_style_color(imgui.Col_.title_bg, C("track"))
    imgui.push_style_color(imgui.Col_.title_bg_active, C("pill"))
    imgui.push_style_var(imgui.StyleVar_.window_rounding, 10.0)
    imgui.push_style_var(imgui.StyleVar_.window_border_size, 1.0)
    imgui.set_next_window_bg_alpha(anim.fade_in("Help", True))
    visible, app.show_help = imgui.begin(f"{T('Help')}###help", True,
                                         imgui.WindowFlags_.no_collapse | imgui.WindowFlags_.no_saved_settings)
    imgui.pop_style_var(2)
    imgui.pop_style_color(3)
    if not visible:
        imgui.end()
        return
    keep_inside(app, "help")
    if imgui.is_window_focused(imgui.FocusedFlags_.root_and_child_windows) and \
            imgui.is_key_pressed(imgui.Key.escape, False) and not imgui.get_io().want_text_input:
        app.show_help = False
    if app.help_focus:
        imgui.set_keyboard_focus_here()
        app.help_focus = False
    imgui.set_next_item_width(-1 if not app.help_q else imgui.get_content_region_avail().x - 30)
    _, app.help_q = imgui.input_text_with_hint("##hq", T("Search"), app.help_q)
    if app.help_q and th.clear_x("hq", "Clear the search"):
        app.help_q = ""
    q = fold(app.help_q)
    tabs = [("concepts", th.ICON_BULB, "Concepts"), ("glossary", th.ICON_BOOK, "Glossary"),
            ("shortcuts", th.ICON_KEYBOARD, "Shortcuts")]
    if imgui.begin_tab_bar("help_tabs"):
        for key, icon, name in tabs:
            flags = imgui.TabItemFlags_.set_selected if app.help_tab_set == key else 0
            if imgui.begin_tab_item(f"{icon}  {T(name)}###h_{key}", None, flags)[0]:
                app.help_tab = key
                imgui.push_style_color(imgui.Col_.child_bg, C("bg", 0.0))
                imgui.begin_child(f"help_{key}", imgui.ImVec2(0, 0))
                imgui.pop_style_color()
                {"concepts": _concepts, "glossary": _glossary, "shortcuts": _shortcuts}[key](app, q)
                imgui.end_child()
                imgui.end_tab_item()
        app.help_tab_set = None
        imgui.end_tab_bar()
    remember_pos(app, "help")
    imgui.end()


def _match(q, *texts):
    return not q or q in fold(" ".join(texts))


def _concepts(app, q):
    shown = 0
    for k, e in enumerate(helptext.concepts()):
        if not _match(q, e["term"], e.get("en", ""), e["text"], e.get("where", "")):
            continue
        shown += 1
        with th.card(f"cc{k}", flags=imgui.ChildFlags_.auto_resize_y):
            imgui.text_colored(C("accent"), e.get("icon", th.ICON_BULB))
            imgui.same_line()
            imgui.text(e["term"])
            imgui.push_text_wrap_pos(0)
            imgui.text_colored(C("text_dim"), e["text"])
            if e.get("where"):
                imgui.text_colored(C("text_dim"), f"{T('Where you see it')}:  {e['where']}")
            imgui.pop_text_wrap_pos()
        imgui.dummy(imgui.ImVec2(0, 2))
    if not shown:
        th.small(T("No results for “{q}”", q=app.help_q))


def _glossary(app, q):
    entries = [e for e in helptext.glossary() if _match(q, e["term"], e.get("en", ""), e["text"])]
    if not entries:
        th.small(T("No results for “{q}”", q=app.help_q))
        return
    with th.card("gloss", flags=imgui.ChildFlags_.auto_resize_y):
        for k, e in enumerate(sorted(entries, key=lambda e: fold(e["term"]))):
            if k:
                imgui.separator()
            imgui.text(e["term"])
            if e.get("en") and e["en"] != e["term"]:
                imgui.same_line()
                th.small(e["en"])
            imgui.push_text_wrap_pos(0)
            imgui.text_colored(C("text_dim"), e["text"])
            imgui.pop_text_wrap_pos()
            if e.get("related"):
                th.small(f"{T('Related')}: {', '.join(e['related'])}")


def _shortcuts(app, q):
    groups = []
    for c in COMMANDS:
        if c.keys and c.group not in groups:
            groups.append(c.group)
    if th.button(f"{th.ICON_COPY}  {T('Copy')}"):
        imgui.set_clipboard_text("\n".join(f"{c.keys:<18} {T(c.label)}" for c in COMMANDS if c.keys))
    for g in groups:
        rows = [c for c in COMMANDS if c.group == g and c.keys and _match(q, T(c.label), c.label, c.keys)]
        if not rows:
            continue
        th.section(T(g))
        with th.card(f"sc_{g}", flags=imgui.ChildFlags_.auto_resize_y, padding=(14, 8)):
            for k, c in enumerate(rows):
                if k:
                    imgui.separator()
                x = imgui.get_cursor_pos_x() + imgui.get_content_region_avail().x
                imgui.align_text_to_frame_padding()
                imgui.text(T(c.label))
                dl = imgui.get_window_draw_list()
                combos = c.keys.split(" / ")
                tw = sum(th.chips_width(k_) for k_ in combos) + 16 * (len(combos) - 1)
                imgui.same_line(x - tw)
                p = imgui.get_cursor_screen_pos()
                for j, combo in enumerate(combos):
                    w_ = th.key_chip(dl, imgui.ImVec2(p.x, p.y + 2), combo)
                    p = imgui.ImVec2(p.x + w_ + (16 if j < len(combos) - 1 else 0), p.y)
                imgui.dummy(imgui.ImVec2(tw, imgui.get_frame_height()))
