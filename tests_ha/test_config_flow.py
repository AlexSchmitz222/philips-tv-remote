from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

DOMAIN = "philips_titan"


async def test_pairing_flow(hass: HomeAssistant, fake_tv) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"host": "192.168.178.78"})
    assert result["step_id"] == "pin"

    # wrong PIN -> error, new pair/request issued
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"pin": "0000"})
    assert result["errors"] == {"base": "invalid_pin"}
    assert fake_tv.log.count(("POST", "pair/request")) == 2

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"pin": "1234"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "65PQS8651/12"
    assert result["data"]["mac"] == "bc:c2:d9:64:15:b8"
    assert result["data"]["password"] == "secret"
    assert result["result"].unique_id == "bc:c2:d9:64:15:b8"


async def test_cannot_connect(hass: HomeAssistant, fake_tv) -> None:
    fake_tv.on = False
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"host": "192.168.178.78"})
    assert result["errors"] == {"base": "cannot_connect"}


async def test_options_scan_interval(hass: HomeAssistant, fake_tv) -> None:
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    entry = MockConfigEntry(domain=DOMAIN, title="TV", unique_id="x",
                            data={"host": "tv", "username": "u", "password": "p"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.update_interval.total_seconds() == 5

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"scan_interval": 10})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.runtime_data.update_interval.total_seconds() == 10  # reloaded


async def test_mac_from_network_devices_when_arp_fails(hass: HomeAssistant, fake_tv) -> None:
    from unittest.mock import patch
    with patch("custom_components.philips_titan.config_flow.arp_lookup", return_value=None):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"host": "192.168.178.78"})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"pin": "1234"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["mac"] == "bc:c2:d9:64:15:b8"
    assert result["result"].unique_id == "bc:c2:d9:64:15:b8"


# ----------------------------------------------------------------- more user-flow branches

async def _user_flow(hass, host="192.168.178.78", **extra):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    return await hass.config_entries.flow.async_configure(result["flow_id"], {"host": host, **extra})


async def test_not_supported_android_tv(hass: HomeAssistant, fake_tv) -> None:
    fake_tv.system["featuring"]["systemfeatures"]["os_type"] = "Android"
    result = await _user_flow(hass)
    assert result["errors"] == {"base": "not_supported"}


async def test_pairing_request_refused(hass: HomeAssistant, fake_tv) -> None:
    fake_tv.pair_request_ok = False
    result = await _user_flow(hass)
    assert result["errors"] == {"base": "pairing_failed"}


async def test_manual_mac_and_already_configured(hass: HomeAssistant, fake_tv) -> None:
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    MockConfigEntry(domain=DOMAIN, unique_id="aa:bb:cc:dd:ee:ff", data={"host": "old"}).add_to_hass(hass)
    result = await _user_flow(hass, mac="AA-BB-CC-DD-EE-FF")
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"


async def test_pin_connection_lost(hass: HomeAssistant, fake_tv) -> None:
    result = await _user_flow(hass)
    fake_tv.on = False
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"pin": "1234"})
    assert result["errors"] == {"base": "cannot_connect"}


async def test_wrong_pin_and_new_request_fails(hass: HomeAssistant, fake_tv) -> None:
    result = await _user_flow(hass)
    fake_tv.pair_request_ok = False
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"pin": "0000"})
    assert result["errors"] == {"base": "pairing_failed"}


async def test_no_mac_anywhere(hass: HomeAssistant, fake_tv) -> None:
    from unittest.mock import patch
    fake_tv.network_devices_ok = False
    with patch("custom_components.philips_titan.config_flow.arp_lookup", return_value=None):
        result = await _user_flow(hass)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"pin": "1234"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert "mac" not in result["data"] and result["result"].unique_id == "192.168.178.78"
    await hass.async_block_till_done()
    from homeassistant.helpers import issue_registry as ir
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"no_mac_{result['result'].entry_id}")


def test_arp_lookup(tmp_path, monkeypatch) -> None:
    from pathlib import Path
    from custom_components.philips_titan import config_flow
    arp = tmp_path / "arp"
    arp.write_text(
        "IP address HW type Flags HW address Mask Device\n"
        "192.168.178.78 0x1 0x2 bc:c2:d9:64:15:b8 * eth0\n"
        "192.168.178.9 0x1 0x0 00:00:00:00:00:00 * eth0\n"
    )
    real = Path
    monkeypatch.setattr(config_flow, "Path", lambda p: arp if p == "/proc/net/arp" else real(p))
    assert config_flow.arp_lookup("192.168.178.78") == "bc:c2:d9:64:15:b8"
    assert config_flow.arp_lookup("192.168.178.9") is None
    assert config_flow.arp_lookup("10.0.0.1") is None
    monkeypatch.setattr(config_flow, "Path", lambda p: tmp_path / "missing")
    assert config_flow.arp_lookup("192.168.178.78") is None


# ----------------------------------------------------------------- zeroconf

def _zc(host="192.168.178.78"):
    from ipaddress import ip_address
    from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
    return ZeroconfServiceInfo(
        ip_address=ip_address(host), ip_addresses=[ip_address(host)], hostname="tv.local.",
        name="6_65PQS8651/12._philipstv_s_rpc._tcp.local.", port=1926,
        type="_philipstv_s_rpc._tcp.local.", properties={},
    )


async def test_zeroconf_discovery_pairs(hass: HomeAssistant, fake_tv) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=_zc())
    assert result["step_id"] == "zeroconf_confirm"
    fake_tv.pair_request_ok = False
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["errors"] == {"base": "pairing_failed"}
    fake_tv.pair_request_ok = True
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "pin"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"pin": "1234"})
    assert result["type"] is FlowResultType.CREATE_ENTRY and result["data"]["host"] == "192.168.178.78"


async def test_zeroconf_android_tv_ignored(hass: HomeAssistant, fake_tv) -> None:
    fake_tv.system["featuring"]["systemfeatures"]["os_type"] = "Android"
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=_zc())
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "not_supported"


async def test_zeroconf_updates_host_of_existing_entry(hass: HomeAssistant, fake_tv) -> None:
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    entry = MockConfigEntry(domain=DOMAIN, unique_id="bc:c2:d9:64:15:b8", data={"host": "192.168.178.10"})
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=_zc())
    assert result["reason"] == "already_configured"
    assert entry.data["host"] == "192.168.178.78"


# ----------------------------------------------------------------- reauth / reconfigure

async def _entry(hass):
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    entry = MockConfigEntry(domain=DOMAIN, title="65PQS8651/12", unique_id="bc:c2:d9:64:15:b8",
                            data={"host": "192.168.178.78", "username": "old", "password": "old",
                                  "mac": "bc:c2:d9:64:15:b8"})
    entry.add_to_hass(hass)
    return entry


async def test_reauth(hass: HomeAssistant, fake_tv) -> None:
    entry = await _entry(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    fake_tv.on = False
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["errors"] == {"base": "cannot_connect"}
    fake_tv.on = True
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"pin": "1234"})
    assert result["reason"] == "reauth_successful"
    assert entry.data["password"] == "secret"
    await hass.async_block_till_done()  # let the triggered reload finish


async def test_reconfigure_new_host(hass: HomeAssistant, fake_tv) -> None:
    entry = await _entry(hass)
    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    fake_tv.on = False
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"host": "192.168.178.79"})
    assert result["errors"] == {"base": "cannot_connect"}
    fake_tv.on = True
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"host": "192.168.178.79"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"pin": "1234"})
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["host"] == "192.168.178.79"
    await hass.async_block_till_done()  # let the triggered reload finish


async def test_reconfigure_wrong_device(hass: HomeAssistant, fake_tv) -> None:
    from unittest.mock import patch
    entry = await _entry(hass)
    result = await entry.start_reconfigure_flow(hass)
    with patch("custom_components.philips_titan.config_flow.arp_lookup", return_value="11:22:33:44:55:66"):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"host": "192.168.178.50"})
    assert result["reason"] == "wrong_device"


# ----------------------------------------------------------------- options: MQTT failures

async def test_options_mqtt_unreachable(hass: HomeAssistant, fake_tv) -> None:
    from unittest.mock import patch
    from custom_components.philips_titan.titan.mqtt import TitanMqttError

    class Broken:
        def __init__(self, host, timeout=10): ...
        def start(self): raise TitanMqttError("no route")
        def close(self): ...

    entry = await _entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    with patch("custom_components.philips_titan.titan.mqtt.MqttPairing", Broken):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"scan_interval": 5, "mqtt_push": True})
    assert result["step_id"] == "mqtt_pair" and result["errors"] == {"base": "mqtt_failed"}


async def test_options_mqtt_wrong_pin_then_unreachable(hass: HomeAssistant, fake_tv) -> None:
    from unittest.mock import patch
    from custom_components.philips_titan.titan.mqtt import TitanMqttError
    calls = {"start": 0}

    class Flaky:
        def __init__(self, host, timeout=10): ...
        def start(self):
            calls["start"] += 1
            if calls["start"] > 1:
                raise TitanMqttError("gone")
        def finish(self, pin): raise TitanMqttError("wrong")
        def close(self): ...

    entry = await _entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    with patch("custom_components.philips_titan.titan.mqtt.MqttPairing", Flaky):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"scan_interval": 5, "mqtt_push": True})
        result = await hass.config_entries.options.async_configure(result["flow_id"], {"pin": "1"})
    assert result["errors"] == {"base": "mqtt_failed"}
