"""Philips TV (Titan OS) integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant

from .coordinator import TitanConfigEntry, TitanCoordinator
from .titan import TitanTV

PLATFORMS = [Platform.LIGHT, Platform.MEDIA_PLAYER, Platform.NUMBER, Platform.REMOTE, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: TitanConfigEntry) -> bool:
    tv = TitanTV(entry.data[CONF_HOST], entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
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
    entry.async_create_background_task(
        hass, coordinator.async_notify_loop(), f"{entry.title} notifychange"
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_updated(hass: HomeAssistant, entry: TitanConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: TitanConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.tv.close()
    return unloaded
