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


class TestDeferredQuit:
    """``NSTerminateLater`` — the third reply pywebview could not express.

    AppKit's ``applicationShouldTerminate:`` returns one of three values
    (Cancel=0, Now=1, Later=2). pywebview answered ``Foundation.YES``/``NO``,
    which are 1 and 0, so the reply was correct but never complete: an app
    could not say "ask the user, I will answer shortly", which is what the
    standard Save / Don't Save / Cancel review on quit requires.

    ``defer_quit()`` answers Later; ``resume_quit(allow)`` delivers the answer
    via ``replyToApplicationShouldTerminate:``.
    """

    def test_defer_returns_later_and_skips_window_polling(self, env):
        import AppKit

        import webview

        delegate, calls, on_before_quit = env
        on_before_quit(webview.defer_quit)

        reply = delegate.applicationShouldTerminate_(None)

        assert reply == AppKit.NSTerminateLater
        assert 'poll' not in calls, 'a deferred quit has not been decided yet'

    def test_cancel_outranks_defer(self, env):
        import AppKit

        import webview

        delegate, calls, on_before_quit = env

        def refuse_and_defer():
            webview.defer_quit()
            return False

        on_before_quit(refuse_and_defer)
        reply = delegate.applicationShouldTerminate_(None)

        assert reply == AppKit.NSTerminateCancel
        assert webview._quit_deferred is False, (
            'an outright refusal must clear the deferral, or the app is left '
            'waiting for a reply that will never come'
        )

    def test_second_request_while_pending_coalesces(self, env):
        import AppKit

        import webview

        delegate, calls, on_before_quit = env
        on_before_quit(webview.defer_quit)

        assert delegate.applicationShouldTerminate_(None) == AppKit.NSTerminateLater
        calls.clear()
        # A second Cmd+Q while the review is still open must not stack another
        # pending terminate, nor fall through to polling.
        assert delegate.applicationShouldTerminate_(None) == AppKit.NSTerminateLater
        assert calls == []

    def test_no_defer_leaves_the_normal_path(self, env):
        import AppKit

        import webview

        delegate, calls, _ = env

        assert delegate.applicationShouldTerminate_(None) == AppKit.NSTerminateNow
        assert calls == ['poll']
        assert webview._quit_deferred is False

    def test_resume_replies_and_clears_pending(self, env, monkeypatch):
        import webview
        from webview.platforms import cocoa

        delegate, _calls, on_before_quit = env
        on_before_quit(webview.defer_quit)
        delegate.applicationShouldTerminate_(None)

        replies = []
        monkeypatch.setattr(
            cocoa.BrowserView,
            'app',
            type(
                'StubApp', (), {'replyToApplicationShouldTerminate_': staticmethod(replies.append)}
            )(),
        )
        # Run the main-thread marshal inline.
        monkeypatch.setattr(cocoa.AppHelper, 'callAfter', lambda fn, *a: fn(*a))

        cocoa.resume_quit(True)

        assert replies == [True]
        assert webview._quit_deferred is False, 'pending state must clear'

    def test_resume_without_pending_is_a_noop(self, env, monkeypatch):
        from webview.platforms import cocoa

        replies = []
        monkeypatch.setattr(
            cocoa.BrowserView,
            'app',
            type(
                'StubApp', (), {'replyToApplicationShouldTerminate_': staticmethod(replies.append)}
            )(),
        )
        monkeypatch.setattr(cocoa.AppHelper, 'callAfter', lambda fn, *a: fn(*a))

        cocoa.resume_quit(True)  # nothing deferred

        assert replies == [], 'replying with no deferral pending is an AppKit error'


class TestQuitDeferredAccessor:
    """Consumers need the pending state without reaching for a private."""

    def test_reports_pending_between_defer_and_resume(self, env, monkeypatch):
        import webview
        from webview.platforms import cocoa

        delegate, _calls, on_before_quit = env
        assert webview.quit_deferred() is False

        on_before_quit(webview.defer_quit)
        delegate.applicationShouldTerminate_(None)
        assert webview.quit_deferred() is True

        monkeypatch.setattr(
            cocoa.BrowserView,
            'app',
            type(
                'StubApp', (), {'replyToApplicationShouldTerminate_': staticmethod(lambda _v: None)}
            )(),
        )
        monkeypatch.setattr(cocoa.AppHelper, 'callAfter', lambda fn, *a: fn(*a))
        cocoa.resume_quit(True)
        assert webview.quit_deferred() is False


class TestResumeQuitDispatch:
    """The public entry point, which is what a framework layer calls."""

    def test_dispatches_to_the_active_backend(self, monkeypatch):
        import webview

        seen = []
        monkeypatch.setattr(
            webview,
            'guilib',
            type('StubGui', (), {'resume_quit': staticmethod(seen.append)})(),
        )
        webview.resume_quit(True)
        assert seen == [True]

    def test_coerces_to_bool(self, monkeypatch):
        import webview

        seen = []
        monkeypatch.setattr(
            webview,
            'guilib',
            type('StubGui', (), {'resume_quit': staticmethod(seen.append)})(),
        )
        webview.resume_quit(1)
        assert seen == [True], 'the ObjC BOOL must not receive a Python int'

    def test_backend_without_support_warns_instead_of_raising(self, monkeypatch):
        import webview

        monkeypatch.setattr(webview, 'guilib', type('StubGui', (), {})())
        webview.resume_quit(True)  # must not raise
