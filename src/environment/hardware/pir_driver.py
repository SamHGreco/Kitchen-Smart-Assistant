"""PIR motion sensor hardware drivers.

Defines the `PIRDriver` interface plus a real GPIO-backed implementation and
a mock implementation with an identical public API.
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod

from app.shared.exceptions import SensorReadError


class PIRDriver(ABC):
    """Public interface implemented by both the real and mock PIR drivers."""

    @abstractmethod
    def read(self) -> bool:
        """Return True if motion is currently detected. Raises SensorReadError on failure."""

    @abstractmethod
    def close(self) -> None:
        """Release any hardware resources."""


class RealPIRDriver(PIRDriver):
    """Real PIR driver using a GPIO digital input, via RPi.GPIO.

    Requires PIR_GPIO_PIN to be set in config.py before use. The GPIO import
    is deferred to first use so this module can still be imported on
    machines without the library/hardware installed.
    """

    def __init__(self, gpio_pin: int | None) -> None:
        if gpio_pin is None:
            raise ValueError("PIR_GPIO_PIN is not configured in config.py")
        self._gpio_pin = gpio_pin
        self._gpio = None

    def _ensure_initialized(self):
        if self._gpio is None:
            try:
                import RPi.GPIO as GPIO
            except ImportError as exc:
                raise SensorReadError("RPi.GPIO not available") from exc
            try:
                GPIO.setmode(GPIO.BCM)
                GPIO.setup(self._gpio_pin, GPIO.IN)
            except RuntimeError as exc:
                raise SensorReadError(str(exc)) from exc
            self._gpio = GPIO
        return self._gpio

    def read(self) -> bool:
        gpio = self._ensure_initialized()
        try:
            return bool(gpio.input(self._gpio_pin))
        except RuntimeError as exc:
            raise SensorReadError(str(exc)) from exc

    def close(self) -> None:
        if self._gpio is not None:
            self._gpio.cleanup(self._gpio_pin)
            self._gpio = None


class MockPIRDriver(PIRDriver):
    """Simulated PIR driver for development without hardware."""

    def __init__(self, spontaneous_trigger_probability: float = 0.0) -> None:
        self._spontaneous_trigger_probability = spontaneous_trigger_probability
        self._forced_state: bool | None = None
        self._force_failure = False

    def trigger_motion(self, active: bool = True) -> None:
        """Force subsequent reads to report motion (active=False clears it)."""
        self._forced_state = active

    def force_failure(self, active: bool = True) -> None:
        """Make subsequent reads raise SensorReadError, for exercising fault-handling logic."""
        self._force_failure = active

    def read(self) -> bool:
        if self._force_failure:
            raise SensorReadError("Simulated PIR failure")
        if self._forced_state is not None:
            return self._forced_state
        return random.random() < self._spontaneous_trigger_probability

    def close(self) -> None:
        pass
