"""Audible/visual alarm output control (Phase 5).

Wraps an `AlarmOutputDriver` (real or mock) and exposes a single, idempotent
on/off switch for the buzzer + LED together, so gas-alarm logic never needs
to know about GPIO pins or driver details. The LED/buzzer stay on for as
long as the alarm condition is active - callers are responsible for calling
`set_alarm_active(False)` only once the underlying condition truly clears.
"""

from __future__ import annotations

import logging
import threading

from app import config
from environment.hardware.alarm_outputs import (
    AlarmOutputDriver,
    MockAlarmOutputDriver,
    RealAlarmOutputDriver,
)

logger = logging.getLogger(__name__)


def _create_driver() -> AlarmOutputDriver:
    if config.HARDWARE_MODE:
        return RealAlarmOutputDriver(config.BUZZER_GPIO_PIN, config.ALARM_LED_GPIO_PIN)
    return MockAlarmOutputDriver()


class AlarmController:
    """Drives the buzzer + LED outputs from a single alarm on/off state.

    Public API (safe for other subsystems/threads to call):
        set_alarm_active(active), is_alarm_active(), close()
    """

    def __init__(self, driver: AlarmOutputDriver | None = None) -> None:
        self._driver = driver if driver is not None else _create_driver()
        self._lock = threading.Lock()
        self._active = False

    def set_alarm_active(self, active: bool) -> None:
        """Turn the buzzer + LED on or off together. No-op if already in that state."""
        with self._lock:
            if active == self._active:
                return
            self._active = active
            self._driver.set_buzzer(active)
            self._driver.set_led(active)
        if active:
            logger.warning("Alarm outputs ACTIVATED (buzzer + LED)")
        else:
            logger.info("Alarm outputs DEACTIVATED")

    def is_alarm_active(self) -> bool:
        with self._lock:
            return self._active

    def close(self) -> None:
        """De-energize outputs and release the driver."""
        self.set_alarm_active(False)
        self._driver.close()
