"""Diagnostic sensor platform for the SmartBed integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfInformation,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType, StateType
from homeassistant.util import dt as dt_util

from .const import CONF_ENTRY_KEY, DATA_ENTRIES, DOMAIN
from .entity import SmartBedEntity, SmartBedRuntimeData
from .models import SmartBedState

_LOGGER = logging.getLogger(__name__)

BOOT_TIME_DRIFT_THRESHOLD = timedelta(seconds=5)


@dataclass(frozen=True, kw_only=True)
class SmartBedSensorEntityDescription(SensorEntityDescription):
    """Describes a SmartBed diagnostic sensor entity."""

    value_fn: Callable[[SmartBedState], StateType | datetime] | None = None
    attrs_fn: Callable[[SmartBedState], dict[str, Any]] | None = None


DIAGNOSTIC_SENSORS: tuple[SmartBedSensorEntityDescription, ...] = (
    SmartBedSensorEntityDescription(
        key="rssi",
        name="Wi-Fi RSSI",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.rssi,
    ),
    SmartBedSensorEntityDescription(
        key="free_heap",
        name="Free Heap",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_display_precision=0,
        icon="mdi:memory",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.free_heap,
    ),
    SmartBedSensorEntityDescription(
        key="firmware_version",
        name="Firmware Version",
        icon="mdi:chip",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.version,
        attrs_fn=lambda state: {
            "build": state.build,
            "max_run_duration_ms": state.max_run_duration_ms,
        },
    ),
    SmartBedSensorEntityDescription(
        key="ip_address",
        name="IP Address",
        icon="mdi:ip-network",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.ip,
        attrs_fn=lambda state: {"hostname": state.hostname},
    ),
)

LAST_BOOT_SENSOR_DESCRIPTION = SmartBedSensorEntityDescription(
    key="last_boot",
    name="Last Boot",
    device_class=SensorDeviceClass.TIMESTAMP,
    icon="mdi:clock-start",
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up SmartBed diagnostic sensors discovered by the cover platform."""
    if discovery_info is None or CONF_ENTRY_KEY not in discovery_info:
        _LOGGER.warning(
            "SmartBed diagnostic sensors are discovered automatically from the cover "
            "platform; direct YAML configuration under 'sensor:' is ignored"
        )
        return

    entry_key: str = discovery_info[CONF_ENTRY_KEY]
    runtime_data: SmartBedRuntimeData | None = (
        hass.data.get(DOMAIN, {}).get(DATA_ENTRIES, {}).get(entry_key)
    )
    if runtime_data is None:
        _LOGGER.warning(
            "No SmartBed runtime data found for discovery key %r", entry_key
        )
        return

    entities: list[SensorEntity] = [
        SmartBedDiagnosticSensor(runtime_data, description)
        for description in DIAGNOSTIC_SENSORS
    ]
    entities.append(
        SmartBedLastBootSensor(runtime_data, LAST_BOOT_SENSOR_DESCRIPTION)
    )
    async_add_entities(entities)


class SmartBedDiagnosticSensor(SmartBedEntity, SensorEntity):
    """Representation of a SmartBed diagnostic sensor."""

    entity_description: SmartBedSensorEntityDescription

    def __init__(
        self,
        runtime_data: SmartBedRuntimeData,
        description: SmartBedSensorEntityDescription,
    ) -> None:
        """Initialize the diagnostic sensor."""
        super().__init__(runtime_data)
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{self._clean_url}_{description.key}"
        self._attr_name = f"{runtime_data.name} {description.name}"

    @property
    def native_value(self) -> StateType | datetime:
        """Return the current sensor value from coordinator data."""
        if (
            self.coordinator.data is None
            or self.entity_description.value_fn is None
        ):
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return optional diagnostic attributes from coordinator data."""
        if (
            self.coordinator.data is None
            or self.entity_description.attrs_fn is None
        ):
            return None
        return self.entity_description.attrs_fn(self.coordinator.data)


class SmartBedLastBootSensor(SmartBedDiagnosticSensor):
    """Timestamp sensor estimating ESP8266 boot time with jitter deadband."""

    def __init__(
        self,
        runtime_data: SmartBedRuntimeData,
        description: SmartBedSensorEntityDescription,
    ) -> None:
        """Initialize the boot timestamp sensor."""
        super().__init__(runtime_data, description)
        self._last_processed_data: SmartBedState | None = None
        self._last_uptime_ms: int | None = None
        self._last_boot: datetime | None = None

    @property
    def native_value(self) -> datetime | None:
        """Return the stabilized boot timestamp, updating on reboot or drift."""
        data = self.coordinator.data
        if data is None:
            return None

        if data is self._last_processed_data:
            return self._last_boot

        self._last_processed_data = data
        candidate = (
            dt_util.utcnow() - timedelta(milliseconds=data.uptime_ms)
        ).replace(microsecond=0)

        # Update on initial poll, reboot/millis()-rollover, or genuine clock drift (> 5 s)
        if (
            self._last_boot is None
            or (
                self._last_uptime_ms is not None
                and data.uptime_ms < self._last_uptime_ms
            )
            or abs(candidate - self._last_boot) > BOOT_TIME_DRIFT_THRESHOLD
        ):
            self._last_boot = candidate

        self._last_uptime_ms = data.uptime_ms
        return self._last_boot
