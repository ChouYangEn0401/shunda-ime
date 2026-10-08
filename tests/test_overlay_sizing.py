"""The panel window's size bookkeeping (smartime.ui.overlay), driven without
a real window: user32 and the anchor lookups are replaced, so only the
measure/place state machine is under test."""

import threading

import pytest

ov = pytest.importorskip("smartime.ui.overlay")

SIZES = {"hint": (18, 18), "candidates": (420, 300)}  # the composing dot, then a panel


class FakeUser32:
    def __init__(self):
        self.placed: list[tuple[int, int]] = []

    def SetWindowPos(self, hwnd, after, x, y, width, height, flags):
        self.placed.append((width, height))

    def InvalidateRect(self, *args):
        pass

    def ShowWindow(self, *args):
        pass

    def SetTimer(self, *args):
        pass

    def KillTimer(self, *args):
        pass


@pytest.fixture
def panel(monkeypatch):
    fake = FakeUser32()
    monkeypatch.setattr(ov, "user32", fake)
    monkeypatch.setattr(ov, "work_area", lambda rect: ((0, 0, 1920, 1080), 96))
    anchor = {"rect": (100, 100, 114, 126)}
    monkeypatch.setattr(ov, "find_anchor", lambda: (anchor["rect"], 1) if anchor["rect"] else None)
    monkeypatch.setattr(ov, "caret_rect", lambda: None)

    o = ov.Overlay.__new__(ov.Overlay)  # no thread, no real window
    o.dock_under, o._lock, o._hwnd, o._owner = None, threading.Lock(), 1, None
    o._want, o._shown, o._size, o._stale = None, None, (0, 0), False
    o._scale, o._fonts, o._last_anchor_at, o._pos = 1.0, object(), 0.0, None
    o._measure = lambda scale: SIZES[o._shown[1]]

    def show(kind):
        o._want = ("me", kind, None, None, 1.0, False)
        o._update()

    def hide():
        o._want = None
        o._update()

    return o, fake, anchor, show, hide


def test_a_panel_shown_before_its_anchor_exists_is_sized_for_itself(panel):
    """Reported: ::/;; sometimes opened as a tiny box with the new content
    clipped inside, until the next arrow key. The show arrived while PIME
    was rebuilding its message window (no anchor), so nothing was measured;
    the follow timer then found the anchor and placed the window with the
    previous panel's size."""
    o, fake, anchor, show, hide = panel
    show("hint")
    assert fake.placed[-1] == SIZES["hint"]
    hide()

    anchor["rect"] = None  # PIME's window is mid-rebuild
    show("candidates")
    placed_before = len(fake.placed)
    anchor["rect"] = (100, 100, 114, 126)  # and it is back
    o._follow()
    assert len(fake.placed) > placed_before
    assert fake.placed[-1] == SIZES["candidates"], "must not reuse the dot's 18×18"


def test_following_a_moving_anchor_does_not_remeasure_every_tick(panel):
    o, fake, anchor, show, hide = panel
    calls = []
    measure = o._measure
    o._measure = lambda scale: calls.append(1) or measure(scale)
    show("candidates")
    anchor["rect"] = (300, 300, 314, 326)
    o._follow()
    o._follow()
    assert len(calls) == 1, "only a new model is measured; moving it is just a move"
