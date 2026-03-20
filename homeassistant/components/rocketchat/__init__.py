"""The Rocket.Chat integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TOKEN, CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .config_flow import RocketChatOptionsFlowHandler, create_options_flow
from .const import CONF_USER_ID, DOMAIN, PLATFORMS
from .ddp import RocketChatDDPClient


type RocketChatConfigEntry = ConfigEntry


@dataclass
class RocketChatRuntimeData:
    """Container for integration runtime data."""

    client: RocketChatDDPClient


async def async_setup_entry(hass: HomeAssistant, entry: RocketChatConfigEntry) -> bool:
    """Set up Rocket.Chat from a config entry."""

    hass.data.setdefault(DOMAIN, {})
    session = async_get_clientsession(hass)
    client = RocketChatDDPClient(
        hass,
        session,
        entry.data[CONF_URL],
        entry.data[CONF_USER_ID],
        entry.data[CONF_TOKEN],
    )
    await client.async_connect()

    hass.data[DOMAIN][entry.entry_id] = RocketChatRuntimeData(client)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: RocketChatConfigEntry) -> bool:
    """Unload a Rocket.Chat config entry."""

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok and (runtime := hass.data[DOMAIN].pop(entry.entry_id, None)):
        await runtime.client.async_close()
    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Handle migration of config entries."""

    return True


async def async_get_options_flow(config_entry: ConfigEntry) -> RocketChatOptionsFlowHandler:
    """Return the options flow handler factory."""

    return create_options_flow(config_entry)
