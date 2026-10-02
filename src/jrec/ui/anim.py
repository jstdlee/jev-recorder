"""Motion for the UI (animate-it skill): only where it explains a change, never on keyboard actions.

  view moves from buttons, minimap clicks and jumps   220 ms, ease-out cubic-bezier(0.23, 1, 0.32, 1)
  progress bars                                        glide 250 ms, linear (constant motion)
  dialogs opening                                      fade 150 ms, ease-out (modals stay centred)
'Reduce motion' (Settings) turns view moves off and keeps the fades.
"""
import time


def cubic_bezier(x1, y1, x2, y2):
    """CSS cubic-bezier as a function of progress t in [0, 1] (Newton + bisection on x(s) = t)."""
    def coord(s, a, b):
        return 3 * a * s * (1 - s) ** 2 + 3 * b * s * s * (1 - s) + s ** 3

    def slope(s, a, b):
        return 3 * a * (1 - s) ** 2 + 6 * (b - a) * s * (1 - s) + 3 * (1 - b) * s * s

    def f(t):
        if t <= 0:
            return 0.0
        if t >= 1:
            return 1.0
        s = t
        for _ in range(8):
            dx = coord(s, x1, x2) - t
            d = slope(s, x1, x2)
            if abs(dx) < 1e-6 or abs(d) < 1e-6:
                break
            s -= dx / d
        if not (0 <= s <= 1) or abs(coord(s, x1, x2) - t) > 1e-4:   # fall back to bisection
            lo, hi = 0.0, 1.0
            for _ in range(40):
                s = (lo + hi) / 2
                if coord(s, x1, x2) < t:
                    lo = s
                else:
                    hi = s
        return coord(s, y1, y2)
    return f


EASE_OUT = cubic_bezier(0.23, 1, 0.32, 1)
VIEW_MS, FADE_MS, GLIDE_MS = 220, 150, 250


class Tween:
    """Values (tuples) moving from `a` to `b` over `ms` with `ease`."""
    def __init__(self, a, b, ms, ease=EASE_OUT):
        self.a, self.b, self.ms, self.ease = tuple(a), tuple(b), ms, ease
        self.t0 = time.monotonic()

    def value(self):
        k = self.ease(min(1.0, (time.monotonic() - self.t0) * 1000 / self.ms))
        return tuple(x + (y - x) * k for x, y in zip(self.a, self.b))

    @property
    def done(self):
        return (time.monotonic() - self.t0) * 1000 >= self.ms


class Glide:
    """A displayed number that follows its target at constant speed (no jumps on progress bars)."""
    def __init__(self):
        self.shown, self.tw, self.target = 0.0, None, 0.0

    def __call__(self, target):
        if target < self.shown - 1e-6:          # a new job, or a reset: no backwards slide
            self.shown, self.tw, self.target = target, None, target
        elif abs(target - self.target) > 1e-6:
            self.tw = Tween((self.shown,), (target,), GLIDE_MS, lambda k: k)
            self.target = target
        if self.tw:
            self.shown = self.tw.value()[0]
            if self.tw.done:
                self.tw = None
        return self.shown

    @property
    def active(self):
        return self.tw is not None


_opened = {}


def fade_in(name, is_open):
    """Alpha for a dialog that opened `name`; restarts each time it opens."""
    now = time.monotonic()
    if not is_open:
        _opened.pop(name, None)
        return 1.0
    t0 = _opened.setdefault(name, now)
    return EASE_OUT(min(1.0, (now - t0) * 1000 / FADE_MS))


def fading():
    now = time.monotonic()
    return any((now - t0) * 1000 < FADE_MS for t0 in _opened.values())
