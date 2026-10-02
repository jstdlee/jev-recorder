"""Pop-up windows: recorder import, settings, one transcript row, a note, a speaker name, job progress."""
import threading
import urllib.request

from imgui_bundle import imgui

from .. import db
from .. import cohere_asr
from .. import theme as th
from ..theme import C
from . import anim
from .flags import LANG, lang_badge
from .timeline import fmt_offset

TRANSLATE_TARGETS = ["English", "Chinese", "Cantonese", "Malay"]


def _center(width):
    vp = imgui.get_main_viewport()
    # centred every frame (the height is only known after the first frame; no title bar to drag anyway)
    imgui.set_next_window_pos(imgui.ImVec2(vp.work_pos.x + vp.work_size.x / 2, vp.work_pos.y + vp.work_size.y / 2),
                              imgui.Cond_.always, imgui.ImVec2(0.5, 0.5))
    w = min(width, vp.work_size.x - 60)
    imgui.set_next_window_size(imgui.ImVec2(w, 0), imgui.Cond_.always)
    # never taller than the window: long dialogs scroll inside
    imgui.set_next_window_size_constraints(imgui.ImVec2(w, 0), imgui.ImVec2(w, vp.work_size.y * 0.88))


def _begin_modal(name, open_flag, width):
    if open_flag and not imgui.is_popup_open(name):
        imgui.open_popup(name)
    _center(width)
    imgui.push_style_color(imgui.Col_.popup_bg, C("bg"))
    imgui.push_style_var(imgui.StyleVar_.alpha, anim.fade_in(name, imgui.is_popup_open(name)))
    opened, _ = imgui.begin_popup_modal(name, None, imgui.WindowFlags_.no_saved_settings | imgui.WindowFlags_.no_title_bar)
    imgui.pop_style_var()
    imgui.pop_style_color()
    if opened and imgui.is_key_pressed(imgui.Key.escape, False) and not imgui.get_io().want_text_input:
        imgui.close_current_popup()
        imgui.end_popup()
        return None
    return opened


def title(text):
    imgui.push_font(None, imgui.get_style().font_size_base * 1.2)
    imgui.text(text)
    imgui.pop_font()


def row_line(label, value):
    imgui.text(label)
    imgui.same_line(140 * imgui.get_style().font_scale_main)
    th.small(value)


# ------------------------------------------------------------- settings (floating, movable, searchable)
def _settings_rows(app):
    """[(section, title, description, render)] — render(title, desc) draws one Magpie row."""
    prof = app.cfg.llm_profile()
    name = app.cfg.llm.get("default")

    def seg_row(key, options, labels, setter):
        def render(t, d):
            ch, v = setting_row(app, t, d, key, getter[key](), options, labels)
            if ch:
                setter(v)
        return render

    getter = {"theme": lambda: app.prefs["theme"], "size": lambda: app.prefs["text_size"],
              "axis": lambda: app.prefs["axis"], "dspeed": lambda: app.player.speed,
              "dskip": lambda: app.skip_silence, "dsound": lambda: app.player.sound,
              "chunk": lambda: int(prof.get("chunk_chars", 256000)), "overlap": lambda: int(prof.get("overlap_chars", 8000)),
              "tto": lambda: app.prefs["translate_to"], "aeng": lambda: app.cfg.analysis.get("engine", "rules"),
              "asr": lambda: app.cfg.asr.get("engine", "qwen"),
              "rmotion": lambda: bool(app.prefs.get("reduce_motion"))}

    def set_skip(v):
        app.skip_silence = v
        app.set_pref("skip_silence", v)

    def set_sound(v):
        app.player.sound = v
        app.set_pref("sound", v)
        app.player.restart()

    def llm_field(key, hint):
        def render(t, d):
            buf = app.llm_edit.setdefault(key, str(prof.get(key, "") or ""))
            done, buf = text_row(app, t, d, f"llm_{key}", buf, hint)
            app.llm_edit[key] = buf
            if done and buf != str(prof.get(key, "") or ""):
                app.cfg.save_llm(name, {key: buf})
        return render

    def test_row(t, d):
        hl(app, t)
        hl(app, d, small=True)
        if th.button("Test connection"):
            app.llm_test = "Checking…"
            threading.Thread(target=_test_llm, args=(app, dict(prof)), daemon=True).start()
        if app.llm_test:
            imgui.same_line()
            imgui.align_text_to_frame_padding()
            th.small(app.llm_test, "ok" if app.llm_test.startswith("Connected") else
                     "text_dim" if app.llm_test == "Checking…" else "danger")

    def jev_field(key, hint):
        def render(t, d):
            k = "jev_" + key
            buf = app.llm_edit.setdefault(k, str(app.cfg.jev.get(key, "") or ""))
            done, buf = text_row(app, t, d, k, buf, hint)
            app.llm_edit[k] = buf
            if done and buf != str(app.cfg.jev.get(key, "") or ""):
                app.cfg.save_section("jev", {key: buf})
        return render

    def jev_test_row(t, d):
        hl(app, t)
        hl(app, d, small=True)
        if th.button("Test jev"):
            app.jev_test = "Checking…"
            threading.Thread(target=_test_jev, args=(app, dict(app.cfg.jev)), daemon=True).start()
        if app.jev_test:
            imgui.same_line()
            imgui.align_text_to_frame_padding()
            th.small(app.jev_test, "ok" if app.jev_test.startswith("Connected") else
                     "text_dim" if app.jev_test == "Checking…" else "danger")

    def asr_lang_row(t, d):
        buf = app.llm_edit.setdefault("asr_lang", app.cfg.asr.get("language", "auto"))
        done, buf = text_row(app, t, d, "asr_lang", buf, "auto", width=120)
        app.llm_edit["asr_lang"] = buf
        if done:
            v = buf.strip().lower()
            if v == "auto" or v in cohere_asr.LANGS:
                app.cfg.save_section("asr", {"language": v})
            else:
                app.llm_edit["asr_lang"] = app.cfg.asr.get("language", "auto")

    def info_row(text):
        def render(t, d):
            hl(app, t)
            imgui.push_text_wrap_pos(0)
            th.small(text)
            imgui.pop_text_wrap_pos()
        return render

    return [
        ("Appearance", "Theme", "Dark or light; applies at once",
         seg_row("theme", ["Dark", "Light"], None, lambda v: app.set_pref("theme", v))),
        ("Appearance", "Text size", "Everything in the window; Ctrl+ Ctrl– Ctrl+0 too",
         seg_row("size", [1.0, 1.1, 1.25, 1.5], ["100%", "110%", "125%", "150%"], lambda v: app.set_pref("text_size", v))),
        ("Appearance", "Reduce motion", "Move the timeline at once instead of gliding; dialogs still fade",
         seg_row("rmotion", [False, True], ["Off", "On"], lambda v: app.set_pref("reduce_motion", v))),
        ("Appearance", "Time axis", "Label the timeline with the clock, or time since the clip starts",
         seg_row("axis", ["clock", "offset"], ["Clock", "From start"], lambda v: app.set_pref("axis", v))),
        ("Playback", "Speed", "Pitch stays natural at every speed",
         seg_row("dspeed", [1.0, 1.25, 1.5, 2.0, 3.0], ["1×", "1.25×", "1.5×", "2×", "3×"], app.set_speed)),
        ("Playback", "Sound", "Clearer is a live noise filter; Cleaned plays the DeepFilterNet copy",
         seg_row("dsound", ["original", "clearer", "cleaned"], ["Original", "Clearer", "Cleaned"], set_sound)),
        ("Playback", "Skip silence", "Jump over quiet gaps longer than 3 s while playing",
         seg_row("dskip", [False, True], ["Off", "On"], set_skip)),
        ("Summaries and translation", "Server", "Any OpenAI-compatible endpoint", llm_field("base_url", "http://localhost:8888/v1")),
        ("Summaries and translation", "Model", "Name the server expects", llm_field("model", "default")),
        ("Summaries and translation", "API key variable", "Read the key from this environment variable",
         llm_field("api_key_env", "OPENAI_API_KEY")),
        ("Summaries and translation", "Chunk size", "Long transcripts are summarised in parts this long (characters)",
         seg_row("chunk", [32000, 64000, 128000, 256000], ["32k", "64k", "128k", "256k"],
                 lambda v: app.cfg.save_llm(name, {"chunk_chars": v}))),
        ("Summaries and translation", "Overlap", "Each part repeats the end of the previous one, for context",
         seg_row("overlap", [2000, 8000, 16000], ["2k", "8k", "16k"], lambda v: app.cfg.save_llm(name, {"overlap_chars": v}))),
        ("Summaries and translation", "Translate into", "Target language for the translate buttons",
         seg_row("tto", TRANSLATE_TARGETS, None, lambda v: app.set_pref("translate_to", v))),
        ("Summaries and translation", "Connection", "Check that the server answers", test_row),
        ("Transcription", "Speech model", "Used by the next Transcribe; files already done keep their text",
         seg_row("asr", ["qwen", "cohere"], ["Qwen3-ASR", "Cohere Transcribe"],
                 lambda v: app.cfg.save_section("asr", {"engine": v}))),
        ("Transcription", "Cohere language", "auto, or one of " + " ".join(cohere_asr.LANGS)
         + "; auto lets Qwen3-ASR find it and keeps Qwen text for other languages", asr_lang_row),
        ("Analysis", "Engine", "Rules work offline; LLM and jev need their servers",
         seg_row("aeng", ["rules", "llm", "jev", "check"], ["Rules", "LLM", "jev", "LLM + jev"],
                 lambda v: app.cfg.save_section("analysis", {"engine": v}))),
        ("Analysis", "jev server", "Julia-1 /v1/systemone, for relationship scores and checking claims",
         jev_field("url", "http://127.0.0.1:8011")),
        ("Analysis", "jev model", "Model name the jev server expects", jev_field("model", "julia-1")),
        ("Analysis", "jev connection", "Check that jev answers", jev_test_row),
        ("Library", "Folder", "Where recordings, clips and the database live", info_row(str(app.cfg.library))),
        ("Library", "Evidence", "What is never changed",
         info_row("Original recordings and clips are never changed. Notes, translations, names, moments and summaries "
                  "are kept separately in the library database.")),
    ]


def settings(app):
    """A normal floating window: movable, closable, stays above the main window, with a sticky search."""
    if not app.show_settings:
        anim.fade_in("Settings", False)
        return
    vp = imgui.get_main_viewport()
    w = min(720 * app.prefs["text_size"], vp.work_size.x - 60)
    imgui.set_next_window_size(imgui.ImVec2(w, vp.work_size.y * 0.8), imgui.Cond_.appearing)
    imgui.set_next_window_pos(imgui.ImVec2(vp.work_pos.x + vp.work_size.x - w / 2 - 30, vp.work_pos.y + vp.work_size.y / 2),
                              imgui.Cond_.appearing, imgui.ImVec2(0.5, 0.5))
    imgui.push_style_color(imgui.Col_.window_bg, C("bg"))
    imgui.push_style_color(imgui.Col_.title_bg, C("track"))
    imgui.push_style_color(imgui.Col_.title_bg_active, C("pill"))
    imgui.push_style_var(imgui.StyleVar_.window_border_size, 1.0)
    imgui.push_style_var(imgui.StyleVar_.window_rounding, 10.0)
    imgui.set_next_window_bg_alpha(anim.fade_in("Settings", True))
    visible, app.show_settings = imgui.begin("Settings", True, imgui.WindowFlags_.no_collapse
                                             | imgui.WindowFlags_.no_saved_settings)
    imgui.pop_style_var(2)
    imgui.pop_style_color(3)
    if not visible:
        imgui.end()
        return
    if imgui.is_window_focused(imgui.FocusedFlags_.root_and_child_windows) and \
            imgui.is_key_pressed(imgui.Key.escape, False) and not imgui.get_io().want_text_input:
        app.show_settings = False
    # sticky search: stays put while the settings below scroll
    if app.settings_focus:
        imgui.set_keyboard_focus_here()
        app.settings_focus = False
    imgui.set_next_item_width(-1 if not app.settings_query else imgui.get_content_region_avail().x - 30)
    _, app.settings_query = imgui.input_text_with_hint("##sq", "Search settings (Ctrl+P)", app.settings_query)
    if app.settings_query and th.clear_x("sq", "Clear the search"):
        app.settings_query = ""
    q = app.settings_query.strip().lower()
    rows = [r for r in _settings_rows(app) if not q or q in (r[0] + " " + r[1] + " " + r[2]).lower()]
    imgui.push_style_color(imgui.Col_.child_bg, C("bg", 0.0))   # page background; the cards stand out
    imgui.begin_child("settings_body", imgui.ImVec2(0, 0))
    imgui.pop_style_color()
    if not rows:
        imgui.dummy(imgui.ImVec2(0, 10))
        imgui.text_colored(C("text_dim"), f"No setting matches “{app.settings_query}”.")
    sections = []
    for sec, *_ in rows:
        if sec not in sections:
            sections.append(sec)
    for sec in sections:
        th.section(sec)
        with th.card(f"set_{sec}", flags=imgui.ChildFlags_.auto_resize_y):
            first = True
            for s_, t, d, render in rows:
                if s_ != sec:
                    continue
                if not first:
                    imgui.separator()
                first = False
                render(t, d)
    imgui.dummy(imgui.ImVec2(0, 4))
    th.small("Changes are saved as you make them.")
    imgui.end_child()
    imgui.end()


def _test_llm(app, prof):
    try:
        with urllib.request.urlopen(prof["base_url"].rstrip("/") + "/models", timeout=5) as r:
            import json
            ids = [m.get("id") for m in json.loads(r.read()).get("data", [])]
        app.llm_test = f"Connected: {', '.join(ids[:3]) or 'no models listed'}"
    except Exception as e:
        app.llm_test = f"Not reachable: {str(e)[:80]}"


def _test_jev(app, jev):
    try:
        with urllib.request.urlopen(jev["url"].rstrip("/") + "/health", timeout=5) as r:
            r.read()
        app.jev_test = f"Connected to {jev['url']}"
    except Exception as e:
        app.jev_test = f"Not reachable: {str(e)[:80]}"


def hl(app, text, small=False):
    """Text with the settings search match highlighted (yellow wash behind the matched words)."""
    if small:
        imgui.push_font(None, imgui.get_style().font_size_base * 0.88)
    q = app.settings_query.strip().lower()
    p = imgui.get_cursor_screen_pos()
    low = text.lower()
    if q and q in low:
        i = low.index(q)
        x0 = p.x + imgui.calc_text_size(text[:i]).x
        x1 = x0 + imgui.calc_text_size(text[i:i + len(q)]).x
        imgui.get_window_draw_list().add_rect_filled(imgui.ImVec2(x0 - 1, p.y), imgui.ImVec2(x1 + 1, p.y + imgui.get_text_line_height()),
                                                     th.U("match", 0.45), 3.0)
    imgui.text_colored(C("text_dim" if small else "text"), text)
    if small:
        imgui.pop_font()


def setting_row(app, title_, desc, id_, value, options, labels=None):
    """Magpie row: title + one grey line on the left, segmented control on the right."""
    labels = labels or [str(o) for o in options]
    y0 = imgui.get_cursor_pos_y()
    hl(app, title_)
    hl(app, desc, small=True)
    y1 = imgui.get_cursor_pos_y()
    w = th.seg_width(labels)
    imgui.set_cursor_pos(imgui.ImVec2(imgui.get_window_width() - w - 14, y0 + (y1 - y0 - imgui.get_frame_height()) / 2 - 2))
    ch, v = th.seg(id_, value, options, labels)
    imgui.set_cursor_pos(imgui.ImVec2(imgui.get_style().window_padding.x, y1))
    imgui.dummy(imgui.ImVec2(0, 0))
    return ch, v


def text_row(app, title_, desc, id_, buf, hint, width=300):
    """Row with an inline field on the right; returns (finished_editing, text). Saved when you leave the field."""
    y0 = imgui.get_cursor_pos_y()
    hl(app, title_)
    hl(app, desc, small=True)
    y1 = imgui.get_cursor_pos_y()
    w = width * app.prefs["text_size"]
    imgui.set_cursor_pos(imgui.ImVec2(imgui.get_window_width() - w - 14, y0 + (y1 - y0 - imgui.get_frame_height()) / 2 - 2))
    imgui.set_next_item_width(w)
    _, buf = imgui.input_text_with_hint(f"##{id_}", hint, buf)
    done = imgui.is_item_deactivated_after_edit()
    imgui.set_cursor_pos(imgui.ImVec2(imgui.get_style().window_padding.x, y1))
    imgui.dummy(imgui.ImVec2(0, 0))
    return done, buf


# ------------------------------------------------------------- one transcript row
def row_view(app):
    rv = app.row_view
    r = _begin_modal("Row", rv is not None, 760 * app.prefs["text_size"])
    if r is None:
        app.row_view = None
        return
    if not r:
        return
    c, i = rv
    s = c.segments[i]
    t_next = c.segments[i + 1]["_t0"] if i + 1 < len(c.segments) else c.duration
    title(f"{c.speaker(s, i) or 'Speaker'}  ·  {s['abs_start'][11:19]}–{s['abs_end'][11:19]}")
    th.small(f"{fmt_offset(s['_t0'])} into the clip  ·  {s['_t1'] - s['_t0']:.1f} s  ·  row {i + 1} of {len(c.segments)}")
    imgui.dummy(imgui.ImVec2(0, 4))
    with th.card("rv_orig", flags=imgui.ChildFlags_.auto_resize_y):
        lang_badge(s.get("lang"), clickable=False, id_="rvo")
        imgui.same_line()
        th.small(f"Original, {s.get('lang') or 'unknown language'}")
        imgui.push_text_wrap_pos(0)
        imgui.text(s["text"])
        imgui.pop_text_wrap_pos()
    for L, tr in c.translations.items():
        if i in tr:
            with th.card(f"rv_{L}", flags=imgui.ChildFlags_.auto_resize_y):
                lang_badge(L, clickable=False, id_=f"rv{L}")
                imgui.same_line()
                th.small(f"Translation, {L}")
                imgui.push_text_wrap_pos(0)
                imgui.text(tr[i])
                imgui.pop_text_wrap_pos()
    notes = c.notes_in(s["_t0"] if i else 0.0, t_next)
    th.section("Your notes")
    with th.card("rv_notes", flags=imgui.ChildFlags_.auto_resize_y):
        for nt in notes:
            imgui.push_style_color(imgui.Col_.text, C("note"))
            if imgui.selectable(f"{c.abs_at(nt['t']):%H:%M:%S}  {nt['text']}##rvn{nt['id']}", False)[0]:
                app.edit_note(c, nt)
            imgui.pop_style_color()
        if not notes:
            th.small("No notes on this row yet.")
        if th.button("Add a note to this row"):
            app.new_note(c, s["_t0"])
    imgui.dummy(imgui.ImVec2(0, 4))
    if th.primary_button("Play row"):
        app.seek(c, max(0.0, s["_t0"] - 0.2), play=True)
    imgui.same_line()
    if th.button("Repeat row", help_="Loop this row (A–B) until you stop it"):
        app.range_ab = (max(0.0, s["_t0"] - 0.3), min(c.duration, s["_t1"] + 0.3))
        app.loop = True
        app.seek(c, app.range_ab[0], play=True)
    imgui.same_line()
    to = app.prefs["translate_to"]
    if th.button(f"Translate into {to}", disabled=app.job_busy or i in c.translations.get(to, {}),
                 why="Already translated" if i in c.translations.get(to, {}) else "A job is running"):
        app.translate(c, to, rows=[i])
    imgui.same_line()
    if th.button("Copy text"):
        imgui.set_clipboard_text(s["text"] + "".join(f"\n[{L}] {tr[i]}" for L, tr in c.translations.items() if i in tr))
    imgui.same_line()
    if th.button("Close"):
        imgui.close_current_popup()
        app.row_view = None
    imgui.end_popup()


# ------------------------------------------------------------- notes
def note_editor(app):
    ne = app.note_edit
    r = _begin_modal("Note", ne is not None, 560 * app.prefs["text_size"])
    if r is None:
        app.note_edit = None
        return
    if not r:
        return
    c = ne["conv"]
    title("Edit note" if ne.get("id") else "New note")
    th.small(f"At {c.abs_at(ne['t']):%Y-%m-%d %H:%M:%S}  ·  {fmt_offset(ne['t'])} into the clip. "
             "Notes are yours: shown in purple, stored apart from the recording.")
    if ne.pop("focus", False):
        imgui.set_keyboard_focus_here()
    _, ne["text"] = imgui.input_text_multiline("##note", ne["text"], imgui.ImVec2(-1, 110 * app.prefs["text_size"]))
    if th.primary_button("Save", disabled=not ne["text"].strip(), why="Write something first"):
        if ne.get("id"):
            db.update_note(app.con, ne["id"], ne["text"].strip())
        else:
            db.add_note(app.con, c.name, ne["t"], c.abs_at(ne["t"]).isoformat(), ne["text"].strip())
        c.notes = db.notes(app.con, c.name)
        imgui.close_current_popup()
        app.note_edit = None
        app._cache = {}
    imgui.same_line()
    if th.button("Cancel"):
        imgui.close_current_popup()
        app.note_edit = None
    if ne.get("id"):
        imgui.same_line()
        imgui.push_style_color(imgui.Col_.text, C("danger"))
        if imgui.button("Delete note"):
            db.delete_note(app.con, ne["id"])
            c.notes = db.notes(app.con, c.name)
            imgui.close_current_popup()
            app.note_edit = None
            app._cache = {}
        imgui.pop_style_color()
    imgui.end_popup()


# ------------------------------------------------------------- speaker name
def speaker_editor(app):
    se = app.speaker_edit
    r = _begin_modal("Speaker", se is not None, 560 * app.prefs["text_size"])
    if r is None:
        app.speaker_edit = None
        return
    if not r:
        return
    c, k, row = se["conv"], se["speaker"], se.get("row")
    n_rows = len(c.voice_rows(k))
    title(f"Who is {c.default_name(k)}?")
    th.small("Names are kept in the library database; the recording is not changed.")
    if se.pop("focus", False):
        imgui.set_keyboard_focus_here()
    imgui.set_next_item_width(-1)
    enter, se["name"] = imgui.input_text_with_hint("##spk", f"e.g. Mum  (empty = back to {c.default_name(k)})",
                                                   se["name"], imgui.InputTextFlags_.enter_returns_true)
    known = sorted(db.people(app.con))
    if known:
        th.small("People you have named before")
        for j, name in enumerate(known[:24]):
            if j:
                imgui.same_line(0, 4)
                if imgui.get_content_region_avail().x < imgui.calc_text_size(name).x + 24:
                    imgui.new_line()
            if imgui.small_button(f"{name}##p{j}"):
                se["name"] = name
    imgui.dummy(imgui.ImVec2(0, 4))
    if row is not None:
        _, se["scope"] = th.labeled_seg("Change", "scope", se["scope"], ["row", "voice"],
                                        ["Only this row", f"All {n_rows} rows of this voice"],
                                        [f"Just row {row + 1} (e.g. the voice was mixed up here)",
                                         f"Every row labelled {c.default_name(k)} in this conversation"])
    imgui.dummy(imgui.ImVec2(0, 4))
    if th.primary_button("Save") or enter:
        if row is not None and se["scope"] == "row":
            db.set_row_speaker(app.con, c.name, row, se["name"])
        else:
            db.set_speaker_name(app.con, c.name, k, se["name"])
            if row is not None and row in c.row_names and not se["name"].strip():
                db.set_row_speaker(app.con, c.name, row, "")
        c.names = db.speaker_names(app.con, c.name)
        c.row_names = db.row_speakers(app.con, c.name)
        app._cache = {}
        imgui.close_current_popup()
        app.speaker_edit = None
    imgui.same_line()
    if th.button("Cancel"):
        imgui.close_current_popup()
        app.speaker_edit = None
    imgui.end_popup()


# ------------------------------------------------------------- moments
def moment_editor(app):
    me = app.moment_edit
    r = _begin_modal("Moment", me is not None, 520 * app.prefs["text_size"])
    if r is None:
        app.moment_edit = None
        return
    if not r:
        return
    c = me["conv"]
    title("Save this stretch as a moment")
    th.small(f"{c.abs_at(me['a']):%Y-%m-%d %H:%M:%S} – {c.abs_at(me['b']):%H:%M:%S}  ({me['b'] - me['a']:.1f} s). "
             "Listed under Moments on the left.")
    if me.pop("focus", False):
        imgui.set_keyboard_focus_here()
    imgui.set_next_item_width(-1)
    enter, me["label"] = imgui.input_text_with_hint("##ml", "What happens here, e.g. 'promise about the roof'",
                                                    me["label"], imgui.InputTextFlags_.enter_returns_true)
    if th.primary_button("Save", disabled=not me["label"].strip(), why="Give it a short label") or \
            (enter and me["label"].strip()):
        db.add_moment(app.con, c.name, me["a"], me["b"], c.abs_at(me["a"]).isoformat(), c.abs_at(me["b"]).isoformat(),
                      me["label"].strip())
        c.moments = db.moments(app.con, c.name)
        app._cache = {}
        imgui.close_current_popup()
        app.moment_edit = None
    imgui.same_line()
    if th.button("Cancel"):
        imgui.close_current_popup()
        app.moment_edit = None
    imgui.end_popup()


# ------------------------------------------------------------- job progress
def progress(app):
    r = _begin_modal("Progress", app.show_progress, 640 * app.prefs["text_size"])
    if r is None:
        app.show_progress = False
        return
    if not r:
        return
    title(app.job_label or "Background job")
    busy = app.job_busy
    stopped = getattr(app, "job_stopped", False)
    th.small((f"Running for {app.job_elapsed():.0f} s. You can keep listening and taking notes meanwhile."
              if busy else ("Stopped." if stopped else "Failed: see the log below." if app.job_exit else "Finished.")),
             "warn" if stopped and not busy else "danger" if app.job_exit and not busy else "text_dim")
    imgui.dummy(imgui.ImVec2(0, 4))
    files = app.job_files
    overall = app.job_overall()
    overall = app.job_overall_smooth()
    imgui.progress_bar(overall if busy or not app.job_exit else 0.0, imgui.ImVec2(-1, 0),
                       f"Overall  ·  {overall * 100:.0f}%")
    th.section("Conversations")
    with th.card("prog_files", flags=imgui.ChildFlags_.auto_resize_y):
        if not files:
            th.small("Loading models (the first run takes 1-2 minutes)…" if busy else "Nothing to show.")
        for k, name in enumerate(files, 1):
            i = app.job_file[0] if app.job_file else 0
            if k < i or (not busy and not app.job_exit):
                frac, lab = 1.0, "done"
            elif k == i:
                frac, lab = app.job_file_frac(), app.job_stage_label()
            else:
                frac, lab = 0.0, "waiting"
            imgui.text(app.conv_label(name))
            imgui.progress_bar(frac, imgui.ImVec2(-1, 0), lab)
    th.section("Log")
    with th.card("prog_log", imgui.ImVec2(0, 140 * app.prefs["text_size"]), padding=(10, 8)):
        for line in app.proc_log[-60:]:
            th.small(line, "danger" if "rror" in line or "failed" in line else "text_dim")
        if app.job_busy:
            imgui.set_scroll_here_y(1.0)
    if busy:
        imgui.push_style_color(imgui.Col_.text, C("danger"))
        if imgui.button(f"{th.ICON_STOP}  Stop"):
            app.stop_job()
        imgui.pop_style_color()
        th.tip("End this job now. Finished conversations are kept; the current one stays as it was.")
        imgui.same_line()
    if th.button("Hide" if busy else "Close"):
        imgui.close_current_popup()
        app.show_progress = False
    if not busy and app.proc_log:
        imgui.same_line()
        if th.button("Clear"):
            app.proc_log = []
            imgui.close_current_popup()
            app.show_progress = False
    imgui.end_popup()


# ------------------------------------------------------------- recorder import
def import_dialog(app):
    pi = app.pending_import
    r = _begin_modal("Recorder connected", bool(pi and pi.get("open")), 1000)
    if r is None:
        app.pending_import = None
        return
    if not r or not pi:
        if r:
            imgui.end_popup()
        return
    from ..cli import _fmt_dur, _fmt_size, human_flag
    n_all = len(pi["cands"])
    title(f"{n_all} new recording{'s' if n_all != 1 else ''} on the {pi['device'].name}")
    th.small(f"{pi['mount']}  ·  mounted read-only. Nothing is copied until you press Import.")
    imgui.dummy(imgui.ImVec2(0, 2))
    tflags = (imgui.TableFlags_.sizing_stretch_prop | imgui.TableFlags_.borders_inner_h | imgui.TableFlags_.row_bg
              | imgui.TableFlags_.scroll_y)
    rows_h = min(420, 44 * (n_all + 1) + 6)
    if imgui.begin_table("cands", 6, tflags, imgui.ImVec2(-1, rows_h)):
        for name, weight in (("", 0.4), ("File", 3.0), ("Size", 1.0), ("Length", 1.0), ("Start", 2.4), ("Flags", 1.6)):
            imgui.table_setup_column(name, imgui.TableColumnFlags_.width_stretch, weight)
        imgui.table_setup_scroll_freeze(0, 1)
        imgui.table_headers_row()
        for i, cnd in enumerate(pi["cands"]):
            imgui.table_next_row()
            imgui.table_next_column()
            _, pi["checked"][i] = imgui.checkbox(f"##c{i}", pi["checked"][i])
            st = cnd.start
            for v in (cnd.rel.split("/")[-1], _fmt_size(cnd.size), _fmt_dur(cnd.duration),
                      f"{st.start:%Y-%m-%d %H:%M:%S} ({st.confidence})" if st else "?",
                      ", ".join(human_flag(f) for f in st.flags) if st and st.flags else ""):
                imgui.table_next_column()
                imgui.text_wrapped(v)
        imgui.end_table()
    n = sum(pi["checked"])
    size = sum(cnd.size for cnd, k in zip(pi["cands"], pi["checked"]) if k)
    imgui.dummy(imgui.ImVec2(0, 4))
    if not pi.get("done"):
        if th.primary_button(f"Import {n} recording{'s' if n != 1 else ''} ({_fmt_size(size)})",
                             disabled=app.importing or n == 0, why="Tick at least one recording"):
            items = [cnd for cnd, k in zip(pi["cands"], pi["checked"]) if k]
            threading.Thread(target=app.do_import, args=(items, pi["device"], pi["serial"]), daemon=True).start()
            pi["done"] = True
        imgui.same_line()
        if th.button("Skip"):
            app.pending_import = None
            imgui.close_current_popup()
    else:
        if th.primary_button("Transcribe now", disabled=app.importing, why="Still copying"):
            app.start_processing()
            app.pending_import = None
            imgui.close_current_popup()
        imgui.same_line()
        if th.button("Close"):
            app.pending_import = None
            imgui.close_current_popup()
    if app.import_msg:
        th.small(app.import_msg, "danger" if "failed" in app.import_msg else "text_dim")
    imgui.end_popup()
