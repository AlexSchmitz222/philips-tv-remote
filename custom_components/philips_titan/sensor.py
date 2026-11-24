"""Current input (GET context) and, optionally, the Ambilight colour."""

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


async def async_setup_entry(
    hass: HomeAssistant, entry: TitanConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    entities: list[SensorEntity] = [TitanInputSensor(entry.runtime_data)]
    if entry.runtime_data.read_colors:
        entities.append(AmbilightColorSensor(entry.runtime_data))
    async_add_entities(entities)


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


class AmbilightColorSensor(TitanEntity, SensorEntity):
    """Average colour the LEDs show, e.g. to let other lights follow the picture.

    State is ``#rrggbb``; ``rgb_color`` can be passed to light.turn_on.
    """

    _attr_translation_key = "ambilight_color"

    def __init__(self, coordinator: TitanCoordinator) -> None:
        super().__init__(coordinator, "ambilight_color")

    @property
    def _colors(self):
        return self.coordinator.data.colors if self.coordinator.data else None

    @property
    def available(self) -> bool:
        return super().available and self.tv_on

    @property
    def native_value(self) -> str | None:
        c = self._colors
        return "#{:02x}{:02x}{:02x}".format(*c.average) if c and c.average else None

    @property
    def extra_state_attributes(self) -> dict:
        c = self._colors
        if not c or not c.average:
            return {}
        return {"rgb_color": list(c.average), **{side: list(v) for side, v in c.sides.items()}}
