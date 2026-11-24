"""Polling coordinator – the only place that reads from the TV."""

from __future__ import annotations

from dataclasses import dataclass, replace

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, LOGGER, UPDATE_INTERVAL, WAKE_REFRESH_DELAY
from .titan import AmbilightState, TitanTV, Volume
from .titan.client import TitanAuthError, TitanError, TitanUnreachableError
from .titan.models import FIXED_COLOUR
from .titan.wol import wake


@dataclass
class TitanData:
    on: bool
    ambilight: AmbilightState | None = None
    volume: Volume | None = None


type TitanConfigEntry = ConfigEntry[TitanCoordinator]


class TitanCoordinator(DataUpdateCoordinator[TitanData]):
    config_entry: TitanConfigEntry

    def __init__(self, hass: HomeAssistant, entry: TitanConfigEntry, tv: TitanTV) -> None:
        super().__init__(
            hass, LOGGER, config_entry=entry, name=DOMAIN, update_interval=UPDATE_INTERVAL
        )
        self.tv = tv
        # Fixed colour set via ambilight/lounge. It cannot be read back
        # (GET lounge crashes the TV), so it is remembered here.
        self.lounge_hs: tuple[float, float] | None = None
        # Style to restore when the light is switched on without arguments.
        self.last_style_key = "standard"

    async def _async_update_data(self) -> TitanData:
        try:
            ambilight = await self.tv.ambilight_state()
            volume = await self.tv.volume()
        except TitanUnreachableError:
            return TitanData(on=False)  # standby
        except TitanAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except TitanError as err:
            raise UpdateFailed(str(err)) from err

        was_off = self.data is not None and not self.data.on
        if ambilight.on and ambilight.style:
            self.last_style_key = ambilight.style.key
            # After standby the TV shows its menu colour, not the lounge colour.
            if was_off and ambilight.style == FIXED_COLOUR and self.lounge_hs:
                LOGGER.debug("TV is back on, re-sending lounge colour %s", self.lounge_hs)
                try:
                    await self.send_lounge_colour(ambilight)
                except TitanError as err:
                    LOGGER.warning("Could not restore lounge colour: %s", err)
        return TitanData(on=True, ambilight=ambilight, volume=volume)

    async def send_lounge_colour(self, current: AmbilightState | None) -> None:
        h, s = self.lounge_hs or (0.0, 0.0)
        await self.tv.set_ambilight_colour(round(h * 255 / 360), round(s * 255 / 100), 255, current)

    @property
    def mac(self) -> str | None:
        return self.config_entry.data.get(CONF_MAC)

    async def async_wake(self) -> None:
        """Wake-on-LAN (the API itself is unreachable in standby)."""
        if not self.mac:
            return
        await self.hass.async_add_executor_job(wake, self.mac)

        async def _refresh(_now) -> None:
            await self.async_request_refresh()

        async_call_later(self.hass, WAKE_REFRESH_DELAY, _refresh)

    async def async_standby(self) -> None:
        await self.tv.standby()
        # The API is gone right after this; reflect it without polling.
        self.async_set_updated_data(TitanData(on=False))

    def set_volume_optimistic(self, current: int | None = None, muted: bool | None = None) -> None:
        if self.data and self.data.volume:
            vol = replace(
                self.data.volume,
                current=self.data.volume.current if current is None else current,
                muted=self.data.volume.muted if muted is None else muted,
            )
            self.async_set_updated_data(replace(self.data, volume=vol))

    def set_ambilight_optimistic(self, **changes) -> None:
        """Reflect a command immediately; the next poll confirms it.
        (Refreshes are debounced to protect the TV, so they may lag.)"""
        if self.data and self.data.ambilight:
            amb = replace(self.data.ambilight, **changes)
            if amb.on and amb.style:
                self.last_style_key = amb.style.key
            self.async_set_updated_data(replace(self.data, ambilight=amb))
