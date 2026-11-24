"""TV as a media player: power and volume."""

from __future__ import annotations

from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import TitanConfigEntry, TitanCoordinator
from .const import DOMAIN
from .entity import LatestCommand, TitanEntity, tv_command

BASE_FEATURES = (
    MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.PLAY_MEDIA
)

# Playback is controlled with remote keys. The API does not report whether
# something is playing, so the entity stays "on" and only sends commands.
MEDIA_KEYS = {
    "play": "Play",
    "pause": "Pause",
    "play_pause": "PlayPause",
    "stop": "Stop",
    "next": "Next",
    "previous": "Previous",
}


async def async_setup_entry(
    hass: HomeAssistant, entry: TitanConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([TitanMediaPlayer(entry.runtime_data)])


class TitanMediaPlayer(TitanEntity, MediaPlayerEntity):
    _attr_name = None  # main entity of the device
    _attr_device_class = MediaPlayerDeviceClass.TV

    def __init__(self, coordinator: TitanCoordinator) -> None:
        super().__init__(coordinator, "media_player")
        self._volume_commands = LatestCommand()
        self._attr_supported_features = BASE_FEATURES
        if coordinator.mac:
            self._attr_supported_features |= MediaPlayerEntityFeature.TURN_ON

    @property
    def state(self) -> MediaPlayerState:
        return MediaPlayerState.ON if self.tv_on else MediaPlayerState.OFF

    @property
    def source(self) -> str | None:
        """Raw activity context, e.g. "WatchExtension" while an HDMI device is shown."""
        data = self.coordinator.data
        return data.context if data and data.on else None

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
        async def send(current: int) -> None:
            await self.coordinator.tv.set_volume(current)
            self.coordinator.set_volume_optimistic(current=current)

        await self._volume_commands.submit(lambda _pending: round(volume * v.max), send)

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

    @tv_command
    async def async_media_play(self) -> None:
        await self.coordinator.tv.send_key(MEDIA_KEYS["play"])

    @tv_command
    async def async_media_pause(self) -> None:
        await self.coordinator.tv.send_key(MEDIA_KEYS["pause"])

    @tv_command
    async def async_media_play_pause(self) -> None:
        await self.coordinator.tv.send_key(MEDIA_KEYS["play_pause"])

    @tv_command
    async def async_media_stop(self) -> None:
        await self.coordinator.tv.send_key(MEDIA_KEYS["stop"])

    @tv_command
    async def async_media_next_track(self) -> None:
        await self.coordinator.tv.send_key(MEDIA_KEYS["next"])

    @tv_command
    async def async_media_previous_track(self) -> None:
        await self.coordinator.tv.send_key(MEDIA_KEYS["previous"])

    @tv_command
    async def async_play_media(self, media_type: str, media_id: str, **kwargs: Any) -> None:
        """media_content_type "channel", media_content_id "12" -> digit keys."""
        if media_type != MediaType.CHANNEL or not str(media_id).strip().isdigit():
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="only_channel_numbers",
                translation_placeholders={"type": str(media_type), "id": str(media_id)},
            )
        await self.coordinator.tv.send_channel_number(media_id)
