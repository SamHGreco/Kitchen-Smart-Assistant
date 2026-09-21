"""Temperature/humidity monitoring subsystem logic.

Wraps a `TemperatureHumidityDriver` (real or mock) and polls it on a
background thread, exposing the latest reading in a thread-safe way. This is
the only module other subsystem code should use for temperature/humidity -
never the hardware driver directly.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

from app import config
from app.shared.exceptions import SensorReadError
from app.shared.models import SensorHealth
from environment.hardware.dht11_driver import (
    DHT11Driver,
    MockDHT11Driver,
    TemperatureHumidityDriver,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TemperatureHumidityReading:
    """Latest temperature/humidity snapshot, safe to hand to other code."""

    temperature_c: float | None
    humidity_percent: float | None
    health: SensorHealth
    timestamp: datetime


def _create_driver() -> TemperatureHumidityDriver:
    if config.HARDWARE_MODE:
        return DHT11Driver(config.DHT11_GPIO_PIN)
    return MockDHT11Driver()


class TemperatureHumidityMonitor:
    """Polls the DHT11 on a background thread and exposes the latest reading.

    Public API (safe for other subsystems/threads to call):
        start(), stop(), get_reading(), get_temperature_c(),
        get_humidity_percent(), get_health()
    """

    def __init__(
        self,
        driver: TemperatureHumidityDriver | None = None,
        poll_interval_seconds: float | None = None,
        max_consecutive_failures: int | None = None,
    ) -> None:
        self._driver = driver if driver is not None else _create_driver()
        self._poll_interval_seconds = (
            poll_interval_seconds
            if poll_interval_seconds is not None
            else config.DHT11_POLL_INTERVAL_SECONDS
        )
        self._max_consecutive_failures = (
            max_consecutive_failures
            if max_consecutive_failures is not None
            else config.DHT11_MAX_CONSECUTIVE_FAILURES
        )

        self._lock = threading.Lock()
        self._latest = TemperatureHumidityReading(
            temperature_c=None,
            humidity_percent=None,
            health=SensorHealth.FAULT,
            timestamp=datetime.now(timezone.utc),
        )
        self._consecutive_failures = 0

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the background polling thread. Safe to call once; a no-op if already running."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="TemperatureHumidityMonitor", daemon=True
        )
        self._thread.start()
        logger.info(
            "Temperature/humidity monitor started (poll interval=%.1fs)",
            self._poll_interval_seconds,
        )

    def stop(self) -> None:
        """Signal the polling thread to exit and release the driver. Blocks briefly."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self._poll_interval_seconds + 1.0)
            self._thread = None
        self._driver.close()
        logger.info("Temperature/humidity monitor stopped")

    def get_reading(self) -> TemperatureHumidityReading:
        """Return the latest reading snapshot. Thread-safe."""
        with self._lock:
            return self._latest

    def get_temperature_c(self) -> float | None:
        return self.get_reading().temperature_c

    def get_humidity_percent(self) -> float | None:
        return self.get_reading().humidity_percent

    def get_health(self) -> SensorHealth:
        return self.get_reading().health

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._poll_once()
            self._stop_event.wait(self._poll_interval_seconds)

    def _poll_once(self) -> None:
        try:
            reading = self._driver.read()
        except SensorReadError as exc:
            self._handle_failure(exc)
            return
        self._handle_success(reading)

    def _handle_success(self, reading) -> None:
        with self._lock:
            was_fault = self._latest.health == SensorHealth.FAULT
            self._consecutive_failures = 0
            self._latest = TemperatureHumidityReading(
                temperature_c=reading.temperature_c,
                humidity_percent=reading.humidity_percent,
                health=SensorHealth.OK,
                timestamp=datetime.now(timezone.utc),
            )
        logger.debug(
            "DHT11 reading: %.1fC, %.1f%% RH", reading.temperature_c, reading.humidity_percent
        )
        if was_fault:
            logger.info("Temperature/humidity sensor recovered")

    def _handle_failure(self, exc: Exception) -> None:
        with self._lock:
            self._consecutive_failures += 1
            was_fault = self._latest.health == SensorHealth.FAULT
            if self._consecutive_failures >= self._max_consecutive_failures:
                new_health = SensorHealth.FAULT
                # Drop stale values once faulted so consumers never mistake
                # an old reading for a current one.
                temperature_c = None
                humidity_percent = None
            else:
                new_health = SensorHealth.DEGRADED
                temperature_c = self._latest.temperature_c
                humidity_percent = self._latest.humidity_percent
            self._latest = TemperatureHumidityReading(
                temperature_c=temperature_c,
                humidity_percent=humidity_percent,
                health=new_health,
                timestamp=datetime.now(timezone.utc),
            )
        logger.warning(
            "DHT11 read failed (%d/%d consecutive): %s",
            self._consecutive_failures,
            self._max_consecutive_failures,
            exc,
        )
        if new_health == SensorHealth.FAULT and not was_fault:
            logger.error(
                "Temperature/humidity sensor marked FAULT after %d consecutive failures",
                self._consecutive_failures,
            )
