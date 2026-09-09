"""Billing catalog includes SEO addon."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.billing import SEO_ADDONS, _get_one_off_product


def test_seo_addon_catalog():
    product = _get_one_off_product("addon", "seo_full")
    assert product["amount_cents"] == 4900
    assert product["seo_credits"] == 1
    assert "seo_full" in SEO_ADDONS


def test_unknown_addon_raises():
    try:
        _get_one_off_product("addon", "nope")
        assert False, "expected ValueError"
    except ValueError:
        pass
