"""Remote control: send keys."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any

from homeassistant.components.remote import RemoteEntity
from homeassistant.components.remote.const import ATTR_DELAY_SECS, ATTR_NUM_REPEATS
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import TitanConfigEntry, TitanCoordinator
from .entity import TitanEntity, tv_command
from .titan.models import KEYS


# No HA-side limit: the client serialises and spaces requests itself, and rapid
# commands must reach the entity concurrently to be coalesced (LatestCommand).
PARALLEL_UPDATES = 0

async def async_setup_entry(
    hass: HomeAssistant, entry: TitanConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([TitanRemote(entry.runtime_data)])


class TitanRemote(TitanEntity, RemoteEntity):
    _attr_translation_key = "remote"

    def __init__(self, coordinator: TitanCoordinator) -> None:
        super().__init__(coordinator, "remote")

    @property
    def is_on(self) -> bool:
        return self.tv_on

    @tv_command
    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_wake()

    @tv_command
    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_standby()

    @tv_command
    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        commands = list(command)
        # Only known key names: unknown requests are a risk on this API.
        if unknown := [c for c in commands if c not in KEYS]:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_key",
                translation_placeholders={"keys": ", ".join(unknown), "valid": ", ".join(KEYS)},
            )
        repeats = kwargs.get(ATTR_NUM_REPEATS, 1)
        delay = kwargs.get(ATTR_DELAY_SECS, 0)  # library throttle applies on top
        for i in range(repeats):
            for key in commands:
                await self.coordinator.tv.send_key(key)
            if delay and i < repeats - 1:
                await asyncio.sleep(delay)
