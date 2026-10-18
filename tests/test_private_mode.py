"""Private mode starts each run with no stored data -- and only each run.

A window opened while others are open shares their cookie store on Cocoa (the
default WKWebsiteDataStore) and on WebView2 (one InPrivate session per user
data folder). Clearing that store whenever a window was created cleared the
cookies of every window already open: a page that a server had given a
session cookie lost it as soon as any second window appeared.
"""

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import webview

from .util import run_test

_COOKIE = 'private-mode-test=kept'


class _Handler(BaseHTTPRequestHandler):
    """``/set`` answers with a session cookie, ``/check`` with the cookies it
    was sent."""

    def do_GET(self) -> None:  # noqa: N802 -- BaseHTTPRequestHandler's name
        if self.path == '/set':
            body = b'<html><body><h1>cookie set</h1></body></html>'
            self.send_response(200)
            self.send_header('Set-Cookie', f'{_COOKIE}; Path=/; HttpOnly; SameSite=Strict')
            self.send_header('Content-Type', 'text/html')
        else:
            body = (self.headers.get('Cookie') or '').encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{httpd.server_address[1]}'
    httpd.shutdown()
    httpd.server_close()


def _cookies_sent(window) -> str:
    # A synchronous request, so evaluate_js returns its answer.
    return window.evaluate_js(
        '(function () { var x = new XMLHttpRequest();'
        " x.open('GET', '/check', false); x.send(); return x.responseText; })()"
    )


def test_a_second_window_keeps_the_first_windows_cookies(server):
    window = webview.create_window('Private mode', f'{server}/set')
    run_test(webview, window, _second_window_keeps_cookies, start_args={'private_mode': True})


def _second_window_keeps_cookies(window):
    assert _cookies_sent(window) == _COOKIE
    second = webview.create_window('Second', html='<html><body><h1>second</h1></body></html>')
    try:
        second.events.loaded.wait()
        # The clear is asynchronous: give it time to land before looking.
        time.sleep(1)
        assert _cookies_sent(window) == _COOKIE
    finally:
        second.destroy()
