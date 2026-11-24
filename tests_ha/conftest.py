from pathlib import Path
from unittest.mock import patch

import custom_components

# pytest-homeassistant-custom-component ships its own `custom_components`
# package; make ours importable next to it.
_ours = str(Path(__file__).resolve().parents[1] / "custom_components")
if _ours not in custom_components.__path__:
    custom_components.__path__.append(_ours)

import pytest

from .fake_tv import FakeTV


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def fake_tv():
    tv = FakeTV()
    make = tv.factory()
    with (
        patch("custom_components.philips_titan.TitanTV", side_effect=make),
        patch("custom_components.philips_titan.config_flow.TitanTV", side_effect=make),
        patch("custom_components.philips_titan.config_flow.arp_lookup", return_value="bc:c2:d9:64:15:b8"),
        patch("custom_components.philips_titan.coordinator.wake") as wake,
    ):
        tv.wake = wake
        yield tv
