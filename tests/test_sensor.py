"""Tests for the SmartBed diagnostic sensor platform."""

from datetime import UTC, datetime, timedelta
import logging
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfInformation,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.setup import async_setup_component

from custom_components.smartbed.const import DATA_ENTRIES, DOMAIN
from custom_components.smartbed.cover import SCAN_INTERVAL
from custom_components.smartbed.entity import SmartBedRuntimeData
from custom_components.smartbed.models import SmartBedAxisState, SmartBedState
from custom_components.smartbed.sensor import (
    DIAGNOSTIC_SENSORS,
    LAST_BOOT_SENSOR_DESCRIPTION,
    SmartBedDiagnosticSensor,
    SmartBedLastBootSensor,
    async_setup_platform,
)


def _make_state(
    *,
    hostname: str = "esp-smartbed-controller",
    version: str = "2.0.0",
    build: str = "Nov 20 2026 22:00:00",
    wifi_connected: bool = True,
    ip: str = "192.168.178.51",
    rssi: int = -62,
    uptime_ms: int = 123456,
    free_heap: int = 44800,
    max_run_duration_ms: int = 30000,
) -> SmartBedState:
    """Create a SmartBedState for sensor tests."""
    idle = SmartBedAxisState(direction="stopped", source="none", remaining_ms=0)
    return SmartBedState(
        hostname=hostname,
        version=version,
        build=build,
        wifi_connected=wifi_connected,
        ip=ip,
        rssi=rssi,
        uptime_ms=uptime_ms,
        free_heap=free_heap,
        max_run_duration_ms=max_run_duration_ms,
        head=idle,
        foot=idle,
    )


def _create_coordinator_and_sensors(
    hass,
    mock_api: MagicMock,
) -> tuple[
    DataUpdateCoordinator[SmartBedState | None],
    dict[str, SmartBedDiagnosticSensor],
]:
    """Create a real DataUpdateCoordinator with all diagnostic sensors."""
    mock_api.async_get_status = AsyncMock(return_value=None)
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
    sensors: dict[str, SmartBedDiagnosticSensor] = {
        desc.key: SmartBedDiagnosticSensor(runtime_data, desc)
        for desc in DIAGNOSTIC_SENSORS
    }
    sensors[LAST_BOOT_SENSOR_DESCRIPTION.key] = SmartBedLastBootSensor(
        runtime_data, LAST_BOOT_SENSOR_DESCRIPTION
    )
    for sensor in sensors.values():
        sensor.hass = hass
        sensor.async_write_ha_state = MagicMock()
    return coordinator, sensors


async def test_diagnostic_sensors_metadata_and_device_info(hass):
    """Test unique_id, device_class, state_class, unit, category, and device_info."""
    mock_api = MagicMock()
    mock_api.is_connected.return_value = True
    coordinator, sensors = _create_coordinator_and_sensors(hass, mock_api)
    try:
        assert set(sensors.keys()) == {
            "rssi",
            "free_heap",
            "firmware_version",
            "ip_address",
            "last_boot",
        }

        for key, sensor in sensors.items():
            assert sensor.should_poll is False
            assert sensor.unique_id == f"{DOMAIN}_esp-smartbed-controller.local_{key}"
            assert sensor.entity_category == EntityCategory.DIAGNOSTIC
            assert sensor.device_info["identifiers"] == {
                (DOMAIN, "esp-smartbed-controller.local")
            }
            assert sensor.device_info["name"] == "SmartBed"
            assert sensor.device_info["sw_version"] is None

        rssi = sensors["rssi"]
        assert rssi.name == "SmartBed Wi-Fi RSSI"
        assert rssi.device_class == SensorDeviceClass.SIGNAL_STRENGTH
        assert rssi.state_class == SensorStateClass.MEASUREMENT
        assert rssi.native_unit_of_measurement == SIGNAL_STRENGTH_DECIBELS_MILLIWATT

        heap = sensors["free_heap"]
        assert heap.name == "SmartBed Free Heap"
        assert heap.device_class == SensorDeviceClass.DATA_SIZE
        assert heap.state_class == SensorStateClass.MEASUREMENT
        assert heap.native_unit_of_measurement == UnitOfInformation.BYTES

        fw = sensors["firmware_version"]
        assert fw.name == "SmartBed Firmware Version"
        assert fw.device_class is None
        assert fw.state_class is None

        ip = sensors["ip_address"]
        assert ip.name == "SmartBed IP Address"
        assert ip.device_class is None
        assert ip.state_class is None

        boot = sensors["last_boot"]
        assert boot.name == "SmartBed Last Boot"
        assert boot.device_class == SensorDeviceClass.TIMESTAMP
        assert boot.state_class is None
    finally:
        await coordinator.async_shutdown()


async def test_diagnostic_sensors_values_attributes_and_availability(hass):
    """Test sensor values, extra attributes, disconnect handling, and recovery."""
    mock_api = MagicMock()
    mock_api.is_connected.return_value = True
    coordinator, sensors = _create_coordinator_and_sensors(hass, mock_api)
    try:
        for sensor in sensors.values():
            await sensor.async_added_to_hass()
            assert sensor.native_value is None
            assert sensor.extra_state_attributes is None
            assert sensor.available is True

        mock_api.async_get_status.return_value = _make_state()
        await coordinator.async_refresh()

        assert sensors["rssi"].native_value == -62
        assert sensors["rssi"].extra_state_attributes is None
        assert sensors["free_heap"].native_value == 44800
        assert sensors["firmware_version"].native_value == "2.0.0"
        assert sensors["firmware_version"].extra_state_attributes == {
            "build": "Nov 20 2026 22:00:00",
            "max_run_duration_ms": 30000,
        }
        assert sensors["firmware_version"].device_info["sw_version"] == "2.0.0"
        assert sensors["ip_address"].native_value == "192.168.178.51"
        assert sensors["ip_address"].extra_state_attributes == {
            "hostname": "esp-smartbed-controller"
        }

        # Connection drop marks sensors unavailable
        mock_api.async_get_status.return_value = None
        mock_api.is_connected.return_value = False
        await coordinator.async_refresh()
        for sensor in sensors.values():
            assert sensor.available is False

        # Reconnect updates values
        mock_api.is_connected.return_value = True
        mock_api.async_get_status.return_value = _make_state(
            rssi=-55, free_heap=45120, version="2.1.0", ip="192.168.178.60"
        )
        await coordinator.async_refresh()
        assert sensors["rssi"].available is True
        assert sensors["rssi"].native_value == -55
        assert sensors["free_heap"].native_value == 45120
        assert sensors["firmware_version"].native_value == "2.1.0"
        assert sensors["ip_address"].native_value == "192.168.178.60"
    finally:
        await coordinator.async_shutdown()


async def test_last_boot_sensor_stabilization_and_reboot_rollover(hass):
    """Test Last Boot jitter deadband, caching, reboot detection, and 49.7d rollover."""
    mock_api = MagicMock()
    mock_api.is_connected.return_value = True
    coordinator, sensors = _create_coordinator_and_sensors(hass, mock_api)
    boot_sensor = sensors["last_boot"]
    assert isinstance(boot_sensor, SmartBedLastBootSensor)

    t0 = datetime(2026, 11, 20, 22, 0, 0, 400000, tzinfo=UTC)
    now_ref = t0

    try:
        await boot_sensor.async_added_to_hass()
        assert boot_sensor.extra_state_attributes is None

        with patch(
            "custom_components.smartbed.sensor.dt_util.utcnow",
            side_effect=lambda: now_ref,
        ):
            # 1. Initial poll: uptime 60 s -> boot at 21:59:00 (microseconds stripped)
            mock_api.async_get_status.return_value = _make_state(uptime_ms=60_000)
            await coordinator.async_refresh()
            initial_boot = boot_sensor.native_value
            assert initial_boot == datetime(2026, 11, 20, 21, 59, 0, tzinfo=UTC)

            # Repeated reads for same SmartBedState object do not recompute even if clock moves
            now_ref = t0 + timedelta(seconds=60)
            assert boot_sensor.native_value == initial_boot

            # 2. Poll with +2 s jitter (<= 5 s deadband) -> timestamp stays unchanged
            now_ref = t0 + timedelta(seconds=12)
            mock_api.async_get_status.return_value = _make_state(uptime_ms=70_000)
            await coordinator.async_refresh()
            assert boot_sensor.native_value == initial_boot

            # 3. ESP reboot (uptime_ms decreased from 70_000 to 5_000) -> updates immediately
            now_ref = t0 + timedelta(seconds=20)
            mock_api.async_get_status.return_value = _make_state(uptime_ms=5_000)
            await coordinator.async_refresh()
            reboot_ts = boot_sensor.native_value
            assert reboot_ts == datetime(2026, 11, 20, 22, 0, 15, tzinfo=UTC)

            # 4. Simulate 49.7-day millis() rollover: jump near uint32 max then wrap to 5_000
            now_ref = t0 + timedelta(days=50)
            mock_api.async_get_status.return_value = _make_state(
                uptime_ms=4_294_960_000
            )
            await coordinator.async_refresh()
            pre_rollover_ts = boot_sensor.native_value
            assert pre_rollover_ts is not None

            now_ref = now_ref + timedelta(seconds=12, milliseconds=296)
            mock_api.async_get_status.return_value = _make_state(uptime_ms=5_000)
            await coordinator.async_refresh()
            assert boot_sensor.native_value != pre_rollover_ts

            # 5. Large positive clock drift (> 5 s) triggers update
            now_ref = now_ref + timedelta(seconds=10)
            mock_api.async_get_status.return_value = _make_state(uptime_ms=5_000)
            await coordinator.async_refresh()
            assert boot_sensor.native_value == (
                now_ref - timedelta(milliseconds=5_000)
            ).replace(microsecond=0)

            # 6. Coordinator data None -> returns None
            mock_api.async_get_status.return_value = None
            await coordinator.async_refresh()
            assert boot_sensor.native_value is None
    finally:
        await coordinator.async_shutdown()


async def test_sensor_setup_platform_without_discovery_info_warns(hass, caplog):
    """Test manual YAML setup under sensor: logs a warning and adds no entities."""
    add_entities = MagicMock()
    with caplog.at_level(logging.WARNING):
        await async_setup_platform(hass, {}, add_entities, discovery_info=None)

    assert not add_entities.called
    assert any(r.levelno == logging.WARNING for r in caplog.records)


async def test_end_to_end_cover_discovers_sensors_single_poll(
    hass, enable_custom_integrations
):
    """Test full HA setup loads covers + diagnostic sensors via a single coordinator poll."""
    mock_api = MagicMock()
    mock_api.is_connected.return_value = True
    sample_state = _make_state(
        rssi=-58,
        free_heap=43210,
        uptime_ms=90_000,
        version="2.0.0",
        ip="192.168.178.51",
    )
    sample_state = SmartBedState(
        hostname=sample_state.hostname,
        version=sample_state.version,
        build=sample_state.build,
        wifi_connected=sample_state.wifi_connected,
        ip=sample_state.ip,
        rssi=sample_state.rssi,
        uptime_ms=sample_state.uptime_ms,
        free_heap=sample_state.free_heap,
        max_run_duration_ms=sample_state.max_run_duration_ms,
        head=SmartBedAxisState(direction="up", source="web", remaining_ms=15000),
        foot=SmartBedAxisState(direction="stopped", source="none", remaining_ms=0),
    )
    mock_api.async_get_status = AsyncMock(return_value=sample_state)

    with patch(
        "custom_components.smartbed.cover.EspSmartBedApiClient",
        return_value=mock_api,
    ):
        assert await async_setup_component(
            hass,
            "cover",
            {
                "cover": [
                    {
                        "platform": "smartbed",
                        "name": "SmartBed",
                        "base_url": "http://esp-smartbed-controller.local",
                    }
                ]
            },
        )
        await hass.async_block_till_done()

    runtime_data: SmartBedRuntimeData = hass.data[DOMAIN][DATA_ENTRIES][
        "esp-smartbed-controller.local"
    ]
    try:
        await runtime_data.coordinator.async_refresh()
        await hass.async_block_till_done()

        # Covers + all 5 diagnostic sensors share one poll
        assert mock_api.async_get_status.await_count == 1

        head_state = hass.states.get("cover.smartbed_head_motor")
        foot_state = hass.states.get("cover.smartbed_foot_motor")
        assert head_state is not None
        assert head_state.state == "opening"
        assert head_state.attributes["source"] == "web"
        assert head_state.attributes["remaining_ms"] == 15000
        assert foot_state is not None
        assert foot_state.state == "closed"
        assert foot_state.attributes["source"] == "none"

        expected_sensor_ids = {
            "sensor.smartbed_wi_fi_rssi": "-58",
            "sensor.smartbed_free_heap": "43210",
            "sensor.smartbed_firmware_version": "2.0.0",
            "sensor.smartbed_ip_address": "192.168.178.51",
        }
        for entity_id, expected_state in expected_sensor_ids.items():
            st = hass.states.get(entity_id)
            assert st is not None, f"Missing {entity_id}"
            assert st.state == expected_state

        boot_state = hass.states.get("sensor.smartbed_last_boot")
        assert boot_state is not None
        assert boot_state.state not in ("unknown", "unavailable")

        registry = er.async_get(hass)
        device_ids = set()
        for entity_id in (
            "cover.smartbed_head_motor",
            "cover.smartbed_foot_motor",
            *expected_sensor_ids.keys(),
            "sensor.smartbed_last_boot",
        ):
            entry = registry.async_get(entity_id)
            assert entry is not None, f"Missing registry entry for {entity_id}"
            device_ids.add(entry.device_id)
            if entity_id.startswith("sensor."):
                assert entry.entity_category == EntityCategory.DIAGNOSTIC

        assert len(device_ids) == 1
    finally:
        await runtime_data.coordinator.async_shutdown()
