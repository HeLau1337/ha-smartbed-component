"""Handles communication with the ESP8266 webserver API endpoint for setting the SmartBed's state."""

import json
import logging

import asyncio
import aiohttp

from .models import SmartBedMotorState, SmartBedState

_LOGGER = logging.getLogger(__name__)


class EspSmartBedApiClient:
    """Handles communication with the ESP8266 webserver API endpoint for setting the SmartBed's state."""

    SET_STATE_ENDPOINT = "set"
    STATUS_ENDPOINT = "status"
    DEFAULT_TIMEOUT = 60

    def __init__(self, base_url: str, session: aiohttp.ClientSession) -> None:
        """Initialize the API by setting the base url."""
        self._base_url = base_url
        self._session = session
        self._is_connected = True

    def is_connected(self) -> bool:
        """Return the connection state."""
        return self._is_connected

    async def _async_request(self, endpoint: str, params: dict = None) -> tuple[int, str, str] | None:
        """Perform a request to the API endpoint with error handling and connection state management."""
        try:
            async with self._session.get(
                f"{self._base_url}/{endpoint}", params=params, timeout=self.DEFAULT_TIMEOUT
            ) as response:
                text = await response.text()
                if not self._is_connected:
                    _LOGGER.info("SmartBed reconnected")
                    self._is_connected = True
                return response.status, str(response.url), text
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            if self._is_connected:
                _LOGGER.warning("Connection to SmartBed failed: %s", err)
                self._is_connected = False
            return None

    async def async_test_connection(self) -> bool:
        """Test the connection to the base url."""
        result = await self._async_request("")
        if result:
            return result[0] == 200
        return False

    async def async_set_motor_state(self, motor: SmartBedMotorState) -> bool | None:
        """Send a GET request to the API endpoint for setting a new state of the SmartBed."""
        params = {
            f"{motor.type.value}u": motor.up,
            f"{motor.type.value}d": motor.down,
        }

        result = await self._async_request(self.SET_STATE_ENDPOINT, params)
        if result:
            return result[0] == 200
        return None

    async def async_get_status(self) -> SmartBedState | None:
        """Get the current state of the SmartBed."""
        result = await self._async_request(self.STATUS_ENDPOINT)
        if result:
            status, url, text = result
            return self._handle_response(status, url, text)
        return None

    def _handle_response(
        self, status: int, url: str, text: str
    ) -> SmartBedState | None:
        _LOGGER.debug(
            "Sent GET request was: %s",
            url,
        )
        if status == 200:
            _LOGGER.debug(
                "Response status code: %s | Response text: %s",
                status,
                text,
            )
            resp_json = json.loads(text)
            return SmartBedState(**resp_json)
        
        _LOGGER.error(
            "Response status code: %s | Response text: %s",
            status,
            text,
        )
        return None
