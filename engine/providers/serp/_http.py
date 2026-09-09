"""Tiny HTTP helpers shared by SERP adapters."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional


def get_json(
    url: str,
    *,
    timeout: int = 20,
    headers: Optional[dict[str, str]] = None,
    data: Optional[bytes] = None,
    method: Optional[str] = None,
) -> dict[str, Any]:
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def post_json(
    url: str,
    payload: Any,
    *,
    timeout: int = 30,
    headers: Optional[dict[str, str]] = None,
) -> Any:
    body = json.dumps(payload).encode("utf-8")
    merged = {"Content-Type": "application/json", **(headers or {})}
    return get_json(url, timeout=timeout, headers=merged, data=body, method="POST")


def encode_query(params: dict[str, Any]) -> str:
    return urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})


def clean_domain(domain: str) -> str:
    return (
        domain.lower()
        .replace("https://", "")
        .replace("http://", "")
        .replace("www.", "")
        .rstrip("/")
    )
