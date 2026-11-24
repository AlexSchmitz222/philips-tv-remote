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
