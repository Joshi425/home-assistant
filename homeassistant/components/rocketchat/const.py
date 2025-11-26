"""Constants for the Rocket.Chat integration."""

from homeassistant.const import Platform

DOMAIN = "rocketchat"

CONF_CHANNELS = "channels"
CONF_USER_ID = "user_id"

PLATFORMS = [Platform.EVENT]

EVENT_TYPE_MESSAGE = "message"
