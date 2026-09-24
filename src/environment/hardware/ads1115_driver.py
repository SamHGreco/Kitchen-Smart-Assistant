"""ADS1115 ADC hardware drivers used to read the conditioned MQ-4 gas sensor
output. Defines the `ADS1115Driver` interface plus a real I2C-backed
implementation and a mock implementation with an identical public API.
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod

from app.shared.exceptions import SensorReadError


class ADS1115Driver(ABC):
    """Public interface implemented by both the real and mock ADS1115 drivers."""

    @abstractmethod
    def read_voltage(self, channel: int) -> float:
        """Return the measured voltage on the given single-ended channel (0-3).

        Raises SensorReadError on I2C communication failure.
        """

    @abstractmethod
    def read_raw(self, channel: int) -> int:
        """Return the raw ADC code on the given channel."""

    @abstractmethod
    def close(self) -> None:
        """Release any hardware resources."""


class RealADS1115Driver(ADS1115Driver):
    """Real ADS1115 driver over I2C, via adafruit-circuitpython-ads1x15.

    Requires the MQ-4's 5V analog output to be conditioned/divided to
    3.3V-safe levels before this ADC, per the subsystem hardware notes. The
    I2C/library imports are deferred to first use so this module can still
    be imported on machines without the library/hardware installed.
    """

    def __init__(self, i2c_address: int, gain: float, alert_ready_pin: int | None = None) -> None:
        self._i2c_address = i2c_address
        self._gain = gain
        self._alert_ready_pin = alert_ready_pin
        self._ads = None
        self._ads_module = None
        self._gpio = None
        self._channels: dict[int, object] = {}

    def _get_ads(self):
        if self._ads is None:
            try:
                import board
                import busio
                import adafruit_ads1x15.ads1115 as ads_module
            except ImportError as exc:
                raise SensorReadError("adafruit-circuitpython-ads1x15 / board not available") from exc
            try:
                i2c = busio.I2C(board.SCL, board.SDA)
                self._ads = ads_module.ADS1115(i2c, address=self._i2c_address, gain=self._gain)
            except OSError as exc:
                raise SensorReadError(str(exc)) from exc
            self._ads_module = ads_module
            self._setup_alert_ready_pin()
        return self._ads

    def _setup_alert_ready_pin(self) -> None:
        if self._alert_ready_pin is None or self._gpio is not None:
            return
        try:
            import RPi.GPIO as GPIO  # type: ignore[reportMissingModuleSource]
        except ImportError as exc:
            raise SensorReadError("RPi.GPIO not available for ADS1115 ALERT/RDY input") from exc
        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self._alert_ready_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        except RuntimeError as exc:
            raise SensorReadError(str(exc)) from exc
        self._gpio = GPIO

    def _get_channel(self, channel: int):
        if channel not in self._channels:
            try:
                from adafruit_ads1x15.analog_in import AnalogIn
            except ImportError as exc:
                raise SensorReadError("adafruit-circuitpython-ads1x15 not available") from exc
            ads = self._get_ads()
            pins = (self._ads_module.P0, self._ads_module.P1, self._ads_module.P2, self._ads_module.P3)
            if not 0 <= channel < len(pins):
                raise SensorReadError(f"Invalid ADS1115 channel {channel}")
            self._channels[channel] = AnalogIn(ads, pins[channel])
        return self._channels[channel]

    def read_voltage(self, channel: int) -> float:
        try:
            return self._get_channel(channel).voltage
        except SensorReadError:
            raise
        except OSError as exc:
            raise SensorReadError(str(exc)) from exc

    def read_raw(self, channel: int) -> int:
        try:
            return self._get_channel(channel).value
        except SensorReadError:
            raise
        except OSError as exc:
            raise SensorReadError(str(exc)) from exc

    def close(self) -> None:
        self._channels.clear()
        self._ads = None
        self._ads_module = None
        if self._gpio is not None and self._alert_ready_pin is not None:
            self._gpio.cleanup(self._alert_ready_pin)
            self._gpio = None


class MockADS1115Driver(ADS1115Driver):
    """Simulated ADS1115 driver for development without hardware.

    Generates a stable "clean air" baseline voltage. Call `simulate_gas_event()`
    to force a temporary spike/change for exercising alarm logic in tests.
    """

    def __init__(self, baseline_voltage: float = 0.4) -> None:
        self._baseline_voltage = baseline_voltage
        self._forced_voltage: float | None = None
        self._force_failure = False

    def simulate_gas_event(self, voltage: float | None) -> None:
        """Force subsequent reads to hover around `voltage` (None resumes baseline)."""
        self._forced_voltage = voltage

    def force_failure(self, active: bool = True) -> None:
        """Make subsequent reads raise SensorReadError, for exercising fault-handling logic."""
        self._force_failure = active

    def read_voltage(self, channel: int) -> float:
        if self._force_failure:
            raise SensorReadError("Simulated ADS1115 failure")
        center = self._forced_voltage if self._forced_voltage is not None else self._baseline_voltage
        return center + random.uniform(-0.05, 0.05)

    def read_raw(self, channel: int) -> int:
        if self._force_failure:
            raise SensorReadError("Simulated ADS1115 failure")
        return int(self.read_voltage(channel) / 4.096 * 32767)

    def close(self) -> None:
        pass
