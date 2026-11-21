"""Tests for the SmartBed cover platform."""

from datetime import timedelta
import logging
from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntityFeature,
)
from homeassistant.const import (
    CONF_NAME,
    CONF_SCAN_INTERVAL,
    STATE_CLOSED,
    STATE_OPEN,
    STATE_UNKNOWN,
)
from homeassistant.core import State
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from custom_components.smartbed import async_setup
from custom_components.smartbed.const import (
    CONF_BASE_URL,
    DATA_ENTRIES,
    DOMAIN,
)
from custom_components.smartbed.cover import (
    SCAN_INTERVAL,
    SmartBedMotor,
    async_setup_platform,
)
from custom_components.smartbed.entity import SmartBedRuntimeData, clean_base_url
from custom_components.smartbed.models import (
    ControlSource,
    MotorDirection,
    SmartBedAxisState,
    SmartBedMotorState,
    SmartBedMotorType,
    SmartBedState,
)


def _make_axis(
    direction: MotorDirection = "stopped",
    source: ControlSource = "none",
    remaining_ms: int = 0,
) -> SmartBedAxisState:
    """Create a SmartBedAxisState for cover tests."""
    return SmartBedAxisState(
        direction=direction, source=source, remaining_ms=remaining_ms
    )


def _make_state(
    head: SmartBedAxisState | None = None,
    foot: SmartBedAxisState | None = None,
    *,
    version: str = "2.0.0",
    rssi: int = -62,
    uptime_ms: int = 123456,
    free_heap: int = 44800,
) -> SmartBedState:
    """Create a unified SmartBedState for cover tests."""
    return SmartBedState(
        hostname="esp-smartbed-controller",
        version=version,
        build="Nov 20 2026 22:00:00",
        wifi_connected=True,
        ip="192.168.178.51",
        rssi=rssi,
        uptime_ms=uptime_ms,
        free_heap=free_heap,
        max_run_duration_ms=30000,
        head=head if head is not None else _make_axis(),
        foot=foot if foot is not None else _make_axis(),
    )


def create_motor(
    motor_type: SmartBedMotorType = SmartBedMotorType.HEAD,
    mock_api: MagicMock | None = None,
    coordinator: DataUpdateCoordinator | MagicMock | None = None,
    base_url: str = "http://esp-smartbed-controller.local",
) -> SmartBedMotor:
    """Helper to instantiate SmartBedMotor with mocks."""
    if mock_api is None:
        mock_api = MagicMock()
        mock_api.is_connected.return_value = True

    if coordinator is None:
        coordinator = MagicMock(spec=DataUpdateCoordinator)
        coordinator.last_update_success = True
        coordinator.data = None

    runtime_data = SmartBedRuntimeData(
        name="SmartBed",
        base_url=base_url,
        clean_url=clean_base_url(base_url),
        api=mock_api,
        coordinator=coordinator,
    )
    return SmartBedMotor(runtime_data, motor_type)


def create_coordinator_and_motors(
    hass,
    mock_api: MagicMock,
) -> tuple[DataUpdateCoordinator[SmartBedState | None], SmartBedMotor, SmartBedMotor]:
    """Create a real DataUpdateCoordinator with Head and Foot motors ready for HA setup."""
    coordinator: DataUpdateCoordinator[SmartBedState | None] = DataUpdateCoordinator(
        hass,
        logging.getLogger(__name__),
        config_entry=None,
        name="SmartBed",
        update_method=mock_api.async_get_status,
        update_interval=SCAN_INTERVAL,
    )
    runtime_data = SmartBedRuntimeData(
        name="SmartBed",
        base_url="http://esp-smartbed-controller.local",
        clean_url="esp-smartbed-controller.local",
        api=mock_api,
        coordinator=coordinator,
    )
    head_motor = SmartBedMotor(runtime_data, SmartBedMotorType.HEAD)
    foot_motor = SmartBedMotor(runtime_data, SmartBedMotorType.FOOT)
    for motor in (head_motor, foot_motor):
        motor.hass = hass
        motor.async_write_ha_state = MagicMock()
        motor.async_get_last_state = AsyncMock(return_value=None)
    return coordinator, head_motor, foot_motor


def test_motor_initial_state():
    """Test initial state and attributes of SmartBedMotor."""
    motor = create_motor(SmartBedMotorType.HEAD)

    assert motor._attr_assumed_state is True
    assert motor._attr_device_class == CoverDeviceClass.SHUTTER
    assert motor._attr_supported_features == (
        CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
    )
    assert motor.should_poll is False
    # Crucial fix: is_closed must be boolean True initially, never None
    assert motor.is_closed is True
    assert motor.is_opening is False
    assert motor.is_closing is False
    assert motor.extra_state_attributes == {}
    assert motor.device_info["sw_version"] is None
    assert motor.available is True
    assert motor.unique_id == f"{DOMAIN}_esp-smartbed-controller.local_h"


def test_device_info_groups_both_motors_under_single_device():
    """Test both motors share the same device_info identifier while keeping unique_ids distinct."""
    coordinator = MagicMock(spec=DataUpdateCoordinator)
    coordinator.last_update_success = True
    coordinator.data = _make_state(version="2.0.0")

    head_motor = create_motor(
        SmartBedMotorType.HEAD,
        coordinator=coordinator,
        base_url="http://esp-smartbed-controller.local",
    )
    foot_motor = create_motor(
        SmartBedMotorType.FOOT,
        coordinator=coordinator,
        base_url="https://esp-smartbed-controller.local/",
    )

    assert head_motor.unique_id != foot_motor.unique_id
    assert head_motor.unique_id == f"{DOMAIN}_esp-smartbed-controller.local_h"
    assert foot_motor.unique_id == f"{DOMAIN}_esp-smartbed-controller.local_f"

    expected_identifiers = {(DOMAIN, "esp-smartbed-controller.local")}
    assert head_motor.device_info["identifiers"] == expected_identifiers
    assert foot_motor.device_info["identifiers"] == expected_identifiers
    assert head_motor.device_info["name"] == "SmartBed"
    assert foot_motor.device_info["name"] == "SmartBed"
    assert head_motor.device_info["sw_version"] == "2.0.0"
    assert foot_motor.device_info["sw_version"] == "2.0.0"
    assert (
        head_motor.device_info["configuration_url"]
        == "http://esp-smartbed-controller.local"
    )


async def test_motor_state_restoration():
    """Test state restoration across restarts using RestoreEntity."""
    motor = create_motor(SmartBedMotorType.HEAD)
    motor.hass = MagicMock()

    # Case 1: Restore OPEN state
    motor.async_get_last_state = AsyncMock(
        return_value=State("cover.smartbed_head_motor", STATE_OPEN)
    )
    await motor.async_added_to_hass()
    assert motor.is_closed is False

    # Case 2: Restore CLOSED state
    motor.async_get_last_state = AsyncMock(
        return_value=State("cover.smartbed_head_motor", STATE_CLOSED)
    )
    await motor.async_added_to_hass()
    assert motor.is_closed is True

    # Case 3: Restore UNKNOWN / None state (defaults to flat/closed)
    motor.async_get_last_state = AsyncMock(
        return_value=State("cover.smartbed_head_motor", STATE_UNKNOWN)
    )
    await motor.async_added_to_hass()
    assert motor.is_closed is True


async def test_motor_open_action(hass):
    """Test async_open_cover calls API and syncs both motors and attributes via coordinator."""
    mock_api = MagicMock()
    mock_api.is_connected.return_value = True
    response_state = _make_state(
        head=_make_axis(direction="up", source="web", remaining_ms=30000)
    )
    mock_api.async_set_motor_state = AsyncMock(return_value=response_state)

    coordinator, head_motor, foot_motor = create_coordinator_and_motors(hass, mock_api)
    try:
        await head_motor.async_added_to_hass()
        await foot_motor.async_added_to_hass()
        head_motor.async_write_ha_state.reset_mock()
        foot_motor.async_write_ha_state.reset_mock()

        await head_motor.async_open_cover()

        mock_api.async_set_motor_state.assert_awaited_once_with(
            SmartBedMotorState(type=SmartBedMotorType.HEAD, up="on", down="off")
        )
        assert coordinator.data == response_state
        assert head_motor.is_closed is False
        assert head_motor.is_opening is True
        assert head_motor.is_closing is False
        assert head_motor.extra_state_attributes == {
            "source": "web",
            "remaining_ms": 30000,
        }
        assert foot_motor.is_closed is True
        assert foot_motor.is_opening is False
        assert foot_motor.extra_state_attributes == {
            "source": "none",
            "remaining_ms": 0,
        }
        assert head_motor.async_write_ha_state.called
        assert foot_motor.async_write_ha_state.called
    finally:
        await coordinator.async_shutdown()


async def test_motor_close_action(hass):
    """Test async_close_cover calls API and syncs state via coordinator."""
    mock_api = MagicMock()
    mock_api.is_connected.return_value = True
    response_state = _make_state(
        head=_make_axis(direction="down", source="web", remaining_ms=14000)
    )
    mock_api.async_set_motor_state = AsyncMock(return_value=response_state)

    coordinator, head_motor, foot_motor = create_coordinator_and_motors(hass, mock_api)
    try:
        await head_motor.async_added_to_hass()
        await foot_motor.async_added_to_hass()
        head_motor._is_closed = False
        head_motor.async_write_ha_state.reset_mock()
        foot_motor.async_write_ha_state.reset_mock()

        await head_motor.async_close_cover()

        mock_api.async_set_motor_state.assert_awaited_once_with(
            SmartBedMotorState(type=SmartBedMotorType.HEAD, up="off", down="on")
        )
        assert head_motor.is_closed is True
        assert head_motor.is_closing is True
        assert head_motor.is_opening is False
        assert head_motor.extra_state_attributes == {
            "source": "web",
            "remaining_ms": 14000,
        }
        assert head_motor.async_write_ha_state.called
        assert foot_motor.async_write_ha_state.called
    finally:
        await coordinator.async_shutdown()


async def test_motor_stop_action(hass):
    """Test async_stop_cover stops only the target motor and preserves other axis state."""
    mock_api = MagicMock()
    mock_api.is_connected.return_value = True
    response_state = _make_state(
        head=_make_axis(direction="stopped", source="none", remaining_ms=0),
        foot=_make_axis(direction="up", source="web", remaining_ms=24500),
    )
    mock_api.async_set_motor_state = AsyncMock(return_value=response_state)

    coordinator, head_motor, foot_motor = create_coordinator_and_motors(hass, mock_api)
    try:
        await head_motor.async_added_to_hass()
        await foot_motor.async_added_to_hass()
        head_motor._is_closed = False
        head_motor._axis_state = _make_axis(
            direction="up", source="web", remaining_ms=10000
        )
        head_motor.async_write_ha_state.reset_mock()
        foot_motor.async_write_ha_state.reset_mock()

        await head_motor.async_stop_cover()

        mock_api.async_set_motor_state.assert_awaited_once_with(
            SmartBedMotorState(type=SmartBedMotorType.HEAD, up="off", down="off")
        )
        assert head_motor.is_opening is False
        assert head_motor.is_closing is False
        assert head_motor.is_closed is False
        assert head_motor.extra_state_attributes == {
            "source": "none",
            "remaining_ms": 0,
        }
        assert foot_motor.is_opening is True
        assert foot_motor.is_closed is False
        assert foot_motor.extra_state_attributes == {
            "source": "web",
            "remaining_ms": 24500,
        }
        assert head_motor.async_write_ha_state.called
        assert foot_motor.async_write_ha_state.called
    finally:
        await coordinator.async_shutdown()


async def test_motor_command_reflects_wired_remote_override(hass):
    """Test cover reflects authoritative ESP state when wired remote overrides a web command."""
    mock_api = MagicMock()
    mock_api.is_connected.return_value = True
    override_state = _make_state(
        head=_make_axis(direction="down", source="remote", remaining_ms=29500)
    )
    mock_api.async_set_motor_state = AsyncMock(return_value=override_state)

    coordinator, head_motor, foot_motor = create_coordinator_and_motors(hass, mock_api)
    try:
        await head_motor.async_added_to_hass()
        await foot_motor.async_added_to_hass()

        await head_motor.async_open_cover()

        assert head_motor.is_opening is False
        assert head_motor.is_closing is True
        assert head_motor.is_closed is True
        assert head_motor.extra_state_attributes == {
            "source": "remote",
            "remaining_ms": 29500,
        }
    finally:
        await coordinator.async_shutdown()


async def test_motor_command_malformed_response_keeps_state(hass):
    """Test malformed /set response (None while connected) preserves previous state."""
    mock_api = MagicMock()
    mock_api.is_connected.return_value = True
    mock_api.async_set_motor_state = AsyncMock(return_value=None)

    coordinator, head_motor, foot_motor = create_coordinator_and_motors(hass, mock_api)
    try:
        await head_motor.async_added_to_hass()
        await foot_motor.async_added_to_hass()
        head_motor._is_closed = False
        head_motor.async_write_ha_state.reset_mock()
        foot_motor.async_write_ha_state.reset_mock()

        await head_motor.async_close_cover()

        assert head_motor.is_closed is False
        assert head_motor.is_closing is False
        assert head_motor.available is True
        assert foot_motor.available is True
    finally:
        await coordinator.async_shutdown()


async def test_motor_command_connection_drop_marks_both_unavailable(hass):
    """Test connection drop during a cover command marks both entities unavailable immediately."""
    mock_api = MagicMock()
    mock_api.is_connected.return_value = True

    async def _disconnect_on_command(_motor_state):
        mock_api.is_connected.return_value = False
        return None

    mock_api.async_set_motor_state = AsyncMock(side_effect=_disconnect_on_command)

    coordinator, head_motor, foot_motor = create_coordinator_and_motors(hass, mock_api)
    try:
        await head_motor.async_added_to_hass()
        await foot_motor.async_added_to_hass()
        head_motor.async_write_ha_state.reset_mock()
        foot_motor.async_write_ha_state.reset_mock()

        await head_motor.async_open_cover()

        assert head_motor.available is False
        assert foot_motor.available is False
        assert head_motor.async_write_ha_state.called
        assert foot_motor.async_write_ha_state.called
    finally:
        await coordinator.async_shutdown()


async def test_motor_polling_update_head_and_foot(hass):
    """Test DataUpdateCoordinator fetches status once and updates both motors."""
    mock_api = MagicMock()
    mock_api.is_connected.return_value = True
    mock_api.async_get_status = AsyncMock(
        return_value=_make_state(
            head=_make_axis(direction="up", source="web", remaining_ms=12000),
            foot=_make_axis(direction="down", source="remote", remaining_ms=25000),
        )
    )

    coordinator, head_motor, foot_motor = create_coordinator_and_motors(hass, mock_api)

    try:
        await head_motor.async_added_to_hass()
        await foot_motor.async_added_to_hass()

        # 1. Single refresh: Head opening, Foot closing
        await coordinator.async_refresh()
        assert mock_api.async_get_status.await_count == 1

        assert head_motor.is_opening is True
        assert head_motor.is_closed is False
        assert head_motor.extra_state_attributes == {
            "source": "web",
            "remaining_ms": 12000,
        }
        assert head_motor.available is True

        assert foot_motor.is_closing is True
        assert foot_motor.is_closed is True
        assert foot_motor.extra_state_attributes == {
            "source": "remote",
            "remaining_ms": 25000,
        }
        assert foot_motor.available is True

        # 2. Both resting / flat
        mock_api.async_get_status.return_value = _make_state()
        await coordinator.async_refresh()
        assert mock_api.async_get_status.await_count == 2

        assert head_motor.is_opening is False
        assert head_motor.is_closing is False
        assert head_motor.extra_state_attributes == {
            "source": "none",
            "remaining_ms": 0,
        }
        assert foot_motor.is_opening is False
        assert foot_motor.is_closing is False

        # 3. Connection drop marks both entities unavailable
        mock_api.async_get_status.return_value = None
        mock_api.is_connected.return_value = False
        await coordinator.async_refresh()
        assert head_motor.available is False
        assert foot_motor.available is False
    finally:
        await coordinator.async_shutdown()


async def test_setup_platform(hass):
    """Test async_setup_platform instantiates Head/Foot entities and stores runtime data."""
    assert await async_setup(hass, {}) is True

    add_entities = MagicMock()
    config = {
        CONF_NAME: "SmartBed",
        CONF_BASE_URL: "http://esp-smartbed-controller.local",
    }
    await async_setup_platform(hass, config, add_entities)
    await hass.async_block_till_done()

    assert add_entities.called
    entities = add_entities.call_args[0][0]
    assert len(entities) == 2

    head_motor, foot_motor = entities
    try:
        assert head_motor.name == "SmartBed Head Motor"
        assert foot_motor.name == "SmartBed Foot Motor"
        assert head_motor.should_poll is False
        assert foot_motor.should_poll is False
        assert head_motor.coordinator is foot_motor.coordinator
        assert head_motor._api is foot_motor._api
        assert head_motor.coordinator.update_interval == timedelta(seconds=10)
        assert (
            head_motor.device_info["identifiers"]
            == foot_motor.device_info["identifiers"]
        )
        assert head_motor.device_info["identifiers"] == {
            (DOMAIN, "esp-smartbed-controller.local")
        }
        runtime_data = hass.data[DOMAIN][DATA_ENTRIES]["esp-smartbed-controller.local"]
        assert runtime_data.coordinator is head_motor.coordinator
    finally:
        await head_motor.coordinator.async_shutdown()

    # Verify custom scan_interval in YAML config is respected
    custom_add_entities = MagicMock()
    custom_config = {
        CONF_NAME: "SmartBed",
        CONF_BASE_URL: "http://esp-smartbed-controller.local",
        CONF_SCAN_INTERVAL: timedelta(seconds=20),
    }
    await async_setup_platform(hass, custom_config, custom_add_entities)
    await hass.async_block_till_done()
    custom_entities = custom_add_entities.call_args[0][0]
    try:
        assert custom_entities[0].coordinator.update_interval == timedelta(seconds=20)
    finally:
        await custom_entities[0].coordinator.async_shutdown()
