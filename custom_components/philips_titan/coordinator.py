"""Coordinator – the only place that reads from the TV.

Two sources:
* polling every ``scan_interval`` (default 5 s): ambilight state + volume;
* a ``notifychange`` long-poll as a best-effort accelerator. In one test the
  TV answered within 0.08 s when a menu setting changed; minutes later the
  same requests stayed unanswered (see docs/api.md). Polling therefore stays
  the source of truth, the long-poll only triggers earlier refreshes.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import timedelta
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LOGGER,
    NOTIFY_MIN_GAP,
    NOTIFY_RETRY,
    NOTIFY_TIMEOUT,
    WAKE_REFRESH_DELAY,
)
from .titan import AmbilightState, TitanTV, Volume
from .titan.client import TitanAuthError, TitanError, TitanUnreachableError
from .titan.models import FIXED_COLOUR
from .titan.system import system_info
from .titan.wol import wake


@dataclass
class TitanData:
    on: bool
    ambilight: AmbilightState | None = None
    volume: Volume | None = None
    context: str | None = None  # e.g. "WatchExtension" (HDMI), from notifychange


type TitanConfigEntry = ConfigEntry[TitanCoordinator]


class TitanCoordinator(DataUpdateCoordinator[TitanData]):
    config_entry: TitanConfigEntry

    def __init__(self, hass: HomeAssistant, entry: TitanConfigEntry, tv: TitanTV) -> None:
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
            # notifychange-triggered refreshes should show up right away
            request_refresh_debouncer=Debouncer(hass, LOGGER, cooldown=1.0, immediate=True),
        )
        self.tv = tv
        # Fixed colour set via ambilight/lounge. It cannot be read back
        # (GET lounge crashes the TV), so it is remembered here.
        self.lounge_hs: tuple[float, float] | None = None
        # Style to restore when the light is switched on without arguments.
        self.last_style_key = "standard"
        self._context: str | None = None
        self.system_info: dict[str, str | None] = {}

    async def async_load_system_info(self) -> None:
        """Model/serial for the device registry (one unauthenticated GET)."""
        try:
            self.system_info = system_info(await self.tv.system())
        except TitanError as err:
            LOGGER.debug("No system info (TV off?): %s", err)

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
        return TitanData(on=True, ambilight=ambilight, volume=volume, context=self._context)

    # ------------------------------------------------------------ push

    async def async_notify_loop(self) -> None:
        """Long-poll notifychange forever (cancelled on unload)."""
        state: dict[str, Any] = {}
        while True:
            if not (self.data and self.data.on):
                state = {}
                await asyncio.sleep(self.update_interval.total_seconds())
                continue
            started = time.monotonic()
            try:
                result = await self.tv.notify_change(state, timeout=NOTIFY_TIMEOUT)
            except TitanUnreachableError:
                state = {}
                await self.async_request_refresh()  # standby -> poll marks it off
                await asyncio.sleep(NOTIFY_RETRY)
                continue
            except TitanAuthError as err:
                LOGGER.warning("notifychange rejected (%s); falling back to polling only", err)
                return
            except TitanError as err:
                LOGGER.debug("notifychange failed: %s", err)
                state = {}
                await asyncio.sleep(NOTIFY_RETRY)
                continue

            if result is not None:
                first = not state
                state = {**state, **result}
                self._apply_notify(result)
                if not first:
                    await self.async_request_refresh()
            # never spin: at most one long-poll start per NOTIFY_MIN_GAP
            await asyncio.sleep(max(0.0, NOTIFY_MIN_GAP - (time.monotonic() - started)))

    def _apply_notify(self, result: dict[str, Any]) -> None:
        ctx = result.get("context")
        if isinstance(ctx, dict) and ctx.get("level1"):
            self._context = ctx["level1"]
            if self.data and self.data.on and self.data.context != self._context:
                self.async_set_updated_data(replace(self.data, context=self._context))

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
