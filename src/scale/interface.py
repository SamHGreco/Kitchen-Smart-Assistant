"""
WeightSensor interface for the scale subsystem. 

Defines the common API (tare, read_weight) that every sensor 
implementation satisfies, plus two implementations:
-The implementation SimulatedWeightSensor generates 
simulated weight readings for development and testing without physical hardware.
-The implementation HX711WeightSensor composes hx711_driver.HX711Driver 
for raw readings and calibration.CalibrationParams for converting raw values to grams.
"""

from abc import ABC, abstractmethod
import random
import time

from .hx711_driver import HX711Driver
from .calibration import CalibrationParams, apply_calibration


class WeightSensor(ABC):
    """Common interface every weight sensor implementation satisfies."""

    @abstractmethod
    def tare(self) -> None:
        """Zero out the scale at its current load so that any readings are relative to this weight."""
        raise NotImplementedError

    @abstractmethod
    def read_weight(self) -> float:
        """Return the current weight in grams, tare-adjusted."""
        raise NotImplementedError

    def read_stable_weight(self, samples: int = 5, delay: float = 0.1) -> float:
        """Average several readings to reduce single-sample noise."""
        readings = []
        for _ in range(samples):
            readings.append(self.read_weight())
            time.sleep(delay)
        return sum(readings) / len(readings)


class SimulatedWeightSensor(WeightSensor):
    """Generates simulated weight readings without physical hardware."""

    def __init__(self, base_weight: float = 500.0, noise: float = 2.0):
        self._tare_offset = 0.0
        self._base_weight = base_weight
        self._noise = noise

        def tare(self) -> None:
            self._tare_offset = self._base_weight + random.uniform(-self._noise, self._noise)

        def read_weight(self) -> float:
            raw = self._base_weight + random.uniform(-self._noise, self._noise)
            return raw - self._tare_offset

        def set_simulated_load(self, grams: float) -> None:
            """Changes the weight this sensor reports, for testing purposes."""
            self._base_weight = grams


class HX711WeightSensor(WeightSensor):
    """
    Composes HX711Driver (raw readings) and CalibrationParams 
    (raw-to-grams conversion) behind the WeightSensor API.
    """

    def __init__(self, dout_pin: int, sck_pin: int, calibration: CalibrationParams):
        self._driver = HX711Driver(dout_pin=dout_pin, sck_pin=sck_pin)
        self._calibration = calibration
        self._tare_offset_grams = 0.0

    def tare(self) -> None:
        raw = self._driver.raw_read()
        self._tare_offset_grams = apply_calibration(raw, self._calibration)

    def read_weight(self) -> float:
        raw = self._driver.raw_read()
        grams = apply_calibration(raw, self._calibration)
        return grams - self._tare_offset_grams


if __name__ == "__main__":
    # Runs without physical hardware, demonstrates basic sensor behavior
    # using the SimulatedWeightSensor.
    sensor = SimulatedWeightSensor(base_weight=750.0)
    sensor.tare()
    print("Tared. Single read:", sensor.read_weight())
    print("Stable read (5 samples):", sensor.read_stable_weight())

    sensor.set_simulated_load(600.0)
    print("After simulated usage, stable read:", sensor.read_stable_weight())
