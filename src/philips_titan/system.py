"""Decode the encrypted fields of GET /system (needs `cryptography`)."""

from __future__ import annotations

import base64
from typing import Any

from .pairing import AUTH_SHARED_KEY


def decrypt_field(value: str) -> str | None:
    """AES-CBC, key = first 16 bytes of the shared key, IV = first 16 bytes."""
    if not value:
        return None
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives.padding import PKCS7
    except ImportError:
        return None
    try:
        raw = base64.b64decode(value)
        dec = Cipher(algorithms.AES(AUTH_SHARED_KEY[:16]), modes.CBC(raw[:16])).decryptor()
        unpad = PKCS7(128).unpadder()
        out = unpad.update(dec.update(raw[16:]) + dec.finalize()) + unpad.finalize()
        return out.decode()
    except Exception:  # noqa: BLE001 - malformed field: just no value
        return None


def system_info(system: dict[str, Any]) -> dict[str, str | None]:
    """name, model (chassis), serial, software version (None if placeholder)."""
    sw = decrypt_field(system.get("softwareversion_encrypted", ""))
    if sw and sw.strip("-0.") == "":
        sw = None
    return {
        "name": system.get("name"),
        "model": decrypt_field(system.get("model_encrypted", "")),
        "serial": decrypt_field(system.get("serialnumber_encrypted", "")),
        "sw_version": sw,
    }
