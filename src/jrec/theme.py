"""Look and feel: Magpie layout + native macOS tokens (polish-ui skill), for Dear ImGui.

Soft page, rounded cards, tiny caps section titles, segmented pills for choices, the
accent colour only where something is selected, focused or primary.
"""
import json
from contextlib import contextmanager
from pathlib import Path

from imgui_bundle import imgui

from .i18n import T
from .paths import config_dir

PREFS_PATH = config_dir() / "ui.json"
TOOLTIP_DELAY = 2.0          # seconds the pointer rests before a tooltip shows (polish-app §5)
DEFAULT_PREFS = {"theme": "System", "lang": "system", "text_size": 1.0, "speed": 1.0, "skip_silence": True, "follow": True,
                 "translate_to": "English", "axis": "clock", "sound": "original", "channel": "both",
                 "rows": "line", "preview_split": 0.42, "subtitles": True, "reduce_motion": False}


def hexc(h, a=1.0):
    h = h.lstrip("#")
    return imgui.ImVec4(int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255, a)


TOKENS = {
    "Dark": {"bg": "#1c1c1f", "card": "#252528", "card_border": "#303034", "divider": "#2c2c30", "text": "#e8e8ec",
             "text_dim": "#8e8e96", "track": "#2e2e33", "pill": "#3a3a40", "pill_border": "#45454b",
             "accent": "#0a84ff", "danger": "#ff453a", "warn": "#ff9f0a", "ok": "#30d158",
             "wave": "#64a8ff", "pad_shade": "#1f1f22", "playhead": "#f5f5f7", "match": "#ffd60a", "ab": "#ff9f0a",
             "note": "#bf5af2"},
    "Light": {"bg": "#f4f4f6", "card": "#ffffff", "card_border": "#e3e3e8", "divider": "#ececf0", "text": "#212126",
              "text_dim": "#737379", "track": "#f1f1f4", "pill": "#ffffff", "pill_border": "#e3e3e8",
              "accent": "#007aff", "danger": "#ff3b30", "warn": "#c93400", "ok": "#248a3d",
              "wave": "#2f7de1", "pad_shade": "#ebebef", "playhead": "#1d1d1f", "match": "#e0a800", "ab": "#ff8a00",
              "note": "#9a3fc4"},
    "Tokyo Night": {"bg": "#1a1b26", "card": "#1f2335", "card_border": "#292e42", "divider": "#292e42",
                    "text": "#c0caf5", "text_dim": "#8089b3", "track": "#292e42", "pill": "#343a55",
                    "pill_border": "#3b4261", "accent": "#7aa2f7", "danger": "#f7768e", "warn": "#e0af68",
                    "ok": "#9ece6a", "wave": "#7dcfff", "pad_shade": "#16161e", "playhead": "#c0caf5",
                    "match": "#e0af68", "ab": "#ff9e64", "note": "#bb9af7"},
}
THEMES = ["System", "Light", "Dark", "Tokyo Night"]


def system_theme():
    """Dark or Light from the OS (GNOME color-scheme / gtk theme name; Windows AppsUseLightTheme)."""
    import subprocess
    import sys
    try:
        if sys.platform == "win32":
            import winreg
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            return "Light" if winreg.QueryValueEx(k, "AppsUseLightTheme")[0] else "Dark"
        out = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"], capture_output=True,
                             text=True, timeout=2).stdout
        if "dark" in out:
            return "Dark"
        out = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"], capture_output=True,
                             text=True, timeout=2).stdout
        return "Dark" if "dark" in out.lower() else "Light"
    except Exception:
        return "Dark"


_system_cache = []


def resolve(theme):
    if theme == "System":
        if not _system_cache:
            _system_cache.append(system_theme())
        return _system_cache[0]
    return theme if theme in TOKENS else "Dark"

TK = dict(TOKENS["Dark"])   # current tokens as hex; C(name) -> ImVec4


def C(name, a=1.0):
    return hexc(TK[name], a)


def U(name, a=1.0):
    return imgui.get_color_u32(C(name, a))


def load_prefs():
    try:
        return {**DEFAULT_PREFS, **json.loads(PREFS_PATH.read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return dict(DEFAULT_PREFS)


def save_prefs(p):
    try:
        PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        PREFS_PATH.write_text(json.dumps(p, indent=1), encoding="utf-8")
    except OSError:
        pass


def apply(theme="Dark", text_size=1.0):
    TK.clear()
    TK.update(TOKENS[resolve(theme)])
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
    st.anti_aliased_lines = st.anti_aliased_fill = True
    st.hover_delay_normal = TOOLTIP_DELAY
    st.hover_stationary_delay = 0.15
    st.hover_flags_for_tooltip_mouse = imgui.HoveredFlags_.stationary | imgui.HoveredFlags_.delay_normal
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
def tip(text, keys=""):
    """Tooltip after the hover delay (2 s; at once when moving between tooltips). Shows the shortcut."""
    if imgui.is_item_hovered(imgui.HoveredFlags_.for_tooltip | imgui.HoveredFlags_.allow_when_disabled):
        imgui.set_tooltip(T(text) + (f"    {keys}" if keys else ""))


def section(title):
    """Tiny grey ALL CAPS section title."""
    imgui.push_font(None, imgui.get_style().font_size_base * 0.80)
    t = T(title)
    imgui.text_colored(C("text_dim"), t.upper() if t.isascii() else t)
    imgui.pop_font()


def small(text, color="text_dim"):
    imgui.push_font(None, imgui.get_style().font_size_base * 0.88)
    imgui.text_colored(C(color), T(text))
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


def seg_width(labels, icons=None, translate=True):
    labels = [T(l) for l in labels] if translate else list(labels)
    fw = imgui.get_font_size() * 0.75 * 1.5 + 6
    return 4 + sum(imgui.calc_text_size(l).x + 22 + (fw if icons and icons[i] else 0) for i, l in enumerate(labels))


def seg(id_, value, options, labels=None, tips=None, icons=None, fill=None, translate=True):
    """Segmented control: all options visible, the chosen one is a raised pill. Returns (changed, value).
    icons: optional per-option country codes; a small flag is drawn before the label.
    fill: total width to stretch to (segments share it equally), e.g. the sidebar's width."""
    labels = labels or [str(o) for o in options]
    labels = [T(l) for l in labels] if translate else list(labels)
    fw = imgui.get_font_size() * 0.75 * 1.5 + 6
    dl = imgui.get_window_draw_list()
    p = imgui.get_cursor_screen_pos()
    h = imgui.get_frame_height()
    w = max(seg_width(labels, icons), fill or 0)
    each = (w - 4) / len(labels) if fill else None
    dl.add_rect_filled(p, imgui.ImVec2(p.x + w, p.y + h), U("track"), 7.0)
    changed, x = False, p.x + 2
    imgui.push_id(id_)
    for i, (opt, lab) in enumerate(zip(options, labels)):
        icon = icons[i] if icons else None
        iw = each or (imgui.calc_text_size(lab).x + 22 + (fw if icon else 0))
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
        tx = x + (iw - ts.x - (fw if icon else 0)) / 2
        if icon:
            from .ui.flags import draw_flag
            fh = imgui.get_font_size() * 0.75
            draw_flag(dl, icon, tx, p.y + (h - fh) / 2, fh)
            tx += fw
        dl.add_text(imgui.ImVec2(tx, p.y + (h - ts.y) / 2), U("text") if (on or hov) else U("text_dim"), lab)
        x += iw
    imgui.pop_id()
    imgui.set_cursor_screen_pos(imgui.ImVec2(p.x + w, p.y))
    imgui.dummy(imgui.ImVec2(0, h))
    return changed, value


def labeled_seg(label, id_, value, options, labels=None, tips=None, icons=None):
    imgui.align_text_to_frame_padding()
    imgui.text_colored(C("text_dim"), T(label))
    imgui.same_line(0, 6)
    return seg(id_, value, options, labels, tips, icons)


def primary_button(label, disabled=False, why=""):
    """Accent fill, white text. One per screen."""
    imgui.begin_disabled(disabled)
    imgui.push_style_color(imgui.Col_.button, C("accent"))
    imgui.push_style_color(imgui.Col_.button_hovered, C("accent", 0.88))
    imgui.push_style_color(imgui.Col_.button_active, C("accent", 0.75))
    imgui.push_style_color(imgui.Col_.text, hexc("#ffffff"))
    pressed = imgui.button(T(label))
    imgui.pop_style_color(4)
    imgui.end_disabled()
    if disabled and why:
        tip(why)
    return pressed


def button(label, disabled=False, why="", help_=""):
    imgui.begin_disabled(disabled)
    pressed = imgui.button(T(label))
    imgui.end_disabled()
    if disabled and why:
        tip(why)
    elif help_:
        tip(help_)
    return pressed


# Font Awesome 6 glyphs (merged into the main font)
ICON_X = "\uf00d"        # xmark
ICON_NOTE = "\uf249"     # note-sticky
ICON_OPEN = "\uf065"     # expand
ICON_PEN = "\uf304"
ICON_STAR = "\uf005"
ICON_STOP = "\uf04d"       # stop (square)
ICON_EXPAND = "\uf31e"     # up-right-and-down-left-from-center
ICON_GEAR = "\uf013"
ICON_MIN = "\uf2d1"        # window-minimize
ICON_MAX = "\uf2d0"        # window-maximize
ICON_RESTORE = "\uf2d2"    # window-restore
ICON_TAG = "\uf02b"
ICON_CARET = "\uf0d7"      # caret-down
ICON_SEARCH = "\uf002"
ICON_TALKS = "\uf086"      # comments
ICON_PEOPLE = "\uf0c0"     # users
ICON_FILES = "\uf1c7"      # file-audio
ICON_MOMENTS = "\uf02e"    # bookmark
ICON_TAGS = "\uf02c"       # tags


def clear_x(id_, tip_text="Clear"):
    """A small ✕ icon button drawn right after a field; returns True when pressed."""
    imgui.same_line(0, 4)
    imgui.push_style_color(imgui.Col_.button, C("track", 0.0))
    imgui.push_style_color(imgui.Col_.text, C("text_dim"))
    pressed = imgui.button(f"{ICON_X}##{id_}")
    imgui.pop_style_color(2)
    tip(tip_text)
    return pressed
ICON_LIST_CHECK = ""
ICON_HELP = ""       # circle-question
ICON_WAND = ""       # wand-magic-sparkles (feature highlight only)
ICON_PAUSE = ""
ICON_PLAY = ""
ICON_RETRY = ""      # rotate-right
ICON_TRASH = ""
ICON_UP = ""
ICON_DOWN = ""
ICON_FOLDER = ""
ICON_THEME = ""      # circle-half-stroke
ICON_LANG = ""
ICON_KEYBOARD = ""
ICON_BOOK = ""
ICON_BULB = ""
ICON_COPY = ""
ICON_ERROR = ""      # circle-exclamation
ICON_WARN = ""
ICON_INFO = ""
ICON_CHECK = ""
ICON_WAIT = ""       # hourglass-half
ICON_EYE = ""
ICON_TERMINAL = ""
ICON_TEXT = ""       # font


def feature_button(id_, icon, label, disabled=False, why="", keys=""):
    """The feature highlight (polish-app §9): accent-tinted fill, accent icon, label. Max two per view."""
    imgui.begin_disabled(disabled)
    imgui.push_style_color(imgui.Col_.button, C("accent", 0.14))
    imgui.push_style_color(imgui.Col_.button_hovered, C("accent", 0.24))
    imgui.push_style_color(imgui.Col_.button_active, C("accent", 0.32))
    imgui.push_style_color(imgui.Col_.text, C("accent"))
    imgui.push_style_var(imgui.StyleVar_.frame_border_size, 1.0)
    imgui.push_style_color(imgui.Col_.border, C("accent", 0.35))
    pressed = imgui.button(f"{icon}  {T(label)}##{id_}")
    imgui.pop_style_color(5)
    imgui.pop_style_var()
    imgui.end_disabled()
    tip(why if disabled and why else label, keys)
    return pressed


def key_chip(dl, pos, keys, scale=0.82):
    """Draw 'Ctrl+P' as small key chips; returns the width used."""
    fs = imgui.get_font_size() * scale
    x = pos.x
    for k in keys.split("+"):
        w = imgui.calc_text_size(k).x * scale + 8
        dl.add_rect_filled(imgui.ImVec2(x, pos.y), imgui.ImVec2(x + w, pos.y + fs + 4), U("track"), 4.0)
        dl.add_rect(imgui.ImVec2(x, pos.y), imgui.ImVec2(x + w, pos.y + fs + 4), U("pill_border"), 4.0)
        dl.add_text(imgui.get_font(), fs, imgui.ImVec2(x + 4, pos.y + 2), U("text_dim"), k)
        x += w + 3
    return x - pos.x


def chips_width(keys, scale=0.82):
    return sum(imgui.calc_text_size(k).x * scale + 11 for k in keys.split("+")) if keys else 0.0
ICON_SQUARE = "\uf0c8"      # maximize
ICON_CLONE = "\uf24d"       # restore
ICON_ABOUT = "\uf05a"
