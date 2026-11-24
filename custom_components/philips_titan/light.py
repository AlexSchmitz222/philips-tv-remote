"""Ambilight as a light entity."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .coordinator import TitanConfigEntry, TitanCoordinator
from .entity import LatestCommand, TitanEntity, tv_command
from .titan.models import BRIGHTNESS_MAX, FIXED_COLOUR, STYLES, STYLES_BY_KEY

STYLES_BY_NAME = {s.name: s for s in STYLES}


async def async_setup_entry(
    hass: HomeAssistant, entry: TitanConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([AmbilightLight(entry.runtime_data)])


def to_ha_brightness(value: int) -> int:
    return max(1, round(value * 255 / BRIGHTNESS_MAX))


def to_tv_brightness(value: int) -> int:
    return max(0, min(BRIGHTNESS_MAX, round(value * BRIGHTNESS_MAX / 255)))


class AmbilightLight(TitanEntity, LightEntity, RestoreEntity):
    _attr_translation_key = "ambilight"
    _attr_color_mode = ColorMode.HS
    _attr_supported_color_modes = {ColorMode.HS}
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_effect_list = [s.name for s in STYLES]

    def __init__(self, coordinator: TitanCoordinator) -> None:
        super().__init__(coordinator, "ambilight")
        self._commands = LatestCommand()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # The lounge colour cannot be read from the TV – restore the last one.
        if self.coordinator.lounge_hs is None and (last := await self.async_get_last_state()):
            if hs := last.attributes.get(ATTR_HS_COLOR):
                self.coordinator.lounge_hs = (float(hs[0]), float(hs[1]))

    @property
    def available(self) -> bool:
        return super().available and self.tv_on

    @property
    def _state(self):
        return self.coordinator.data.ambilight if self.coordinator.data else None

    @property
    def is_on(self) -> bool | None:
        return self._state.on if self._state else None

    @property
    def brightness(self) -> int | None:
        st = self._state
        return to_ha_brightness(st.brightness) if st and st.brightness is not None else None

    @property
    def effect(self) -> str | None:
        st = self._state
        return st.style.name if st and st.on and st.style else None

    @property
    def hs_color(self) -> tuple[float, float] | None:
        return self.coordinator.lounge_hs or (0.0, 0.0)

    @tv_command
    async def async_turn_on(self, **kwargs: Any) -> None:
        def merge(pending: dict[str, Any] | None) -> dict[str, Any]:
            job = dict(pending) if isinstance(pending, dict) else {}
            # colour and effect exclude each other: the newer one wins
            if ATTR_HS_COLOR in kwargs:
                job.pop(ATTR_EFFECT, None)
            if ATTR_EFFECT in kwargs:
                job.pop(ATTR_HS_COLOR, None)
            job.update(kwargs)
            return job

        await self._commands.submit(merge, self._apply)

    @tv_command
    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._commands.submit(lambda _pending: "off", self._apply)

    async def _apply(self, job: dict[str, Any] | str) -> None:
        """Run one (possibly merged) job: "off" or turn_on kwargs."""
        if job == "off":
            await self.coordinator.tv.ambilight_off()
            self.coordinator.set_ambilight_optimistic(on=False)
            return
        kwargs = job
        tv, st = self.coordinator.tv, self._state

        style_changed = False
        if ATTR_HS_COLOR in kwargs:
            h, s = kwargs[ATTR_HS_COLOR]
            self.coordinator.lounge_hs = (float(h), float(s))
            await self.coordinator.send_lounge_colour(st)
            style_changed = not (st and st.on and st.style == FIXED_COLOUR)
            self.coordinator.set_ambilight_optimistic(on=True, style=FIXED_COLOUR)
        elif ATTR_EFFECT in kwargs:
            style = STYLES_BY_NAME[kwargs[ATTR_EFFECT]]
            await self._activate(style.key)
            style_changed = not (st and st.on and st.style == style)
            self.coordinator.set_ambilight_optimistic(on=True, style=style)
        elif not (st and st.on):
            style = STYLES_BY_KEY[self.coordinator.last_style_key]
            await self._activate(style.key)
            style_changed = True
            self.coordinator.set_ambilight_optimistic(on=True, style=style)

        # Brightness is stored per style, so write it after a style change.
        if ATTR_BRIGHTNESS in kwargs:
            value = to_tv_brightness(kwargs[ATTR_BRIGHTNESS])
            await tv.set_ambilight_brightness(value)
            self.coordinator.set_ambilight_optimistic(brightness=value)
        elif style_changed:
            # the new style has its own stored brightness -> read it back
            await self.coordinator.async_request_refresh()

    async def _activate(self, key: str) -> None:
        if key == FIXED_COLOUR.key and self.coordinator.lounge_hs:
            await self.coordinator.send_lounge_colour(self._state)
        else:
            await self.coordinator.tv.set_ambilight_style(STYLES_BY_KEY[key].key, self._state)

