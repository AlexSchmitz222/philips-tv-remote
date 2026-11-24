"""Opt-in MQTT push (Titan OS state/power, channels/state)."""

import asyncio
from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

DOMAIN = "philips_titan"
PLAYER = "media_player.65pqs8651_12"
LIGHT = "light.65pqs8651_12_ambilight"


class FakePairing:
    started = 0

    def __init__(self, host, timeout=10):
        self.host = host

    def start(self):
        FakePairing.started += 1

    def finish(self, pin):
        from custom_components.philips_titan.titan.mqtt import TitanMqttError
        if pin != "4321":
            raise TitanMqttError("pairing/finish: wrong PIN")
        return "mq-user", "mq-pass"

    def close(self):
        pass


class FakeListener:
    instance = None

    def __init__(self, host, username, password, on_message, on_connection=None):
        self.args = (host, username, password)
        self.on_message, self.on_connection = on_message, on_connection
        self.started = self.stopped = False
        FakeListener.instance = self

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


async def _setup(hass, options):
    entry = MockConfigEntry(
        domain=DOMAIN, title="65PQS8651/12", unique_id="bc:c2:d9:64:15:b8",
        data={"host": "tv", "username": "u", "password": "p", "mac": "bc:c2:d9:64:15:b8"},
        options=options,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_opt_in_pairing(hass: HomeAssistant, fake_tv) -> None:
    entry = await _setup(hass, {})
    with patch("custom_components.philips_titan.titan.mqtt.MqttPairing", FakePairing), \
         patch("custom_components.philips_titan.titan.mqtt.MqttListener", FakeListener):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"scan_interval": 5, "mqtt_push": True})
        assert result["step_id"] == "mqtt_pair"
        result = await hass.config_entries.options.async_configure(result["flow_id"], {"pin": "0000"})
        assert result["errors"] == {"base": "invalid_pin"}
        result = await hass.config_entries.options.async_configure(result["flow_id"], {"pin": "4321"})
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
    assert entry.options["mqtt_username"] == "mq-user"
    assert FakeListener.instance.started and FakeListener.instance.args == ("tv", "mq-user", "mq-pass")


async def test_opt_out_drops_credentials(hass: HomeAssistant, fake_tv) -> None:
    with patch("custom_components.philips_titan.titan.mqtt.MqttListener", FakeListener):
        entry = await _setup(hass, {"mqtt_username": "a", "mqtt_password": "b"})
        listener = FakeListener.instance
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"scan_interval": 5, "mqtt_push": False})
        await hass.async_block_till_done()
    assert "mqtt_username" not in entry.options and "mqtt_password" not in entry.options
    assert listener.stopped  # reload stopped the old listener


async def test_push_power_and_input(hass: HomeAssistant, fake_tv) -> None:
    with patch("custom_components.philips_titan.titan.mqtt.MqttListener", FakeListener):
        entry = await _setup(hass, {"mqtt_username": "a", "mqtt_password": "b"})
    coordinator = entry.runtime_data
    lst = FakeListener.instance
    assert hass.states.get(PLAYER).state == "on"

    # messages arrive from paho's thread
    await hass.async_add_executor_job(lst.on_connection, True)
    await hass.async_add_executor_job(lst.on_message, "state/power", {"power": "standby"})
    await hass.async_block_till_done()
    assert hass.states.get(PLAYER).state == "off"          # instantly, no poll needed

    # JointSpace still answers right after switching off: polling must not flip it back
    before = len(fake_tv.log)
    await coordinator.async_refresh()
    assert hass.states.get(PLAYER).state == "off"
    assert len(fake_tv.log) == before                      # not even asked

    await hass.async_add_executor_job(lst.on_message, "state/power", {"power": "on"})
    for _ in range(20):
        await asyncio.sleep(0.05)
        await hass.async_block_till_done()
    assert hass.states.get(PLAYER).state == "on"

    # input change pushed -> immediate refresh reads the new context
    fake_tv.context = "WatchSatellite"
    await asyncio.sleep(1.1)  # debouncer cooldown of the previous refresh
    await hass.async_add_executor_job(lst.on_message, "channels/state", {"state": "inactive", "channel": None})
    for _ in range(20):
        await asyncio.sleep(0.05)
        await hass.async_block_till_done()
    assert hass.states.get("sensor.65pqs8651_12_input").state == "satellite"


async def test_push_ignored_while_disconnected(hass: HomeAssistant, fake_tv) -> None:
    """A stale 'standby' must not hide a TV that is on once MQTT is gone."""
    with patch("custom_components.philips_titan.titan.mqtt.MqttListener", FakeListener):
        entry = await _setup(hass, {"mqtt_username": "a", "mqtt_password": "b"})
    lst = FakeListener.instance
    await hass.async_add_executor_job(lst.on_connection, True)
    await hass.async_add_executor_job(lst.on_message, "state/power", {"power": "standby"})
    await hass.async_add_executor_job(lst.on_connection, False)
    await hass.async_block_till_done()
    await entry.runtime_data.async_refresh()
    assert hass.states.get(PLAYER).state == "on"           # polling decides again
