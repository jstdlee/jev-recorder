"""Look and feel: Magpie layout + native macOS tokens (polish-ui skill), for Dear ImGui.

Soft page, rounded cards, tiny caps section titles, segmented pills for choices, the
accent colour only where something is selected, focused or primary.
"""
import json
from contextlib import contextmanager
from pathlib import Path

from imgui_bundle import imgui

PREFS_PATH = Path("~/.config/jrec/ui.json").expanduser()
DEFAULT_PREFS = {"theme": "Dark", "text_size": 1.0, "speed": 1.0, "skip_silence": True, "follow": True}


def hexc(h, a=1.0):
    h = h.lstrip("#")
    return imgui.ImVec4(int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255, a)


TOKENS = {
    "Dark": {"bg": "#1c1c1f", "card": "#252528", "card_border": "#303034", "divider": "#2c2c30", "text": "#e8e8ec",
             "text_dim": "#8e8e96", "track": "#2e2e33", "pill": "#3a3a40", "pill_border": "#45454b",
             "accent": "#0a84ff", "danger": "#ff453a", "warn": "#ff9f0a", "ok": "#30d158",
             "wave": "#64a8ff", "pad_shade": "#1f1f22", "playhead": "#ffd60a"},
    "Light": {"bg": "#f4f4f6", "card": "#ffffff", "card_border": "#e3e3e8", "divider": "#ececf0", "text": "#212126",
              "text_dim": "#737379", "track": "#f1f1f4", "pill": "#ffffff", "pill_border": "#e3e3e8",
              "accent": "#007aff", "danger": "#ff3b30", "warn": "#c93400", "ok": "#248a3d",
              "wave": "#2f7de1", "pad_shade": "#ebebef", "playhead": "#e08600"},
}

T = dict(TOKENS["Dark"])   # current tokens as hex; C(name) -> ImVec4


def C(name, a=1.0):
    return hexc(T[name], a)


def U(name, a=1.0):
    return imgui.get_color_u32(C(name, a))


def load_prefs():
    try:
        return {**DEFAULT_PREFS, **json.loads(PREFS_PATH.read_text())}
    except (OSError, ValueError):
        return dict(DEFAULT_PREFS)


def save_prefs(p):
    try:
        PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        PREFS_PATH.write_text(json.dumps(p, indent=1))
    except OSError:
        pass


def apply(theme="Dark", text_size=1.0):
    T.clear()
    T.update(TOKENS.get(theme, TOKENS["Dark"]))
    st = imgui.get_style()
    st.window_rounding, st.child_rounding, st.frame_rounding = 0, 10, 6
    st.popup_rounding, st.grab_rounding, st.scrollbar_rounding = 10, 6, 6
    st.window_border_size, st.child_border_size, st.frame_border_size, st.popup_border_size = 0, 1, 0, 1
    st.window_padding = imgui.ImVec2(16, 14)
    st.frame_padding = imgui.ImVec2(10, 4)
    st.item_spacing = imgui.ImVec2(8, 8)
    st.item_inner_spacing = imgui.ImVec2(6, 4)
    st.cell_padding = imgui.ImVec2(8, 5)
    st.scrollbar_size = 10
    st.selectable_text_align = imgui.ImVec2(0, 0.5)
    st.font_scale_main = text_size
    col = imgui.Col_
    for k, v in {
        col.window_bg: C("bg"), col.child_bg: C("card"), col.popup_bg: C("card"), col.border: C("card_border"),
        col.text: C("text"), col.text_disabled: C("text_dim"),
        col.frame_bg: C("track"), col.frame_bg_hovered: C("pill"), col.frame_bg_active: C("pill"),
        col.button: C("track"), col.button_hovered: C("pill"), col.button_active: C("pill_border"),
        col.header: C("accent", 0.22), col.header_hovered: C("track"), col.header_active: C("accent", 0.30),
        col.check_mark: C("accent"), col.slider_grab: C("accent"), col.slider_grab_active: C("accent"),
        col.plot_histogram: C("accent"), col.separator: C("divider"),
        col.scrollbar_bg: C("card", 0.0), col.scrollbar_grab: C("track"), col.scrollbar_grab_hovered: C("pill_border"),
        col.scrollbar_grab_active: C("pill_border"),
        col.table_header_bg: C("card"), col.table_row_bg: C("card", 0.0), col.table_row_bg_alt: C("track", 0.45),
        col.table_border_light: C("divider"), col.table_border_strong: C("card_border"),
        col.nav_cursor: C("accent", 0.5), col.text_selected_bg: C("accent", 0.35),
        col.modal_window_dim_bg: hexc("#000000", 0.35), col.title_bg: C("bg"), col.title_bg_active: C("bg"),
    }.items():
        st.set_color_(k, v)


# ---------------------------------------------------------------- helpers
def tip(text):
    if imgui.is_item_hovered(imgui.HoveredFlags_.delay_short | imgui.HoveredFlags_.allow_when_disabled):
        imgui.set_tooltip(text)


def section(title):
    """Tiny grey ALL CAPS section title."""
    imgui.push_font(None, imgui.get_style().font_size_base * 0.80)
    imgui.text_colored(C("text_dim"), title.upper())
    imgui.pop_font()


def small(text, color="text_dim"):
    imgui.push_font(None, imgui.get_style().font_size_base * 0.88)
    imgui.text_colored(C(color), text)
    imgui.pop_font()


@contextmanager
def card(id_, size=imgui.ImVec2(0, 0), padding=(14, 12), flags=0):
    imgui.push_style_var(imgui.StyleVar_.window_padding, imgui.ImVec2(*padding))
    imgui.begin_child(id_, size, imgui.ChildFlags_.borders | imgui.ChildFlags_.always_use_window_padding | flags)
    try:
        yield
    finally:
        imgui.end_child()
        imgui.pop_style_var()


def seg_width(labels):
    return 4 + sum(imgui.calc_text_size(l).x + 22 for l in labels)


def seg(id_, value, options, labels=None, tips=None):
    """Segmented control: all options visible, the chosen one is a raised pill. Returns (changed, value)."""
    labels = labels or [str(o) for o in options]
    dl = imgui.get_window_draw_list()
    p = imgui.get_cursor_screen_pos()
    h = imgui.get_frame_height()
    w = seg_width(labels)
    dl.add_rect_filled(p, imgui.ImVec2(p.x + w, p.y + h), U("track"), 7.0)
    changed, x = False, p.x + 2
    imgui.push_id(id_)
    for i, (opt, lab) in enumerate(zip(options, labels)):
        iw = imgui.calc_text_size(lab).x + 22
        imgui.set_cursor_screen_pos(imgui.ImVec2(x, p.y))
        imgui.push_id(i)
        if imgui.invisible_button("##s", imgui.ImVec2(iw, h)) and value != opt:
            value, changed = opt, True
        hov, held = imgui.is_item_hovered(), imgui.is_item_active()
        if tips:
            tip(tips[i])
        imgui.pop_id()
        a, b = imgui.ImVec2(x, p.y + 2), imgui.ImVec2(x + iw, p.y + h - 2)
        on = value == opt
        if on:
            dl.add_rect_filled(a, b, U("pill"), 6.0)
            dl.add_rect(a, b, U("pill_border"), 6.0)
        elif held:
            dl.add_rect_filled(a, b, U("pill_border", 0.6), 6.0)
        ts = imgui.calc_text_size(lab)
        dl.add_text(imgui.ImVec2(x + (iw - ts.x) / 2, p.y + (h - ts.y) / 2),
                    U("text") if (on or hov) else U("text_dim"), lab)
        x += iw
    imgui.pop_id()
    imgui.set_cursor_screen_pos(imgui.ImVec2(p.x + w, p.y))
    imgui.dummy(imgui.ImVec2(0, h))
    return changed, value


def labeled_seg(label, id_, value, options, labels=None, tips=None):
    imgui.align_text_to_frame_padding()
    imgui.text_colored(C("text_dim"), label)
    imgui.same_line(0, 6)
    return seg(id_, value, options, labels, tips)


def primary_button(label, disabled=False, why=""):
    """Accent fill, white text. One per screen."""
    imgui.begin_disabled(disabled)
    imgui.push_style_color(imgui.Col_.button, C("accent"))
    imgui.push_style_color(imgui.Col_.button_hovered, C("accent", 0.88))
    imgui.push_style_color(imgui.Col_.button_active, C("accent", 0.75))
    imgui.push_style_color(imgui.Col_.text, hexc("#ffffff"))
    pressed = imgui.button(label)
    imgui.pop_style_color(4)
    imgui.end_disabled()
    if disabled and why:
        tip(why)
    return pressed


def button(label, disabled=False, why="", help_=""):
    imgui.begin_disabled(disabled)
    pressed = imgui.button(label)
    imgui.end_disabled()
    if disabled and why:
        tip(why)
    elif help_:
        tip(help_)
    return pressed
