"""Config flow for the Rocket.Chat integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from aiohttp import ClientError
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_TOKEN, CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_CHANNELS, CONF_USER_ID, DOMAIN
from .ddp import RocketChatClientError, RocketChatDDPClient


async def _async_get_client(
    hass: HomeAssistant, user_input: Mapping[str, Any]
) -> RocketChatDDPClient:
    """Create and authenticate a client for config flow validation."""

    session = async_get_clientsession(hass)
    client = RocketChatDDPClient(
        hass,
        session,
        user_input[CONF_URL],
        user_input[CONF_USER_ID],
        user_input[CONF_TOKEN],
    )
    await client.async_connect()
    return client


class RocketChatConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Rocket.Chat."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""

        self._auth_input: dict[str, Any] | None = None
        self._channels: dict[str, str] = {}

    async def async_step_user(
        self, user_input: Mapping[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""

        errors: dict[str, str] = {}
        client: RocketChatDDPClient | None = None
        if user_input:
            try:
                client = await _async_get_client(self.hass, user_input)
                channels = await client.async_list_channels()
            except RocketChatClientError:
                errors["base"] = "cannot_connect"
            except ClientError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(user_input[CONF_USER_ID])
                self._abort_if_unique_id_configured()
                self._auth_input = dict(user_input)
                self._channels = {
                    channel.identifier: channel.name for channel in channels
                }
                return await self.async_step_channels()
            finally:
                if client is not None:
                    await client.async_close()

        data_schema = vol.Schema(
            {
                vol.Required(CONF_URL): str,
                vol.Required(CONF_USER_ID): str,
                vol.Required(CONF_TOKEN): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)

    async def async_step_channels(
        self, user_input: Mapping[str, Any] | None = None
    ) -> FlowResult:
        """Handle channel selection."""

        assert self._auth_input is not None
        errors: dict[str, str] = {}

        if user_input:
            if not user_input[CONF_CHANNELS]:
                errors["base"] = "no_channels"
            else:
                data = {
                    **self._auth_input,
                    CONF_CHANNELS: [
                        {"id": channel_id, "name": self._channels[channel_id]}
                        for channel_id in user_input[CONF_CHANNELS]
                    ],
                }
                return self.async_create_entry(title=self._auth_input[CONF_URL], data=data)

        if not self._channels:
            errors["base"] = "no_channels"

        return self.async_show_form(
            step_id="channels",
            data_schema=vol.Schema(
                {vol.Required(CONF_CHANNELS, default=list(self._channels)): cv.multi_select(self._channels)}
            ),
            errors=errors,
        )


class RocketChatOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Rocket.Chat options flows."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize the options flow."""

        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: Mapping[str, Any] | None = None
    ) -> FlowResult:
        """Manage options for the integration."""

        errors: dict[str, str] = {}
        client: RocketChatDDPClient | None = None
        if user_input:
            return self.async_create_entry(title="", data=user_input)

        hass = self.hass
        try:
            client = await _async_get_client(hass, self.config_entry.data)
            channels = await client.async_list_channels()
        except (RocketChatClientError, ClientError):
            errors["base"] = "cannot_connect"
            channels = []
        finally:
            if client is not None:
                await client.async_close()

        existing_channels = self.config_entry.data.get(CONF_CHANNELS, [])
        existing_ids = [channel["id"] for channel in existing_channels]
        channel_map = {channel.identifier: channel.name for channel in channels}

        if not channel_map:
            errors["base"] = errors.get("base", "no_channels")

        default_ids = [channel_id for channel_id in existing_ids if channel_id in channel_map]

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {vol.Required(CONF_CHANNELS, default=default_ids): cv.multi_select(channel_map)}
            ),
            errors=errors,
        )


def create_options_flow(
    config_entry: config_entries.ConfigEntry,
) -> RocketChatOptionsFlowHandler:
    """Create the options flow handler."""

    return RocketChatOptionsFlowHandler(config_entry)
