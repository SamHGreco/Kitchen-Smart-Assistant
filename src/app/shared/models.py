"""Shared enums and dataclasses that form the public contract between the
environment / safety / power subsystem and the rest of the team's code.

Other subsystems should only ever consume these types (and the manager
classes that produce them) - never the hardware drivers underneath.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class SensorHealth(Enum):
    """Health of a single hardware sensor, independent of any alarm state."""

    OK = "ok"
    DEGRADED = "degraded"
    FAULT = "fault"


class SafetyState(Enum):
    """Overall safety state published to the GUI and used to drive alarms/wake."""

    NORMAL = "normal"
    WARNING = "warning"
    ALARM = "alarm"
    SENSOR_FAULT = "sensor_fault"


class ActivityType(Enum):
    """Sources of user/system activity that PowerManager reacts to."""

    TOUCH = "touch"
    MOTION = "motion"
    BARCODE = "barcode"
    WEIGHT = "weight"
    SAFETY_ALARM = "safety_alarm"


class UIState(Enum):
    """Coarse UI state PowerManager needs. The GUI subsystem maps its actual
    screens onto this - only HOME is treated specially by the sleep logic.
    """

    HOME = "home"
    OTHER = "other"


def celsius_to_fahrenheit(celsius: float) -> float:
    """Convert a Celsius temperature to Fahrenheit."""
    return celsius * 9.0 / 5.0 + 32.0


@dataclass(frozen=True)
class EnvironmentStatus:
    """Read-only snapshot of the environment/safety subsystem.

    Obtain the latest snapshot via `EnvironmentManager.get_status()`; this
    object itself never changes after it is created.
    """

    temperature_c: float | None
    humidity_percent: float | None
    temp_alarm: bool
    humidity_alarm: bool
    gas_raw: int | None
    gas_voltage: float | None
    gas_alarm: bool
    motion_detected: bool
    safety_state: SafetyState
    sensor_fault: bool
    temp_humidity_health: SensorHealth
    gas_health: SensorHealth
    motion_health: SensorHealth
    timestamp: datetime

    @property
    def temperature_f(self) -> float | None:
        """Temperature in Fahrenheit, for display convenience only."""
        if self.temperature_c is None:
            return None
        return celsius_to_fahrenheit(self.temperature_c)


@dataclass(frozen=True)
class GasAlarmThresholds:
    """Current gas alarm tuning, readable/settable at runtime by the UI subsystem."""

    threshold_voltage: float
    hysteresis_voltage: float
    debounce_seconds: float


@dataclass(frozen=True)
class TempAlarmThresholds:
    """Current high-temperature alarm tuning, readable/settable at runtime by the UI subsystem."""

    threshold_c: float
    hysteresis_c: float
    debounce_seconds: float


@dataclass(frozen=True)
class HumidityAlarmThresholds:
    """Current high-humidity alarm tuning, readable/settable at runtime by the UI subsystem."""

    threshold_percent: float
    hysteresis_percent: float
    debounce_seconds: float
