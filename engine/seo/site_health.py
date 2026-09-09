"""AI Site Health crawler — SSRF-safe, bounded."""

from __future__ import annotations

import logging
import re
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any, Optional

logger = logging.getLogger(__name__)

MAX_PAGES = 25
MAX_BYTES = 512_000
FETCH_TIMEOUT = 10


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self._in_title = False
        self.meta_description = ""
        self.h1s: list[str] = []
        self.canonical = ""
        self.has_viewport = False
        self.links: list[str] = []
        self.has_schema = False
        self._in_h1 = False
        self._h1_buf = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        ad = {k: (v or "") for k, v in attrs}
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            name = (ad.get("name") or ad.get("property") or "").lower()
            if name == "description":
                self.meta_description = ad.get("content", "")
            if name == "viewport":
                self.has_viewport = True
        elif tag == "link" and ad.get("rel", "").lower() == "canonical":
            self.canonical = ad.get("href", "")
        elif tag == "h1":
            self._in_h1 = True
            self._h1_buf = ""
        elif tag == "a" and ad.get("href"):
            self.links.append(ad["href"])
        elif tag == "script" and "ld+json" in (ad.get("type") or "").lower():
            self.has_schema = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag == "h1" and self._in_h1:
            self._in_h1 = False
            text = self._h1_buf.strip()
            if text:
                self.h1s.append(text)

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        if self._in_h1:
            self._h1_buf += data


def _is_blocked_ip(ip: str) -> bool:
    try:
        parts = [int(p) for p in ip.split(".")]
    except ValueError:
        return True
    if len(parts) != 4:
        return True
    a, b = parts[0], parts[1]
    if a == 0 or a == 127 or a == 10:
        return True
    if a == 172 and 16 <= b <= 31:
        return True
    if a == 192 and b == 168:
        return True
    if a == 169 and b == 254:
        return True
    return False


def _is_safe_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    if not host or host == "localhost" or host.endswith(".localhost"):
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = info[4][0]
        if ":" in ip:
            low = ip.lower()
            if ip == "::1" or low.startswith("fc") or low.startswith("fd") or low.startswith("fe80"):
                return False
            continue
        if _is_blocked_ip(ip):
            return False
    return True


def _fetch(url: str) -> tuple[Optional[int], str, Optional[str]]:
    if not _is_safe_url(url):
        return None, "", "blocked_url"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "GathaSiteHealth/1.0"})
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT, context=ctx) as resp:
            status = getattr(resp, "status", 200)
            raw = resp.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                return status, "", "body_too_large"
            return status, raw.decode("utf-8", errors="replace"), None
    except Exception as exc:  # noqa: BLE001
        return None, "", str(exc)[:200]


def crawl_site_health(start_url: str, max_pages: int = MAX_PAGES) -> dict[str, Any]:
    if not start_url.startswith("http"):
        start_url = "https://" + start_url.lstrip("/")

    parsed = urllib.parse.urlparse(start_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    queue = [start_url]
    seen: set[str] = set()
    pages: list[dict[str, Any]] = []
    robots_ok = None
    sitemap_ok = None

    robots_status, _, robots_err = _fetch(urllib.parse.urljoin(origin, "/robots.txt"))
    robots_ok = robots_status == 200 and not robots_err
    sm_status, _, sm_err = _fetch(urllib.parse.urljoin(origin, "/sitemap.xml"))
    sitemap_ok = sm_status == 200 and not sm_err

    while queue and len(pages) < max_pages:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        status, html, err = _fetch(url)
        parser = _LinkParser()
        if html:
            try:
                parser.feed(html)
            except Exception:  # noqa: BLE001
                pass
        page = {
            "url": url,
            "status": status,
            "error": err,
            "title": parser.title.strip(),
            "meta_description": bool(parser.meta_description.strip()),
            "h1_count": len(parser.h1s),
            "canonical": parser.canonical or None,
            "has_viewport": parser.has_viewport,
            "has_schema": parser.has_schema,
            "https": url.startswith("https://"),
        }
        pages.append(page)

        for href in parser.links:
            abs_url = urllib.parse.urljoin(url, href)
            if not abs_url.startswith(origin):
                continue
            abs_url = abs_url.split("#")[0]
            if abs_url not in seen and abs_url not in queue:
                queue.append(abs_url)

    ok_pages = [p for p in pages if p.get("status") and int(p["status"]) < 400]
    def pct(pred) -> float:
        if not ok_pages:
            return 0.0
        return round(100 * sum(1 for p in ok_pages if pred(p)) / len(ok_pages), 1)

    summary = {
        "pages_crawled": len(pages),
        "ok_pages": len(ok_pages),
        "https_pct": pct(lambda p: p.get("https")),
        "title_pct": pct(lambda p: bool(p.get("title"))),
        "meta_pct": pct(lambda p: p.get("meta_description")),
        "h1_pct": pct(lambda p: (p.get("h1_count") or 0) > 0),
        "viewport_pct": pct(lambda p: p.get("has_viewport")),
        "schema_pct": pct(lambda p: p.get("has_schema")),
        "robots_txt": robots_ok,
        "sitemap_xml": sitemap_ok,
    }

    return {
        "pages": pages,
        "summary": summary,
        "error": None if pages else "crawl_failed",
    }
