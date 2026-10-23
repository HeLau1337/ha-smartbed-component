"""Tests for EspSmartBedApiClient."""

from unittest.mock import AsyncMock, MagicMock
import aiohttp
import pytest

from custom_components.smartbed.esp_smartbed_api_client import EspSmartBedApiClient
from custom_components.smartbed.models import SmartBedMotorState, SmartBedMotorType, SmartBedState


@pytest.fixture
def mock_session():
    """Create a mock aiohttp ClientSession."""
    return MagicMock(spec=aiohttp.ClientSession)


async def test_get_status_success(mock_session):
    """Test successful status retrieval."""
    mock_get = AsyncMock()
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.url = "http://192.168.1.100/status"
    mock_response.text = AsyncMock(
        return_value='{"hu": "off", "hd": "off", "fu": "on", "fd": "off"}'
    )
    mock_get.__aenter__.return_value = mock_response
    mock_session.get.return_value = mock_get

    client = EspSmartBedApiClient("http://192.168.1.100", mock_session)
    status = await client.async_get_status()

    assert isinstance(status, SmartBedState)
    assert status.hu == "off"
    assert status.hd == "off"
    assert status.fu == "on"
    assert status.fd == "off"
    assert client.is_connected() is True


async def test_get_status_connection_error_and_recovery(mock_session):
    """Test connection error handling and subsequent recovery."""
    mock_get = AsyncMock()
    mock_get.__aenter__.side_effect = aiohttp.ClientError("Connection refused")
    mock_session.get.return_value = mock_get

    client = EspSmartBedApiClient("http://192.168.1.100", mock_session)
    assert client.is_connected() is True

    # First failed request
    status = await client.async_get_status()
    assert status is None
    assert client.is_connected() is False

    # Second failed request (suppresses duplicate warning)
    status = await client.async_get_status()
    assert status is None
    assert client.is_connected() is False

    # Recovery
    mock_success = AsyncMock()
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.url = "http://192.168.1.100/status"
    mock_response.text = AsyncMock(
        return_value='{"hu": "off", "hd": "off", "fu": "off", "fd": "off"}'
    )
    mock_success.__aenter__.return_value = mock_response
    mock_session.get.return_value = mock_success

    status = await client.async_get_status()
    assert status is not None
    assert client.is_connected() is True


async def test_set_motor_state(mock_session):
    """Test setting motor state."""
    mock_get = AsyncMock()
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.url = "http://192.168.1.100/set?hu=on&hd=off"
    mock_response.text = AsyncMock(return_value="OK")
    mock_get.__aenter__.return_value = mock_response
    mock_session.get.return_value = mock_get

    client = EspSmartBedApiClient("http://192.168.1.100", mock_session)
    motor = SmartBedMotorState(type=SmartBedMotorType.HEAD, up="on", down="off")

    success = await client.async_set_motor_state(motor)
    assert success is True
    mock_session.get.assert_called_with(
        "http://192.168.1.100/set",
        params={"hu": "on", "hd": "off"},
        timeout=EspSmartBedApiClient.DEFAULT_TIMEOUT,
    )


async def test_test_connection(mock_session):
    """Test connection testing."""
    mock_get = AsyncMock()
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.url = "http://192.168.1.100/"
    mock_response.text = AsyncMock(return_value="OK")
    mock_get.__aenter__.return_value = mock_response
    mock_session.get.return_value = mock_get

    client = EspSmartBedApiClient("http://192.168.1.100", mock_session)
    assert await client.async_test_connection() is True

    # Error case
    mock_get.__aenter__.side_effect = aiohttp.ClientError("Unreachable")
    assert await client.async_test_connection() is False
