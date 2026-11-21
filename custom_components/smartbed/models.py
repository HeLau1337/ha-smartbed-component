"""Data classes for SmartBed data."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

type OnOff = Literal["on", "off"]
type MotorDirection = Literal["up", "down", "stopped"]
type ControlSource = Literal["web", "remote", "none"]

VALID_ON_OFF: tuple[OnOff, OnOff] = ("on", "off")
VALID_DIRECTIONS: tuple[MotorDirection, ...] = ("up", "down", "stopped")
VALID_CONTROL_SOURCES: tuple[ControlSource, ...] = ("web", "remote", "none")


def _require_str(value: object, field_name: str) -> str:
    """Validate that a field is a string."""
    if not isinstance(value, str):
        raise ValueError(
            f"Invalid value for {field_name!r}: {value!r} (expected string)"
        )
    return value


def _require_bool(value: object, field_name: str) -> bool:
    """Validate that a field is strictly a boolean."""
    if not isinstance(value, bool):
        raise ValueError(
            f"Invalid value for {field_name!r}: {value!r} (expected boolean)"
        )
    return value


def _require_int(
    value: object, field_name: str, *, min_value: int | None = None
) -> int:
    """Validate that a field is an integer (excluding bool) and within bounds."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            f"Invalid value for {field_name!r}: {value!r} (expected integer)"
        )
    if min_value is not None and value < min_value:
        raise ValueError(
            f"Invalid value for {field_name!r}: {value!r} (expected >= {min_value})"
        )
    return value


def _extract_required_fields(
    data: object, required_keys: tuple[str, ...], label: str
) -> dict[str, Any]:
    """Validate that data is a dict containing every required key."""
    if not isinstance(data, dict):
        raise TypeError(f"Expected JSON object for {label}, got {type(data).__name__}")
    missing = [key for key in required_keys if key not in data]
    if missing:
        raise ValueError(f"Missing required {label} keys: {', '.join(missing)}")
    return data


class SmartBedMotorType(Enum):
    """Used for configuration of a SmartBed cover entity."""

    HEAD = "h"
    FOOT = "f"


@dataclass
class SmartBedMotorState:
    """Defines a motor command payload sent to GET /set."""

    type: SmartBedMotorType
    up: OnOff
    down: OnOff


@dataclass(frozen=True)
class SmartBedAxisState:
    """Defines the runtime state of a single SmartBed motor axis."""

    direction: MotorDirection
    source: ControlSource
    remaining_ms: int

    def __post_init__(self) -> None:
        """Validate direction, control source, and non-negative remaining duration."""
        if self.direction not in VALID_DIRECTIONS:
            raise ValueError(
                f"Invalid SmartBedAxisState direction: {self.direction!r} "
                f"(expected one of {VALID_DIRECTIONS})"
            )
        if self.source not in VALID_CONTROL_SOURCES:
            raise ValueError(
                f"Invalid SmartBedAxisState source: {self.source!r} "
                f"(expected one of {VALID_CONTROL_SOURCES})"
            )
        _require_int(self.remaining_ms, "remaining_ms", min_value=0)

    @classmethod
    def from_dict(cls, data: object, axis_name: str = "axis") -> SmartBedAxisState:
        """Parse and validate an axis object from a unified /status JSON payload."""
        obj = _extract_required_fields(
            data, ("direction", "source", "remainingMs"), axis_name
        )
        return cls(
            direction=obj["direction"],
            source=obj["source"],
            remaining_ms=obj["remainingMs"],
        )


@dataclass(frozen=True)
class SmartBedState:
    """Defines the unified status and diagnostics state of the SmartBed."""

    hostname: str
    version: str
    build: str
    wifi_connected: bool
    ip: str
    rssi: int
    uptime_ms: int
    free_heap: int
    max_run_duration_ms: int
    head: SmartBedAxisState
    foot: SmartBedAxisState

    def __post_init__(self) -> None:
        """Validate field types and numeric bounds."""
        _require_str(self.hostname, "hostname")
        _require_str(self.version, "version")
        _require_str(self.build, "build")
        _require_bool(self.wifi_connected, "wifi_connected")
        _require_str(self.ip, "ip")
        _require_int(self.rssi, "rssi")
        _require_int(self.uptime_ms, "uptime_ms", min_value=0)
        _require_int(self.free_heap, "free_heap", min_value=0)
        _require_int(self.max_run_duration_ms, "max_run_duration_ms", min_value=1)
        if not isinstance(self.head, SmartBedAxisState):
            raise TypeError("head must be a SmartBedAxisState")
        if not isinstance(self.foot, SmartBedAxisState):
            raise TypeError("foot must be a SmartBedAxisState")

    def axis(self, motor_type: SmartBedMotorType) -> SmartBedAxisState:
        """Return the axis state for the given motor type."""
        return self.head if motor_type == SmartBedMotorType.HEAD else self.foot

    @classmethod
    def from_dict(cls, data: object) -> SmartBedState:
        """Parse and validate a unified /status JSON payload."""
        obj = _extract_required_fields(
            data,
            (
                "hostname",
                "version",
                "build",
                "wifiConnected",
                "ip",
                "rssi",
                "uptimeMs",
                "freeHeap",
                "maxRunDurationMs",
                "head",
                "foot",
            ),
            "SmartBedState",
        )
        return cls(
            hostname=obj["hostname"],
            version=obj["version"],
            build=obj["build"],
            wifi_connected=obj["wifiConnected"],
            ip=obj["ip"],
            rssi=obj["rssi"],
            uptime_ms=obj["uptimeMs"],
            free_heap=obj["freeHeap"],
            max_run_duration_ms=obj["maxRunDurationMs"],
            head=SmartBedAxisState.from_dict(obj["head"], "head"),
            foot=SmartBedAxisState.from_dict(obj["foot"], "foot"),
        )
