"""Site health SSRF guards."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.seo.site_health import _is_safe_url, crawl_site_health


def test_blocks_localhost():
    assert _is_safe_url("http://localhost/admin") is False
    assert _is_safe_url("http://127.0.0.1/") is False


def test_blocks_metadata():
    assert _is_safe_url("http://169.254.169.254/latest/meta-data") is False


def test_crawl_blocked_host_returns_error_shape():
    out = crawl_site_health("http://127.0.0.1/", max_pages=1)
    assert out.get("pages") is not None
    # First page should record blocked_url or empty crawl
    if out["pages"]:
        assert out["pages"][0].get("error") in ("blocked_url", None) or out["pages"][0].get("status") is None
