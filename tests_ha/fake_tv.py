"""Fake Titan OS TV on top of httpx.MockTransport."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

SYSTEM = {
    "name": "65PQS8651/12",
    "api_version": {"Major": 6, "Minor": 1, "Patch": 0},
    "featuring": {"systemfeatures": {"pairing_type": "digest_auth_pairing", "os_type": "Linux"}},
    # real encrypted values from the 65PQS8651/12 (model TPN266E, placeholder sw version)
    "model_encrypted": "K2kseVsmQFgkd15gKkJ+aj0n5NuODh3TdvfyYRUMx9U=",
    "softwareversion_encrypted": "K2kseVsmQFgkd15gKkJ+atJJI6kYBl5fIhF2Isg2DFHegH9Cg/LU4b6H/tjCh/AJ",
}


class FakeTV:
    def __init__(self) -> None:
        self.on = True
        self.pin = "1234"
        self.menu = {300: {"activenode_id": 320}, 320: {"selected_item": 322},
                     330: {"selected_item": 331}, 340: {"selected_item": 345},
                     710: {"value": 5}, 720: {"value": 0}}
        self.volume = {"muted": False, "current": 16, "min": 0, "max": 60}
        self.lounge = None
        self.keys: list[str] = []
        self.log: list[tuple[str, str]] = []
        self.context = "WatchTv"
        self.notify_supported = True
        self._changed: asyncio.Event | None = None

    # ---- simulate the user changing things on the TV itself
    def remote_menu_change(self, node: int, data: dict) -> None:
        self.menu.setdefault(node, {}).update(data)
        self._signal()

    def remote_context_change(self, level1: str) -> None:
        self.context = level1
        self._signal()

    def _signal(self) -> None:
        if self._changed:
            self._changed.set()

    def _notify_state(self) -> dict:
        return {"powerstate": {"powerstate": "On"},
                "context": {"level1": self.context, "level2": "NA", "level3": "NA", "data": "NA"}}

    async def handler(self, request: httpx.Request) -> httpx.Response:
        if not self.on:
            raise httpx.ConnectError("No route to host", request=request)
        path = request.url.path.removeprefix("/6/")
        body = json.loads(request.content) if request.content else None
        self.log.append((request.method, path))
        if path == "system":
            return httpx.Response(200, json=SYSTEM)
        if path == "pair/request":
            return httpx.Response(200, json={"error_id": "SUCCESS", "auth_key": "secret", "timestamp": 42, "timeout": 60})
        if path == "pair/grant":
            ok = body["auth"]["pin"] == self.pin
            return httpx.Response(200, json={"error_id": "SUCCESS" if ok else "INVALID_PIN"})
        if path == "menuitems/settings/current":
            vals = [{"value": {"Nodeid": n["nodeid"], "data": self.menu.get(n["nodeid"], {})}} for n in body["nodes"]]
            return httpx.Response(200, json={"version": 1, "values": vals})
        if path == "menuitems/settings/update":
            v = body["values"][0]["value"]
            self.menu.setdefault(v["Nodeid"], {}).update(v["data"])
            self._signal()
            return httpx.Response(200, json={})
        if path == "audio/volume":
            if request.method == "POST":
                self.volume["current"] = body["current"]  # muted flag is ignored by the TV
                return httpx.Response(200)
            return httpx.Response(200, json=self.volume)
        if path == "notifychange":
            if not self.notify_supported:
                return httpx.Response(404)
            if not body["notification"]:
                return httpx.Response(200, json=self._notify_state())
            self._changed = asyncio.Event()
            try:
                await asyncio.wait_for(self._changed.wait(), timeout=request.extensions["timeout"]["read"])
            except TimeoutError:
                raise httpx.ReadTimeout("idle", request=request) from None
            return httpx.Response(200, json=self._notify_state())
        if path == "menuitems/settings/structure":
            fixture = Path(__file__).parents[1] / "tests/fixtures/structure_65pqs8651.json"
            return httpx.Response(200, json=json.loads(fixture.read_text()))
        if path == "ambilight/processed":
            return httpx.Response(200, json={"layer1": {
                "left": {"0": {"r": 255, "g": 0, "b": 0}, "1": {"r": 255, "g": 0, "b": 0}},
                "top": {"0": {"r": 0, "g": 0, "b": 255}},
                "right": {"0": {"r": 0, "g": 255, "b": 0}}, "bottom": {}}})
        if path == "context":
            return httpx.Response(200, json={"level1": self.context, "level2": "NA", "level3": "NA", "data": "NA"})
        if path == "network/devices":
            return httpx.Response(200, json=[
                {"id": "eth0", "mac": "bc:c2:d9:64:15:b8", "ip": "192.168.178.78", "type": "Ethernet", "wake-on-lan": "Enabled"},
                {"id": "wifi0", "mac": "44:ef:26:5a:8a:aa", "type": "Wifi", "wake-on-lan": "Disabled"},
            ])
        if path == "input/key":
            self.keys.append(body["key"])
            if body["key"] == "Mute":
                self.volume["muted"] = not self.volume["muted"]
            if body["key"] == "Standby":
                self.on = False
            return httpx.Response(200)
        if path == "ambilight/lounge" and request.method == "POST":
            self.lounge = body["color"]
            return httpx.Response(200)
        return httpx.Response(404)

    def factory(self):
        """Replacement for TitanTV(...) that talks to this fake."""
        from custom_components.philips_titan.titan import TitanTV

        def make(host, username=None, password=None, **kw):
            client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: self.handler(r)))
            return TitanTV(host, username, password, min_interval=0, write_interval=0, key_interval=0, client=client)

        return make
