from datetime import timedelta
import json

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
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=6))
    await hass.async_block_till_done()
    assert hass.states.get(PLAYER).state == "off"

    await hass.services.async_call("media_player", "turn_on", {"entity_id": PLAYER}, blocking=True)
    fake_tv.wake.assert_called_once_with("bc:c2:d9:64:15:b8")
    fake_tv.on = True
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=20))
    await hass.async_block_till_done()
    assert hass.states.get(PLAYER).state == "on"


async def test_lounge_colour_restored_after_standby(hass: HomeAssistant, fake_tv) -> None:
    await setup(hass)
    await hass.services.async_call("light", "turn_on", {"entity_id": LIGHT, "hs_color": [120, 100]}, blocking=True)
    fake_tv.on = False
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=6))
    await hass.async_block_till_done()
    fake_tv.on, fake_tv.lounge = True, None  # TV forgot the lounge colour
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=12))
    await hass.async_block_till_done()
    assert fake_tv.lounge == {"hue": 85, "saturation": 255, "brightness": 255}


async def test_saturation(hass: HomeAssistant, fake_tv) -> None:
    await setup(hass)
    ent = "number.65pqs8651_12_ambilight_saturation"
    assert hass.states.get(ent).state == "0"
    await hass.services.async_call("number", "set_value", {"entity_id": ent, "value": -2}, blocking=True)
    assert fake_tv.menu[720]["value"] == -2
    assert hass.states.get(ent).state == "-2"


async def test_media_keys(hass: HomeAssistant, fake_tv) -> None:
    await setup(hass)
    for service in ("media_play", "media_pause", "media_play_pause", "media_stop",
                    "media_next_track", "media_previous_track"):
        await hass.services.async_call("media_player", service, {"entity_id": PLAYER}, blocking=True)
    assert fake_tv.keys == ["Play", "Pause", "PlayPause", "Stop", "Next", "Previous"]


async def test_remote_change_arrives_via_notifychange(hass: HomeAssistant, fake_tv) -> None:
    """A change made on the TV shows up long before the next 5 s poll."""
    import asyncio
    await setup(hass)
    await asyncio.sleep(1.2)  # let the long-poll start (baseline + waiting request)
    polls_before = fake_tv.log.count(("GET", "audio/volume"))
    fake_tv.remote_menu_change(300, {"activenode_id": 330})  # user picks an audio style
    for _ in range(40):
        await asyncio.sleep(0.05)
        await hass.async_block_till_done()
        if hass.states.get(LIGHT).attributes.get("effect") == "Lumina":
            break
    assert hass.states.get(LIGHT).attributes.get("effect") == "Lumina"
    assert fake_tv.log.count(("GET", "audio/volume")) == polls_before + 1  # one triggered refresh


async def test_source_from_context(hass: HomeAssistant, fake_tv) -> None:
    import asyncio
    await setup(hass)
    await asyncio.sleep(1.2)
    fake_tv.remote_context_change("WatchExtension")
    for _ in range(40):
        await asyncio.sleep(0.05)
        await hass.async_block_till_done()
        if hass.states.get(PLAYER).attributes.get("source") == "WatchExtension":
            break
    assert hass.states.get(PLAYER).attributes.get("source") == "WatchExtension"


async def test_works_without_notifychange(hass: HomeAssistant, fake_tv) -> None:
    fake_tv.notify_supported = False
    await setup(hass)
    assert hass.states.get(LIGHT).state == "on"


async def test_device_info(hass: HomeAssistant, fake_tv) -> None:
    from homeassistant.helpers import device_registry as dr
    entry = await setup(hass)
    (dev,) = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert dev.model == "65PQS8651/12" and dev.model_id == "TPN266E" and dev.sw_version is None


async def test_rapid_commands_are_coalesced(hass: HomeAssistant, fake_tv) -> None:
    """Dragging the colour wheel: only the first and the latest colour are sent."""
    import asyncio
    entry = await setup(hass)
    entry.runtime_data.tv.write_interval = 0.2  # commands take time, like on the real TV
    fake_tv.menu[300] = {"activenode_id": 340}  # already fixed colour
    await hass.services.async_call("light", "turn_on", {"entity_id": LIGHT, "effect": "Fixed colour"}, blocking=True)
    lounge_posts = []
    orig = fake_tv.handler

    async def counting(request):
        if request.url.path.endswith("ambilight/lounge"):
            lounge_posts.append(json.loads(request.content)["color"]["hue"])
        return await orig(request)

    fake_tv.handler = counting
    calls = [
        hass.services.async_call("light", "turn_on", {"entity_id": LIGHT, "hs_color": [h, 100]}, blocking=True)
        for h in (0, 60, 120, 180, 240)
    ]
    await asyncio.gather(*calls)
    assert lounge_posts[-1] == round(240 * 255 / 360)
    assert len(lounge_posts) <= 2, lounge_posts


async def test_colour_then_brightness_both_kept(hass: HomeAssistant, fake_tv) -> None:
    import asyncio
    entry = await setup(hass)
    entry.runtime_data.tv.write_interval = 0.2
    await asyncio.gather(
        hass.services.async_call("light", "turn_on", {"entity_id": LIGHT, "effect": "Party"}, blocking=True),
        hass.services.async_call("light", "turn_on", {"entity_id": LIGHT, "hs_color": [120, 100]}, blocking=True),
        hass.services.async_call("light", "turn_on", {"entity_id": LIGHT, "brightness": 51}, blocking=True),
    )
    assert fake_tv.lounge["hue"] == 85        # colour from the 2nd call
    assert fake_tv.menu[710]["value"] == 2    # brightness from the 3rd call


async def test_input_sensor_from_polling(hass: HomeAssistant, fake_tv) -> None:
    fake_tv.notify_supported = False  # must work from polling alone
    fake_tv.context = "WatchExtension"
    await setup(hass)
    assert hass.states.get("sensor.65pqs8651_12_input").state == "HDMI"
    assert hass.states.get(PLAYER).attributes["source"] == "WatchExtension"


async def test_volume_number_in_tv_steps(hass: HomeAssistant, fake_tv) -> None:
    fake_tv.volume["current"] = 5
    await setup(hass)
    ent = "number.65pqs8651_12_volume"
    st = hass.states.get(ent)
    assert st.state == "5" and st.attributes["max"] == 60
    await hass.services.async_call("number", "set_value", {"entity_id": ent, "value": 12}, blocking=True)
    assert fake_tv.volume["current"] == 12
    assert hass.states.get(PLAYER).attributes["volume_level"] == 12 / 60
