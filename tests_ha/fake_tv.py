"""Fake Titan OS TV on top of httpx.MockTransport."""

from __future__ import annotations

import json

import httpx

SYSTEM = {
    "name": "65PQS8651/12",
    "api_version": {"Major": 6, "Minor": 1, "Patch": 0},
    "featuring": {"systemfeatures": {"pairing_type": "digest_auth_pairing", "os_type": "Linux"}},
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

    def handler(self, request: httpx.Request) -> httpx.Response:
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
            return httpx.Response(200, json={})
        if path == "audio/volume":
            if request.method == "POST":
                self.volume["current"] = body["current"]  # muted flag is ignored by the TV
                return httpx.Response(200)
            return httpx.Response(200, json=self.volume)
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
            client = httpx.AsyncClient(transport=httpx.MockTransport(self.handler))
            return TitanTV(host, username, password, min_interval=0, client=client)

        return make
