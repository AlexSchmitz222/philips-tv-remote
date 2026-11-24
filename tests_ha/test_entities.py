from datetime import timedelta

from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

DOMAIN = "philips_titan"
LIGHT = "light.65pqs8651_12_ambilight"
PLAYER = "media_player.65pqs8651_12"
REMOTE = "remote.65pqs8651_12_remote"


async def setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, title="65PQS8651/12", unique_id="bc:c2:d9:64:15:b8",
        data={"host": "tv", "username": "u", "password": "p", "mac": "bc:c2:d9:64:15:b8"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_initial_state(hass: HomeAssistant, fake_tv) -> None:
    await setup(hass)
    light = hass.states.get(LIGHT)
    assert light.state == "on"
    assert light.attributes["effect"] == "Standard"
    assert light.attributes["brightness"] == 128  # 5/10
    player = hass.states.get(PLAYER)
    assert player.state == "on"
    assert player.attributes["volume_level"] == 16 / 60


async def test_effect_colour_brightness(hass: HomeAssistant, fake_tv) -> None:
    await setup(hass)
    await hass.services.async_call("light", "turn_on", {"entity_id": LIGHT, "effect": "Party"}, blocking=True)
    assert fake_tv.menu[300]["activenode_id"] == 330 and fake_tv.menu[330]["selected_item"] == 332
    assert hass.states.get(LIGHT).attributes["effect"] == "Party"

    await hass.services.async_call(
        "light", "turn_on", {"entity_id": LIGHT, "hs_color": [240, 100], "brightness": 255}, blocking=True
    )
    assert fake_tv.menu[300]["activenode_id"] == 340
    assert fake_tv.lounge == {"hue": 170, "saturation": 255, "brightness": 255}
    assert fake_tv.menu[710]["value"] == 10

    await hass.services.async_call("light", "turn_off", {"entity_id": LIGHT}, blocking=True)
    assert fake_tv.menu[300]["activenode_id"] == 310
    assert hass.states.get(LIGHT).state == "off"

    # turn on without arguments -> last style (fixed colour, with lounge colour)
    fake_tv.lounge = None
    await hass.services.async_call("light", "turn_on", {"entity_id": LIGHT}, blocking=True)
    assert fake_tv.menu[300]["activenode_id"] == 340
    assert fake_tv.lounge == {"hue": 170, "saturation": 255, "brightness": 255}


async def test_volume_and_keys(hass: HomeAssistant, fake_tv) -> None:
    await setup(hass)
    await hass.services.async_call("media_player", "volume_set", {"entity_id": PLAYER, "volume_level": 0.5}, blocking=True)
    assert fake_tv.volume["current"] == 30
    await hass.services.async_call("media_player", "volume_up", {"entity_id": PLAYER}, blocking=True)
    assert fake_tv.keys == ["VolumeUp"]
    await hass.services.async_call("media_player", "volume_mute", {"entity_id": PLAYER, "is_volume_muted": True}, blocking=True)
    assert fake_tv.volume["muted"] is True and fake_tv.keys[-1] == "Mute"
    await hass.services.async_call("media_player", "volume_mute", {"entity_id": PLAYER, "is_volume_muted": True}, blocking=True)
    assert fake_tv.keys.count("Mute") == 1  # already muted -> no toggle
    await hass.services.async_call("remote", "send_command", {"entity_id": REMOTE, "command": ["Home", "CursorDown"]}, blocking=True)
    assert fake_tv.keys[-2:] == ["Home", "CursorDown"]


async def test_unknown_key_rejected(hass: HomeAssistant, fake_tv) -> None:
    import pytest
    from homeassistant.exceptions import ServiceValidationError
    await setup(hass)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call("remote", "send_command", {"entity_id": REMOTE, "command": ["Explode"]}, blocking=True)
    assert "Explode" not in fake_tv.keys


async def test_standby_and_wake(hass: HomeAssistant, fake_tv) -> None:
    await setup(hass)
    await hass.services.async_call("media_player", "turn_off", {"entity_id": PLAYER}, blocking=True)
    assert hass.states.get(PLAYER).state == "off"
    assert hass.states.get(LIGHT).state == "unavailable"

    # poll while off: no error, stays off
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done()
    assert hass.states.get(PLAYER).state == "off"

    await hass.services.async_call("media_player", "turn_on", {"entity_id": PLAYER}, blocking=True)
    fake_tv.wake.assert_called_once_with("bc:c2:d9:64:15:b8")
    fake_tv.on = True
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=60))
    await hass.async_block_till_done()
    assert hass.states.get(PLAYER).state == "on"


async def test_lounge_colour_restored_after_standby(hass: HomeAssistant, fake_tv) -> None:
    await setup(hass)
    await hass.services.async_call("light", "turn_on", {"entity_id": LIGHT, "hs_color": [120, 100]}, blocking=True)
    fake_tv.on = False
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done()
    fake_tv.on, fake_tv.lounge = True, None  # TV forgot the lounge colour
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=62))
    await hass.async_block_till_done()
    assert fake_tv.lounge == {"hue": 85, "saturation": 255, "brightness": 255}


async def test_saturation(hass: HomeAssistant, fake_tv) -> None:
    await setup(hass)
    ent = "number.65pqs8651_12_ambilight_saturation"
    assert hass.states.get(ent).state == "0"
    await hass.services.async_call("number", "set_value", {"entity_id": ent, "value": -2}, blocking=True)
    assert fake_tv.menu[720]["value"] == -2
    assert hass.states.get(ent).state == "-2"
