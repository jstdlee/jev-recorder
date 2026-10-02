"""Transcript table: time · language flag · speaker · text · notes · view.

click = select a row · double-click = jump there and play · flag = switch this row between the
original and its translation · speaker = rename · Open = the row in a window.
"""
from imgui_bundle import imgui

from .. import theme as th
from ..theme import C, U
from .flags import lang_badge
from .timeline import speaker_color


def shown(app, c, i):
    """(text, language) shown for row i: the translation when the row or the view asks for it."""
    s = c.segments[i]
    want = app.row_lang.get((c.name, i), app.view_lang)
    if want and i in c.translations.get(want, {}):
        return c.translations[want][i], want
    return s["text"], s.get("lang")


def draw(app, c):
    if not c.segments:
        imgui.text_colored(C("text_dim"), "Not transcribed yet. Press Transcribe above.")
        return
    spk = sorted({s.get("speaker") for s in c.segments if s.get("speaker")})
    cur = app.player.position() if app.player.conv is c and app.player.playing else None
    ts = app.prefs["text_size"]
    match_set = set(app.match_idx)
    flags = imgui.TableFlags_.row_bg | imgui.TableFlags_.sizing_stretch_prop | imgui.TableFlags_.scroll_y \
        | imgui.TableFlags_.resizable
    if not imgui.begin_table("tr", 6, flags):
        return
    imgui.table_setup_scroll_freeze(0, 1)
    imgui.table_setup_column("Time", imgui.TableColumnFlags_.width_fixed, 64 * ts)
    imgui.table_setup_column("", imgui.TableColumnFlags_.width_fixed, 22 * ts)
    imgui.table_setup_column("By", imgui.TableColumnFlags_.width_fixed, 70 * ts)
    imgui.table_setup_column("Text", imgui.TableColumnFlags_.width_stretch, 3.0)
    imgui.table_setup_column("Notes", imgui.TableColumnFlags_.width_stretch, 1.0)
    imgui.table_setup_column("", imgui.TableColumnFlags_.width_fixed, 46 * ts)
    imgui.table_headers_row()
    n = len(c.segments)
    # notes grouped by row once per frame (not a scan per row)
    notes_by_row = {}
    starts = [x["_t0"] for x in c.segments]
    import bisect
    for nt in c.notes:
        k = max(0, bisect.bisect_right(starts, nt["t"]) - 1)
        notes_by_row.setdefault(k, []).append(nt)
    for i, s in enumerate(c.segments):
        t_next = c.segments[i + 1]["_t0"] if i + 1 < n else c.duration
        imgui.table_next_row()
        imgui.push_id(i)
        active = cur is not None and s["_t0"] <= cur < s["_t1"]
        selected = app.sel_row == (c.name, i)
        if active:
            imgui.table_set_bg_color(imgui.TableBgTarget_.row_bg1, U("playhead", 0.10))
        elif selected:
            imgui.table_set_bg_color(imgui.TableBgTarget_.row_bg1, U("accent", 0.16))
        elif i in match_set:
            imgui.table_set_bg_color(imgui.TableBgTarget_.row_bg1, U("match", 0.14))
        # time: the whole row is one selectable spanning all columns
        imgui.table_next_column()
        imgui.push_style_color(imgui.Col_.text, C("text_dim"))
        clicked = imgui.selectable(f"{s['abs_start'][11:19]}##row", selected,
                                   imgui.SelectableFlags_.span_all_columns | imgui.SelectableFlags_.allow_overlap
                                   | imgui.SelectableFlags_.allow_double_click)[0]
        imgui.pop_style_color()
        if clicked:
            app.sel_row = (c.name, i)
            if imgui.is_mouse_double_clicked(0):
                app.seek(c, max(0.0, s["_t0"] - 0.2), play=True)
        # language flag of what is shown; click toggles original / translation
        text, lang = shown(app, c, i)
        imgui.table_next_column()
        if lang_badge(lang, id_=str(i)):
            app.toggle_row_lang(c, i)
        has_tr = [L for L in c.translations if i in c.translations[L]]
        th.tip(f"{lang or 'unknown'}" + (" (translation). Click: show the original" if lang != s.get("lang")
                                           else (f". Click: show {app.prefs['translate_to']}" if has_tr
                                                 else f". Click: translate into {app.prefs['translate_to']}")))
        # by: who is speaking (click to name them; this row only, or every row of this voice)
        imgui.table_next_column()
        if s.get("speaker"):
            k = spk.index(s["speaker"])
            imgui.push_style_color(imgui.Col_.text, imgui.color_convert_u32_to_float4(speaker_color(k, 1.0)))
            name = c.speaker(s, i)
            if imgui.selectable(f"{name}{' •' if i in c.row_names else ''}##spk", False,
                                imgui.SelectableFlags_.allow_overlap)[0]:
                app.rename_speaker(c, s["speaker"], i)
            imgui.pop_style_color()
            th.tip(f"Name who is speaking ({s['speaker']}). • = named for this row only")
        # text
        imgui.table_next_column()
        if lang != s.get("lang"):
            imgui.text_colored(C("text"), text)
        else:
            imgui.text_wrapped(text)
        # notes inside this row's stretch of time, wrapped, in purple (click one to edit)
        imgui.table_next_column()
        for nt in notes_by_row.get(i, ()):
            imgui.push_style_color(imgui.Col_.text, C("note"))
            imgui.push_text_wrap_pos(0)
            imgui.text_wrapped(nt["text"])
            imgui.pop_text_wrap_pos()
            imgui.pop_style_color()
            if imgui.is_item_clicked():
                app.edit_note(c, nt)
            th.tip(f"Your note at {c.abs_at(nt['t']):%H:%M:%S}. Click to edit")
        # icons: add a note, open the row
        imgui.table_next_column()
        imgui.push_style_color(imgui.Col_.button, C("track", 0.0))
        imgui.push_style_color(imgui.Col_.text, C("note"))
        if imgui.small_button(f"{th.ICON_NOTE}##addnote"):
            app.new_note(c, s["_t0"])
        imgui.pop_style_color()
        th.tip("Add a note to this row (M adds one at the playhead)")
        imgui.same_line(0, 6)
        imgui.push_style_color(imgui.Col_.text, C("text_dim"))
        if imgui.small_button(f"{th.ICON_OPEN}##open"):
            app.open_row(c, i)
        imgui.pop_style_color(2)
        th.tip("Open this row: full text, translation, notes, repeat")
        if (active and app.follow) or (app.scroll_to_t is not None and s["_t0"] <= app.scroll_to_t < t_next):
            imgui.set_scroll_here_y(0.35)
            if not active:
                app.scroll_to_t = None
        imgui.pop_id()
    imgui.end_table()
