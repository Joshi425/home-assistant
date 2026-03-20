"""Event entities for Rocket.Chat channels."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_CHANNELS, DOMAIN, EVENT_TYPE_MESSAGE


async def async_setup_entry(
    hass, entry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Rocket.Chat events from a config entry."""

    channels = entry.options.get(CONF_CHANNELS, entry.data[CONF_CHANNELS])
    runtime = hass.data[DOMAIN][entry.entry_id]
    entities = [
        RocketChatChannelEvent(
            runtime.client, entry.entry_id, channel_data["id"], channel_data["name"]
        )
        for channel_data in channels
    ]
    async_add_entities(entities)


class RocketChatChannelEvent(EventEntity):
    """Representation of a Rocket.Chat room as an event entity."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, client, entry_id: str, room_id: str, name: str) -> None:
        """Initialize the event entity."""

        self._client = client
        self._room_id = room_id
        self._unsub = None
        self._attr_unique_id = f"{entry_id}_{room_id}"
        self._attr_event_types = [EVENT_TYPE_MESSAGE]
        self._attr_name = name

    async def async_added_to_hass(self) -> None:
        """Handle entity added to hass."""

        await super().async_added_to_hass()
        self._unsub = await self._client.async_subscribe_room(
            self._room_id, self._handle_message
        )

    async def async_will_remove_from_hass(self) -> None:
        """Handle entity removal."""

        if self._unsub:
            self._unsub()
        await super().async_will_remove_from_hass()

    @callback
    def _handle_message(self, payload: dict[str, Any]) -> None:
        """Process an incoming message event."""

        self._trigger_event(EVENT_TYPE_MESSAGE, payload)
        self.async_write_ha_state()
