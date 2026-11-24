"""Base entity."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from functools import wraps
from typing import Any, cast

from homeassistant.const import CONF_MAC
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo, format_mac
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import TitanCoordinator
from .titan.client import TitanError


class TitanEntity(CoordinatorEntity[TitanCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: TitanCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        base_id = entry.unique_id or entry.entry_id
        self._attr_unique_id = f"{base_id}_{key}"
        mac = entry.data.get(CONF_MAC)
        info = coordinator.system_info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, base_id)},
            connections={(CONNECTION_NETWORK_MAC, format_mac(mac))} if mac else set(),
            manufacturer="Philips",
            model=info.get("name") or entry.title,
            model_id=info.get("model"),
            serial_number=info.get("serial"),
            sw_version=info.get("sw_version"),
            name=entry.title,
        )

    @property
    def tv_on(self) -> bool:
        return bool(self.coordinator.data and self.coordinator.data.on)


def tv_command[_F: Callable[..., Coroutine[Any, Any, None]]](func: _F) -> _F:
    """Turn library errors into translated HomeAssistantError for actions."""

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> None:
        try:
            await func(*args, **kwargs)
        except TitanError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    return cast(_F, wrapper)


class LatestCommand:
    """Coalesce rapid commands (clicking, dragging a slider/colour wheel).

    While one command runs, newer ones are merged into a single pending job;
    when the running one finishes, only that merged job is sent. The TV
    crashed when settings were written in quick succession.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._job: Any = None

    async def submit(
        self, merge: Callable[[Any], Any], execute: Callable[[Any], Awaitable[None]]
    ) -> None:
        self._job = merge(self._job)
        async with self._lock:
            job, self._job = self._job, None
            if job is None:
                return  # already sent as part of a merged job
            await execute(job)
