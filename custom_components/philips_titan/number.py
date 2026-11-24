"""Ambilight saturation (menu node 720, -2..2) and volume in TV steps."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import TitanConfigEntry, TitanCoordinator
from .entity import LatestCommand, TitanEntity, tv_command
from .titan.models import Volume


# No HA-side limit: the client serialises and spaces requests itself, and rapid
# commands must reach the entity concurrently to be coalesced (LatestCommand).
PARALLEL_UPDATES = 0

async def async_setup_entry(
    hass: HomeAssistant, entry: TitanConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([AmbilightSaturation(entry.runtime_data), TitanVolume(entry.runtime_data)])


class AmbilightSaturation(TitanEntity, NumberEntity):
    _attr_translation_key = "ambilight_saturation"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False  # rarely changed
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: TitanCoordinator) -> None:
        super().__init__(coordinator, "ambilight_saturation")
        self._commands = LatestCommand()

    @property
    def native_min_value(self) -> float:
        sat = self.coordinator.tv.layout.saturation
        return sat.min if sat else -2

    @property
    def native_max_value(self) -> float:
        sat = self.coordinator.tv.layout.saturation
        return sat.max if sat else 2

    @property
    def available(self) -> bool:
        return super().available and self.tv_on and self.coordinator.tv.layout.saturation is not None

    @property
    def native_value(self) -> float | None:
        amb = self.coordinator.data.ambilight if self.coordinator.data else None
        return amb.saturation if amb else None

    @tv_command
    async def async_set_native_value(self, value: float) -> None:
        async def send(v: int) -> None:
            await self.coordinator.tv.set_ambilight_saturation(v)
            self.coordinator.set_ambilight_optimistic(saturation=v)

        await self._commands.submit(lambda _pending: int(value), send)


class TitanVolume(TitanEntity, NumberEntity):
    """Volume in the TV's own steps (0-60), unlike the media player's percent."""

    _attr_translation_key = "volume"
    _attr_entity_registry_enabled_default = False  # the media player covers volume too
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: TitanCoordinator) -> None:
        super().__init__(coordinator, "volume")
        self._commands = LatestCommand()

    @property
    def _volume(self) -> Volume | None:
        return self.coordinator.data.volume if self.coordinator.data else None

    @property
    def available(self) -> bool:
        return super().available and self.tv_on and self._volume is not None

    @property
    def native_min_value(self) -> float:
        return self._volume.min if self._volume else 0

    @property
    def native_max_value(self) -> float:
        return self._volume.max if self._volume else 60

    @property
    def native_value(self) -> float | None:
        return self._volume.current if self._volume else None

    @tv_command
    async def async_set_native_value(self, value: float) -> None:
        async def send(v: int) -> None:
            await self.coordinator.tv.set_volume(v)
            self.coordinator.set_volume_optimistic(current=v)

        await self._commands.submit(lambda _pending: int(value), send)
