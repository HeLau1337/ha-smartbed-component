"""Tests for the SmartBed cover platform."""

from unittest.mock import AsyncMock, MagicMock
from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntityFeature,
)
from homeassistant.const import CONF_NAME, STATE_CLOSED, STATE_OPEN, STATE_UNKNOWN
from homeassistant.core import State

from custom_components.smartbed.const import (
    CONF_API,
    CONF_BASE_URL,
    CONF_MOTOR_TYPE,
    DOMAIN,
)
from custom_components.smartbed.cover import SmartBedMotor
from custom_components.smartbed.models import SmartBedMotorType, SmartBedState


def create_motor(motor_type=SmartBedMotorType.HEAD, mock_api=None):
    """Helper to instantiate SmartBedMotor with mocks."""
    if mock_api is None:
        mock_api = MagicMock()
        mock_api.is_connected.return_value = True

    config = {
        CONF_NAME: f"SmartBed {motor_type.name.capitalize()} Motor",
        CONF_BASE_URL: "http://esp-smartbed-controller.local",
        CONF_API: mock_api,
        CONF_MOTOR_TYPE: motor_type,
    }
    return SmartBedMotor(config)


def test_motor_initial_state():
    """Test initial state and attributes of SmartBedMotor."""
    motor = create_motor(SmartBedMotorType.HEAD)

    assert motor._attr_device_class == CoverDeviceClass.SHUTTER
    assert motor._attr_supported_features == (
        CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
    )
    # Crucial fix: is_closed must be boolean True initially, never None
    assert motor.is_closed is True
    assert motor.is_opening is False
    assert motor.is_closing is False
    assert motor.available is True
    assert motor.unique_id == f"{DOMAIN}_esp-smartbed-controller.local_h"


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


async def test_motor_polling_update_head_and_foot():
    """Test async_update syncing state with ESP hardware response."""
    mock_api = MagicMock()
    head_motor = create_motor(SmartBedMotorType.HEAD, mock_api)
    foot_motor = create_motor(SmartBedMotorType.FOOT, mock_api)

    # 1. Head opening, Foot closed
    mock_api.async_get_status = AsyncMock(
        return_value=SmartBedState(hu="on", hd="off", fu="off", fd="on")
    )
    await head_motor.async_update()
    await foot_motor.async_update()

    assert head_motor.is_opening is True
    assert head_motor.is_closed is False

    assert foot_motor.is_closing is True
    assert foot_motor.is_closed is True

    # 2. Both resting / flat
    mock_api.async_get_status = AsyncMock(
        return_value=SmartBedState(hu="off", hd="off", fu="off", fd="off")
    )
    await head_motor.async_update()
    await foot_motor.async_update()

    assert head_motor.is_opening is False
    assert head_motor.is_closing is False
    assert foot_motor.is_opening is False
    assert foot_motor.is_closing is False


async def test_setup_platform(hass):
    """Test setup_platform instantiates Head and Foot entities."""
    from custom_components.smartbed.cover import setup_platform

    add_entities = MagicMock()
    config = {
        CONF_NAME: "SmartBed",
        CONF_BASE_URL: "http://esp-smartbed-controller.local",
    }
    setup_platform(hass, config, add_entities)

    assert add_entities.called
    entities = add_entities.call_args[0][0]
    assert len(entities) == 2
    assert entities[0].name == "SmartBed Head Motor"
    assert entities[1].name == "SmartBed Foot Motor"
