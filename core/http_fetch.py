"""Bounded, cookie-aware GET for vendor pricing pages.

OVH's CDN answers the first GET of https://us.ovhcloud.com/public-cloud/prices/
(and robots.txt) with a same-URL 307 + a `cdn=` cookie. The cookie is bound
to the TLS connection: a new connection with that cookie is 307'd again,
but a second GET on the same connection returns 200 and the unchanged
pricing page. urllib opens a new connection for every hop, so it reports
307 and the live-check flags the row unreachable.

This helper follows 301/302/303/307/308 on the same HTTP(S) connection
(or a new connection only when the host changes), only to the same host
or to an ovhcloud.com host when the request started on ovhcloud.com, for
at most MAX_REDIRECTS hops, and sends cookies from earlier hops. It never
invents a 200: if the final hop is not a success, the last status is
returned so the live-check still flags unreachable.
"""
from __future__ import annotations

import http.client
import ssl
import urllib.request
from http.cookiejar import CookieJar
from urllib.parse import urljoin, urlsplit

MAX_REDIRECTS = 5
REDIRECT_CODES = {301, 302, 303, 307, 308}


def _host(url: str) -> str:
    host = urlsplit(url).hostname
    return host.lower() if host else ""


def _is_ovhcloud(host: str) -> bool:
    return host == "ovhcloud.com" or host.endswith(".ovhcloud.com")


def redirect_allowed(origin: str, target: str) -> bool:
    """Same host always; ovhcloud.com (any subdomain) only when origin is also ovhcloud.com.

    An https origin never follows a non-https target (no scheme downgrade).
    """
    o, t = urlsplit(origin), urlsplit(target)
    if t.scheme not in ("http", "https"):
        return False
    if o.scheme == "https" and t.scheme != "https":
        return False
    oh, th = _host(origin), _host(target)
    if not oh or not th:
        return False
    if th == oh:
        return True
    return _is_ovhcloud(oh) and _is_ovhcloud(th)


def _default_port(scheme: str) -> int:
    return 443 if scheme == "https" else 80


def _connect(parsed, timeout: float):
    host = parsed.hostname
    if not host:
        raise ValueError("URL has no host")
    port = parsed.port or _default_port(parsed.scheme)
    if parsed.scheme == "https":
        return http.client.HTTPSConnection(host, port, timeout=timeout, context=ssl.create_default_context())
    if parsed.scheme == "http":
        return http.client.HTTPConnection(host, port, timeout=timeout)
    raise ValueError(f"unsupported scheme {parsed.scheme!r}")


def _endpoint_of(url: str) -> tuple[str, str, int]:
    p = urlsplit(url)
    return p.scheme, _host(url), p.port or _default_port(p.scheme)


def _extract_cookies(cj: CookieJar, req: urllib.request.Request, headers) -> None:
    class _Resp:
        def info(self):
            return headers

        def geturl(self):
            return req.full_url

    cj.extract_cookies(_Resp(), req)


def get(url: str, *, headers: dict[str, str], timeout: float = 30,
        max_redirects: int = MAX_REDIRECTS) -> tuple[int | None, str]:
    """GET `url`, following a bounded number of safe redirects on one connection.

    Returns (status, body) on a completed hop, or (None, 'ExcName: ...') on a
    network error. Redirects that fail the host rule, or that exceed
    max_redirects, return the last redirect status and an empty body.
    """
    parsed = urlsplit(url)
    try:
        conn = _connect(parsed, timeout)
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    cj = CookieJar()
    current = url
    last_status: int | None = None
    try:
        for _ in range(max_redirects + 1):
            p = urlsplit(current)
            path = p.path or "/"
            if p.query:
                path += "?" + p.query
            req_headers = dict(headers)
            dummy = urllib.request.Request(current, headers=req_headers)
            cj.add_cookie_header(dummy)
            cookie = dummy.get_header("Cookie")
            if cookie:
                req_headers["Cookie"] = cookie
            conn.request("GET", path, headers=req_headers)
            resp = conn.getresponse()
            st = resp.status
            hdrs = resp.headers
            body = resp.read().decode("utf-8", "ignore")
            _extract_cookies(cj, dummy, hdrs)
            last_status = st
            if st not in REDIRECT_CODES:
                return st, body
            loc = hdrs.get("Location")
            if not loc:
                return st, body
            nxt = urljoin(current, loc)
            if not redirect_allowed(url, nxt):
                return st, ""
            if _endpoint_of(nxt) != _endpoint_of(current):
                conn.close()
                conn = _connect(urlsplit(nxt), timeout)
            current = nxt
        return last_status, ""
    except Exception as e:  # DNS, TLS, timeout, refused
        return None, f"{type(e).__name__}: {e}"
    finally:
        try:
            conn.close()
        except Exception:
            pass
