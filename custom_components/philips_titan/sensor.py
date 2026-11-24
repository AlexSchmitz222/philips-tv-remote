"""Current input / activity (GET context)."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import TitanConfigEntry, TitanCoordinator
from .entity import TitanEntity

# context.level1 values observed on the 65PQS8651/12 (2026-11-24):
CONTEXT_STATES = {
    "NetTv": "home",              # home screen, Disney+, Prime Video
    "WatchSatellite": "satellite",
    "WatchTv": "tv",              # antenna and IP streaming channels
    "WatchExtension": "extension",  # HDMI 1-3, Titan Channels, Joyn
    "NA": "other",                # Netflix, YouTube, AirPlay, mirroring, media, network
}
OPTIONS = [*dict.fromkeys(CONTEXT_STATES.values()), "unknown"]


# Read-only, updated by the coordinator.
PARALLEL_UPDATES = 0

async def async_setup_entry(
    hass: HomeAssistant, entry: TitanConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([TitanInputSensor(entry.runtime_data)])


class TitanInputSensor(TitanEntity, SensorEntity):
    _attr_translation_key = "input"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = OPTIONS

    def __init__(self, coordinator: TitanCoordinator) -> None:
        super().__init__(coordinator, "input")

    @property
    def available(self) -> bool:
        return super().available and self.tv_on

    @property
    def _raw(self) -> dict:
        data = self.coordinator.data
        return (data.context_raw or {}) if data else {}

    @property
    def native_value(self) -> str | None:
        level1 = self._raw.get("level1")
        if not level1:
            return None
        return CONTEXT_STATES.get(level1, "unknown")

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        # everything the TV reports, so unmapped cases can be identified
        return {k: v for k, v in self._raw.items()}

