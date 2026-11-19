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

from custom_components.smartbed.const import (
    CONF_API,
    CONF_BASE_URL,
    CONF_COORDINATOR,
    CONF_MOTOR_TYPE,
    DOMAIN,
)
from custom_components.smartbed.cover import (
    SCAN_INTERVAL,
    SmartBedMotor,
    async_setup_platform,
)
from custom_components.smartbed.models import SmartBedMotorType, SmartBedState


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

    config = {
        CONF_NAME: f"SmartBed {motor_type.name.capitalize()} Motor",
        CONF_BASE_URL: base_url,
        CONF_API: mock_api,
        CONF_COORDINATOR: coordinator,
        CONF_MOTOR_TYPE: motor_type,
    }
    return SmartBedMotor(config)


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
    assert motor.available is True
    assert motor.unique_id == f"{DOMAIN}_esp-smartbed-controller.local_h"


def test_device_info_groups_both_motors_under_single_device():
    """Test both motors share the same device_info identifier while keeping unique_ids distinct."""
    head_motor = create_motor(
        SmartBedMotorType.HEAD,
        base_url="http://esp-smartbed-controller.local",
    )
    foot_motor = create_motor(
        SmartBedMotorType.FOOT,
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


async def test_motor_open_action():
    """Test async_open_cover transitions state and calls API."""
    mock_api = MagicMock()
    mock_api.async_set_motor_state = AsyncMock(return_value=True)
    motor = create_motor(SmartBedMotorType.HEAD, mock_api)
    motor.async_write_ha_state = MagicMock()

    await motor.async_open_cover()

    assert motor.is_closed is False
    assert motor.is_opening is True
    assert motor.is_closing is False
    assert motor.async_write_ha_state.called
    assert mock_api.async_set_motor_state.called


async def test_motor_close_action():
    """Test async_close_cover transitions state and calls API."""
    mock_api = MagicMock()
    mock_api.async_set_motor_state = AsyncMock(return_value=True)
    motor = create_motor(SmartBedMotorType.HEAD, mock_api)
    motor.async_write_ha_state = MagicMock()

    # Pre-set open
    motor._is_closed = False

    await motor.async_close_cover()

    assert motor.is_closed is True
    assert motor.is_closing is True
    assert motor.is_opening is False
    assert motor.async_write_ha_state.called
    assert mock_api.async_set_motor_state.called


async def test_motor_stop_action():
    """Test async_stop_cover turns off relays and notifies HA."""
    mock_api = MagicMock()
    mock_api.async_set_motor_state = AsyncMock(return_value=True)
    motor = create_motor(SmartBedMotorType.HEAD, mock_api)
    motor.async_write_ha_state = MagicMock()

    await motor.async_stop_cover()

    assert motor.is_opening is False
    assert motor.is_closing is False
    assert motor.async_write_ha_state.called
    assert mock_api.async_set_motor_state.called


async def test_motor_polling_update_head_and_foot(hass):
    """Test DataUpdateCoordinator fetches status once and updates both motors."""
    mock_api = MagicMock()
    mock_api.is_connected.return_value = True
    mock_api.async_get_status = AsyncMock(
        return_value=SmartBedState(hu="on", hd="off", fu="off", fd="on")
    )

    coordinator = DataUpdateCoordinator(
        hass,
        logging.getLogger(__name__),
        config_entry=None,
        name="SmartBed",
        update_method=mock_api.async_get_status,
        update_interval=SCAN_INTERVAL,
    )

    head_motor = create_motor(SmartBedMotorType.HEAD, mock_api, coordinator)
    foot_motor = create_motor(SmartBedMotorType.FOOT, mock_api, coordinator)
    for motor in (head_motor, foot_motor):
        motor.hass = hass
        motor.async_write_ha_state = MagicMock()
        motor.async_get_last_state = AsyncMock(return_value=None)

    try:
        await head_motor.async_added_to_hass()
        await foot_motor.async_added_to_hass()

        # 1. Single refresh: Head opening, Foot closing
        await coordinator.async_refresh()
        assert mock_api.async_get_status.await_count == 1

        assert head_motor.is_opening is True
        assert head_motor.is_closed is False
        assert head_motor.available is True

        assert foot_motor.is_closing is True
        assert foot_motor.is_closed is True
        assert foot_motor.available is True

        # 2. Both resting / flat
        mock_api.async_get_status.return_value = SmartBedState(
            hu="off", hd="off", fu="off", fd="off"
        )
        await coordinator.async_refresh()
        assert mock_api.async_get_status.await_count == 2

        assert head_motor.is_opening is False
        assert head_motor.is_closing is False
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
    """Test async_setup_platform instantiates Head and Foot entities with shared coordinator."""
    add_entities = MagicMock()
    config = {
        CONF_NAME: "SmartBed",
        CONF_BASE_URL: "http://esp-smartbed-controller.local",
    }
    await async_setup_platform(hass, config, add_entities)

    assert add_entities.called
    entities = add_entities.call_args[0][0]
    assert len(entities) == 2

    head_motor, foot_motor = entities
    assert head_motor.name == "SmartBed Head Motor"
    assert foot_motor.name == "SmartBed Foot Motor"
    assert head_motor.should_poll is False
    assert foot_motor.should_poll is False
    assert head_motor.coordinator is foot_motor.coordinator
    assert head_motor._api is foot_motor._api
    assert head_motor.coordinator.update_interval == timedelta(seconds=10)
    assert head_motor.device_info["identifiers"] == foot_motor.device_info["identifiers"]
    assert head_motor.device_info["identifiers"] == {
        (DOMAIN, "esp-smartbed-controller.local")
    }
    await head_motor.coordinator.async_shutdown()

    # Verify custom scan_interval in YAML config is respected
    custom_add_entities = MagicMock()
    custom_config = {
        CONF_NAME: "SmartBed",
        CONF_BASE_URL: "http://esp-smartbed-controller.local",
        CONF_SCAN_INTERVAL: timedelta(seconds=20),
    }
    await async_setup_platform(hass, custom_config, custom_add_entities)
    custom_entities = custom_add_entities.call_args[0][0]
    assert custom_entities[0].coordinator.update_interval == timedelta(seconds=20)
    await custom_entities[0].coordinator.async_shutdown()
