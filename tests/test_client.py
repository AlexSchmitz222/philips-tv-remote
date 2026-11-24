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


def make_tv(fake, interval=0.0, write_interval=0.0, key_interval=0.0):
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    return TitanTV("tv", min_interval=interval, write_interval=write_interval,
                   key_interval=key_interval, client=client)


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


def test_writes_spaced_further_than_reads(fake):
    async def go():
        tv = make_tv(fake, interval=0.05, write_interval=0.3)
        await tv.set_ambilight_style("party", await tv.ambilight_state())  # 2 writes
        await tv.volume()                                                   # read
        await tv.set_ambilight_brightness(3)                                # write
    run(go())
    kinds = [("w" if m == "POST" and p != "menuitems/settings/current" else "r") for m, p, _ in fake.log]
    t = fake.times
    write_times = [ti for ti, k in zip(t, kinds) if k == "w"]
    gaps = [b - a for a, b in zip(write_times, write_times[1:])]
    assert len(write_times) == 3 and all(g >= 0.29 for g in gaps), gaps
    # the read in between did not wait for the write interval
    i_read = kinds.index("r", 1)
    assert t[i_read] - t[i_read - 1] < 0.2


def test_ambilight_colors_from_real_dump_shape():
    from philips_titan.models import AmbilightColors
    data = {"layer1": {
        "left": {"0": {"r": 255, "g": 0, "b": 0}, "1": {"r": 255, "g": 0, "b": 0}},
        "top": {"0": {"r": 0, "g": 0, "b": 255}},
        "right": {"0": {"r": 0, "g": 255, "b": 0}},
        "bottom": {},
    }}
    c = AmbilightColors.from_processed(data)
    assert c.leds == 4
    assert c.sides == {"left": (255, 0, 0), "top": (0, 0, 255), "right": (0, 255, 0)}
    assert c.average == (128, 64, 64)
    assert AmbilightColors.from_processed({}).average is None


def test_channel_number_keys(fake):
    async def go():
        tv = make_tv(fake)
        await tv.send_channel_number("102")
        with pytest.raises(ValueError):
            await tv.send_channel_number("1a")
    run(go())
    assert [b["key"] for m, p, b in fake.log if p == "input/key"] == ["Digit1", "Digit0", "Digit2"]


# ---------------------------------------------------------------- menu layout

def _structure_fixture():
    from pathlib import Path
    return json.loads((Path(__file__).parent / "fixtures/structure_65pqs8651.json").read_text())


def test_layout_detected_from_real_structure_matches_default():
    from philips_titan.layout import MenuLayout
    detected = MenuLayout.from_structure(_structure_fixture())
    default = MenuLayout.default()
    assert detected.detected
    assert (detected.style, detected.off, detected.video, detected.audio, detected.colour) == (
        default.style, default.off, default.video, default.audio, default.colour)
    assert detected.brightness == default.brightness and detected.saturation == default.saturation
    assert [(s.key, s.category, s.item) for s in detected.styles] == [
        (s.key, s.category, s.item) for s in default.styles]


def test_layout_prefixed_other_model():
    """55PML9019-style: MLM_PHM_KEY_ prefix, other node ids, an unknown item."""
    from philips_titan.layout import MenuLayout
    P = "MLM_PHM_KEY_"
    structure = {"node": {"node_id": 1, "data": {"nodes": [
        {"node_id": 900, "string_id": P + "MAIN_AMBILIGHT_STYLE", "context": "ambilight_style", "data": {"nodes": [
            {"node_id": 910, "string_id": P + "MAIN_AMBILIGHT_STYLE_OFF", "context": "ambilight_off"},
            {"node_id": 920, "string_id": P + "MAIN_FOLLOW_VIDEO", "context": "ambilight_follow_video", "data": {"enums": [
                {"enum_id": 921, "string_id": P + "MAIN_AMBILIGHT_STYLE_VIDEO_1_2K20"},
                {"enum_id": 929, "string_id": P + "MAIN_AMBILIGHT_VIVID"}]}},
            {"node_id": 940, "string_id": P + "MAIN_FOLLOW_COLOUR", "context": "ambilight_lounge_light", "data": {"enums": [
                {"enum_id": 945, "string_id": P + "MAIN_AMBILIGHT_FIXED_COLOUR"}]}},
        ]}},
        {"node_id": 990, "string_id": P + "BRIGHT", "context": "ambilight_brightness",
         "data": {"slider_data": {"min": 0, "max": 20}}},
    ]}}}
    lay = MenuLayout.from_structure(structure)
    assert lay.style.id == 900 and lay.style.sid == P + "MAIN_AMBILIGHT_STYLE" and lay.off == 910
    assert lay.audio is None
    assert [(s.key, s.item) for s in lay.styles] == [("standard", 921), ("video_929", 929), ("fixed_colour", 945)]
    assert lay.style_by_key("video_929").name == "Main Ambilight Vivid"
    assert lay.brightness.id == 990 and lay.brightness.max == 20
    assert lay.fixed_colour.item == 945


def test_layout_fallback_without_style_node():
    from philips_titan.layout import MenuLayout
    assert MenuLayout.from_structure({"node": {}}).detected is False


def test_client_uses_detected_layout(fake):
    from philips_titan.layout import MenuLayout, Node
    async def go():
        tv = make_tv(fake)
        lay = MenuLayout.default()
        tv.layout = MenuLayout(style=Node(300, "MLM_PHM_KEY_MAIN_AMBILIGHT_STYLE"), off=lay.off, video=lay.video,
                               audio=lay.audio, colour=lay.colour, brightness=lay.brightness,
                               saturation=lay.saturation, styles=lay.styles)
        await tv.ambilight_off()
    run(go())
    body = fake.log[-1][2]["values"][0]["value"]
    assert body["string_id"] == "MLM_PHM_KEY_MAIN_AMBILIGHT_STYLE" and body["data"] == {"activenode_id": 310}


# ---------------------------------------------------------------- error paths / small modules

def _tv(handler, **kw):
    return TitanTV("tv", "u", "p", min_interval=0, write_interval=0, key_interval=0,
                   client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), **kw)


@pytest.mark.parametrize("status,exc", [(401, "TitanAuthError"), (500, "TitanError")])
def test_http_errors(status, exc):
    import philips_titan.client as c
    with pytest.raises(getattr(c, exc)):
        run(_tv(lambda r: httpx.Response(status, text="x")).get("audio/volume"))


def test_non_json_and_empty_bodies():
    assert run(_tv(lambda r: httpx.Response(200, text="Ok")).get("x")) == "Ok"
    assert run(_tv(lambda r: httpx.Response(200, text="  ")).get("x")) is None


@pytest.mark.parametrize("response,expected", [
    (httpx.Response(200, text=""), {}),
    (httpx.Response(200, text="nope"), {}),
    (httpx.Response(200, json=[1]), {}),
])
def test_notify_change_odd_bodies(response, expected):
    assert run(_tv(lambda r: response).notify_change({})) == expected


@pytest.mark.parametrize("status_or_exc,exc", [
    (401, "TitanAuthError"), (503, "TitanError"),
    (httpx.ConnectError("x"), "TitanUnreachableError"), (httpx.RemoteProtocolError("x"), "TitanConnectionError"),
])
def test_notify_change_errors(status_or_exc, exc):
    import philips_titan.client as c

    def handler(request):
        if isinstance(status_or_exc, Exception):
            raise type(status_or_exc)("x", request=request)
        return httpx.Response(status_or_exc)

    with pytest.raises(getattr(c, exc)):
        run(_tv(handler).notify_change({}))


def test_notify_change_refused_during_cooldown():
    import time as _t
    from philips_titan.client import TitanCooldownError
    tv = _tv(lambda r: httpx.Response(200, json={}))
    tv._cooldown_until = _t.monotonic() + 30
    with pytest.raises(TitanCooldownError):
        run(tv.notify_change({}))


def test_wol_mac_fallback_without_enabled():
    tv = _tv(lambda r: httpx.Response(200, json=[{"mac": "aa", "ip": "1.2.3.4", "type": "Wifi", "wake-on-lan": "Disabled"}]))
    assert run(tv.wol_mac()) == "aa"
    assert run(_tv(lambda r: httpx.Response(200, json={})).network_devices()) == []


def test_set_muted_reads_volume_when_needed(fake):
    async def go():
        tv = make_tv(fake)
        await tv.set_muted(True)          # reads volume, toggles
        await tv.set_muted(True, await tv.volume())  # fake ignores muted flag -> toggles again
    run(go())
    assert [b["key"] for m, p, b in fake.log if p == "input/key"] == ["Mute", "Mute"]


def test_layout_without_nodes_raises():
    from philips_titan.client import TitanError
    from philips_titan.layout import MenuLayout
    tv = _tv(lambda r: httpx.Response(200, json={}))
    lay = MenuLayout.default()
    tv.layout = MenuLayout(style=lay.style, off=lay.off, video=lay.video, audio=None, colour=None,
                           brightness=None, saturation=None, styles=lay.styles[:5])
    for coro in (tv.set_ambilight_brightness(3), tv.set_ambilight_saturation(1), tv.set_ambilight_colour(0, 0)):
        with pytest.raises(TitanError):
            run(coro)


def test_standby_and_context_manager(fake):
    async def go():
        async with make_tv(fake) as tv:
            await tv.standby()
    run(go())
    assert fake.log[-1] == ("POST", "input/key", {"key": "Standby"})


def test_wake_sends_to_ports(monkeypatch):
    from philips_titan import wol
    sent = []

    class S:
        def __init__(self, *a): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def setsockopt(self, *a): pass
        def sendto(self, data, addr): sent.append((len(data), addr))

    monkeypatch.setattr(wol.socket, "socket", S)
    wol.wake("bc:c2:d9:64:15:b8")
    assert sent == [(102, ("255.255.255.255", 7)), (102, ("255.255.255.255", 9))]
    with pytest.raises(ValueError):
        wol.magic_packet("12:34")


def test_system_info_bad_values():
    from philips_titan.system import decrypt_field, system_info
    assert decrypt_field("") is None
    assert decrypt_field("not base64 !!") is None
    assert system_info({}) == {"name": None, "model": None, "serial": None, "sw_version": None}


def test_pairing_request_and_grant(fake):
    from philips_titan.client import TitanError
    from philips_titan.pairing import PairingSession, pair_grant, pair_request

    def handler(request):
        path = request.url.path.removeprefix("/6/")
        if path == "system":
            return httpx.Response(200, json={"featuring": {"jsonfeatures": {}}})
        if path == "pair/request":
            body = json.loads(request.content)
            assert body["access"]["scope"] == ["read", "write", "control"]
            return httpx.Response(200, json={"error_id": "SUCCESS", "auth_key": "k", "timestamp": 7})
        if path == "pair/grant":
            pin = json.loads(request.content)["auth"]["pin"]
            return httpx.Response(200, json={"error_id": "SUCCESS" if pin == "1" else "INVALID_PIN"})
        return httpx.Response(404)

    tv = _tv(handler)
    session = run(pair_request(tv))
    assert isinstance(session, PairingSession) and session.password == "k" and len(session.username) == 16
    run(pair_grant(tv, session, "1"))
    with pytest.raises(TitanError, match="INVALID_PIN"):
        run(pair_grant(tv, session, "2"))
    with pytest.raises(TitanError, match="pair/request failed"):
        run(pair_request(_tv(lambda r: httpx.Response(200, json={"error_id": "CONCURRENT_PAIRING"}))))
