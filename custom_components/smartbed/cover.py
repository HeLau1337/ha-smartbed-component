"""Platform for sensor integration."""

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
from homeassistant.const import CONF_NAME, CONF_SCAN_INTERVAL, STATE_CLOSED, STATE_OPEN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.config_validation import PLATFORM_SCHEMA
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import (
    CONF_API,
    CONF_BASE_URL,
    CONF_COORDINATOR,
    CONF_DEFAULT_BASE_URL,
    CONF_DEFAULT_NAME,
    CONF_MOTOR_TYPE,
    DOMAIN,
)
from .esp_smartbed_api_client import EspSmartBedApiClient
from .models import SmartBedMotorState, SmartBedMotorType, SmartBedState

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=10)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_NAME, default=CONF_DEFAULT_NAME): cv.string,
        vol.Required(CONF_BASE_URL, default=CONF_DEFAULT_BASE_URL): cv.string,
        # vol.Required(CONF_MOTOR_TYPE): cv.enum(SmartBedMotorType),
    }
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the cover platform."""
    _LOGGER.info(pformat(config))

    api = EspSmartBedApiClient(
        config[CONF_BASE_URL], async_get_clientsession(hass)
    )
    scan_interval: timedelta = config.get(CONF_SCAN_INTERVAL, SCAN_INTERVAL)
    coordinator: DataUpdateCoordinator[SmartBedState | None] = DataUpdateCoordinator(
        hass,
        _LOGGER,
        config_entry=None,
        name=config[CONF_NAME],
        update_method=api.async_get_status,
        update_interval=scan_interval,
    )

    cover_h = {
        CONF_NAME: f"{config[CONF_NAME]} Head Motor",
        CONF_BASE_URL: config[CONF_BASE_URL],
        CONF_API: api,
        CONF_COORDINATOR: coordinator,
        CONF_MOTOR_TYPE: SmartBedMotorType.HEAD,
    }
    cover_f = cover_h.copy()
    cover_f[CONF_NAME] = f"{config[CONF_NAME]} Foot Motor"
    cover_f[CONF_MOTOR_TYPE] = SmartBedMotorType.FOOT

    async_add_entities([SmartBedMotor(cover_h), SmartBedMotor(cover_f)])


class SmartBedMotor(
    CoordinatorEntity[DataUpdateCoordinator[SmartBedState | None]],
    CoverEntity,
    RestoreEntity,
):
    """Representation of SmartBed motor (head or foot)."""

    _attr_assumed_state: bool = True
    _attr_device_class: CoverDeviceClass | None = CoverDeviceClass.SHUTTER
    _attr_supported_features: CoverEntityFeature | None = (
        CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
    )

    def __init__(self, cover: dict[str, Any]) -> None:
        """Initialize the cover device."""
        super().__init__(cover[CONF_COORDINATOR])
        self._name: str = cover[CONF_NAME]
        self._base_url = cover[CONF_BASE_URL]
        self._api: EspSmartBedApiClient = cover[CONF_API]
        self._motor_state: SmartBedMotorState = SmartBedMotorState(
            type=cover[CONF_MOTOR_TYPE], up="off", down="off"
        )
        self._is_closed: bool = True
        self._opening_duration: int = 0  # seconds
        self._closing_duration: int = 0
        if self._motor_state.type == SmartBedMotorType.HEAD:
            self._fully_opened_duration: int = 20
            self._fully_closed_duration: int = 14
        elif self._motor_state.type == SmartBedMotorType.FOOT:
            self._fully_opened_duration: int = 14
            self._fully_closed_duration: int = 10

    async def async_added_to_hass(self) -> None:
        """Restore last known state upon Home Assistant startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state in (STATE_OPEN, STATE_CLOSED):
            self._is_closed = (last_state.state == STATE_CLOSED)
        if self.coordinator.data is not None:
            self._update_from_coordinator_data(self.coordinator.data)

    @property
    def _clean_url(self) -> str:
        """Return the base URL without scheme or trailing slash."""
        return (
            self._base_url.replace("http://", "")
            .replace("https://", "")
            .strip("/")
        )

    @property
    def unique_id(self) -> str:
        """Return the unique ID for this SmartBed motor."""
        return f"{DOMAIN}_{self._clean_url}_{self._motor_state.type.value}"

    @property
    def device_info(self) -> DeviceInfo:
        """Information about this entity/device."""
        # Both motors must share the exact same identifier to be grouped into one physical device
        base_name = self._name.replace(" Head Motor", "").replace(" Foot Motor", "")
        return DeviceInfo(
            identifiers={(DOMAIN, self._clean_url)},
            name=base_name,
            model="SmartBed ESP Controller",
            manufacturer="Custom Build",
        )

    @property
    def name(self) -> str:
        """Return the display name of this SmartBed motor."""
        return self._name

    @property
    def available(self) -> bool:
        """Return if the entity is available."""
        return super().available and self._api.is_connected()

    @property
    def is_closed(self) -> bool:
        """Return if the cover is closed."""
        return self._is_closed

    @property
    def is_closing(self) -> bool:
        """Return if the cover is closing."""
        return self._motor_state.down == "on"

    @property
    def is_opening(self) -> bool:
        """Return if the cover is opening."""
        return self._motor_state.up == "on"

    def _update_from_coordinator_data(
        self, smart_bed_state: SmartBedState | None
    ) -> None:
        """Update internal motor state from coordinator data."""
        if smart_bed_state:
            if self._motor_state.type == SmartBedMotorType.HEAD:
                self._motor_state.up = smart_bed_state.hu
                self._motor_state.down = smart_bed_state.hd
            elif self._motor_state.type == SmartBedMotorType.FOOT:
                self._motor_state.up = smart_bed_state.fu
                self._motor_state.down = smart_bed_state.fd

            if self._motor_state.down == "on":
                self._is_closed = True
            elif self._motor_state.up == "on":
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
        new_state = SmartBedMotorState(type=self._motor_state.type, up="on", down="off")
        await self._async_apply_motor_state(new_state)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close cover (lower bed motor to flat)."""
        new_state = SmartBedMotorState(type=self._motor_state.type, up="off", down="on")
        await self._async_apply_motor_state(new_state)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        new_state = SmartBedMotorState(
            type=self._motor_state.type, up="off", down="off"
        )
        await self._async_apply_motor_state(new_state)
