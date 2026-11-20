"""Data classes for SmartBed data."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

type OnOff = Literal["on", "off"]
VALID_ON_OFF: tuple[OnOff, OnOff] = ("on", "off")


class SmartBedMotorType(Enum):
    """Used for configuration of a SmartBed cover entity."""

    HEAD = "h"
    FOOT = "f"


@dataclass
class SmartBedMotorState:
    """Defines the state of a SmartBed."""

    type: SmartBedMotorType
    up: OnOff
    down: OnOff


@dataclass
class SmartBedState:
    """Defines the state of a SmartBed."""

    hu: OnOff
    hd: OnOff
    fu: OnOff
    fd: OnOff

    def __post_init__(self) -> None:
        """Validate that every relay channel is strictly 'on' or 'off'."""
        for field_name in ("hu", "hd", "fu", "fd"):
            value = getattr(self, field_name)
            if value not in VALID_ON_OFF:
                raise ValueError(
                    f"Invalid SmartBedState value for {field_name!r}: {value!r} "
                    "(expected 'on' or 'off')"
                )
