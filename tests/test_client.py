"""Offline tests against a fake TV (no network)."""

import asyncio
import json
import time

import httpx
import pytest

from philips_titan import models as m
from philips_titan.client import (
    TitanCooldownError,
    TitanConnectionError,
    TitanTV,
    TitanUnsafeRequestError,
)


class FakeTV:
    """Minimal JointSpace v6 simulation: menu nodes + volume + request log."""

    def __init__(self):
        self.menu = {300: {"activenode_id": 320}, 320: {"selected_item": 322},
                     330: {"selected_item": 331}, 340: {"selected_item": 345},
                     710: {"value": 5}, 720: {"value": 0}}
        self.volume = {"muted": False, "current": 16, "min": 0, "max": 60}
        self.log: list[tuple[str, str, object]] = []
        self.times: list[float] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/6/")
        body = json.loads(request.content) if request.content else None
        self.log.append((request.method, path, body))
        self.times.append(time.monotonic())
        if path == "menuitems/settings/current":
            vals = [{"value": {"Nodeid": n["nodeid"], "data": self.menu.get(n["nodeid"], {})}}
                    for n in body["nodes"]]
            return httpx.Response(200, json={"version": 1, "values": vals})
        if path == "menuitems/settings/update":
            assert body["version"] == 1
            v = body["values"][0]["value"]
            self.menu.setdefault(v["Nodeid"], {}).update(v["data"])
            return httpx.Response(200, json={})
        if path == "audio/volume":
            if request.method == "POST":
                self.volume.update(body)
                return httpx.Response(200)
            return httpx.Response(200, json=self.volume)
        if path in ("input/key", "ambilight/lounge"):
            return httpx.Response(200)
        return httpx.Response(404)

    def writes(self):
        return [(p, b) for meth, p, b in self.log if meth == "POST" and p != "menuitems/settings/current"]


@pytest.fixture
def fake():
    return FakeTV()


def make_tv(fake, interval=0.0):
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    return TitanTV("tv", min_interval=interval, client=client)


def run(coro):
    return asyncio.run(coro)


def test_state_single_request(fake):
    async def go():
        st = await make_tv(fake).ambilight_state()
        assert st.on and st.style.key == "standard" and st.brightness == 5
        assert len(fake.log) == 1
    run(go())


def test_state_off(fake):
    fake.menu[300] = {"activenode_id": 310}
    st = run(make_tv(fake).ambilight_state())
    assert not st.on and st.style is None


def test_style_switch_category_and_item(fake):
    async def go():
        tv = make_tv(fake)
        await tv.set_ambilight_style("party", await tv.ambilight_state())
        assert [b["values"][0]["value"]["Nodeid"] for _, b in fake.writes()] == [300, 330]
        assert fake.menu[300]["activenode_id"] == 330 and fake.menu[330]["selected_item"] == 332
    run(go())


def test_style_same_category_only_item(fake):
    async def go():
        tv = make_tv(fake)
        await tv.set_ambilight_style("cinema", await tv.ambilight_state())
        assert [b["values"][0]["value"]["Nodeid"] for _, b in fake.writes()] == [320]
    run(go())


def test_colour_switches_to_fixed_then_lounge(fake):
    async def go():
        tv = make_tv(fake)
        await tv.set_ambilight_colour(170, 255, 300, await tv.ambilight_state())
        paths = [p for p, _ in fake.writes()]
        assert paths == ["menuitems/settings/update", "ambilight/lounge"]
        assert fake.writes()[1][1]["color"] == {"hue": 170, "saturation": 255, "brightness": 255}
    run(go())


def test_colour_when_fixed_already_only_lounge(fake):
    fake.menu[300] = {"activenode_id": 340}
    async def go():
        tv = make_tv(fake)
        await tv.set_ambilight_colour(0, 255, 128, await tv.ambilight_state())
        assert [p for p, _ in fake.writes()] == ["ambilight/lounge"]
    run(go())


def test_brightness_clamped(fake):
    run(make_tv(fake).set_ambilight_brightness(42))
    assert fake.menu[710]["value"] == 10


def test_volume_and_key(fake):
    async def go():
        tv = make_tv(fake)
        await tv.set_volume(20)
        assert (await tv.volume()).current == 20
        await tv.send_key("Standby")
        assert fake.log[-1] == ("POST", "input/key", {"key": "Standby"})
    run(go())


def test_unsafe_request_never_sent(fake):
    with pytest.raises(TitanUnsafeRequestError):
        run(make_tv(fake).get("ambilight/lounge"))
    assert fake.log == []


def test_throttle_interval(fake):
    async def go():
        tv = make_tv(fake, interval=0.2)
        await asyncio.gather(*(tv.volume() for _ in range(3)))
    run(go())
    gaps = [b - a for a, b in zip(fake.times, fake.times[1:])]
    assert all(g >= 0.19 for g in gaps), gaps


def test_cooldown_after_timeout():
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ReadTimeout("hang", request=request)

    async def go():
        tv = TitanTV("tv", min_interval=0, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        with pytest.raises(TitanConnectionError):
            await tv.volume()
        with pytest.raises(TitanCooldownError):
            await tv.volume()
    run(go())
    assert len(calls) == 1  # second request never reached the TV


def test_magic_packet():
    from philips_titan.wol import magic_packet
    p = magic_packet("bc:c2:d9:64:15:b8")
    assert len(p) == 102 and p[:6] == b"\xff" * 6 and p[6:12] == bytes.fromhex("bcc2d96415b8")


def test_unreachable_no_cooldown():
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ConnectError("No route to host", request=request)

    async def go():
        from philips_titan.client import TitanUnreachableError
        tv = TitanTV("tv", min_interval=0, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        for _ in range(3):
            with pytest.raises(TitanUnreachableError):
                await tv.volume()
    run(go())
    assert len(calls) == 3  # standby: every poll may try again


def test_notify_change_timeout_is_no_change_and_no_cooldown():
    def handler(request):
        raise httpx.ReadTimeout("idle", request=request)

    async def go():
        tv = TitanTV("tv", min_interval=0, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        assert await tv.notify_change({"x": 1}, timeout=0.1) is None
        assert tv._cooldown_until == 0  # long-poll timeout must not look like a hang
    run(go())


def test_notify_change_returns_state():
    def handler(request):
        assert json.loads(request.content) == {"notification": {}}
        return httpx.Response(200, json={"powerstate": {"powerstate": "On"}})

    async def go():
        tv = TitanTV("tv", min_interval=0, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        assert await tv.notify_change() == {"powerstate": {"powerstate": "On"}}
    run(go())


def test_wol_mac_prefers_enabled_ethernet():
    def handler(request):
        return httpx.Response(200, json=[
            {"id": "wifi0", "mac": "44:ef:26:5a:8a:aa", "type": "Wifi", "wake-on-lan": "Disabled"},
            {"id": "eth0", "mac": "bc:c2:d9:64:15:b8", "ip": "1.2.3.4", "type": "Ethernet", "wake-on-lan": "Enabled"},
        ])

    async def go():
        tv = TitanTV("tv", min_interval=0, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        assert await tv.wol_mac() == "bc:c2:d9:64:15:b8"
    run(go())


def test_system_info_decrypts_real_sample():
    from philips_titan.system import system_info
    # model_encrypted from the real 65PQS8651/12 (/system, 2026-11-24)
    info = system_info({"name": "65PQS8651/12", "model_encrypted": "K2kseVsmQFgkd15gKkJ+aj0n5NuODh3TdvfyYRUMx9U=",
                        "softwareversion_encrypted": "K2kseVsmQFgkd15gKkJ+atJJI6kYBl5fIhF2Isg2DFHegH9Cg/LU4b6H/tjCh/AJ"})
    assert info["model"] == "TPN266E"
    assert info["sw_version"] is None  # "-000.000.000.000" placeholder
