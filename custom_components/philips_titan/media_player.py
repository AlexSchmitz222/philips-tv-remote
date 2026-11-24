"""TV as a media player: power and volume."""

from __future__ import annotations

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import TitanConfigEntry, TitanCoordinator
from .entity import TitanEntity, tv_command

BASE_FEATURES = (
    MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.VOLUME_MUTE
)


async def async_setup_entry(
    hass: HomeAssistant, entry: TitanConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([TitanMediaPlayer(entry.runtime_data)])


class TitanMediaPlayer(TitanEntity, MediaPlayerEntity):
    _attr_name = None  # main entity of the device
    _attr_device_class = MediaPlayerDeviceClass.TV

    def __init__(self, coordinator: TitanCoordinator) -> None:
        super().__init__(coordinator, "media_player")
        self._attr_supported_features = BASE_FEATURES
        if coordinator.mac:
            self._attr_supported_features |= MediaPlayerEntityFeature.TURN_ON

    @property
    def state(self) -> MediaPlayerState:
        return MediaPlayerState.ON if self.tv_on else MediaPlayerState.OFF

    @property
    def _volume(self):
        return self.coordinator.data.volume if self.coordinator.data else None

    @property
    def volume_level(self) -> float | None:
        v = self._volume
        return v.current / v.max if v and v.max else None

    @property
    def is_volume_muted(self) -> bool | None:
        return self._volume.muted if self._volume else None

    @tv_command
    async def async_turn_on(self) -> None:
        await self.coordinator.async_wake()

    @tv_command
    async def async_turn_off(self) -> None:
        await self.coordinator.async_standby()

    @tv_command
    async def async_set_volume_level(self, volume: float) -> None:
        v = self._volume
        if v is None:
            return
        current = round(volume * v.max)
        await self.coordinator.tv.set_volume(current, v.muted)
        self.coordinator.set_volume_optimistic(current=current)

    @tv_command
    async def async_mute_volume(self, mute: bool) -> None:
        v = self._volume
        if v is None:
            return
        await self.coordinator.tv.set_muted(mute, v)  # toggles via Mute key
        self.coordinator.set_volume_optimistic(muted=mute)

    @tv_command
    async def async_volume_up(self) -> None:
        await self.coordinator.tv.send_key("VolumeUp")
        if v := self._volume:
            self.coordinator.set_volume_optimistic(current=min(v.max, v.current + 1))

    @tv_command
    async def async_volume_down(self) -> None:
        await self.coordinator.tv.send_key("VolumeDown")
        if v := self._volume:
            self.coordinator.set_volume_optimistic(current=max(v.min, v.current - 1))
