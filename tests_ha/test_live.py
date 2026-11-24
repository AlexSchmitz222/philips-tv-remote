"""End-to-end against the real TV. Run only explicitly:
    TITAN_LIVE=1 pytest -s tests_ha/test_live.py
"""

import asyncio
import json
import os
from pathlib import Path

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant

pytestmark = pytest.mark.skipif(not os.environ.get("TITAN_LIVE"), reason="needs the real TV")
LIGHT = "light.65pqs8651_12_ambilight"
PLAYER = "media_player.65pqs8651_12"


async def test_live_roundtrip(hass: HomeAssistant, socket_enabled) -> None:
    import pytest_socket

    creds = json.loads((Path(__file__).parents[1] / "credentials.json").read_text())
    pytest_socket.socket_allow_hosts([creds["host"], "127.0.0.1"])
    entry = MockConfigEntry(
        domain="philips_titan", title="65PQS8651/12", unique_id="bc:c2:d9:64:15:b8",
        data={"host": creds["host"], "username": creds["username"], "password": creds["password"],
              "mac": "bc:c2:d9:64:15:b8"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    light, player = hass.states.get(LIGHT), hass.states.get(PLAYER)
    print("\nStart:", light.state, light.attributes.get("effect"), light.attributes.get("brightness"),
          "| TV", player.state, "Lautstärke", player.attributes.get("volume_level"))
    assert player.state == "on"
    start_effect = light.attributes.get("effect") or "Video: Standard"

    await hass.services.async_call("light", "turn_on", {"entity_id": LIGHT, "effect": "Video: Cinema"}, blocking=True)
    await hass.async_block_till_done()
    await asyncio.sleep(4)
    tv = entry.runtime_data.tv
    st = await tv.ambilight_state()
    print("nach Cinema (vom TV gelesen):", st.style.key, "Helligkeit", st.brightness)
    assert st.style.key == "cinema"

    await hass.services.async_call("light", "turn_on", {"entity_id": LIGHT, "effect": start_effect}, blocking=True)
    await hass.async_block_till_done()
    await asyncio.sleep(3)
    st = await tv.ambilight_state()
    print("zurück (vom TV gelesen):", st.style.name, "Helligkeit", st.brightness)
    assert start_effect.endswith(st.style.name)

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_live_notifychange(hass: HomeAssistant, socket_enabled) -> None:
    """External change (as if made with the remote) reaches HA via notifychange."""
    import time
    import pytest_socket
    from custom_components.philips_titan.titan import TitanTV

    creds = json.loads((Path(__file__).parents[1] / "credentials.json").read_text())
    pytest_socket.socket_allow_hosts([creds["host"], "127.0.0.1"])
    entry = MockConfigEntry(
        domain="philips_titan", title="65PQS8651/12", unique_id="bc:c2:d9:64:15:b8",
        data={"host": creds["host"], "username": creds["username"], "password": creds["password"],
              "mac": "bc:c2:d9:64:15:b8"},
        options={"scan_interval": 60},  # make sure a poll cannot explain the update
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await asyncio.sleep(3)  # long-poll established

    other = TitanTV(creds["host"], creds["username"], creds["password"])
    try:
        start = (await other.ambilight_state()).brightness
        target = 3 if start != 3 else 4
        print(f"\nHelligkeit extern {start} -> {target}")
        t0 = time.monotonic()
        await other.set_ambilight_brightness(target)
        seen = None
        while time.monotonic() - t0 < 10:
            await asyncio.sleep(0.05)
            b = hass.states.get(LIGHT).attributes.get("brightness")
            if b == round(target * 255 / 10):
                seen = time.monotonic() - t0
                break
        print(f"HA hat die Änderung nach {seen:.2f}s" if seen else "HA hat die Änderung NICHT gesehen")
        print("Quelle (media_player.source):", hass.states.get(PLAYER).attributes.get("source"))
        info = entry.runtime_data.system_info
        print("Geräteinfo: model_id", info.get("model"), "sw", info.get("sw_version"))
        assert seen is not None and seen < 3
    finally:
        await other.set_ambilight_brightness(start)
        await other.close()
        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_live_zeroconf_probe(hass: HomeAssistant, socket_enabled) -> None:
    """Discovery step against the real TV (stops before pairing, no PIN shown)."""
    from ipaddress import ip_address

    import pytest_socket
    from homeassistant import config_entries
    from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

    creds = json.loads((Path(__file__).parents[1] / "credentials.json").read_text())
    pytest_socket.socket_allow_hosts([creds["host"], "127.0.0.1"])
    info = ZeroconfServiceInfo(
        ip_address=ip_address(creds["host"]), ip_addresses=[ip_address(creds["host"])],
        hostname="tv.local.", name="6_65PQS8651/12._philipstv_s_rpc._tcp.local.", port=1926,
        type="_philipstv_s_rpc._tcp.local.", properties={},
    )
    result = await hass.config_entries.flow.async_init(
        "philips_titan", context={"source": config_entries.SOURCE_ZEROCONF}, data=info)
    print("\nZeroconf:", result.get("step_id"), result.get("description_placeholders"))
    assert result["step_id"] == "zeroconf_confirm"
    hass.config_entries.flow.async_abort(result["flow_id"])
