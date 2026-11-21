"""Handles communication with the ESP8266 webserver API endpoint for setting the SmartBed's state."""

from __future__ import annotations

import json
import logging

import aiohttp

from .models import SmartBedMotorState, SmartBedState

_LOGGER = logging.getLogger(__name__)
_MAX_LOG_PAYLOAD_LEN = 200


class EspSmartBedApiClient:
    """Handles communication with the ESP8266 webserver API endpoint for setting the SmartBed's state."""

    SET_STATE_ENDPOINT = "set"
    STATUS_ENDPOINT = "status"
    STOP_ENDPOINT = "stop"
    DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=5)

    def __init__(
        self,
        base_url: str,
        session: aiohttp.ClientSession,
        timeout: aiohttp.ClientTimeout | None = None,
    ) -> None:
        """Initialize the API by setting the base url."""
        self._base_url = base_url.rstrip("/")
        self._session = session
        self._timeout = timeout if timeout is not None else self.DEFAULT_TIMEOUT
        self._is_connected = True

    def is_connected(self) -> bool:
        """Return the connection state."""
        return self._is_connected

    async def _async_request(
        self, endpoint: str, params: dict[str, str] | None = None
    ) -> tuple[int, str, str] | None:
        """Perform a request to the API endpoint with error handling and connection state management."""
        try:
            async with self._session.get(
                f"{self._base_url}/{endpoint}", params=params, timeout=self._timeout
            ) as response:
                text = await response.text()
                if not self._is_connected:
                    _LOGGER.info("SmartBed reconnected")
                    self._is_connected = True
                return response.status, str(response.url), text
        except (aiohttp.ClientError, TimeoutError) as err:
            if self._is_connected:
                _LOGGER.warning("Connection to SmartBed failed: %s", err)
                self._is_connected = False
            return None
        except UnicodeDecodeError as err:
            _LOGGER.warning(
                "Failed to decode SmartBed response for /%s: %s", endpoint, err
            )
            return None

    async def _async_request_state(
        self, endpoint: str, params: dict[str, str] | None = None
    ) -> SmartBedState | None:
        """Perform an endpoint request and parse the resulting SmartBedState."""
        result = await self._async_request(endpoint, params)
        if result:
            status, url, text = result
            return self._handle_response(status, url, text)
        return None

    async def async_test_connection(self) -> bool:
        """Test the connection to the base url."""
        result = await self._async_request("")
        if result:
            return result[0] == 200
        return False

    async def async_set_motor_state(
        self, motor: SmartBedMotorState
    ) -> SmartBedState | None:
        """Send a GET request to the API endpoint for setting a new state of the SmartBed."""
        params = {
            f"{motor.type.value}u": motor.up,
            f"{motor.type.value}d": motor.down,
        }

        return await self._async_request_state(self.SET_STATE_ENDPOINT, params)

    async def async_stop_all(self) -> SmartBedState | None:
        """Send a GET request to immediately stop both motors."""
        return await self._async_request_state(self.STOP_ENDPOINT)

    async def async_get_status(self) -> SmartBedState | None:
        """Get the current state of the SmartBed."""
        return await self._async_request_state(self.STATUS_ENDPOINT)

    def _handle_response(
        self, status: int, url: str, text: str
    ) -> SmartBedState | None:
        """Parse and validate a SmartBed JSON status response."""
        _LOGGER.debug(
            "Sent GET request was: %s",
            url,
        )
        if status == 200:
            _LOGGER.debug(
                "Response status code: %s | Response text: %s", status, text
            )
            try:
                resp_json = json.loads(text)
                return SmartBedState.from_dict(resp_json)
            except (json.JSONDecodeError, TypeError, ValueError) as err:
                preview = (
                    text
                    if len(text) <= _MAX_LOG_PAYLOAD_LEN
                    else f"{text[:_MAX_LOG_PAYLOAD_LEN]}..."
                )
                _LOGGER.warning(
                    "Malformed SmartBed response from %s (%s): %r",
                    url,
                    err,
                    preview,
                )
                return None
        _LOGGER.error("Response status code: %s | Response text: %s", status, text)
        return None
