"""Buttons for remote keys Home Assistant's media player has no control for."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import TitanConfigEntry, TitanCoordinator
from .entity import TitanEntity, tv_command


@dataclass(frozen=True, kw_only=True)
class TitanButtonDescription(ButtonEntityDescription):
    tv_key: str


BUTTONS = (
    TitanButtonDescription(key="rewind", translation_key="rewind", tv_key="Rewind", icon="mdi:rewind"),
    TitanButtonDescription(
        key="fast_forward", translation_key="fast_forward", tv_key="FastForward", icon="mdi:fast-forward"
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: TitanConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities(TitanKeyButton(entry.runtime_data, d) for d in BUTTONS)


class TitanKeyButton(TitanEntity, ButtonEntity):
    entity_description: TitanButtonDescription

    def __init__(self, coordinator: TitanCoordinator, description: TitanButtonDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        return super().available and self.tv_on

    @tv_command
    async def async_press(self) -> None:
        await self.coordinator.tv.send_key(self.entity_description.tv_key)
