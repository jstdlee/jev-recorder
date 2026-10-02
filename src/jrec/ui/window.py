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
