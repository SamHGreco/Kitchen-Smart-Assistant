"""Temperature/humidity monitoring subsystem logic.

Wraps a `TemperatureHumidityDriver` (real or mock) and polls it on a
background thread, applying threshold + hysteresis + debounce logic (mirrors
GasMonitor) to produce stable, chatter-free high-temperature and
high-humidity alarm flags. This is the only module other subsystem code
should use for temperature/humidity - never the hardware driver directly.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

from app import config
from app.shared.exceptions import SensorReadError
from app.shared.models import HumidityAlarmThresholds, SensorHealth, TempAlarmThresholds
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
    temp_alarm: bool
    humidity_alarm: bool
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
        get_humidity_percent(), is_temp_alarm_active(),
        is_humidity_alarm_active(), get_health(), get_temp_alarm_thresholds(),
        set_temp_alarm_thresholds(), get_humidity_alarm_thresholds(),
        set_humidity_alarm_thresholds()
    """

    def __init__(
        self,
        driver: TemperatureHumidityDriver | None = None,
        poll_interval_seconds: float | None = None,
        max_consecutive_failures: int | None = None,
        temp_alarm_threshold_c: float | None = None,
        temp_alarm_hysteresis_c: float | None = None,
        temp_alarm_debounce_seconds: float | None = None,
        humidity_alarm_threshold_percent: float | None = None,
        humidity_alarm_hysteresis_percent: float | None = None,
        humidity_alarm_debounce_seconds: float | None = None,
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
        self._temp_alarm_threshold_c = (
            temp_alarm_threshold_c if temp_alarm_threshold_c is not None else config.TEMP_HIGH_THRESHOLD_C
        )
        self._temp_alarm_hysteresis_c = (
            temp_alarm_hysteresis_c if temp_alarm_hysteresis_c is not None else config.TEMP_HIGH_HYSTERESIS_C
        )
        self._temp_alarm_debounce_seconds = (
            temp_alarm_debounce_seconds
            if temp_alarm_debounce_seconds is not None
            else config.TEMP_ALARM_DEBOUNCE_SECONDS
        )
        self._humidity_alarm_threshold_percent = (
            humidity_alarm_threshold_percent
            if humidity_alarm_threshold_percent is not None
            else config.HUMIDITY_HIGH_THRESHOLD_PERCENT
        )
        self._humidity_alarm_hysteresis_percent = (
            humidity_alarm_hysteresis_percent
            if humidity_alarm_hysteresis_percent is not None
            else config.HUMIDITY_HIGH_HYSTERESIS_PERCENT
        )
        self._humidity_alarm_debounce_seconds = (
            humidity_alarm_debounce_seconds
            if humidity_alarm_debounce_seconds is not None
            else config.HUMIDITY_ALARM_DEBOUNCE_SECONDS
        )

        self._lock = threading.Lock()
        self._latest = TemperatureHumidityReading(
            temperature_c=None,
            humidity_percent=None,
            temp_alarm=False,
            humidity_alarm=False,
            health=SensorHealth.FAULT,
            timestamp=datetime.now(timezone.utc),
        )
        self._consecutive_failures = 0
        self._temp_alarm_active = False
        self._temp_above_threshold_since: datetime | None = None
        self._humidity_alarm_active = False
        self._humidity_above_threshold_since: datetime | None = None

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

    def is_temp_alarm_active(self) -> bool:
        return self.get_reading().temp_alarm

    def is_humidity_alarm_active(self) -> bool:
        return self.get_reading().humidity_alarm

    def get_health(self) -> SensorHealth:
        return self.get_reading().health

    def get_temp_alarm_thresholds(self) -> TempAlarmThresholds:
        """Return the currently active high-temperature alarm tuning. Thread-safe."""
        with self._lock:
            return TempAlarmThresholds(
                threshold_c=self._temp_alarm_threshold_c,
                hysteresis_c=self._temp_alarm_hysteresis_c,
                debounce_seconds=self._temp_alarm_debounce_seconds,
            )

    def set_temp_alarm_thresholds(
        self,
        threshold_c: float | None = None,
        hysteresis_c: float | None = None,
        debounce_seconds: float | None = None,
    ) -> None:
        """Change high-temperature alarm tuning at runtime (e.g. from the UI subsystem).

        Any parameter left as None keeps its current value. Thread-safe;
        takes effect starting with the next sample.
        """
        if hysteresis_c is not None and hysteresis_c < 0:
            raise ValueError("hysteresis_c must be >= 0")
        if debounce_seconds is not None and debounce_seconds < 0:
            raise ValueError("debounce_seconds must be >= 0")
        with self._lock:
            if threshold_c is not None:
                self._temp_alarm_threshold_c = threshold_c
            if hysteresis_c is not None:
                self._temp_alarm_hysteresis_c = hysteresis_c
            if debounce_seconds is not None:
                self._temp_alarm_debounce_seconds = debounce_seconds
            updated = (self._temp_alarm_threshold_c, self._temp_alarm_hysteresis_c, self._temp_alarm_debounce_seconds)
        logger.info("Temperature alarm thresholds updated: threshold=%.1fC hysteresis=%.1fC debounce=%.1fs", *updated)

    def get_humidity_alarm_thresholds(self) -> HumidityAlarmThresholds:
        """Return the currently active high-humidity alarm tuning. Thread-safe."""
        with self._lock:
            return HumidityAlarmThresholds(
                threshold_percent=self._humidity_alarm_threshold_percent,
                hysteresis_percent=self._humidity_alarm_hysteresis_percent,
                debounce_seconds=self._humidity_alarm_debounce_seconds,
            )

    def set_humidity_alarm_thresholds(
        self,
        threshold_percent: float | None = None,
        hysteresis_percent: float | None = None,
        debounce_seconds: float | None = None,
    ) -> None:
        """Change high-humidity alarm tuning at runtime (e.g. from the UI subsystem).

        Any parameter left as None keeps its current value. Thread-safe;
        takes effect starting with the next sample.
        """
        if threshold_percent is not None and not 0 <= threshold_percent <= 100:
            raise ValueError("threshold_percent must be between 0 and 100")
        if hysteresis_percent is not None and hysteresis_percent < 0:
            raise ValueError("hysteresis_percent must be >= 0")
        if debounce_seconds is not None and debounce_seconds < 0:
            raise ValueError("debounce_seconds must be >= 0")
        with self._lock:
            if threshold_percent is not None:
                self._humidity_alarm_threshold_percent = threshold_percent
            if hysteresis_percent is not None:
                self._humidity_alarm_hysteresis_percent = hysteresis_percent
            if debounce_seconds is not None:
                self._humidity_alarm_debounce_seconds = debounce_seconds
            updated = (
                self._humidity_alarm_threshold_percent,
                self._humidity_alarm_hysteresis_percent,
                self._humidity_alarm_debounce_seconds,
            )
        logger.info(
            "Humidity alarm thresholds updated: threshold=%.1f%% hysteresis=%.1f%% debounce=%.1fs", *updated
        )

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
        now = datetime.now(timezone.utc)
        with self._lock:
            was_fault = self._latest.health == SensorHealth.FAULT
            self._consecutive_failures = 0

            temp_changed = self._update_temp_alarm_state(reading.temperature_c, now)
            humidity_changed = self._update_humidity_alarm_state(reading.humidity_percent, now)

            self._latest = TemperatureHumidityReading(
                temperature_c=reading.temperature_c,
                humidity_percent=reading.humidity_percent,
                temp_alarm=self._temp_alarm_active,
                humidity_alarm=self._humidity_alarm_active,
                health=SensorHealth.OK,
                timestamp=now,
            )
        logger.debug(
            "DHT11 reading: %.1fC, %.1f%% RH", reading.temperature_c, reading.humidity_percent
        )
        if was_fault:
            logger.info("Temperature/humidity sensor recovered")
        if temp_changed:
            if self._temp_alarm_active:
                logger.warning(
                    "TEMPERATURE ALARM STARTED (temp=%.1fC >= threshold=%.1fC)",
                    reading.temperature_c,
                    self._temp_alarm_threshold_c,
                )
            else:
                logger.info("TEMPERATURE ALARM CLEARED (temp=%.1fC)", reading.temperature_c)
        if humidity_changed:
            if self._humidity_alarm_active:
                logger.warning(
                    "HUMIDITY ALARM STARTED (humidity=%.1f%% >= threshold=%.1f%%)",
                    reading.humidity_percent,
                    self._humidity_alarm_threshold_percent,
                )
            else:
                logger.info("HUMIDITY ALARM CLEARED (humidity=%.1f%%)", reading.humidity_percent)

    def _update_temp_alarm_state(self, temperature_c: float, now: datetime) -> bool:
        self._temp_alarm_active, self._temp_above_threshold_since, changed = self._update_threshold_alarm(
            self._temp_alarm_active,
            self._temp_above_threshold_since,
            temperature_c,
            self._temp_alarm_threshold_c,
            self._temp_alarm_hysteresis_c,
            self._temp_alarm_debounce_seconds,
            now,
        )
        return changed

    def _update_humidity_alarm_state(self, humidity_percent: float, now: datetime) -> bool:
        self._humidity_alarm_active, self._humidity_above_threshold_since, changed = self._update_threshold_alarm(
            self._humidity_alarm_active,
            self._humidity_above_threshold_since,
            humidity_percent,
            self._humidity_alarm_threshold_percent,
            self._humidity_alarm_hysteresis_percent,
            self._humidity_alarm_debounce_seconds,
            now,
        )
        return changed

    @staticmethod
    def _update_threshold_alarm(
        active: bool,
        above_threshold_since: datetime | None,
        value: float,
        threshold: float,
        hysteresis: float,
        debounce_seconds: float,
        now: datetime,
    ) -> tuple[bool, datetime | None, bool]:
        """Generic threshold + hysteresis + debounce alarm step.

        Mirrors GasMonitor._update_alarm_state() so temperature/humidity
        alarms behave identically to the gas alarm (no chatter near the
        threshold, requires a sustained condition to trip).
        Returns (new_active, new_above_threshold_since, changed).
        """
        previous = active
        if not active:
            if value >= threshold:
                if above_threshold_since is None:
                    above_threshold_since = now
                if (now - above_threshold_since).total_seconds() >= debounce_seconds:
                    active = True
                    above_threshold_since = None
            else:
                above_threshold_since = None
        else:
            if value < threshold - hysteresis:
                active = False
        return active, above_threshold_since, previous != active

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
            # Freeze the alarm flags too - a sensor fault must not silently
            # clear (or fabricate) a real high-temp/high-humidity alarm.
            self._latest = TemperatureHumidityReading(
                temperature_c=temperature_c,
                humidity_percent=humidity_percent,
                temp_alarm=self._temp_alarm_active,
                humidity_alarm=self._humidity_alarm_active,
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
