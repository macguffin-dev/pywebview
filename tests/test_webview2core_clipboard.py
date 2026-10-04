"""
Unit tests for WebView2Core._should_allow_clipboard_read() - which pages may read
the clipboard without WebView2's permission prompt, shared by the
WinForms/EdgeChromium and WinUI3 backends.

Skipped outside Windows for the same reason as test_webview2core_header_diff.py:
webview.platforms.webview2core cannot be imported there.
"""

import sys
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != 'win32',
    reason='webview2core.py imports webview.platforms.win32, which requires ctypes.windll',
)


def _allows(uri, real_url):
    from webview.platforms.webview2core import WebView2Core

    core = SimpleNamespace(pywebview_window=SimpleNamespace(real_url=real_url))
    return WebView2Core._should_allow_clipboard_read(core, uri)


class TestShouldAllowClipboardRead:
    def test_the_windows_own_origin_may_read(self):
        assert _allows('http://127.0.0.1:8000/', 'http://127.0.0.1:8000/?pywebview_id=window_1')

    def test_another_origin_is_left_to_the_prompt(self):
        assert not _allows('https://example.com/', 'http://127.0.0.1:8000/')

    def test_a_window_without_a_url_allows_nothing(self):
        # HTML-string content has no origin of its own to trust.
        assert not _allows('about:blank', None)
