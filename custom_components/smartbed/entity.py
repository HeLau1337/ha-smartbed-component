"""Shared entity base class and runtime data for the SmartBed integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN
from .esp_smartbed_api_client import EspSmartBedApiClient
from .models import SmartBedState


def clean_base_url(base_url: str) -> str:
    """Return the base URL without scheme or trailing slash."""
    return base_url.replace("http://", "").replace("https://", "").strip("/")


@dataclass
class SmartBedRuntimeData:
    """Runtime dependencies shared across SmartBed platforms."""

    name: str
    base_url: str
    clean_url: str
    api: EspSmartBedApiClient
    coordinator: DataUpdateCoordinator[SmartBedState | None]


class SmartBedEntity(CoordinatorEntity[DataUpdateCoordinator[SmartBedState | None]]):
    """Base entity shared by SmartBed cover and diagnostic sensor entities."""

    def __init__(self, runtime_data: SmartBedRuntimeData) -> None:
        """Initialize the SmartBed entity with shared coordinator and API client."""
        super().__init__(runtime_data.coordinator)
        self._runtime_data = runtime_data
        self._base_url = runtime_data.base_url
        self._clean_url = runtime_data.clean_url
        self._api = runtime_data.api

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info grouping all SmartBed entities under one device."""
        sw_version = (
            self.coordinator.data.version
            if self.coordinator.data is not None
            else None
        )
        return DeviceInfo(
            identifiers={(DOMAIN, self._clean_url)},
            name=self._runtime_data.name,
            model="SmartBed ESP Controller",
            manufacturer="Custom Build",
            sw_version=sw_version,
            configuration_url=self._base_url,
        )

    @property
    def available(self) -> bool:
        """Return if the entity is available."""
        return super().available and self._api.is_connected()
