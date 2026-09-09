"""Webhook signature helper."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.webhooks import sign_payload


def test_sign_payload_stable():
    a = sign_payload("secret", b'{"event":"audit.completed"}')
    b = sign_payload("secret", b'{"event":"audit.completed"}')
    c = sign_payload("other", b'{"event":"audit.completed"}')
    assert a == b
    assert a != c
    assert len(a) == 64
