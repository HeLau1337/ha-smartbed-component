"""Cover platform for the SmartBed integration."""

from __future__ import annotations

from datetime import timedelta
import logging
from pprint import pformat
from typing import Any

import voluptuous as vol

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.const import (
    CONF_NAME,
    CONF_SCAN_INTERVAL,
    STATE_CLOSED,
    STATE_OPEN,
    Platform,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import discovery
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.config_validation import PLATFORM_SCHEMA
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_BASE_URL,
    CONF_DEFAULT_BASE_URL,
    CONF_DEFAULT_NAME,
    CONF_ENTRY_KEY,
    DATA_ENTRIES,
    DATA_HASS_CONFIG,
    DOMAIN,
)
from .entity import SmartBedEntity, SmartBedRuntimeData, clean_base_url
from .esp_smartbed_api_client import EspSmartBedApiClient
from .models import (
    SmartBedAxisState,
    SmartBedMotorState,
    SmartBedMotorType,
    SmartBedState,
)

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=10)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_NAME, default=CONF_DEFAULT_NAME): cv.string,
        vol.Required(CONF_BASE_URL, default=CONF_DEFAULT_BASE_URL): cv.string,
    }
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the SmartBed cover platform and schedule diagnostic sensor discovery."""
    _LOGGER.info(pformat(config))

    name: str = config[CONF_NAME]
    base_url: str = config[CONF_BASE_URL]
    api = EspSmartBedApiClient(base_url, async_get_clientsession(hass))
    scan_interval: timedelta = config.get(CONF_SCAN_INTERVAL, SCAN_INTERVAL)
    coordinator: DataUpdateCoordinator[SmartBedState | None] = DataUpdateCoordinator(
        hass,
        _LOGGER,
        config_entry=None,
        name=name,
        update_method=api.async_get_status,
        update_interval=scan_interval,
    )

    runtime_data = SmartBedRuntimeData(
        name=name,
        base_url=base_url,
        clean_url=clean_base_url(base_url),
        api=api,
        coordinator=coordinator,
    )

    domain_data = hass.data.setdefault(DOMAIN, {})
    entries = domain_data.setdefault(DATA_ENTRIES, {})
    entries[runtime_data.clean_url] = runtime_data

    async_add_entities(
        [
            SmartBedMotor(runtime_data, SmartBedMotorType.HEAD),
            SmartBedMotor(runtime_data, SmartBedMotorType.FOOT),
        ]
    )

    if (hass_config := domain_data.get(DATA_HASS_CONFIG)) is not None:
        hass.async_create_task(
            discovery.async_load_platform(
                hass,
                Platform.SENSOR,
                DOMAIN,
                {CONF_ENTRY_KEY: runtime_data.clean_url},
                hass_config,
            )
        )


class SmartBedMotor(SmartBedEntity, CoverEntity, RestoreEntity):
    """Representation of a SmartBed motor (head or foot)."""

    _attr_assumed_state: bool = True
    _attr_device_class: CoverDeviceClass | None = CoverDeviceClass.SHUTTER
    _attr_supported_features: CoverEntityFeature | None = (
        CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
    )

    def __init__(
        self, runtime_data: SmartBedRuntimeData, motor_type: SmartBedMotorType
    ) -> None:
        """Initialize the cover device."""
        super().__init__(runtime_data)
        self._motor_type = motor_type
        motor_label = (
            "Head Motor" if motor_type == SmartBedMotorType.HEAD else "Foot Motor"
        )
        self._name: str = f"{runtime_data.name} {motor_label}"
        self._axis_state: SmartBedAxisState | None = None
        self._is_closed: bool = True
        self._opening_duration: int = 0  # seconds
        self._closing_duration: int = 0
        if motor_type == SmartBedMotorType.HEAD:
            self._fully_opened_duration: int = 20
            self._fully_closed_duration: int = 14
        elif motor_type == SmartBedMotorType.FOOT:
            self._fully_opened_duration: int = 14
            self._fully_closed_duration: int = 10

    async def async_added_to_hass(self) -> None:
        """Restore last known state upon Home Assistant startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state in (STATE_OPEN, STATE_CLOSED):
            self._is_closed = last_state.state == STATE_CLOSED
        if self.coordinator.data is not None:
            self._update_from_coordinator_data(self.coordinator.data)

    @property
    def unique_id(self) -> str:
        """Return the unique ID for this SmartBed motor."""
        return f"{DOMAIN}_{self._clean_url}_{self._motor_type.value}"

    @property
    def name(self) -> str:
        """Return the display name of this SmartBed motor."""
        return self._name

    @property
    def is_closed(self) -> bool:
        """Return if the cover is closed."""
        return self._is_closed

    @property
    def is_closing(self) -> bool:
        """Return if the cover is closing."""
        return self._axis_state is not None and self._axis_state.direction == "down"

    @property
    def is_opening(self) -> bool:
        """Return if the cover is opening."""
        return self._axis_state is not None and self._axis_state.direction == "up"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return axis control source and remaining run duration attributes."""
        if self._axis_state is None:
            return {}
        return {
            "source": self._axis_state.source,
            "remaining_ms": self._axis_state.remaining_ms,
        }

    def _update_from_coordinator_data(
        self, smart_bed_state: SmartBedState | None
    ) -> None:
        """Update internal motor state from coordinator data."""
        if smart_bed_state:
            axis = smart_bed_state.axis(self._motor_type)
            self._axis_state = axis
            if axis.direction == "down":
                self._is_closed = True
            elif axis.direction == "up":
                self._is_closed = False

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_from_coordinator_data(self.coordinator.data)
        self.async_write_ha_state()

    async def _async_apply_motor_state(self, new_state: SmartBedMotorState) -> None:
        """Send a motor command and propagate the resulting state via the coordinator."""
        result_state = await self._api.async_set_motor_state(new_state)
        if result_state is None:
            if not self._api.is_connected():
                self.coordinator.async_update_listeners()
            return

        self.coordinator.async_set_updated_data(result_state)

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover (raise bed motor)."""
        new_state = SmartBedMotorState(type=self._motor_type, up="on", down="off")
        await self._async_apply_motor_state(new_state)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close cover (lower bed motor to flat)."""
        new_state = SmartBedMotorState(type=self._motor_type, up="off", down="on")
        await self._async_apply_motor_state(new_state)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        new_state = SmartBedMotorState(type=self._motor_type, up="off", down="off")
        await self._async_apply_motor_state(new_state)
