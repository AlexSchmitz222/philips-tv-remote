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
