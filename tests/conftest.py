"""Fixtures for testing SmartBed custom component."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations defined in custom_components."""
    yield
