"""The app-level ``before_quit`` event.

``applicationShouldTerminate_`` is Cocoa's application-level question: "should
this application exit?" pywebview answers it by AND-ing every window's
window-level ``closing`` handler, which loses the distinction AppKit draws
between NSApplicationDelegate and NSWindowDelegate. An embedding app gets no
say in a decision the platform assigns to the app delegate.

``webview.events.before_quit`` restores that seat: it fires once, before any
window is polled, and a handler returning ``False`` cancels the terminate
without any window being asked.

macOS-only by design. No other backend has an application-level veto moment —
winforms has per-form ``FormClosing``, qt per-window ``closeEvent``, gtk
per-window ``confirm_close`` — so on those platforms quitting *is* the windows
closing, and there is nothing for this event to order itself against.
"""

import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != 'darwin',
    reason='applicationShouldTerminate_ is a Cocoa-only lifecycle moment',
)


@pytest.fixture
def env(monkeypatch):
    """A real AppDelegate over fake windows, with the per-window poll recorded.

    ``should_close`` is instrumented rather than exercised: these are tests about
    *ordering* between the app-level event and the window-level poll, and the
    real ``should_close`` needs localization and a confirmation dialog.

    ``before_quit`` is the real module-level event, subscribed through the public
    ``+=`` and unsubscribed on teardown. Do not swap the Event object out with
    monkeypatch instead: handlers then register on an instance the delegate is
    not reading, and the tests pass or fail depending on execution order.
    """
    import AppKit

    import webview
    from webview.platforms import cocoa

    calls = []

    fake_instance = type('FakeInstance', (), {'pywebview_window': object()})()
    monkeypatch.setattr(cocoa.BrowserView, 'instances', {'w0': fake_instance})

    def fake_should_close(window):
        calls.append('poll')
        return AppKit.NSTerminateNow

    monkeypatch.setattr(cocoa.BrowserView, 'should_close', staticmethod(fake_should_close))

    registered = []

    def on_before_quit(handler):
        webview.events.before_quit += handler
        registered.append(handler)

    delegate = cocoa.BrowserView.AppDelegate.alloc().init()
    yield delegate, calls, on_before_quit

    for handler in registered:
        webview.events.before_quit -= handler


def test_before_quit_fires_before_any_window_is_polled(env):
    delegate, calls, on_before_quit = env
    on_before_quit(lambda: calls.append('before_quit'))

    delegate.applicationShouldTerminate_(None)

    assert calls == ['before_quit', 'poll'], (
        'the app-level hook must run before window-level polling; a handler '
        'that sets an "app is quitting" flag is useless if the windows have '
        'already been asked'
    )


def test_handler_returning_false_cancels_without_polling_windows(env):
    import AppKit

    delegate, calls, on_before_quit = env
    on_before_quit(lambda: False)

    reply = delegate.applicationShouldTerminate_(None)

    assert reply == AppKit.NSTerminateCancel
    assert 'poll' not in calls, 'a vetoed quit must not ask the windows at all'


def test_handler_returning_none_allows_the_quit(env):
    import AppKit

    delegate, calls, on_before_quit = env
    on_before_quit(lambda: None)

    reply = delegate.applicationShouldTerminate_(None)

    assert reply == AppKit.NSTerminateNow
    assert calls == ['poll']


def test_no_handlers_leaves_existing_behaviour_unchanged(env):
    import AppKit

    delegate, calls, _ = env

    reply = delegate.applicationShouldTerminate_(None)

    assert reply == AppKit.NSTerminateNow
    assert calls == ['poll']


def test_a_window_refusing_still_cancels(env, monkeypatch):
    """The window-level veto keeps working; before_quit is added, not swapped."""
    import AppKit

    from webview.platforms import cocoa

    delegate, calls, _ = env
    monkeypatch.setattr(
        cocoa.BrowserView,
        'should_close',
        staticmethod(lambda window: AppKit.NSTerminateCancel),
    )

    reply = delegate.applicationShouldTerminate_(None)

    assert reply == AppKit.NSTerminateCancel
