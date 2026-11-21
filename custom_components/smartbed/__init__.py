"""The SmartBed integration by HeLau1337."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import DATA_ENTRIES, DATA_HASS_CONFIG, DOMAIN

PLATFORMS: list[Platform] = [Platform.COVER, Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the SmartBed integration and capture hass_config for platform discovery."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    domain_data[DATA_HASS_CONFIG] = config
    domain_data.setdefault(DATA_ENTRIES, {})
    return True
