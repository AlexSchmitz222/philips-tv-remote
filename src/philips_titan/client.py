"""Low-level async client for the JointSpace v6 API on Titan OS.

Design constraints learned from the device (PQS8651/12):
* HTTPS on port 1926 with a self-signed TPV certificate.
* HTTP Digest auth. The body must be sent with the *first* request – an empty
  probe POST is answered with 503 instead of 401. httpx does this correctly.
* Requests are serialised through a lock with a minimum interval. A stress
  test ran 4 requests/s for 90 s without any slowdown (2026-11-24); the
  known API hang came from GET ambilight/lounge, which is blocked below.
"""

from __future__ import annotations

import asyncio
import json
import ssl
import time
from typing import Any

import httpx

from . import models as m
from .layout import MenuLayout
from .models import AmbilightColors, AmbilightState, Volume

DEFAULT_PORT = 1926
API_VERSION = 6
DEFAULT_MIN_INTERVAL = 0.5  # between any two requests; reads stress-tested fine at 0.25 s
# Writes need far more room: the TV re-applies Ambilight/menu state and
# crashed when settings were changed in quick succession (2026-11-24, HA
# with 0.5 s for everything). The original notes said 1.5-2 s.
# Write stress test 2026-11-25: brightness and style writes fine at 1.0-1.5 s;
# category switches + lounge colour at 1.0 s: one write took 1.2 s (others
# ~0.02 s) -> 1.5 s keeps a margin.
WRITE_INTERVAL = 1.5  # between two setting writes (menu update, ambilight, volume)
KEY_INTERVAL = 1.0    # between two remote keys (untested below; conservative)
# POSTs that only read
READ_POSTS = frozenset({"menuitems/settings/current", "pair/request", "pair/grant"})
DEFAULT_TIMEOUT = 10.0
CONNECT_TIMEOUT = 4.0  # in standby the TV is not reachable at all

# After a timeout the API is usually wedged; hammering it makes things worse.
# Requests fail fast during a growing cooldown instead.
COOLDOWN_START = 30.0
COOLDOWN_MAX = 300.0

# Requests known to wedge the API on Titan OS. They are refused client-side.
UNSAFE_REQUESTS: dict[tuple[str, str], str] = {
    ("GET", "ambilight/lounge"): "hängte die API auf (Dump 2026-11-24, PQS8651)",
}


class TitanError(Exception):
    """Base error."""


class TitanConnectionError(TitanError):
    """TV not reachable / timed out."""


class TitanAuthError(TitanError):
    """Credentials rejected."""


class TitanUnreachableError(TitanConnectionError):
    """No TCP connection possible – normally the TV is in standby."""


class TitanCooldownError(TitanConnectionError):
    """Request refused because the TV recently stopped responding."""


class TitanUnsafeRequestError(TitanError):
    """Request is on the list of requests known to crash the TV."""


def _ssl_context() -> ssl.SSLContext:
    # No CA loading (blocking disk I/O, and the cert is self-signed anyway).
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    # The TV's TLS stack is old; be lenient about ciphers / key sizes.
    ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
    return ctx


class TitanTV:
    def __init__(
        self,
        host: str,
        username: str | None = None,
        password: str | None = None,
        *,
        port: int = DEFAULT_PORT,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        write_interval: float = WRITE_INTERVAL,
        key_interval: float = KEY_INTERVAL,
        timeout: float = DEFAULT_TIMEOUT,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.host = host
        self.base_url = f"https://{host}:{port}/{API_VERSION}/"
        self.min_interval = min_interval
        self.write_interval = write_interval
        self.key_interval = key_interval
        self._last_write = 0.0
        self.layout = MenuLayout.default()
        self._auth = httpx.DigestAuth(username, password) if username else None
        self._own_client = client is None
        self._client = client or httpx.AsyncClient(
            verify=_ssl_context(), timeout=httpx.Timeout(timeout, connect=CONNECT_TIMEOUT)
        )
        self._lock = asyncio.Lock()
        self._last_request = 0.0
        self._cooldown = 0.0
        self._cooldown_until = 0.0

    async def close(self) -> None:
        if self._own_client:
            await self._client.aclose()

    async def __aenter__(self) -> "TitanTV":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    def set_credentials(self, username: str, password: str) -> None:
        self._auth = httpx.DigestAuth(username, password)

    # ------------------------------------------------------------------ core

    async def request(
        self,
        method: str,
        path: str,
        body: Any = None,
        *,
        auth: bool = True,
        auth_override: httpx.Auth | None = None,
        allow_unsafe: bool = False,
    ) -> Any:
        """Send one throttled request and return the decoded JSON (or None)."""
        path = path.strip("/")
        reason = UNSAFE_REQUESTS.get((method.upper(), path))
        if reason and not allow_unsafe:
            raise TitanUnsafeRequestError(f"{method} {path} gesperrt: {reason}")
        url = self.base_url + path
        content = None
        headers = {}
        if body is not None:
            content = json.dumps(body, separators=(",", ":")).encode()
            headers["Content-Type"] = "application/json"
        use_auth = auth_override or (self._auth if auth else None)

        async with self._lock:
            remaining = self._cooldown_until - time.monotonic()
            if remaining > 0:
                raise TitanCooldownError(
                    f"{method} {path}: TV hat zuletzt nicht geantwortet, "
                    f"Pause noch {remaining:.0f} s"
                )
            kind = _request_kind(method, path)
            gap = {"write": self.write_interval, "key": self.key_interval}.get(kind, 0.0)
            wait = max(
                self._last_request + self.min_interval,
                self._last_write + gap if gap else 0.0,
            ) - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                resp = await self._client.request(
                    method, url, content=content, headers=headers, auth=use_auth
                )
            except (httpx.ConnectError, httpx.ConnectTimeout) as err:
                # TV off / standby: not a wedged API, so no cooldown.
                raise TitanUnreachableError(f"{method} {path}: {err!r}") from err
            except (httpx.TimeoutException, httpx.TransportError) as err:
                # Connected but no (valid) answer: API most likely wedged.
                self._cooldown = min(
                    max(self._cooldown * 2, COOLDOWN_START), COOLDOWN_MAX
                )
                self._cooldown_until = time.monotonic() + self._cooldown
                raise TitanConnectionError(f"{method} {path}: {err!r}") from err
            finally:
                self._last_request = time.monotonic()
                if kind != "read":
                    self._last_write = self._last_request
            self._cooldown = 0.0

        if resp.status_code == 401:
            raise TitanAuthError(f"{method} {path}: 401 Unauthorized")
        if resp.status_code >= 400:
            raise TitanError(f"{method} {path}: HTTP {resp.status_code} {resp.text[:200]}")
        if not resp.content.strip():
            return None
        try:
            return resp.json()
        except ValueError:
            return resp.text

    async def get(self, path: str, *, auth: bool = True) -> Any:
        return await self.request("GET", path, auth=auth)

    async def post(self, path: str, body: Any, *, auth: bool = True) -> Any:
        return await self.request("POST", path, body, auth=auth)

    # ------------------------------------------------------------- helpers

    async def system(self) -> dict[str, Any]:
        return await self.get("system", auth=False)

    async def menu_structure(self) -> dict[str, Any]:
        return await self.get("menuitems/settings/structure")

    async def menu_current(self, node_ids: list[int]) -> dict[str, Any]:
        return await self.post(
            "menuitems/settings/current",
            {"version": 1, "nodes": [{"nodeid": n} for n in node_ids]},
        )

    async def menu_update(self, node_id: int, string_id: str, data: dict[str, Any]) -> Any:
        """Write a menu node. Titan OS requires ``version: 1``."""
        return await self.post(
            "menuitems/settings/update",
            {
                "version": 1,
                "values": [
                    {
                        "value": {
                            "Nodeid": node_id,
                            "Controllable": True,
                            "Available": True,
                            "string_id": string_id,
                            "data": data,
                        }
                    }
                ],
            },
        )

    # ------------------------------------------------------- high level API
    # Each method sends only request sequences verified on the device
    # (docs/api.md). Writes to the same node are not repeated needlessly.

    async def load_menu_layout(self) -> MenuLayout:
        """Detect node ids / items from the menu structure (one GET).
        Keeps the default layout if the structure can't be read."""
        self.layout = MenuLayout.from_structure(await self.menu_structure())
        return self.layout

    async def ambilight_state(self) -> AmbilightState:
        """Read style, brightness and saturation in a single request."""
        lay = self.layout
        values = _menu_values(await self.menu_current(lay.state_nodes))
        active = (values.get(lay.style.id) or {}).get("activenode_id")
        style = None
        if active in (n.id for n in lay.categories):
            item = (values.get(active) or {}).get("selected_item")
            style = lay.style_for(active, item)
            if style is None and len([s for s in lay.styles if s.category == active]) == 1:
                style = next(s for s in lay.styles if s.category == active)
        return m.AmbilightState(
            on=active is not None and active != lay.off,
            style=style,
            brightness=(values.get(lay.brightness.id) or {}).get("value") if lay.brightness else None,
            saturation=(values.get(lay.saturation.id) or {}).get("value") if lay.saturation else None,
        )

    async def ambilight_colors(self) -> AmbilightColors:
        """LED colours (GET ambilight/processed – safe, unlike lounge).

        On the 65PQS8651/12 (fw 066.002.126.131) processed, measured and cached
        return all zeros in every style, so this is not useful there.
        """
        return AmbilightColors.from_processed(await self.get("ambilight/processed") or {})

    async def ambilight_off(self) -> None:
        lay = self.layout
        await self.menu_update(lay.style.id, lay.style.sid, {"activenode_id": lay.off})

    async def set_ambilight_style(
        self, key: str, current: AmbilightState | None = None
    ) -> None:
        """Activate a style. ``current`` (from ambilight_state) avoids
        redundant writes – the TV ignores re-selecting the active item anyway."""
        lay = self.layout
        style = lay.style_by_key(key)
        cur_cat = current.style.category if current and current.on and current.style else None
        cur_item = current.style.item if current and current.style else None
        if cur_cat != style.category:
            await self.menu_update(lay.style.id, lay.style.sid, {"activenode_id": style.category})
        # a list with a single entry (fixed colour) always has it selected
        single = len([s for s in lay.styles if s.category == style.category]) == 1
        if not single and cur_item != style.item:
            await self.menu_update(style.category, style.category_sid, {"selected_item": style.item})

    async def set_ambilight_brightness(self, value: int) -> None:
        """Menu brightness (0..10 on the 65PQS8651) – works for all styles."""
        b = self.layout.brightness
        if b is None:
            raise TitanError("this TV has no Ambilight brightness node")
        await self.menu_update(b.id, b.sid, {"value": max(b.min, min(b.max, int(value)))})

    async def set_ambilight_saturation(self, value: int) -> None:
        sat = self.layout.saturation
        if sat is None:
            raise TitanError("this TV has no Ambilight saturation node")
        await self.menu_update(sat.id, sat.sid, {"value": max(sat.min, min(sat.max, int(value)))})

    async def set_ambilight_colour(
        self,
        hue: int,
        saturation: int,
        brightness: int = 255,
        current: AmbilightState | None = None,
    ) -> None:
        """Fixed colour, HSB each 0..255 (hue 0 = red, 85 = green, 170 = blue).

        Switches to the fixed-colour style first unless ``current`` says it
        is already active. Note: after standby the TV shows its menu colour
        again, the lounge colour has to be re-sent.
        """
        fixed = self.layout.fixed_colour
        if fixed is None:
            raise TitanError("this TV has no fixed-colour Ambilight style")
        if not (current and current.on and current.style == fixed):
            await self.set_ambilight_style(fixed.key, current)
        clamp = lambda v: max(0, min(255, int(v)))  # noqa: E731
        await self.post(
            "ambilight/lounge",
            {
                "color": {"hue": clamp(hue), "saturation": clamp(saturation), "brightness": clamp(brightness)},
                "colordelta": {"hue": 0, "saturation": 0, "brightness": 0},
                "speed": 0,
                "mode": "Default",
            },
        )

    async def volume(self) -> Volume:
        d = await self.get("audio/volume")
        return m.Volume(current=d["current"], muted=d["muted"], min=d.get("min", 0), max=d.get("max", 60))

    async def set_volume(self, current: int, muted: bool = False) -> None:
        await self.post("audio/volume", {"muted": muted, "current": int(current)})

    async def set_muted(self, muted: bool, current: Volume | None = None) -> None:
        """Mute/unmute. ``audio/volume`` ignores the ``muted`` flag on Titan OS,
        so this toggles with the Mute key – only if the state differs."""
        if current is None:
            current = await self.volume()
        if current.muted != muted:
            await self.send_key("Mute")

    async def notify_change(
        self, state: dict[str, Any] | None = None, timeout: float = 30.0
    ) -> dict[str, Any] | None:
        """Long-poll ``notifychange``.

        Returns as soon as the TV's state differs from ``state`` (pass the
        previous result; ``{}`` returns the full state immediately). Returns
        None if nothing changed within ``timeout``.

        WARNING – not for continuous use on Titan OS: a long-poll that the
        client abandons (timeout) apparently stays open on the TV. They pile
        up until the TV only answers 503 (2026-11-24); a power cycle clears
        it. Notifications also arrived only sporadically. The HA integration
        therefore polls instead. Kept for experiments.

        Runs outside the request lock, and its read timeout is the normal
        "no change" case, so it never starts a cooldown.
        """
        if time.monotonic() < self._cooldown_until:
            raise TitanCooldownError("notifychange: cooldown active")
        try:
            resp = await self._client.post(
                self.base_url + "notifychange",
                json={"notification": state or {}},
                auth=self._auth,
                timeout=httpx.Timeout(timeout + 5, connect=CONNECT_TIMEOUT),
            )
        except httpx.ReadTimeout:
            return None
        except (httpx.ConnectError, httpx.ConnectTimeout) as err:
            raise TitanUnreachableError(f"notifychange: {err!r}") from err
        except (httpx.TimeoutException, httpx.TransportError) as err:
            # TV closing a lingering connection is not unusual
            raise TitanConnectionError(f"notifychange: {err!r}") from err
        if resp.status_code == 401:
            raise TitanAuthError("notifychange: 401 Unauthorized")
        if resp.status_code >= 400:
            raise TitanError(f"notifychange: HTTP {resp.status_code}")
        if not resp.content.strip():
            return {}
        try:
            data = resp.json()
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    async def network_devices(self) -> list[dict[str, Any]]:
        data = await self.get("network/devices")
        return data if isinstance(data, list) else []

    async def wol_mac(self) -> str | None:
        """MAC of the interface with Wake-on-LAN enabled (Ethernet preferred)."""
        devices = await self.network_devices()
        devices.sort(key=lambda d: d.get("type") != "Ethernet")
        for dev in devices:
            if dev.get("mac") and str(dev.get("wake-on-lan", "")).lower() == "enabled":
                return dev["mac"]
        return next((d["mac"] for d in devices if d.get("mac") and d.get("ip")), None)

    async def send_key(self, key: str) -> None:
        await self.post("input/key", {"key": key})

    async def send_channel_number(self, number: str | int) -> None:
        """Type a channel number with the digit keys (TV switches after its
        own entry timeout). Keys are throttled by KEY_INTERVAL."""
        digits = str(number).strip()
        if not digits.isdigit() or len(digits) > 4:
            raise ValueError(f"invalid channel number: {number!r}")
        for d in digits:
            await self.send_key(f"Digit{d}")

    async def standby(self) -> None:
        await self.send_key("Standby")


def _request_kind(method: str, path: str) -> str:
    """read / key / write – writes are spaced much further apart."""
    if method.upper() != "POST" or path in READ_POSTS:
        return "read"
    if path == "input/key":
        return "key"
    return "write"


def _menu_values(response: Any) -> dict[int, dict[str, Any]]:
    """Map Nodeid -> data from a menuitems/settings/current response."""
    out: dict[int, dict[str, Any]] = {}

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            if isinstance(o.get("Nodeid"), int):
                out[o["Nodeid"]] = o.get("data") or {}
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(response)
    return out
