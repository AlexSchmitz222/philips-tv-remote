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
    start_effect = light.attributes.get("effect") or "Standard"

    await hass.services.async_call("light", "turn_on", {"entity_id": LIGHT, "effect": "Cinema"}, blocking=True)
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
    assert st.style.name == start_effect

    assert await hass.config_entries.async_unload(entry.entry_id)
