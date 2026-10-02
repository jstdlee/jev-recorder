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


def fit(text, width):
    """One line that fits `width`, ending in … when cut (binary search, visible rows only)."""
    text = text.replace("\n", " ")
    if imgui.calc_text_size(text).x <= width:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if imgui.calc_text_size(text[:mid] + "…").x <= width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + "…"


def draw(app, c):
    if not c.segments:
        imgui.text_colored(C("text_dim"), "Not transcribed yet. Press Transcribe above.")
        return
    if app.prefs.get("rows", "line") == "line":
        return draw_lines(app, c)
    return draw_wrapped(app, c)


def draw_lines(app, c):
    """One line per row, fixed height: the whole row highlights as one block, and only the rows on
    screen are drawn (fast for long recordings). The selected row is shown in full in Preview."""
    spk = sorted({s.get("speaker") for s in c.segments if s.get("speaker")})
    playing = app.player.conv is c and app.player.playing
    cur = app.player.position() if playing else None
    ts = app.prefs["text_size"]
    match_set = set(app.match_idx)
    from .insights import important_rows
    important = important_rows(c)
    notes_by_row = _notes_by_row(c)
    flags = imgui.TableFlags_.row_bg | imgui.TableFlags_.sizing_stretch_prop | imgui.TableFlags_.scroll_y \
        | imgui.TableFlags_.resizable
    if not imgui.begin_table("trl", 6, flags):
        return
    imgui.table_setup_scroll_freeze(0, 1)
    imgui.table_setup_column("Time", imgui.TableColumnFlags_.width_fixed, 64 * ts)
    imgui.table_setup_column("", imgui.TableColumnFlags_.width_fixed, 22 * ts)
    imgui.table_setup_column("By", imgui.TableColumnFlags_.width_fixed, 70 * ts)
    imgui.table_setup_column("Text", imgui.TableColumnFlags_.width_stretch, 4.0)
    imgui.table_setup_column("Notes", imgui.TableColumnFlags_.width_stretch, 1.0)
    imgui.table_setup_column("", imgui.TableColumnFlags_.width_fixed, 62 * ts)
    imgui.table_headers_row()
    row_h = imgui.get_frame_height() + 2
    n = len(c.segments)
    # keep the playing row, or a jumped-to row, in view (direct scroll: the list can be long)
    want = None
    if cur is not None and app.follow:
        want = c.seg_at(cur)
    if app.scroll_to_t is not None:
        want = max(0, min(n - 1, next((i for i, s in enumerate(c.segments) if s["_t1"] > app.scroll_to_t), n - 1)))
        app.scroll_to_t = None
    if want is not None:
        top, view_h = imgui.get_scroll_y(), imgui.get_window_height() - row_h * 2
        y = want * row_h
        if y < top or y > top + view_h:
            imgui.set_scroll_y(max(0.0, y - view_h * 0.35))
    clipper = imgui.ListClipper()
    clipper.begin(n, row_h)
    active_i = c.seg_at(cur) if cur is not None else None
    while clipper.step():
        for i in range(clipper.display_start, clipper.display_end):
            s = c.segments[i]
            imgui.table_next_row(0, row_h)
            imgui.push_id(i)
            selected = app.sel_row == (c.name, i)
            if i == active_i:
                imgui.table_set_bg_color(imgui.TableBgTarget_.row_bg1, U("playhead", 0.10))
            elif i in match_set and not selected:
                imgui.table_set_bg_color(imgui.TableBgTarget_.row_bg1, U("match", 0.14))
            imgui.table_next_column()
            imgui.push_style_color(imgui.Col_.text, C("text_dim"))
            clicked = imgui.selectable(f"{s['abs_start'][11:19]}##row", selected,
                                       imgui.SelectableFlags_.span_all_columns | imgui.SelectableFlags_.allow_overlap
                                       | imgui.SelectableFlags_.allow_double_click, imgui.ImVec2(0, row_h - 4))[0]
            imgui.pop_style_color()
            if clicked:
                app.sel_row = (c.name, i)
                if imgui.is_mouse_double_clicked(0):
                    app.seek(c, max(0.0, s["_t0"] - 0.2), play=True)
                else:
                    app.cursor = s["_t0"]          # click = select and put the playhead there (no scrolling)
            text, lang = shown(app, c, i)
            imgui.table_next_column()
            if lang_badge(lang, id_=str(i)):
                app.toggle_row_lang(c, i)
            th.tip(f"{lang or 'unknown'}: click to switch original / translation")
            imgui.table_next_column()
            if s.get("speaker"):
                k = spk.index(s["speaker"])
                imgui.push_style_color(imgui.Col_.text, imgui.color_convert_u32_to_float4(speaker_color(k, 1.0)))
                name = c.speaker(s, i)
                if imgui.selectable(f"{name}{' •' if i in c.row_names else ''}##spk", False,
                                    imgui.SelectableFlags_.allow_overlap)[0]:
                    app.rename_speaker(c, s["speaker"], i)
                imgui.pop_style_color()
                th.tip(f"Name who is speaking ({s['speaker']})")
            imgui.table_next_column()
            w = imgui.get_content_region_avail().x
            if i in important:
                imgui.text_colored(C("match"), th.ICON_STAR)
                th.tip(f"Important: {important[i]}")
                imgui.same_line(0, 6)
                w -= imgui.get_font_size() + 6
            imgui.text(fit(text, w))
            if imgui.is_item_hovered(imgui.HoveredFlags_.delay_normal) and imgui.calc_text_size(text).x > w:
                imgui.set_tooltip(text[:600])
            imgui.table_next_column()
            notes = notes_by_row.get(i, ())
            if notes:
                imgui.push_style_color(imgui.Col_.text, C("note"))
                imgui.text(fit((f"({len(notes)}) " if len(notes) > 1 else "") + notes[0]["text"],
                               imgui.get_content_region_avail().x))
                imgui.pop_style_color()
                if imgui.is_item_clicked():
                    app.edit_note(c, notes[0])
                th.tip("\n".join(f"{c.abs_at(nt['t']):%H:%M:%S}  {nt['text']}" for nt in notes))
            imgui.table_next_column()
            _row_icons(app, c, i, s)
            imgui.pop_id()
    imgui.end_table()


def _notes_by_row(c):
    import bisect
    out, starts = {}, [x["_t0"] for x in c.segments]
    for nt in c.notes:
        out.setdefault(max(0, bisect.bisect_right(starts, nt["t"]) - 1), []).append(nt)
    return out


def _row_icons(app, c, i, s):
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
    th.tip("Open this row in a window")


def draw_wrapped(app, c):
    spk = sorted({s.get("speaker") for s in c.segments if s.get("speaker")})
    cur = app.player.position() if app.player.conv is c and app.player.playing else None
    ts = app.prefs["text_size"]
    match_set = set(app.match_idx)
    from .insights import important_rows
    important = important_rows(c)
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
    imgui.table_setup_column("", imgui.TableColumnFlags_.width_fixed, 62 * ts)
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
        # text (★ = marked important by the analysis)
        imgui.table_next_column()
        if i in important:
            imgui.text_colored(C("match"), th.ICON_STAR)
            th.tip(f"Important: {important[i]}")
            imgui.same_line(0, 6)
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
