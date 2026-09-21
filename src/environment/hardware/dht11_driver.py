"""DHT11 temperature/humidity hardware drivers.

Defines the `TemperatureHumidityDriver` interface plus a real GPIO-backed
implementation and a mock implementation with an identical public API, so
higher-level code never needs to know which one is in use.
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.shared.exceptions import SensorReadError


@dataclass
class DHT11Reading:
    temperature_c: float
    humidity_percent: float


class TemperatureHumidityDriver(ABC):
    """Public interface implemented by both the real and mock DHT11 drivers."""

    @abstractmethod
    def read(self) -> DHT11Reading:
        """Return a single reading. Raises SensorReadError on failure."""

    @abstractmethod
    def close(self) -> None:
        """Release any hardware resources."""


class DHT11Driver(TemperatureHumidityDriver):
    """Real DHT11 driver using a GPIO digital pin, via adafruit-circuitpython-dht.

    Requires DHT11_GPIO_PIN to be set in config.py before use. The GPIO
    library import is deferred to first use so this module can still be
    imported on machines without the library/hardware installed.
    """

    def __init__(self, gpio_pin: int | None) -> None:
        if gpio_pin is None:
            raise ValueError("DHT11_GPIO_PIN is not configured in config.py")
        self._gpio_pin = gpio_pin
        self._device = None

    def _get_device(self):
        if self._device is None:
            try:
                import adafruit_dht
                import board
            except ImportError as exc:
                raise SensorReadError("adafruit-circuitpython-dht / board not available") from exc
            try:
                pin = getattr(board, f"D{self._gpio_pin}")
            except AttributeError as exc:
                raise SensorReadError(f"Unknown board pin for GPIO {self._gpio_pin}") from exc
            self._device = adafruit_dht.DHT11(pin)
        return self._device

    def read(self) -> DHT11Reading:
        device = self._get_device()
        try:
            temperature_c = device.temperature
            humidity_percent = device.humidity
        except RuntimeError as exc:
            # adafruit_dht raises RuntimeError for common, recoverable transient
            # errors (checksum mismatch, timeout) - treat as a failed read, not a crash.
            raise SensorReadError(str(exc)) from exc
        except OSError as exc:
            raise SensorReadError(str(exc)) from exc
        if temperature_c is None or humidity_percent is None:
            raise SensorReadError("DHT11 returned an incomplete reading")
        return DHT11Reading(temperature_c=temperature_c, humidity_percent=humidity_percent)

    def close(self) -> None:
        if self._device is not None:
            self._device.exit()
            self._device = None


class MockDHT11Driver(TemperatureHumidityDriver):
    """Simulated DHT11 driver for development without hardware."""

    def __init__(
        self,
        baseline_temperature_c: float = 22.0,
        baseline_humidity_percent: float = 45.0,
    ) -> None:
        self._baseline_temperature_c = baseline_temperature_c
        self._baseline_humidity_percent = baseline_humidity_percent
        self._force_failure = False

    def force_failure(self, active: bool = True) -> None:
        """Make subsequent reads raise SensorReadError, for exercising fault-handling logic."""
        self._force_failure = active

    def read(self) -> DHT11Reading:
        if self._force_failure:
            raise SensorReadError("Simulated DHT11 failure")
        return DHT11Reading(
            temperature_c=self._baseline_temperature_c + random.uniform(-0.5, 0.5),
            humidity_percent=self._baseline_humidity_percent + random.uniform(-2.0, 2.0),
        )

    def close(self) -> None:
        pass
