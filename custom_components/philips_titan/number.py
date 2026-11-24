"""Ambilight saturation (menu node 720, -2..2)."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import TitanConfigEntry, TitanCoordinator
from .entity import TitanEntity, tv_command
from .titan.models import SATURATION_MAX, SATURATION_MIN


async def async_setup_entry(
    hass: HomeAssistant, entry: TitanConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([AmbilightSaturation(entry.runtime_data)])


class AmbilightSaturation(TitanEntity, NumberEntity):
    _attr_translation_key = "ambilight_saturation"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = SATURATION_MIN
    _attr_native_max_value = SATURATION_MAX
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: TitanCoordinator) -> None:
        super().__init__(coordinator, "ambilight_saturation")

    @property
    def available(self) -> bool:
        return super().available and self.tv_on

    @property
    def native_value(self) -> float | None:
        amb = self.coordinator.data.ambilight if self.coordinator.data else None
        return amb.saturation if amb else None

    @tv_command
    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.tv.set_ambilight_saturation(int(value))
        self.coordinator.set_ambilight_optimistic(saturation=int(value))
