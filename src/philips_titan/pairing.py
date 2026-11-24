"""JointSpace v6 pairing (PIN shown on the TV).

Flow:
1. POST pair/request (no auth) with a device spec -> auth_key, timestamp, timeout.
   The TV now shows a 4-digit PIN.
2. POST pair/grant with Digest auth (user = device id, password = auth_key)
   and an HMAC-SHA1 signature over timestamp + PIN.
3. Afterwards device id / auth_key are the permanent Digest credentials.

The shared HMAC key is the one used by all JointSpace clients (haphilipsjs,
pylips, the official app).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import string
from dataclasses import dataclass
from typing import Any

import httpx

from .client import TitanError, TitanTV

AUTH_SHARED_KEY = base64.b64decode(
    "ZmVay1EQVFOaZhwQ4Kv81ypLAZNczV9sG4KkseXWn1NEk6cXmPKO/MCa9sryslvLCFMnNe4Z4CPXzToowvhHvA=="
)


def _signature(timestamp: str, pin: str) -> str:
    # base64 of the *raw* HMAC-SHA1 digest (same as haphilipsjs 3.3.0)
    digest = hmac.new(AUTH_SHARED_KEY, (timestamp + pin).encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def new_device_id() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(16))


def device_spec(device_id: str, app_name: str = "philips-titan") -> dict[str, Any]:
    return {
        "device_name": app_name,
        "device_os": "Linux",
        "app_id": "org.philips_titan.client",
        "app_name": app_name,
        "type": "native",
        "id": device_id,
    }


@dataclass
class PairingSession:
    device: dict[str, Any]
    auth_key: str
    timestamp: Any
    timeout: int | None

    @property
    def username(self) -> str:
        return str(self.device["id"])

    @property
    def password(self) -> str:
        return self.auth_key


async def pair_request(tv: TitanTV, device_id: str | None = None) -> PairingSession:
    device = device_spec(device_id or new_device_id())
    access: dict[str, Any] = {"scope": ["read", "write", "control"]}
    system = await tv.system()
    if isinstance(system, dict) and system.get("featuring"):
        access["featuring"] = system["featuring"]
    result = await tv.post(
        "pair/request", {"access": access, "device": device}, auth=False
    )
    if not isinstance(result, dict) or result.get("error_id") != "SUCCESS":
        raise TitanError(f"pair/request failed: {result!r}")
    return PairingSession(
        device=device,
        auth_key=result["auth_key"],
        timestamp=result["timestamp"],
        timeout=result.get("timeout"),
    )


async def pair_grant(tv: TitanTV, session: PairingSession, pin: str) -> Any:
    pin = pin.strip()
    body = {
        "auth": {
            "auth_appId": "1",
            "pin": pin,
            "auth_timestamp": session.timestamp,
            "auth_signature": _signature(str(session.timestamp), pin),
        },
        "device": session.device,
    }
    result = await tv.request(
        "POST",
        "pair/grant",
        body,
        auth_override=httpx.DigestAuth(session.username, session.password),
    )
    if isinstance(result, dict) and result.get("error_id") not in (None, "SUCCESS"):
        raise TitanError(f"pair/grant failed: {result!r}")
    return result
