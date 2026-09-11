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
        self.meta_robots = ""
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
            if name == "robots":
                self.meta_robots = ad.get("content", "")
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


def _normalize_url(url: str) -> str:
    """Normalize a URL for comparison: lowercase scheme+host, strip fragment, strip trailing slash."""
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return url.lower().split("#")[0].rstrip("/")
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or "/"
    query = parsed.query
    normalized = f"{scheme}://{netloc}{path}"
    if query:
        normalized += f"?{query}"
    return normalized


def _count_broken_links(page_url: str, links: list[str], origin: str, limit: int = 10) -> int:
    """Check internal links for 404s. Limited to *limit* checks to avoid slowness."""
    checked = 0
    broken = 0
    for href in links:
        if checked >= limit:
            break
        abs_url = urllib.parse.urljoin(page_url, href)
        if not abs_url.startswith(origin):
            continue
        abs_url = abs_url.split("#")[0]
        status, _, _ = _fetch(abs_url)
        checked += 1
        if status is not None and int(status) == 404:
            broken += 1
    return broken


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
        title = parser.title.strip()
        meta_desc = parser.meta_description.strip()
        canonical_href = parser.canonical or None
        # Canonical self-referencing: resolved canonical points to same URL
        canonical_self = False
        if canonical_href:
            canon_abs = urllib.parse.urljoin(url, canonical_href).split("#")[0]
            canonical_self = _normalize_url(canon_abs) == _normalize_url(url)
        # Meta robots noindex
        robots_content = parser.meta_robots.lower()
        meta_robots_noindex = "noindex" in robots_content
        # Broken links (internal only, max 10 checks)
        broken_count = _count_broken_links(url, parser.links, origin, limit=10) if html else 0

        page = {
            "url": url,
            "status": status,
            "error": err,
            "title": title,
            "meta_description": bool(meta_desc),
            "meta_description_text": meta_desc,
            "h1_count": len(parser.h1s),
            "canonical": canonical_href,
            "has_viewport": parser.has_viewport,
            "has_schema": parser.has_schema,
            "https": url.startswith("https://"),
            "canonical_self_referencing": canonical_self,
            "meta_robots_noindex": meta_robots_noindex,
            "title_length": len(title),
            "meta_length": len(meta_desc),
            "broken_links": broken_count,
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

    # Duplicate title / meta detection (titles appearing more than once)
    title_counts: dict[str, int] = {}
    meta_counts: dict[str, int] = {}
    for p in ok_pages:
        t = (p.get("title") or "").strip().lower()
        if t:
            title_counts[t] = title_counts.get(t, 0) + 1
        m = (p.get("meta_description_text") or "").strip().lower()
        if m:
            meta_counts[m] = meta_counts.get(m, 0) + 1
    dup_title_pages = sum(c for t, c in title_counts.items() if c > 1)
    dup_meta_pages = sum(c for t, c in meta_counts.items() if c > 1)

    # Averages
    avg_title_length = round(sum(p.get("title_length") or 0 for p in ok_pages) / len(ok_pages), 1) if ok_pages else 0.0
    avg_meta_length = round(sum(p.get("meta_length") or 0 for p in ok_pages) / len(ok_pages), 1) if ok_pages else 0.0

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
        "canonical_pct": pct(lambda p: p.get("canonical_self_referencing")),
        "noindex_pct": pct(lambda p: p.get("meta_robots_noindex")),
        "broken_links_total": sum(p.get("broken_links") or 0 for p in pages),
        "dup_title_pct": round(100 * dup_title_pages / len(ok_pages), 1) if ok_pages else 0.0,
        "dup_meta_pct": round(100 * dup_meta_pages / len(ok_pages), 1) if ok_pages else 0.0,
        "avg_title_length": avg_title_length,
        "avg_meta_length": avg_meta_length,
        "title_optimal_pct": pct(lambda p: 30 <= (p.get("title_length") or 0) <= 60),
        "meta_optimal_pct": pct(lambda p: 120 <= (p.get("meta_length") or 0) <= 160),
    }

    return {
        "pages": pages,
        "summary": summary,
        "error": None if pages else "crawl_failed",
    }
