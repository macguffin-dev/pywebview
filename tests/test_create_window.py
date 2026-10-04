"""``create_window`` after ``start``: a window is listed once it is made.

Once ``start`` is running, ``create_window`` called off the main thread makes
the window at once and returns it. It appended the window to
``webview.windows`` before making it, so a window whose initialisation was
cancelled (an ``initialized`` handler returning False -- ``create_window``
then returns None), or whose initialisation or native creation raised, stayed
listed though no window exists. Only a window's native close removes an entry,
so nothing ever removed it, and a ``while webview.windows`` loop -- the shape a
GUI-thread worker waiting for every window to close takes -- never ended.

Before ``start`` the window is still listed at once: ``start`` makes every
listed window.
"""

import threading

import pytest

import webview
from webview.window import Window


class FakeGui:
    """A GUI backend, as far as a post-start ``create_window`` reaches it."""

    renderer = 'fake'

    def __init__(self):
        self.created = []
        self.fail = False

    def create_window(self, window):
        if self.fail:
            raise RuntimeError('no native window')
        self.created.append(window)


@pytest.fixture
def gui(monkeypatch):
    fake = FakeGui()
    monkeypatch.setattr(webview, 'guilib', fake)
    return fake


def off_main_thread(fn):
    """``fn()`` on a thread other than the main one -- where ``create_window``
    makes the window at once; its result, or its exception raised here."""
    outcome = {}

    def run():
        try:
            outcome['value'] = fn()
        except Exception as e:
            outcome['error'] = e

    thread = threading.Thread(target=run)
    thread.start()
    thread.join(10)
    assert not thread.is_alive(), 'create_window did not return'
    if 'error' in outcome:
        raise outcome['error']
    return outcome['value']


def create():
    return webview.create_window('Window', 'http://127.0.0.1:1/')


def test_a_window_that_is_made_is_listed(gui):
    window = off_main_thread(create)
    assert window is not None
    assert webview.windows == [window]
    assert gui.created == [window]


def test_a_window_whose_initialisation_is_cancelled_is_not_listed(gui, monkeypatch):
    monkeypatch.setattr(Window, '_initialize', lambda self, gui, server=None: False)
    assert off_main_thread(create) is None
    assert webview.windows == []
    assert gui.created == []


def test_a_window_whose_initialisation_raises_is_not_listed(gui, monkeypatch):
    def broken(self, gui, server=None):
        raise RuntimeError('cannot initialise')

    monkeypatch.setattr(Window, '_initialize', broken)
    with pytest.raises(RuntimeError, match='cannot initialise'):
        off_main_thread(create)
    assert webview.windows == []


def test_a_window_the_gui_cannot_make_is_not_listed(gui):
    gui.fail = True
    with pytest.raises(RuntimeError, match='no native window'):
        off_main_thread(create)
    assert webview.windows == []


def test_before_start_a_window_is_listed_at_once(monkeypatch):
    monkeypatch.setattr(webview, 'guilib', None)
    window = off_main_thread(create)
    assert webview.windows == [window]
