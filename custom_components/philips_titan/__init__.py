"""Philips TV (Titan OS) integration."""

from __future__ import annotations

from typing import Any

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.httpx_client import get_async_client

from homeassistant.const import CONF_MAC

from .const import CONF_MQTT_PASSWORD, CONF_MQTT_USERNAME, DOMAIN, LOGGER
from .coordinator import TitanConfigEntry, TitanCoordinator
from .titan import TitanTV

PLATFORMS = [Platform.LIGHT, Platform.MEDIA_PLAYER, Platform.NUMBER, Platform.REMOTE, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: TitanConfigEntry) -> bool:
    tv = TitanTV(
        entry.data[CONF_HOST],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        # HA's shared client; its no-verify context works with the TV's TLS
        client=get_async_client(hass, verify_ssl=False),
    )
    coordinator = TitanCoordinator(hass, entry, tv)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await tv.close()
        raise
    entry.runtime_data = coordinator
    if coordinator.data.on:
        await coordinator.async_load_system_info()
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    _update_wol_issue(hass, entry)
    if entry.options.get(CONF_MQTT_USERNAME):
        await _async_start_mqtt(hass, entry, coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_updated(hass: HomeAssistant, entry: TitanConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: TitanConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.tv.close()
    return unloaded


async def _async_start_mqtt(
    hass: HomeAssistant, entry: TitanConfigEntry, coordinator: TitanCoordinator
) -> None:
    """Opt-in push listener (Titan OS MQTT). Runs in paho's own thread;
    callbacks are handed to the event loop."""
    from .titan.mqtt import MqttListener

    def on_message(topic: str, payload: dict[str, Any]) -> None:
        hass.loop.call_soon_threadsafe(coordinator.handle_push, topic, payload)

    def on_connection(connected: bool) -> None:
        hass.loop.call_soon_threadsafe(coordinator.handle_mqtt_connection, connected)

    # paho sets up sockets/TLS on construction -> executor
    listener = await hass.async_add_executor_job(
        MqttListener,
        entry.data[CONF_HOST],
        entry.options[CONF_MQTT_USERNAME],
        entry.options[CONF_MQTT_PASSWORD],
        on_message,
        on_connection,
    )
    await hass.async_add_executor_job(listener.start)
    LOGGER.debug("MQTT push listener started")

    async def _stop() -> None:
        await hass.async_add_executor_job(listener.stop)

    entry.async_on_unload(_stop)


def _update_wol_issue(hass: HomeAssistant, entry: TitanConfigEntry) -> None:
    """Without a MAC address the TV cannot be switched on (it is unreachable
    in standby) – tell the user how to fix it."""
    issue_id = f"no_mac_{entry.entry_id}"
    if entry.data.get(CONF_MAC):
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="no_mac",
        translation_placeholders={"name": entry.title},
    )
