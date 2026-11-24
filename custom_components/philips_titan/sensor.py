"""Current input / activity (GET context, level1)."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import TitanConfigEntry, TitanCoordinator
from .entity import TitanEntity

# Values seen on the 65PQS8651/12. Unknown values are shown as reported.
KNOWN = {"WatchExtension": "HDMI"}


async def async_setup_entry(
    hass: HomeAssistant, entry: TitanConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([TitanInputSensor(entry.runtime_data)])


class TitanInputSensor(TitanEntity, SensorEntity):
    _attr_translation_key = "input"

    def __init__(self, coordinator: TitanCoordinator) -> None:
        super().__init__(coordinator, "input")

    @property
    def available(self) -> bool:
        return super().available and self.tv_on

    @property
    def native_value(self) -> str | None:
        ctx = self.coordinator.data.context if self.coordinator.data else None
        return KNOWN.get(ctx, ctx) if ctx else None

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        ctx = self.coordinator.data.context if self.coordinator.data else None
        return {"context": ctx}
