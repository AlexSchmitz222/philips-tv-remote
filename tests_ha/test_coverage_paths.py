"""Error and edge paths of the integration (quality scale: test-coverage)."""

from datetime import timedelta

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

DOMAIN = "philips_titan"
PLAYER = "media_player.65pqs8651_12"
LIGHT = "light.65pqs8651_12_ambilight"
REMOTE = "remote.65pqs8651_12_remote"


async def setup(hass, data=None):
    entry = MockConfigEntry(
        domain=DOMAIN, title="65PQS8651/12", unique_id="bc:c2:d9:64:15:b8",
        data=data or {"host": "tv", "username": "u", "password": "p", "mac": "bc:c2:d9:64:15:b8"},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_auth_failure_starts_reauth(hass: HomeAssistant, fake_tv) -> None:
    fake_tv.fail["menuitems/settings/current"] = 401
    entry = await setup(hass)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert any(f["context"]["source"] == "reauth" for f in hass.config_entries.flow.async_progress())


async def test_server_error_setup_retry_then_unavailable(hass: HomeAssistant, fake_tv) -> None:
    fake_tv.fail["audio/volume"] = 500
    entry = await setup(hass)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    fake_tv.fail.clear()
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    fake_tv.fail["audio/volume"] = 500
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=10))
    await hass.async_block_till_done()
    assert hass.states.get(LIGHT).state == "unavailable"


async def test_structure_unreadable_uses_default_layout(hass: HomeAssistant, fake_tv) -> None:
    fake_tv.fail["menuitems/settings/structure"] = 404
    entry = await setup(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert not entry.runtime_data.tv.layout.detected
    assert hass.states.get(LIGHT).attributes["effect"] == "Video: Standard"


async def test_tv_off_at_start_no_system_info(hass: HomeAssistant, fake_tv) -> None:
    fake_tv.on = False
    entry = await setup(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(PLAYER).state == "off"
    await entry.runtime_data.async_load_system_info()  # unreachable -> silently none
    assert entry.runtime_data.system_info == {}


async def test_command_error_is_translated(hass: HomeAssistant, fake_tv) -> None:
    await setup(hass)
    fake_tv.fail["input/key"] = 500
    with pytest.raises(HomeAssistantError) as exc:
        await hass.services.async_call("media_player", "volume_up", {"entity_id": PLAYER}, blocking=True)
    assert exc.value.translation_key == "command_failed"


async def test_lounge_restore_failure_is_only_logged(hass: HomeAssistant, fake_tv, caplog) -> None:
    entry = await setup(hass)
    await hass.services.async_call("light", "turn_on", {"entity_id": LIGHT, "hs_color": [120, 100]}, blocking=True)
    fake_tv.on = False
    await entry.runtime_data.async_refresh()
    fake_tv.on = True
    fake_tv.fail["ambilight/lounge"] = 500
    await entry.runtime_data.async_refresh()
    assert "Could not restore lounge colour" in caplog.text
    assert hass.states.get(PLAYER).state == "on"


async def test_volume_paths(hass: HomeAssistant, fake_tv) -> None:
    await setup(hass)
    await hass.services.async_call("media_player", "volume_down", {"entity_id": PLAYER}, blocking=True)
    assert fake_tv.keys[-1] == "VolumeDown"
    assert hass.states.get(PLAYER).attributes["volume_level"] == 15 / 60


async def test_volume_without_data_is_noop(hass: HomeAssistant, fake_tv) -> None:
    entry = await setup(hass)
    from custom_components.philips_titan.coordinator import TitanData
    entry.runtime_data.async_set_updated_data(TitanData(on=True, ambilight=entry.runtime_data.data.ambilight))
    await hass.services.async_call("media_player", "volume_set", {"entity_id": PLAYER, "volume_level": 0.5}, blocking=True)
    await hass.services.async_call("media_player", "volume_mute", {"entity_id": PLAYER, "is_volume_muted": True}, blocking=True)
    assert not any(p in ("audio/volume", "input/key") for m, p in fake_tv.log if m == "POST")


async def test_remote_power_and_repeats(hass: HomeAssistant, fake_tv) -> None:
    await setup(hass)
    await hass.services.async_call("remote", "send_command",
                                   {"entity_id": REMOTE, "command": "Back", "num_repeats": 2, "delay_secs": 0.01},
                                   blocking=True)
    assert fake_tv.keys == ["Back", "Back"]
    await hass.services.async_call("remote", "turn_off", {"entity_id": REMOTE}, blocking=True)
    assert fake_tv.keys[-1] == "Standby" and hass.states.get(REMOTE).state == "off"
    await hass.services.async_call("remote", "turn_on", {"entity_id": REMOTE}, blocking=True)
    fake_tv.wake.assert_called_once_with("bc:c2:d9:64:15:b8")


async def test_wake_without_mac_does_nothing(hass: HomeAssistant, fake_tv) -> None:
    entry = await setup(hass, {"host": "tv", "username": "u", "password": "p"})
    await entry.runtime_data.async_wake()
    fake_tv.wake.assert_not_called()


async def test_input_sensor_without_context(hass: HomeAssistant, fake_tv) -> None:
    fake_tv.context = ""  # TV answers but reports no level1
    await setup(hass)
    assert hass.states.get("sensor.65pqs8651_12_input").state == "unknown"
