"""AES-256-GCM encryption for stored API keys/tokens.

app2 (Node.js) encrypts credentials with AES-256-GCM using the shared
TOKEN_ENCRYPTION_KEY env var. app1 (Python) decrypts them here when the
worker needs the plaintext key to call a third-party API.

Ciphertext format (produced by app2/src/lib/encryption.ts):
    <iv>:<authTag>:<data>   (all base64)

The 32-byte key is derived from TOKEN_ENCRYPTION_KEY via SHA-256 so a
human-readable passphrase or a raw Fernet key both work.
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _get_key() -> bytes:
    """Derive a 32-byte AES key from the TOKEN_ENCRYPTION_KEY env var."""
    key = os.environ.get("TOKEN_ENCRYPTION_KEY", "")
    if not key:
        raise RuntimeError(
            "TOKEN_ENCRYPTION_KEY is not set. Generate one with: "
            'python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    return hashlib.sha256(key.encode("utf-8")).digest()[:32]


def encrypt_token(plaintext: str) -> str:
    """Encrypt a token for storage.

    Uses AES-256-GCM and returns the ``<iv>:<authTag>:<data>`` format that
    app2's ``decryptToken`` expects. This lets app1 encrypt when needed
    (e.g. seeding/test fixtures) while remaining cross-compatible.
    """
    iv = os.urandom(12)
    aesgcm = AESGCM(_get_key())
    ct = aesgcm.encrypt(iv, plaintext.encode("utf-8"), None)
    # AESGCM produces ciphertext + 16-byte tag appended.
    data = ct[:-16]
    auth_tag = ct[-16:]
    return ":".join(
        base64.b64encode(part).decode("utf-8")
        for part in (iv, auth_tag, data)
    )


def decrypt_token(ciphertext: str) -> str:
    """Decrypt a token encrypted by app2 (Node.js AES-256-GCM).

    Format: ``<iv>:<authTag>:<data>`` (all base64).
    Returns the plaintext credential.
    """
    parts = ciphertext.split(":")
    if len(parts) != 3:
        raise ValueError("Invalid ciphertext format")
    iv = base64.b64decode(parts[0])
    auth_tag = base64.b64decode(parts[1])
    data = base64.b64decode(parts[2])
    aesgcm = AESGCM(_get_key())
    # AESGCM expects the auth tag appended to the ciphertext.
    plaintext = aesgcm.decrypt(iv, data + auth_tag, None)
    return plaintext.decode("utf-8")


__all__ = ["encrypt_token", "decrypt_token"]
