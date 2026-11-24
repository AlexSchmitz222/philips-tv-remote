"""Diagnostics download (Settings -> Devices -> TV -> Download diagnostics)."""

from __future__ import annotations

from dataclasses import asdict
import time
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .coordinator import TitanConfigEntry

TO_REDACT = {CONF_PASSWORD, CONF_USERNAME, CONF_MAC, CONF_HOST, "serial", "mac", "ip"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: TitanConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    tv = coordinator.tv
    data = coordinator.data
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "system_info": async_redact_data(coordinator.system_info, TO_REDACT),
        "state": async_redact_data(asdict(data), TO_REDACT) if data else None,
        "last_update_success": coordinator.last_update_success,
        "last_exception": repr(coordinator.last_exception) if coordinator.last_exception else None,
        "update_interval_s": coordinator.update_interval.total_seconds()
        if coordinator.update_interval
        else None,
        "lounge_hs": coordinator.lounge_hs,
        "client": {
            "min_interval": tv.min_interval,
            "write_interval": tv.write_interval,
            "key_interval": tv.key_interval,
            "cooldown_remaining_s": max(0.0, round(tv._cooldown_until - time.monotonic(), 1)),
        },
    }
