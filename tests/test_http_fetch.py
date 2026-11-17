"""Bounded cookie-aware GET: same-host (or ovhcloud.com) redirects only; never invent a 200."""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from core import http_fetch

HEADERS = {"User-Agent": "LanternWorksPriceCheck-test", "Accept": "text/html,*/*"}
PAGE = b"<html><body><p>l40s-90 1x L40S $1.8 $1,296</p></body></html>"


def _send(handler, status, *, location=None, cookie=None, body=b"", content_type=None):
    """HTTP/1.1 response with Content-Length so the client can reuse the connection."""
    handler.send_response(status)
    if location is not None:
        handler.send_header("Location", location)
    if cookie is not None:
        handler.send_header("Set-Cookie", cookie)
    if content_type is not None:
        handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    if body:
        handler.wfile.write(body)


def _serve(handler_cls):
    httpd = HTTPServer(("127.0.0.1", 0), handler_cls)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    host, port = httpd.server_address
    return httpd, f"http://{host}:{port}"


def test_redirect_allowed_same_host_and_ovhcloud():
    assert http_fetch.redirect_allowed(
        "https://us.ovhcloud.com/public-cloud/prices/",
        "https://us.ovhcloud.com/public-cloud/prices/",
    )
    assert http_fetch.redirect_allowed(
        "https://us.ovhcloud.com/public-cloud/prices/",
        "https://www.ovhcloud.com/en/public-cloud/prices/",
    )
    assert not http_fetch.redirect_allowed(
        "https://us.ovhcloud.com/public-cloud/prices/",
        "https://evil.example/public-cloud/prices/",
    )
    assert not http_fetch.redirect_allowed(
        "https://verda.com/pricing",
        "https://us.ovhcloud.com/public-cloud/prices/",
    )
    assert not http_fetch.redirect_allowed(
        "https://us.ovhcloud.com/public-cloud/prices/",
        "http://us.ovhcloud.com/public-cloud/prices/",
    )


def test_same_host_cookie_307_returns_final_page():
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            if self.path == "/prices/" and "cdn=" not in (self.headers.get("Cookie") or ""):
                _send(self, 307, location="/prices/", cookie="cdn=test-token; Path=/")
                return
            if self.path == "/prices/":
                _send(self, 200, content_type="text/html", body=PAGE)
                return
            _send(self, 404)

        def log_message(self, *args):
            pass

    httpd, base = _serve(H)
    try:
        st, body = http_fetch.get(base + "/prices/", headers=HEADERS, timeout=5)
        assert st == 200
        assert "$1.8" in body and "$1,296" in body
    finally:
        httpd.shutdown()


def test_offsite_redirect_is_not_followed():
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            _send(self, 307, location="https://evil.example/prices/")

        def log_message(self, *args):
            pass

    httpd, base = _serve(H)
    try:
        st, body = http_fetch.get(base + "/prices/", headers=HEADERS, timeout=5)
        assert st == 307
        assert body == ""
    finally:
        httpd.shutdown()


def test_too_many_hops_returns_last_redirect_status():
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            n = int(self.path.rsplit("/", 1)[-1] or "0")
            _send(self, 307, location=f"/hop/{n + 1}")

        def log_message(self, *args):
            pass

    httpd, base = _serve(H)
    try:
        st, body = http_fetch.get(base + "/hop/0", headers=HEADERS, timeout=5, max_redirects=5)
        assert st == 307
        assert body == ""
    finally:
        httpd.shutdown()


def test_checker_fetch_follows_cookie_307_and_still_flags_a_missing_price():
    """Integration: check_gpu_sources.fetch gets the page; a missing quote still fails."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import check_gpu_sources as c

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            if "cdn=" not in (self.headers.get("Cookie") or ""):
                _send(self, 307, location=self.path, cookie="cdn=test-token; Path=/")
                return
            _send(self, 200, content_type="text/html",
                  body=b"<html><body><p>1x H100 80GB $2.00/h</p></body></html>")

        def log_message(self, *args):
            pass

    httpd, base = _serve(H)
    url = base + "/prices/"
    try:
        st, body = c.fetch(url)
        assert st == 200
        text = c.visible_text(body)
        assert c.price_found("2.00", "1x H100 80GB $2.00/h", text)
        assert not c.price_found("9.99", "1x H100 80GB $9.99/h", text)
    finally:
        httpd.shutdown()
