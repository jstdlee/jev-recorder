"""Our own title bar: move, minimize, maximize/restore and close the borderless window.

Uses the pyglfw binding pointed at imgui-bundle's own libglfw, so both talk to the same GLFW
instance and the same window (a second GLFW copy would not know this window).
"""
import ctypes
import os
from pathlib import Path

from imgui_bundle import hello_imgui

_glfw = None
_drag = None


def _lib():
    global _glfw
    if _glfw is None:
        import imgui_bundle
        so = next((p for p in (Path(imgui_bundle.__file__).parent / n for n in ("libglfw.so.3", "libglfw.so"))
                   if p.exists()), None)
        if so:
            os.environ["PYGLFW_LIBRARY"] = str(so)
        import glfw
        _glfw = glfw
    return _glfw


def _win():
    glfw = _lib()
    return ctypes.cast(hello_imgui.get_glfw_window_address(), ctypes.POINTER(glfw._GLFWwindow))


def available():
    try:
        _win()
        return True
    except Exception:
        return False


def minimize():
    _lib().iconify_window(_win())


def maximized():
    try:
        return bool(_lib().get_window_attrib(_win(), _lib().MAXIMIZED))
    except Exception:
        return False


def toggle_maximize():
    glfw, w = _lib(), _win()
    if glfw.get_window_attrib(w, glfw.MAXIMIZED):
        glfw.restore_window(w)
    else:
        glfw.maximize_window(w)


def close():
    hello_imgui.get_runner_params().app_shall_exit = True


def drag_begin():
    """Remember the window and pointer positions in screen coordinates."""
    global _drag
    glfw, w = _lib(), _win()
    wx, wy = glfw.get_window_pos(w)
    cx, cy = glfw.get_cursor_pos(w)
    _drag = (wx, wy, wx + cx, wy + cy)


def drag_update():
    if not _drag:
        return
    glfw, w = _lib(), _win()
    if glfw.get_window_attrib(w, glfw.MAXIMIZED):
        glfw.restore_window(w)
    wx0, wy0, gx0, gy0 = _drag
    wx, wy = glfw.get_window_pos(w)
    cx, cy = glfw.get_cursor_pos(w)
    gx, gy = wx + cx, wy + cy                       # pointer in screen coordinates now
    glfw.set_window_pos(w, int(wx0 + gx - gx0), int(wy0 + gy - gy0))


def drag_end():
    global _drag
    _drag = None


# ---------------------------------------------------------------- edge resize (borderless window)
_resize = None
EDGE = 5          # px of invisible resize border on every side


def edge_at(x, y, w, h):
    """'n' 's' 'e' 'w' or corners like 'nw' for a pointer at (x, y) in a w × h window; '' inside."""
    v = "n" if y < EDGE else "s" if y > h - EDGE else ""
    hz = "w" if x < EDGE else "e" if x > w - EDGE else ""
    return v + hz


def resize_begin(edge):
    global _resize
    glfw, w = _lib(), _win()
    wx, wy = glfw.get_window_pos(w)
    ww, wh = glfw.get_window_size(w)
    cx, cy = glfw.get_cursor_pos(w)
    _resize = (edge, wx, wy, ww, wh, wx + cx, wy + cy)


def resize_update(min_w=720, min_h=480):
    if not _resize:
        return
    glfw, w = _lib(), _win()
    edge, wx0, wy0, ww0, wh0, gx0, gy0 = _resize
    wx, wy = glfw.get_window_pos(w)
    cx, cy = glfw.get_cursor_pos(w)
    dx, dy = wx + cx - gx0, wy + cy - gy0
    x, y, ww, wh = wx0, wy0, ww0, wh0
    if "e" in edge:
        ww = max(min_w, ww0 + dx)
    if "s" in edge:
        wh = max(min_h, wh0 + dy)
    if "w" in edge:
        ww = max(min_w, ww0 - dx)
        x = wx0 + ww0 - ww
    if "n" in edge:
        wh = max(min_h, wh0 - dy)
        y = wy0 + wh0 - wh
    glfw.set_window_size(w, int(ww), int(wh))
    if (x, y) != (wx0, wy0):
        glfw.set_window_pos(w, int(x), int(y))


def resize_end():
    global _resize
    _resize = None


def resizing():
    return _resize is not None


def geometry():
    """{x, y, w, h, max} of the window now, for the next start."""
    glfw, w = _lib(), _win()
    if glfw.get_window_attrib(w, glfw.MAXIMIZED):
        return {"max": True}
    x, y = glfw.get_window_pos(w)
    ww, wh = glfw.get_window_size(w)
    return {"x": x, "y": y, "w": ww, "h": wh, "max": False}


def focus():
    glfw, w = _lib(), _win()
    if glfw.get_window_attrib(w, glfw.ICONIFIED):
        glfw.restore_window(w)
    glfw.show_window(w)
    glfw.focus_window(w)
    glfw.request_window_attention(w)


def focused():
    try:
        return bool(_lib().get_window_attrib(_win(), _lib().FOCUSED))
    except Exception:
        return True
