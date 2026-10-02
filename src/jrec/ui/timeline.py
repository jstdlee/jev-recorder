"""The timeline: waveform on a real clock, padding shaded, speaker lanes, notes (purple), search
matches (yellow), an A–B range to repeat, playhead, ticks down to single seconds, and a minimap.

  click = seek · double-click = play from there · drag = pan · wheel = zoom at the pointer
  shift+drag = select a range (A–B) · drag an A/B edge = move it · drag the band's top strip = move
  the whole range · right-click = add note / set A or B / play from here
"""
from datetime import timedelta

from imgui_bundle import imgui

from .. import theme as th
from ..theme import C, U
from .data import PEAK_HZ

SPEAKER_COLORS = ["#4a9eff", "#ff9f40", "#5ccf6a", "#d77be0", "#f2d14b", "#5cc8d6", "#b0b0b0", "#ff6b78"]
STEPS = (1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200)
MINOR = {1: 0.2, 2: 0.5, 5: 1, 10: 2, 15: 5, 30: 5, 60: 10, 120: 30, 300: 60, 600: 120, 900: 300,
         1800: 300, 3600: 600, 7200: 1800}


def speaker_color(i, a=0.9):
    return U("text") if i < 0 else th.imgui.get_color_u32(th.hexc(SPEAKER_COLORS[i % len(SPEAKER_COLORS)], a))


def fmt_offset(sec, sign=False):
    s = int(round(abs(sec)))
    txt = f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"
    return (("-" if sec < 0 else "+") if sign else ("-" if sec < 0 else "")) + txt


def clamp_view(a, b, total):
    span = min(total, max(2.0, b - a))
    a = max(0.0, min(total - span, a))
    return a, a + span


def draw(app, c):
    st = imgui.get_style()
    ts = app.prefs["text_size"]
    w = imgui.get_content_region_avail().x
    h_wave, h_lane, h_notes, h_axis = 110 * ts, 26 * ts, 14 * ts, 22 * ts
    h = h_wave + h_lane + h_notes + h_axis
    p0 = imgui.get_cursor_screen_pos()
    imgui.invisible_button("timeline", imgui.ImVec2(w, h), imgui.ButtonFlags_.mouse_button_left
                           | imgui.ButtonFlags_.mouse_button_right)
    hovered = imgui.is_item_hovered()
    dl = imgui.get_window_draw_list()
    v0, v1 = app.view
    span = max(1e-3, v1 - v0)
    x_of = lambda t: p0.x + (t - v0) / span * w
    t_of = lambda x: v0 + (x - p0.x) / w * span
    clipx = lambda x: max(p0.x, min(p0.x + w, x))
    wave_top, wave_bot = p0.y, p0.y + h_wave

    # background, padding shade, A–B range
    dl.add_rect_filled(p0, imgui.ImVec2(p0.x + w, wave_bot), U("track"), 6.0)
    for a, b in ((0.0, c.sp0), (c.sp1, c.duration)):
        if b > v0 and a < v1:
            dl.add_rect_filled(imgui.ImVec2(clipx(x_of(a)), wave_top), imgui.ImVec2(clipx(x_of(b)), wave_bot),
                               U("pad_shade", 0.85))
    if app.range_ab:
        a, b = app.range_ab
        dl.add_rect_filled(imgui.ImVec2(clipx(x_of(a)), wave_top), imgui.ImVec2(clipx(x_of(b)), wave_bot + h_lane),
                           U("accent", 0.20))
        dl.add_rect_filled(imgui.ImVec2(clipx(x_of(a)), wave_top), imgui.ImVec2(clipx(x_of(b)), wave_top + 18 * ts),
                           U("accent", 0.22))
        for t, lab in ((a, "A"), (b, "B")):
            if v0 <= t <= v1:
                dl.add_line(imgui.ImVec2(x_of(t), wave_top), imgui.ImVec2(x_of(t), wave_bot + h_lane), U("accent"), 1.5)
                dl.add_text(imgui.ImVec2(x_of(t) + 3, wave_top + 2), U("accent"), lab)

    # waveform
    if c.peaks is not None:
        mins, maxs = c.peaks
        mid, amp, g = (wave_top + wave_bot) / 2, (h_wave / 2 - 4) * c.gain, c.gain
        col = U("wave")
        n = len(mins)
        for px in range(int(w)):
            a = int((v0 + px / w * span) * PEAK_HZ)
            b = max(a + 1, int((v0 + (px + 1) / w * span) * PEAK_HZ))
            if a >= n:
                break
            lo = max(-1.0, float(mins[a:b].min()) * g) / g
            hi = min(1.0, float(maxs[a:b].max()) * g) / g
            dl.add_line(imgui.ImVec2(p0.x + px, mid - hi * amp), imgui.ImVec2(p0.x + px, mid - lo * amp + 1), col)
    else:
        dl.add_text(imgui.ImVec2(p0.x + 10, wave_top + 8), U("text_dim"), "Drawing the waveform…")

    # search matches: yellow marks over the wave
    for i in app.match_idx:
        s = c.segments[i]
        if s["_t1"] >= v0 and s["_t0"] <= v1:
            x0, x1 = clipx(x_of(s["_t0"])), clipx(max(x_of(s["_t1"]), x_of(s["_t0"]) + 2))
            cur = app.match_pos is not None and app.match_idx[app.match_pos] == i
            dl.add_rect_filled(imgui.ImVec2(x0, wave_top), imgui.ImVec2(x1, wave_top + 5), U("match"))
            dl.add_rect_filled(imgui.ImVec2(x0, wave_top), imgui.ImVec2(x1, wave_bot), U("match", 0.28 if cur else 0.12))

    # speaker lanes
    ly = wave_bot + 3
    spk = sorted({s.get("speaker") for s in c.segments if s.get("speaker")})
    lane_h = (h_lane - 6) / max(1, len(spk))
    for s in c.segments:
        if s["_t1"] < v0 or s["_t0"] > v1:
            continue
        i = spk.index(s["speaker"]) if s.get("speaker") in spk else 0
        y = ly + i * lane_h
        dl.add_rect_filled(imgui.ImVec2(clipx(x_of(s["_t0"])), y),
                           imgui.ImVec2(clipx(max(x_of(s["_t1"]), x_of(s["_t0"]) + 1)), y + max(2.0, lane_h - 1)),
                           speaker_color(i), 1.5)

    # notes strip: purple diamonds
    ny = wave_bot + h_lane + h_notes / 2
    note_hover = None
    for n in c.notes:
        if v0 <= n["t"] <= v1:
            x = x_of(n["t"])
            r = h_notes * 0.38
            dl.add_quad_filled(imgui.ImVec2(x, ny - r), imgui.ImVec2(x + r, ny), imgui.ImVec2(x, ny + r),
                               imgui.ImVec2(x - r, ny), U("note"))
            dl.add_line(imgui.ImVec2(x, wave_top), imgui.ImVec2(x, ny - r), U("note", 0.45), 1.0)
            mp = imgui.get_io().mouse_pos
            if hovered and abs(mp.x - x) <= r + 2 and abs(mp.y - ny) <= r + 3:
                note_hover = n

    # axis: major ticks with labels, minor ticks
    ay = wave_bot + h_lane + h_notes
    step = next((s for s in STEPS if span / s <= max(4, w / (110 * ts))), STEPS[-1])
    minor = MINOR[step]
    base = c.start.timestamp() if app.prefs.get("axis", "clock") == "clock" else 0.0
    k = int((base + v0) // minor + 1)
    while (tt := k * minor - base) <= v1:
        x = x_of(tt)
        major = abs((k * minor) / step - round((k * minor) / step)) < 1e-6
        dl.add_line(imgui.ImVec2(x, ay), imgui.ImVec2(x, ay + (6 if major else 3)), U("text_dim", 1.0 if major else 0.6))
        if major:
            if app.prefs.get("axis", "clock") == "clock":
                lab = c.abs_at(tt).strftime("%H:%M:%S" if step < 60 else "%H:%M")
            else:
                lab = fmt_offset(tt)
            if x + 3 + imgui.calc_text_size(lab).x <= p0.x + w:
                dl.add_text(imgui.ImVec2(x + 3, ay + 4), U("text_dim"), lab)
        k += 1

    # playhead (with skip-silence and A–B loop handled while playing)
    pos = app.player.position() if app.player.conv is c else None
    if pos is not None:
        pos = app.on_playhead(c, pos)
    if pos is not None:
        app.cursor = pos
        if app.follow and not (v0 <= pos <= v1):
            app.view = clamp_view(pos - span * 0.1, pos + span * 0.9, c.duration)
    cx = x_of(app.cursor)
    if p0.x <= cx <= p0.x + w:
        dl.add_line(imgui.ImVec2(cx, wave_top), imgui.ImVec2(cx, ay), U("playhead"), 2)
        dl.add_triangle_filled(imgui.ImVec2(cx - 5, wave_top), imgui.ImVec2(cx + 5, wave_top), imgui.ImVec2(cx, wave_top + 6),
                               U("playhead"))

    # interaction
    io = imgui.get_io()
    if hovered:
        mx = io.mouse_pos.x
        t_m = max(0.0, min(c.duration, t_of(mx)))
        if note_hover:
            imgui.set_tooltip(f"Note at {c.abs_at(note_hover['t']):%H:%M:%S}\n{note_hover['text']}")
        else:
            rel = f"  ·  {fmt_offset(t_m - app.cursor, True)} from the playhead" if abs(t_m - app.cursor) > 0.5 else ""
            imgui.set_tooltip(f"{c.abs_at(t_m):%H:%M:%S}  ·  {fmt_offset(t_m)} into the clip{rel}")
        if io.mouse_wheel:
            f = 0.8 if io.mouse_wheel > 0 else 1.25
            ns = min(c.duration, max(4.0, span * f))
            a = t_m - (mx - p0.x) / w * ns
            app.view = clamp_view(a, a + ns, c.duration)
        grab = None
        if app.range_ab and not io.key_shift:
            ra, rb = app.range_ab
            if abs(mx - x_of(ra)) <= 6:
                grab = "a"
            elif abs(mx - x_of(rb)) <= 6:
                grab = "b"
            elif x_of(ra) < mx < x_of(rb) and io.mouse_pos.y <= wave_top + 18 * ts:
                grab = "band"
        if grab in ("a", "b"):
            imgui.set_mouse_cursor(imgui.MouseCursor_.resize_ew)
        elif grab == "band":
            imgui.set_mouse_cursor(imgui.MouseCursor_.resize_all)
        if imgui.is_mouse_double_clicked(0) and not grab:
            app.seek(c, t_m, play=True)
            app.drag = None
        elif imgui.is_mouse_clicked(0):
            app.drag = {"x": mx, "view": app.view, "t": t_m, "select": io.key_shift, "grab": grab,
                        "range": app.range_ab}
        if imgui.is_mouse_clicked(1):
            app.ctx_t = t_m
            app.ctx_note = note_hover
            imgui.open_popup("timeline_ctx")
    d = app.drag
    if d and imgui.is_mouse_down(0):
        mx = io.mouse_pos.x
        t2 = max(0.0, min(c.duration, t_of(mx)))
        if d.get("grab") in ("a", "b"):
            ra, rb = d["range"]
            na, nb = (t2, rb) if d["grab"] == "a" else (ra, t2)
            app.range_ab = (min(na, nb), max(na, nb))
        elif d.get("grab") == "band":
            ra, rb = d["range"]
            shift = t2 - d["t"]
            shift = max(-ra, min(c.duration - rb, shift))
            app.range_ab = (ra + shift, rb + shift)
        elif d["select"]:
            t2 = max(0.0, min(c.duration, t_of(mx)))
            if abs(mx - d["x"]) > 3:
                app.range_ab = (min(d["t"], t2), max(d["t"], t2))
        elif abs(mx - d["x"]) > 3:
            a, b = d["view"]
            dt = (mx - d["x"]) / w * (b - a)
            app.view = clamp_view(a - dt, b - dt, c.duration)
    if d and imgui.is_mouse_released(0):
        if abs(io.mouse_pos.x - d["x"]) <= 3 and hovered and not d.get("grab"):
            if note_hover:
                app.edit_note(c, note_hover)
            else:
                app.seek(c, max(0.0, min(c.duration, t_of(io.mouse_pos.x))))
        app.drag = None
    context_menu(app, c)

    # minimap: the whole clip, with the visible window
    mh = 16 * ts
    imgui.dummy(imgui.ImVec2(0, 2))
    m0 = imgui.get_cursor_screen_pos()
    imgui.invisible_button("minimap", imgui.ImVec2(w, mh))
    mx_of = lambda t: m0.x + t / max(1e-3, c.duration) * w
    dl.add_rect_filled(m0, imgui.ImVec2(m0.x + w, m0.y + mh), U("track"), 4.0)
    dl.add_rect_filled(imgui.ImVec2(mx_of(c.sp0), m0.y + 3), imgui.ImVec2(mx_of(c.sp1), m0.y + mh - 3), U("wave", 0.55), 2.0)
    for n in c.notes:
        dl.add_line(imgui.ImVec2(mx_of(n["t"]), m0.y), imgui.ImVec2(mx_of(n["t"]), m0.y + mh), U("note"), 1.5)
    for i in app.match_idx:
        x = mx_of(c.segments[i]["_t0"])
        dl.add_line(imgui.ImVec2(x, m0.y), imgui.ImVec2(x, m0.y + 4), U("match"), 2.0)
    dl.add_rect(imgui.ImVec2(mx_of(v0), m0.y), imgui.ImVec2(max(mx_of(v1), mx_of(v0) + 3), m0.y + mh), U("text"), 4.0, 1.5)
    dl.add_line(imgui.ImVec2(mx_of(app.cursor), m0.y), imgui.ImVec2(mx_of(app.cursor), m0.y + mh), U("playhead"), 1.5)
    if imgui.is_item_active():
        t = (io.mouse_pos.x - m0.x) / w * c.duration
        app.view = clamp_view(t - span / 2, t + span / 2, c.duration)
    th.tip("Whole clip: drag to move the view")


def context_menu(app, c):
    if imgui.begin_popup("timeline_ctx"):
        t = app.ctx_t
        th.small(f"{c.abs_at(t):%H:%M:%S}  ·  {fmt_offset(t)} into the clip")
        imgui.separator()
        if imgui.menu_item("Play from here", "", False)[0]:
            app.seek(c, t, play=True)
        if imgui.menu_item("Add note here…", "M", False)[0]:
            app.new_note(c, t)
        if app.ctx_note and imgui.menu_item("Edit this note…", "", False)[0]:
            app.edit_note(c, app.ctx_note)
        imgui.separator()
        if imgui.menu_item("Set A here", "[", False)[0]:
            app.set_a(t)
        if imgui.menu_item("Set B here", "]", False)[0]:
            app.set_b(t)
        if app.range_ab and imgui.menu_item("Clear A–B", "Esc", False)[0]:
            app.range_ab = None
        imgui.end_popup()
