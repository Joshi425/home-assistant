"""Async Rocket.Chat DDP client."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import asyncio
import json
import logging
from typing import Any

from aiohttp import ClientConnectionError, ClientSession, ClientWebSocketResponse, WSMsgType

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .const import EVENT_TYPE_MESSAGE

_LOGGER = logging.getLogger(__name__)


@dataclass
class RocketChatChannel:
    """Representation of a Rocket.Chat channel."""

    identifier: str
    name: str


class RocketChatClientError(HomeAssistantError):
    """Raised when the Rocket.Chat client encounters an error."""


class RocketChatDDPClient:
    """Simple DDP client for Rocket.Chat websocket APIs."""

    def __init__(
        self,
        hass: HomeAssistant,
        session: ClientSession,
        url: str,
        user_id: str,
        token: str,
    ) -> None:
        """Initialize the DDP client."""

        self._hass = hass
        self._session = session
        self._url = url.rstrip("/")
        self._user_id = user_id
        self._token = token
        self._ws: ClientWebSocketResponse | None = None
        self._listener_task: asyncio.Task | None = None
        self._message_id = 0
        self._pending_results: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._subscriptions: dict[str, Callable[[dict[str, Any]], None]] = {}

    async def async_connect(self) -> None:
        """Open the websocket and authenticate."""

        if self._ws is not None:
            return

        try:
            self._ws = await self._session.ws_connect(
                f"{self._url}/websocket", heartbeat=30
            )
        except ClientConnectionError as err:
            raise RocketChatClientError("Failed to connect to Rocket.Chat") from err

        await self._send_json({"msg": "connect", "version": "1", "support": ["1"]})
        response = await self._receive_message()
        if response.get("msg") != "connected":
            raise RocketChatClientError("Rocket.Chat did not accept DDP connection")

        result = await self._call_method(
            "login", {"resume": self._token}, expected_key="id"
        )
        user_id = result.get("id") if isinstance(result, dict) else None
        if user_id != self._user_id:
            raise RocketChatClientError("Rocket.Chat login failed")

        self._listener_task = self._hass.async_create_task(self._message_listener())

    async def async_close(self) -> None:
        """Close the websocket connection."""

        if self._listener_task:
            self._listener_task.cancel()

        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    async def async_list_channels(self) -> list[RocketChatChannel]:
        """Return available channels for the authenticated user."""

        result = await self._call_method("rooms.get", None)
        if not isinstance(result, dict):
            raise RocketChatClientError("Unexpected response when listing channels")

        rooms = result.get("update") or []
        channels: list[RocketChatChannel] = []
        for room in rooms:
            if not isinstance(room, dict):
                continue
            room_id = room.get("_id")
            if not isinstance(room_id, str):
                continue
            name = room.get("name") or room.get("fname") or room_id
            channels.append(RocketChatChannel(room_id, str(name)))
        return channels

    async def async_subscribe_room(
        self, room_id: str, message_callback: Callable[[dict[str, Any]], None]
    ) -> CALLBACK_TYPE:
        """Subscribe to message events for a room."""

        sub_id = self._next_message_id()
        self._subscriptions[sub_id] = message_callback
        await self._send_json(
            {
                "msg": "sub",
                "id": sub_id,
                "name": "stream-room-messages",
                "params": [room_id, False],
            }
        )

        @callback
        def _unsub() -> None:
            self._subscriptions.pop(sub_id, None)
            if self._ws is not None:
                self._hass.async_create_task(
                    self._send_json({"msg": "unsub", "id": sub_id})
                )

        return _unsub

    async def _call_method(
        self, method: str, params: Any | None, expected_key: str | None = "result"
    ) -> Any:
        """Send a DDP method request and return the result."""

        if self._ws is None:
            raise RocketChatClientError("Websocket is not connected")

        msg_id = self._next_message_id()
        future: asyncio.Future[dict[str, Any]] = self._hass.loop.create_future()
        self._pending_results[msg_id] = future
        await self._send_json(
            {"msg": "method", "method": method, "params": [params], "id": msg_id}
        )

        if self._listener_task:
            await future
        else:
            await self._wait_for_result(msg_id)

        data = future.result()
        if expected_key is None:
            return data
        if expected_key not in data:
            raise RocketChatClientError(f"Missing {expected_key} in method response")
        return data[expected_key]

    async def _wait_for_result(self, msg_id: str) -> None:
        """Wait for a method result message."""

        while msg_id in self._pending_results:
            await self._receive_message()

    async def _message_listener(self) -> None:
        """Listen for incoming messages and dispatch callbacks."""

        assert self._ws is not None
        async for message in self._ws:
            if message.type == WSMsgType.TEXT:
                data = json.loads(message.data)
                await self._handle_message(data)
            elif message.type == WSMsgType.ERROR:
                _LOGGER.warning("Rocket.Chat websocket closed unexpectedly")
                break

    async def _handle_message(self, data: dict[str, Any]) -> None:
        """Process a single websocket message."""

        if data.get("msg") == "ping":
            await self._send_json({"msg": "pong"})
            return

        if data.get("msg") == "result":
            if future := self._pending_results.pop(data["id"], None):
                if not future.done():
                    future.set_result(data)
            return

        if data.get("msg") == "changed" and data.get("collection") == "stream-room-messages":
            if (callback := self._subscriptions.get(data.get("id"))) is None:
                return
            fields = data.get("fields") or {}
            for payload in fields.get("args", []):
                callback({"event_type": EVENT_TYPE_MESSAGE, "payload": payload})

    async def _receive_message(self) -> dict[str, Any]:
        """Receive a single websocket message."""

        assert self._ws is not None
        message = await self._ws.receive()
        if message.type != WSMsgType.TEXT:
            raise RocketChatClientError("Unexpected websocket message type")
        data = json.loads(message.data)
        await self._handle_message(data)
        return data

    async def _send_json(self, payload: dict[str, Any]) -> None:
        """Send a JSON payload on the websocket."""

        assert self._ws is not None
        await self._ws.send_json(payload)

    def _next_message_id(self) -> str:
        """Return the next message id."""

        self._message_id += 1
        return str(self._message_id)
