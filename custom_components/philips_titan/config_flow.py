"""Config flow: host -> PIN pairing (PIN is shown on the TV)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import (
    CONF_HOST,
    CONF_MAC,
    CONF_PASSWORD,
    CONF_PIN,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import callback
from homeassistant.helpers.device_registry import format_mac

from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LOGGER,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .titan import PairingSession, TitanTV, pair_grant, pair_request
from .titan.client import TitanConnectionError, TitanError


def arp_lookup(host: str) -> str | None:
    """MAC of host from the kernel ARP table (Linux, same L2 network only)."""
    try:
        lines = Path("/proc/net/arp").read_text().splitlines()[1:]
    except OSError:
        return None
    for line in lines:
        parts = line.split()
        if len(parts) >= 4 and parts[0] == host and parts[3] != "00:00:00:00:00:00":
            return parts[3]
    return None


class TitanConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return TitanOptionsFlow()

    def __init__(self) -> None:
        self._host: str | None = None
        self._mac: str | None = None
        self._name: str = "Philips TV"
        self._tv: TitanTV | None = None
        self._session: PairingSession | None = None

    # ------------------------------------------------------------ helpers

    async def _close(self) -> None:
        if self._tv:
            await self._tv.close()
            self._tv = None

    async def _start_pairing(self) -> None:
        """Ask the TV to show a PIN."""
        assert self._tv
        self._session = await pair_request(self._tv)

    def async_remove(self) -> None:
        if self._tv:
            self.hass.async_create_task(self._close())

    # -------------------------------------------------------------- steps

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._host = user_input[CONF_HOST].strip()
            await self._close()
            self._tv = TitanTV(self._host)
            try:
                system = await self._tv.system()
            except TitanError:
                errors["base"] = "cannot_connect"
            else:
                features = (system or {}).get("featuring", {}).get("systemfeatures", {})
                if features.get("pairing_type") != "digest_auth_pairing":
                    errors["base"] = "not_supported"
                else:
                    self._name = system.get("name") or self._name
                    mac = user_input.get(CONF_MAC) or await self.hass.async_add_executor_job(
                        arp_lookup, self._host
                    )
                    self._mac = format_mac(mac) if mac else None
                    await self.async_set_unique_id(self._mac or self._host)
                    self._abort_if_unique_id_configured(updates={CONF_HOST: self._host})
                    try:
                        await self._start_pairing()
                    except TitanError as err:
                        LOGGER.warning("pair/request failed: %s", err)
                        errors["base"] = "pairing_failed"
                    else:
                        return await self.async_step_pin()

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Required(CONF_HOST): str, vol.Optional(CONF_MAC): str}),
                user_input,
            ),
            errors=errors,
        )

    async def async_step_pin(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            assert self._tv and self._session
            try:
                await pair_grant(self._tv, self._session, user_input[CONF_PIN])
            except TitanConnectionError:
                errors["base"] = "cannot_connect"
            except TitanError as err:
                LOGGER.info("pair/grant failed: %s – requesting a new PIN", err)
                errors["base"] = "invalid_pin"
                try:
                    await self._start_pairing()  # the old PIN is void now
                except TitanError:
                    errors["base"] = "pairing_failed"
            else:
                return await self._finish()

        return self.async_show_form(
            step_id="pin",
            data_schema=vol.Schema({vol.Required(CONF_PIN): str}),
            errors=errors,
            description_placeholders={"name": self._name},
        )

    async def _finish(self) -> ConfigFlowResult:
        assert self._session and self._host and self._tv
        if not self._mac:
            # Paired now -> ask the TV itself (network/devices reports WoL state).
            self._tv.set_credentials(self._session.username, self._session.password)
            try:
                if mac := await self._tv.wol_mac():
                    self._mac = format_mac(mac)
            except TitanError as err:
                LOGGER.debug("network/devices failed: %s", err)
            if self._mac and self.source != SOURCE_REAUTH:
                await self.async_set_unique_id(self._mac)
                self._abort_if_unique_id_configured(updates={CONF_HOST: self._host})
        data = {
            CONF_HOST: self._host,
            CONF_USERNAME: self._session.username,
            CONF_PASSWORD: self._session.password,
        }
        if self._mac:
            data[CONF_MAC] = self._mac
        await self._close()
        if self.source == SOURCE_REAUTH:
            return self.async_update_reload_and_abort(self._get_reauth_entry(), data_updates=data)
        return self.async_create_entry(title=self._name, data=data)

    # ------------------------------------------------------------- reauth

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        self._host = entry_data[CONF_HOST]
        self._mac = entry_data.get(CONF_MAC)
        self._name = self._get_reauth_entry().title
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            await self._close()
            self._tv = TitanTV(self._host)
            try:
                await self._start_pairing()
            except TitanConnectionError:
                errors["base"] = "cannot_connect"
            except TitanError:
                errors["base"] = "pairing_failed"
            else:
                return await self.async_step_pin()
        return self.async_show_form(
            step_id="reauth_confirm",
            errors=errors,
            description_placeholders={"name": self._name},
        )


class TitanOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current): vol.All(
                        vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)
                    )
                }
            ),
        )
