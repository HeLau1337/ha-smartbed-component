"""Tests for EspSmartBedApiClient."""

import json
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.smartbed.esp_smartbed_api_client import EspSmartBedApiClient
from custom_components.smartbed.models import (
    SmartBedAxisState,
    SmartBedMotorState,
    SmartBedMotorType,
    SmartBedState,
)


def _make_status_dict(**overrides: Any) -> dict[str, Any]:
    """Create a valid unified /status JSON dict with optional overrides."""
    payload: dict[str, Any] = {
        "hostname": "esp-smartbed-controller",
        "version": "2.0.0",
        "build": "Nov 20 2026 22:00:00",
        "wifiConnected": True,
        "ip": "192.168.178.51",
        "rssi": -62,
        "uptimeMs": 123456,
        "freeHeap": 44800,
        "maxRunDurationMs": 30000,
        "head": {
            "direction": "stopped",
            "source": "none",
            "remainingMs": 0,
        },
        "foot": {
            "direction": "stopped",
            "source": "none",
            "remainingMs": 0,
        },
    }
    payload.update(overrides)
    return payload


def _make_status_json(**overrides: Any) -> str:
    """Serialize a unified /status JSON dict."""
    return json.dumps(_make_status_dict(**overrides))


def _make_expected_state(**overrides: Any) -> SmartBedState:
    """Build the SmartBedState matching _make_status_dict(**overrides)."""
    return SmartBedState.from_dict(_make_status_dict(**overrides))


def _make_mock_get(
    status: int = 200,
    url: str = "http://192.168.1.100/status",
    text: str = "",
) -> AsyncMock:
    """Create a mock aiohttp get context manager returning a configured response."""
    mock_get = AsyncMock()
    mock_response = MagicMock()
    mock_response.status = status
    mock_response.url = url
    mock_response.text = AsyncMock(return_value=text)
    mock_get.__aenter__.return_value = mock_response
    return mock_get


@pytest.fixture
def mock_session():
    """Create a mock aiohttp ClientSession."""
    return MagicMock(spec=aiohttp.ClientSession)


def test_default_timeout():
    """Test that DEFAULT_TIMEOUT uses a 5-second ClientTimeout."""
    assert EspSmartBedApiClient.DEFAULT_TIMEOUT == aiohttp.ClientTimeout(total=5)


async def test_base_url_trailing_slash_normalized(mock_session):
    """Test that trailing slashes on base_url do not produce double slashes."""
    mock_session.get.return_value = _make_mock_get(
        url="http://192.168.1.100/status",
        text=_make_status_json(),
    )

    client = EspSmartBedApiClient("http://192.168.1.100/", mock_session)
    status = await client.async_get_status()

    assert status == _make_expected_state()
    mock_session.get.assert_called_with(
        "http://192.168.1.100/status",
        params=None,
        timeout=EspSmartBedApiClient.DEFAULT_TIMEOUT,
    )

    mock_session.get.return_value = _make_mock_get(
        url="http://192.168.1.100/",
        text="esp-smartbed-controller server is online",
    )
    assert await client.async_test_connection() is True
    mock_session.get.assert_called_with(
        "http://192.168.1.100/",
        params=None,
        timeout=EspSmartBedApiClient.DEFAULT_TIMEOUT,
    )


async def test_custom_timeout_override(mock_session):
    """Test that a custom ClientTimeout passed to __init__ overrides DEFAULT_TIMEOUT."""
    custom_timeout = aiohttp.ClientTimeout(total=2)
    mock_session.get.return_value = _make_mock_get(text=_make_status_json())

    client = EspSmartBedApiClient(
        "http://192.168.1.100", mock_session, timeout=custom_timeout
    )
    await client.async_get_status()

    mock_session.get.assert_called_with(
        "http://192.168.1.100/status",
        params=None,
        timeout=custom_timeout,
    )


async def test_get_status_success(mock_session):
    """Test successful unified status and diagnostics retrieval."""
    mock_session.get.return_value = _make_mock_get(
        text=_make_status_json(
            foot={"direction": "up", "source": "web", "remainingMs": 24500}
        )
    )

    client = EspSmartBedApiClient("http://192.168.1.100", mock_session)
    status = await client.async_get_status()

    assert isinstance(status, SmartBedState)
    assert status.hostname == "esp-smartbed-controller"
    assert status.version == "2.0.0"
    assert status.wifi_connected is True
    assert status.ip == "192.168.178.51"
    assert status.rssi == -62
    assert status.uptime_ms == 123456
    assert status.free_heap == 44800
    assert status.max_run_duration_ms == 30000
    assert status.head == SmartBedAxisState(
        direction="stopped", source="none", remaining_ms=0
    )
    assert status.foot == SmartBedAxisState(
        direction="up", source="web", remaining_ms=24500
    )
    assert client.is_connected() is True


async def test_get_status_forward_compatible_with_extra_keys(mock_session):
    """Test unknown top-level and axis keys are ignored for forward compatibility."""
    payload = _make_status_dict(resetReason="PowerOn")
    payload["head"]["pwm"] = 255
    mock_session.get.return_value = _make_mock_get(text=json.dumps(payload))

    client = EspSmartBedApiClient("http://192.168.1.100", mock_session)
    status = await client.async_get_status()

    assert status == _make_expected_state()


async def test_get_status_connection_error_and_recovery(mock_session):
    """Test connection error handling and subsequent recovery."""
    mock_get = AsyncMock()
    mock_get.__aenter__.side_effect = aiohttp.ClientError("Connection refused")
    mock_session.get.return_value = mock_get

    client = EspSmartBedApiClient("http://192.168.1.100", mock_session)
    assert client.is_connected() is True

    # First failed request
    assert await client.async_get_status() is None
    assert client.is_connected() is False

    # Second failed request (suppresses duplicate warning)
    assert await client.async_get_status() is None
    assert client.is_connected() is False

    # Recovery
    mock_session.get.return_value = _make_mock_get(text=_make_status_json())
    status = await client.async_get_status()
    assert status == _make_expected_state()
    assert client.is_connected() is True


async def test_get_status_timeout_and_recovery(mock_session, caplog):
    """Test TimeoutError marks disconnected, logs once, and recovers cleanly."""
    mock_get = AsyncMock()
    mock_get.__aenter__.side_effect = TimeoutError("Request timed out")
    mock_session.get.return_value = mock_get

    client = EspSmartBedApiClient("http://192.168.1.100", mock_session)

    with caplog.at_level(logging.WARNING):
        assert await client.async_get_status() is None
        assert client.is_connected() is False
        assert await client.async_get_status() is None
        assert client.is_connected() is False

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1

    mock_session.get.return_value = _make_mock_get(text=_make_status_json())
    status = await client.async_get_status()
    assert status == _make_expected_state()
    assert client.is_connected() is True


async def test_unicode_decode_error_returns_none_without_disconnecting(
    mock_session, caplog
):
    """Test invalid UTF-8 response body logs warning and does not mark disconnected."""
    mock_get = _make_mock_get()
    mock_get.__aenter__.return_value.text = AsyncMock(
        side_effect=UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
    )
    mock_session.get.return_value = mock_get

    client = EspSmartBedApiClient("http://192.168.1.100", mock_session)
    with caplog.at_level(logging.WARNING):
        status = await client.async_get_status()

    assert status is None
    assert client.is_connected() is True
    assert any(r.levelno == logging.WARNING for r in caplog.records)


async def test_http_error_status_returns_none_and_logs_error(mock_session, caplog):
    """Test non-200 HTTP responses return None and log an error."""
    client = EspSmartBedApiClient("http://192.168.1.100", mock_session)

    mock_session.get.return_value = _make_mock_get(
        status=500, url="http://192.168.1.100/status", text="Internal Server Error"
    )
    with caplog.at_level(logging.ERROR):
        assert await client.async_get_status() is None

    mock_session.get.return_value = _make_mock_get(
        status=400,
        url="http://192.168.1.100/set?hu=on&hd=off",
        text="Conflicting or invalid head motor parameters.",
    )
    motor = SmartBedMotorState(type=SmartBedMotorType.HEAD, up="on", down="off")
    with caplog.at_level(logging.ERROR):
        assert await client.async_set_motor_state(motor) is None

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 2
    assert client.is_connected() is True


def _without_key(key: str) -> str:
    """Return serialized status payload with one top-level key removed."""
    data = _make_status_dict()
    del data[key]
    return json.dumps(data)


@pytest.mark.parametrize(
    "payload",
    [
        "",
        '{"hostname": "esp-smartbed-controller"',
        "OK",
        "<html>502 Bad Gateway</html>",
        "[]",
        "null",
        "42",
        '{"hu": "off", "hd": "off", "fu": "off", "fd": "off"}',
        _without_key("head"),
        _without_key("rssi"),
        _make_status_json(head={"direction": "stopped"}),
        _make_status_json(head="stopped"),
        _make_status_json(foot=[]),
        _make_status_json(
            head={"direction": "sideways", "source": "none", "remainingMs": 0}
        ),
        _make_status_json(
            head={"direction": True, "source": "none", "remainingMs": 0}
        ),
        _make_status_json(
            foot={"direction": "up", "source": "app", "remainingMs": 1000}
        ),
        _make_status_json(rssi=True),
        _make_status_json(uptimeMs=False),
        _make_status_json(freeHeap=True),
        _make_status_json(maxRunDurationMs=True),
        _make_status_json(
            head={"direction": "up", "source": "web", "remainingMs": True}
        ),
        _make_status_json(uptimeMs=-1),
        _make_status_json(freeHeap=-1),
        _make_status_json(maxRunDurationMs=0),
        _make_status_json(
            head={"direction": "up", "source": "web", "remainingMs": -1}
        ),
        _make_status_json(wifiConnected="true"),
        _make_status_json(hostname=123),
        _make_status_json(version=None),
    ],
)
async def test_get_status_malformed_payload(mock_session, caplog, payload):
    """Test malformed 200 OK payloads return None, keep connected, and log a warning."""
    mock_session.get.return_value = _make_mock_get(text=payload)

    client = EspSmartBedApiClient("http://192.168.1.100", mock_session)
    with caplog.at_level(logging.WARNING):
        status = await client.async_get_status()

    assert status is None
    assert client.is_connected() is True
    assert any(r.levelno == logging.WARNING for r in caplog.records)


async def test_malformed_long_payload_truncated_in_log(mock_session, caplog):
    """Test oversized malformed responses are truncated to 200 chars in warning logs."""
    mock_session.get.return_value = _make_mock_get(text="X" * 500)

    client = EspSmartBedApiClient("http://192.168.1.100", mock_session)
    with caplog.at_level(logging.WARNING):
        status = await client.async_get_status()

    assert status is None
    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert ("X" * 200 + "...") in warnings[0]
    assert ("X" * 250) not in warnings[0]


async def test_set_motor_state(mock_session):
    """Test setting motor state parses and returns the unified SmartBedState."""
    head_up = {"direction": "up", "source": "web", "remainingMs": 30000}
    mock_session.get.return_value = _make_mock_get(
        url="http://192.168.1.100/set?hu=on&hd=off",
        text=_make_status_json(head=head_up),
    )

    client = EspSmartBedApiClient("http://192.168.1.100", mock_session)
    motor = SmartBedMotorState(type=SmartBedMotorType.HEAD, up="on", down="off")

    state = await client.async_set_motor_state(motor)
    assert state == _make_expected_state(head=head_up)
    mock_session.get.assert_called_with(
        "http://192.168.1.100/set",
        params={"hu": "on", "hd": "off"},
        timeout=EspSmartBedApiClient.DEFAULT_TIMEOUT,
    )


async def test_set_motor_state_connection_error(mock_session):
    """Test setting motor state returns None and marks disconnected on network error."""
    mock_get = AsyncMock()
    mock_get.__aenter__.side_effect = aiohttp.ClientError("Unreachable")
    mock_session.get.return_value = mock_get

    client = EspSmartBedApiClient("http://192.168.1.100", mock_session)
    motor = SmartBedMotorState(type=SmartBedMotorType.HEAD, up="on", down="off")

    assert await client.async_set_motor_state(motor) is None
    assert client.is_connected() is False


async def test_set_motor_state_malformed_payload(mock_session, caplog):
    """Test setting motor state returns None and logs warning on malformed 200 payload."""
    mock_session.get.return_value = _make_mock_get(
        url="http://192.168.1.100/set?hu=on&hd=off",
        text="OK",
    )

    client = EspSmartBedApiClient("http://192.168.1.100", mock_session)
    motor = SmartBedMotorState(type=SmartBedMotorType.HEAD, up="on", down="off")

    with caplog.at_level(logging.WARNING):
        state = await client.async_set_motor_state(motor)

    assert state is None
    assert client.is_connected() is True
    assert any(r.levelno == logging.WARNING for r in caplog.records)


async def test_stop_all_success(mock_session):
    """Test emergency/full stop hits /stop and returns parsed SmartBedState."""
    mock_session.get.return_value = _make_mock_get(
        url="http://192.168.1.100/stop",
        text=_make_status_json(),
    )

    client = EspSmartBedApiClient("http://192.168.1.100", mock_session)
    state = await client.async_stop_all()

    assert state == _make_expected_state()
    mock_session.get.assert_called_with(
        "http://192.168.1.100/stop",
        params=None,
        timeout=EspSmartBedApiClient.DEFAULT_TIMEOUT,
    )


async def test_stop_all_connection_error(mock_session):
    """Test full stop returns None and marks disconnected on network error."""
    mock_get = AsyncMock()
    mock_get.__aenter__.side_effect = aiohttp.ClientError("Unreachable")
    mock_session.get.return_value = mock_get

    client = EspSmartBedApiClient("http://192.168.1.100", mock_session)
    assert await client.async_stop_all() is None
    assert client.is_connected() is False


async def test_stop_all_malformed_payload(mock_session, caplog):
    """Test full stop returns None and logs warning on malformed 200 payload."""
    mock_session.get.return_value = _make_mock_get(
        url="http://192.168.1.100/stop",
        text='{"hu": "off"}',
    )

    client = EspSmartBedApiClient("http://192.168.1.100", mock_session)
    with caplog.at_level(logging.WARNING):
        state = await client.async_stop_all()

    assert state is None
    assert client.is_connected() is True
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_smartbed_state_validation():
    """Test SmartBedAxisState and SmartBedState validate inputs and axis lookup."""
    state = _make_expected_state(
        head={"direction": "up", "source": "web", "remainingMs": 5000}
    )
    assert state.axis(SmartBedMotorType.HEAD) == state.head
    assert state.axis(SmartBedMotorType.FOOT) == state.foot

    with pytest.raises(ValueError):
        SmartBedAxisState(direction="invalid", source="none", remaining_ms=0)  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        SmartBedAxisState(direction="up", source="invalid", remaining_ms=0)  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        SmartBedAxisState(direction="up", source="web", remaining_ms=True)  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        SmartBedAxisState(direction="up", source="web", remaining_ms=-5)

    with pytest.raises(ValueError):
        SmartBedState(
            hostname="esp-smartbed-controller",
            version="2.0.0",
            build="Nov 20 2026 22:00:00",
            wifi_connected=True,
            ip="192.168.178.51",
            rssi=True,  # type: ignore[arg-type]
            uptime_ms=1000,
            free_heap=44800,
            max_run_duration_ms=30000,
            head=state.head,
            foot=state.foot,
        )


async def test_test_connection(mock_session):
    """Test connection testing."""
    mock_session.get.return_value = _make_mock_get(
        url="http://192.168.1.100/",
        text="OK",
    )

    client = EspSmartBedApiClient("http://192.168.1.100", mock_session)
    assert await client.async_test_connection() is True

    # Error case
    mock_get = AsyncMock()
    mock_get.__aenter__.side_effect = aiohttp.ClientError("Unreachable")
    mock_session.get.return_value = mock_get
    assert await client.async_test_connection() is False
