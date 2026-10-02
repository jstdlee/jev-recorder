"""Small drawn flags for transcript languages (no emoji font needed). Tooltip gives the name."""
import math

from imgui_bundle import imgui

# language (as Qwen3-ASR names it) -> (short code, flag)
LANG = {"Chinese": ("中", "CN"), "Cantonese": ("粵", "HK"), "English": ("EN", "GB"), "Malay": ("MS", "MY"),
        "Indonesian": ("ID", "ID"), "Thai": ("TH", "TH"), "Vietnamese": ("VI", "VN"), "Japanese": ("JA", "JP"),
        "Korean": ("KO", "KR"), "Hindi": ("HI", "IN"), "Tamil": ("TA", "IN"), "Filipino": ("TL", "PH")}


def _c(h, a=255):
    return imgui.IM_COL32(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)


def _star(dl, cx, cy, r, col, rot=-math.pi / 2):
    pts = [imgui.ImVec2(cx + (r if k % 2 == 0 else r * 0.42) * math.cos(rot + k * math.pi / 5),
                        cy + (r if k % 2 == 0 else r * 0.42) * math.sin(rot + k * math.pi / 5)) for k in range(10)]
    c = imgui.ImVec2(cx, cy)
    for k in range(10):
        dl.add_triangle_filled(c, pts[k], pts[(k + 1) % 10], col)


def draw_flag(dl, code, x, y, h):
    """Draw the flag for country `code` with its top-left at (x, y), height h, width 1.5 h."""
    w = h * 1.5
    R = lambda x0, y0, x1, y1, col: dl.add_rect_filled(imgui.ImVec2(x + x0 * w, y + y0 * h),
                                                         imgui.ImVec2(x + x1 * w, y + y1 * h), col)
    red, white, blue, yellow = _c("de2910"), _c("ffffff"), _c("0b3d91"), _c("ffde00")
    if code == "CN":
        R(0, 0, 1, 1, red); _star(dl, x + w * 0.18, y + h * 0.3, h * 0.2, yellow)
        for dx, dy in ((0.36, 0.12), (0.42, 0.26), (0.42, 0.44), (0.36, 0.56)):
            _star(dl, x + w * dx, y + h * dy, h * 0.07, yellow)
    elif code == "HK":
        R(0, 0, 1, 1, _c("de2910"))
        for k in range(5):
            a = -math.pi / 2 + k * 2 * math.pi / 5
            dl.add_circle_filled(imgui.ImVec2(x + w / 2 + math.cos(a) * h * 0.16, y + h / 2 + math.sin(a) * h * 0.16),
                                 h * 0.12, white)
    elif code == "GB":
        R(0, 0, 1, 1, _c("012169"))
        for a, b in (((0, 0), (1, 1)), ((0, 1), (1, 0))):
            dl.add_line(imgui.ImVec2(x + a[0] * w, y + a[1] * h), imgui.ImVec2(x + b[0] * w, y + b[1] * h), white, h * 0.2)
        R(0.42, 0, 0.58, 1, white); R(0, 0.36, 1, 0.64, white)
        R(0.46, 0, 0.54, 1, _c("c8102e")); R(0, 0.42, 1, 0.58, _c("c8102e"))
    elif code == "MY":
        for k in range(7):
            R(0, k / 7, 1, (k + 1) / 7, _c("cc0001") if k % 2 == 0 else white)
        R(0, 0, 0.5, 4 / 7, _c("010066")); _star(dl, x + w * 0.3, y + h * 0.29, h * 0.1, yellow)
        dl.add_circle_filled(imgui.ImVec2(x + w * 0.17, y + h * 0.29), h * 0.17, yellow)
        dl.add_circle_filled(imgui.ImVec2(x + w * 0.2, y + h * 0.29), h * 0.14, _c("010066"))
    elif code == "ID":
        R(0, 0, 1, 0.5, _c("ce1126")); R(0, 0.5, 1, 1, white)
    elif code == "TH":
        for (a, b), col in (((0, 1 / 6), "a51931"), ((1 / 6, 2 / 6), "f4f5f8"), ((2 / 6, 4 / 6), "2d2a4a"),
                            ((4 / 6, 5 / 6), "f4f5f8"), ((5 / 6, 1), "a51931")):
            R(0, a, 1, b, _c(col))
    elif code == "VN":
        R(0, 0, 1, 1, _c("da251d")); _star(dl, x + w / 2, y + h / 2, h * 0.3, yellow)
    elif code == "JP":
        R(0, 0, 1, 1, white); dl.add_circle_filled(imgui.ImVec2(x + w / 2, y + h / 2), h * 0.3, _c("bc002d"))
    elif code == "KR":
        R(0, 0, 1, 1, white)
        c = imgui.ImVec2(x + w / 2, y + h / 2)
        dl.path_arc_to(c, h * 0.25, math.pi, 2 * math.pi); dl.path_fill_convex(_c("cd2e3a"))
        dl.path_arc_to(c, h * 0.25, 0, math.pi); dl.path_fill_convex(_c("0047a0"))
    elif code == "IN":
        R(0, 0, 1, 1 / 3, _c("ff9933")); R(0, 1 / 3, 1, 2 / 3, white); R(0, 2 / 3, 1, 1, _c("138808"))
        dl.add_circle(imgui.ImVec2(x + w / 2, y + h / 2), h * 0.13, _c("000080"), 0, 1.0)
    elif code == "PH":
        R(0, 0, 1, 0.5, _c("0038a8")); R(0, 0.5, 1, 1, _c("ce1126"))
        dl.add_triangle_filled(imgui.ImVec2(x, y), imgui.ImVec2(x + w * 0.45, y + h / 2), imgui.ImVec2(x, y + h), white)
        _star(dl, x + w * 0.15, y + h / 2, h * 0.12, yellow)
    else:
        R(0, 0, 1, 1, _c("8e8e96"))
    dl.add_rect(imgui.ImVec2(x, y), imgui.ImVec2(x + w, y + h), _c("000000", 60), 2.0)


def lang_badge(lang, h=None, clickable=True, id_=""):
    """A flag for `lang` as an item (click returns True). Tooltip names the language."""
    h = h or imgui.get_font_size() * 0.82
    w = h * 1.5
    p = imgui.get_cursor_screen_pos()
    pad_y = (imgui.get_text_line_height() - h) / 2
    clicked = imgui.invisible_button(f"##flag{id_}", imgui.ImVec2(w, imgui.get_text_line_height())) if clickable \
        else (imgui.dummy(imgui.ImVec2(w, imgui.get_text_line_height())) or False)
    dl = imgui.get_window_draw_list()
    draw_flag(dl, LANG.get(lang, ("?", "??"))[1], p.x, p.y + pad_y, h)
    return clicked
