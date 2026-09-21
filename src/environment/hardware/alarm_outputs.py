"""Buzzer/LED alarm output hardware drivers.

Defines the `AlarmOutputDriver` interface plus a real GPIO-backed
implementation and a mock implementation with an identical public API.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class AlarmOutputDriver(ABC):
    """Public interface implemented by both the real and mock alarm output drivers."""

    @abstractmethod
    def set_buzzer(self, on: bool) -> None:
        """Turn the audible buzzer on or off."""

    @abstractmethod
    def set_led(self, on: bool) -> None:
        """Turn the visual alarm LED on or off."""

    @abstractmethod
    def close(self) -> None:
        """Release any hardware resources and leave outputs de-energized."""


class RealAlarmOutputDriver(AlarmOutputDriver):
    """Real alarm output driver using GPIO outputs.

    NOTE: control logic is implemented in Phase 5. Requires BUZZER_GPIO_PIN
    and ALARM_LED_GPIO_PIN to be set in config.py. Assumes external
    transistor/MOSFET driver circuitry for the buzzer, per hardware notes.
    """

    def __init__(self, buzzer_pin: int | None, led_pin: int | None) -> None:
        if buzzer_pin is None or led_pin is None:
            raise ValueError("BUZZER_GPIO_PIN / ALARM_LED_GPIO_PIN not configured in config.py")
        self._buzzer_pin = buzzer_pin
        self._led_pin = led_pin

    def set_buzzer(self, on: bool) -> None:
        raise NotImplementedError("RealAlarmOutputDriver.set_buzzer() will be implemented in Phase 5")

    def set_led(self, on: bool) -> None:
        raise NotImplementedError("RealAlarmOutputDriver.set_led() will be implemented in Phase 5")

    def close(self) -> None:
        pass


class MockAlarmOutputDriver(AlarmOutputDriver):
    """Simulated alarm output driver that tracks/logs state for dev and tests."""

    def __init__(self) -> None:
        self.buzzer_on: bool = False
        self.led_on: bool = False

    def set_buzzer(self, on: bool) -> None:
        if on != self.buzzer_on:
            logger.debug("Mock buzzer %s", "ON" if on else "OFF")
        self.buzzer_on = on

    def set_led(self, on: bool) -> None:
        if on != self.led_on:
            logger.debug("Mock LED %s", "ON" if on else "OFF")
        self.led_on = on

    def close(self) -> None:
        self.set_buzzer(False)
        self.set_led(False)
