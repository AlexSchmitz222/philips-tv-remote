"""Config flow: host -> PIN pairing (PIN is shown on the TV)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    SOURCE_RECONFIGURE,
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
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .const import (
    CONF_MQTT_PASSWORD,
    CONF_MQTT_PUSH,
    CONF_MQTT_USERNAME,
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


def is_titan_pairable(system: dict[str, Any]) -> bool:
    """JointSpace v6 with PIN/digest pairing on a Linux (Titan OS) TV."""
    features = system.get("featuring", {}).get("systemfeatures", {})
    return (
        features.get("pairing_type") == "digest_auth_pairing"
        and features.get("os_type") == "Linux"
        and system.get("api_version", {}).get("Major") == 6
    )


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

    def _new_tv(self, host: str) -> TitanTV:
        return TitanTV(host, client=get_async_client(self.hass, verify_ssl=False))

    async def _probe(self, host: str) -> str | None:
        """Check the TV; returns an error key or None. Sets name and MAC."""
        self._host = host
        self._tv = self._new_tv(host)
        try:
            system = await self._tv.system()
        except TitanError:
            return "cannot_connect"
        if not isinstance(system, dict) or not is_titan_pairable(system):
            return "not_supported"
        self._name = system.get("name") or self._name
        if not self._mac:
            mac = await self.hass.async_add_executor_job(arp_lookup, host)
            self._mac = format_mac(mac) if mac else None
        return None

    async def _start_pairing(self) -> str | None:
        """Ask the TV to show a PIN; returns an error key or None."""
        assert self._tv
        try:
            self._session = await pair_request(self._tv)
        except TitanConnectionError:
            return "cannot_connect"
        except TitanError as err:
            LOGGER.warning("pair/request failed: %s", err)
            return "pairing_failed"
        return None

    # -------------------------------------------------------------- user

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if mac := user_input.get(CONF_MAC):
                self._mac = format_mac(mac)
            error = await self._probe(user_input[CONF_HOST].strip())
            if error is None:
                await self.async_set_unique_id(self._mac or self._host)
                self._abort_if_unique_id_configured(updates={CONF_HOST: self._host})
                error = await self._start_pairing()
            if error is None:
                return await self.async_step_pin()
            errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Required(CONF_HOST): str, vol.Optional(CONF_MAC): str}),
                user_input,
            ),
            errors=errors,
        )

    # ----------------------------------------------------------- zeroconf

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """_philipstv_s_rpc._tcp: also announced by Android Philips TVs, which
        is why the TV is checked before anything is offered."""
        if await self._probe(discovery_info.host) is not None:
            return self.async_abort(reason="not_supported")
        await self.async_set_unique_id(self._mac or self._host)
        self._abort_if_unique_id_configured(updates={CONF_HOST: self._host})
        self.context["title_placeholders"] = {"name": self._name}
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if (error := await self._start_pairing()) is None:
                return await self.async_step_pin()
            errors["base"] = error
        return self.async_show_form(
            step_id="zeroconf_confirm",
            errors=errors,
            description_placeholders={"name": self._name, "host": self._host or ""},
        )

    # ---------------------------------------------------------------- pin

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
                # the old PIN is void now
                errors["base"] = await self._start_pairing() or "invalid_pin"
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
            if self._mac and self.source not in (SOURCE_REAUTH, SOURCE_RECONFIGURE):
                await self.async_set_unique_id(self._mac)
                self._abort_if_unique_id_configured(updates={CONF_HOST: self._host})
        data = {
            CONF_HOST: self._host,
            CONF_USERNAME: self._session.username,
            CONF_PASSWORD: self._session.password,
        }
        if self._mac:
            data[CONF_MAC] = self._mac
        if self.source == SOURCE_REAUTH:
            return self.async_update_reload_and_abort(self._get_reauth_entry(), data_updates=data)
        if self.source == SOURCE_RECONFIGURE:
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(), data_updates=data
            )
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
            assert self._host
            self._tv = self._new_tv(self._host)
            if (error := await self._start_pairing()) is None:
                return await self.async_step_pin()
            errors["base"] = error
        return self.async_show_form(
            step_id="reauth_confirm",
            errors=errors,
            description_placeholders={"name": self._name},
        )

    # -------------------------------------------------------- reconfigure

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the host (new IP) – pairs again, the TV must be on."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            self._mac = entry.data.get(CONF_MAC)
            error = await self._probe(user_input[CONF_HOST].strip())
            if error is None and self._mac and entry.unique_id == self._mac:
                # a different TV behind the new address must not take over this entry
                found = await self.hass.async_add_executor_job(arp_lookup, self._host)
                if found and format_mac(found) != self._mac:
                    return self.async_abort(reason="wrong_device")
            if error is None:
                error = await self._start_pairing()
            if error is None:
                return await self.async_step_pin()
            errors["base"] = error
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Required(CONF_HOST): str}), user_input or dict(entry.data)
            ),
            errors=errors,
        )


class TitanOptionsFlow(OptionsFlow):
    """Polling interval and the opt-in MQTT push (second pairing with PIN)."""

    def __init__(self) -> None:
        self._options: dict[str, Any] = {}
        self._pairing: Any = None  # titan.mqtt.MqttPairing while waiting for the PIN

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        opts = self.config_entry.options
        if user_input is not None:
            self._options = {**opts, **user_input}
            paired = bool(opts.get(CONF_MQTT_USERNAME))
            if user_input[CONF_MQTT_PUSH] and not paired:
                return await self.async_step_mqtt_pair()
            if not user_input[CONF_MQTT_PUSH]:
                # opting out discards the MQTT credentials
                self._options.pop(CONF_MQTT_USERNAME, None)
                self._options.pop(CONF_MQTT_PASSWORD, None)
            return self.async_create_entry(data=self._options)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): vol.All(
                        vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)
                    ),
                    vol.Required(
                        CONF_MQTT_PUSH, default=bool(opts.get(CONF_MQTT_USERNAME))
                    ): bool,
                }
            ),
        )

    async def _start_mqtt_pairing(self) -> None:
        from .titan.mqtt import MqttPairing

        await self._close_pairing()
        # paho sets up sockets/TLS on construction -> executor
        pairing = await self.hass.async_add_executor_job(
            MqttPairing, self.config_entry.data[CONF_HOST]
        )
        await self.hass.async_add_executor_job(pairing.start)  # TV shows a PIN
        self._pairing = pairing

    async def _close_pairing(self) -> None:
        if self._pairing is not None:
            await self.hass.async_add_executor_job(self._pairing.close)
            self._pairing = None

    async def async_step_mqtt_pair(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        from .titan.mqtt import TitanMqttError

        errors: dict[str, str] = {}
        if user_input is None:
            try:
                await self._start_mqtt_pairing()
            except TitanMqttError as err:
                LOGGER.warning("MQTT pairing could not start: %s", err)
                errors["base"] = "mqtt_failed"
        else:
            try:
                username, password = await self.hass.async_add_executor_job(
                    self._pairing.finish, user_input[CONF_PIN]
                )
            except TitanMqttError as err:
                LOGGER.info("MQTT pairing failed: %s – requesting a new PIN", err)
                errors["base"] = "invalid_pin"
                try:
                    await self._start_mqtt_pairing()
                except TitanMqttError:
                    errors["base"] = "mqtt_failed"
            else:
                await self._close_pairing()
                self._options[CONF_MQTT_USERNAME] = username
                self._options[CONF_MQTT_PASSWORD] = password
                return self.async_create_entry(data=self._options)

        return self.async_show_form(
            step_id="mqtt_pair",
            data_schema=vol.Schema({vol.Required(CONF_PIN): str}),
            errors=errors,
        )
