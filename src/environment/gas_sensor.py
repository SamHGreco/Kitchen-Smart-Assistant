"""Natural-gas monitoring subsystem logic (MQ-4 via ADS1115).

Wraps an `ADS1115Driver` (real or mock), polls it on a background thread,
applies noise filtering, and runs threshold + hysteresis + debounce logic to
produce a stable, chatter-free gas alarm flag. gas_raw/gas_voltage are RAW
ADC/voltage values only - this subsystem does not claim a calibrated ppm
reading. This is the only module other subsystem code should use for gas
monitoring - never the hardware driver directly.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone

from app import config
from app.shared.exceptions import SensorReadError
from app.shared.models import SensorHealth
from environment.hardware.ads1115_driver import (
    ADS1115Driver,
    MockADS1115Driver,
    RealADS1115Driver,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GasReading:
    """Latest gas-sensor snapshot, safe to hand to other code."""

    gas_raw: int | None
    gas_voltage: float | None
    gas_alarm: bool
    health: SensorHealth
    timestamp: datetime


def _create_driver() -> ADS1115Driver:
    if config.HARDWARE_MODE:
        return RealADS1115Driver(
            config.ADS1115_I2C_ADDRESS,
            config.ADS1115_GAIN,
            config.ADS1115_ALERT_READY_GPIO_PIN,
        )
    return MockADS1115Driver()


class GasMonitor:
    """Polls the MQ-4/ADS1115 on a background thread and exposes a debounced,
    hysteresis-protected alarm state.

    Public API (safe for other subsystems/threads to call):
        start(), stop(), get_reading(), get_gas_voltage(), get_gas_raw(),
        is_gas_alarm_active(), get_health()
    """

    def __init__(
        self,
        driver: ADS1115Driver | None = None,
        channel: int | None = None,
        poll_interval_seconds: float | None = None,
        max_consecutive_failures: int | None = None,
        alarm_threshold_voltage: float | None = None,
        alarm_hysteresis_voltage: float | None = None,
        alarm_debounce_seconds: float | None = None,
        filter_window: int | None = None,
    ) -> None:
        self._driver = driver if driver is not None else _create_driver()
        self._channel = channel if channel is not None else config.ADS1115_GAS_CHANNEL
        self._poll_interval_seconds = (
            poll_interval_seconds
            if poll_interval_seconds is not None
            else config.GAS_POLL_INTERVAL_SECONDS
        )
        self._max_consecutive_failures = (
            max_consecutive_failures
            if max_consecutive_failures is not None
            else config.GAS_MAX_CONSECUTIVE_FAILURES
        )
        self._alarm_threshold_voltage = (
            alarm_threshold_voltage
            if alarm_threshold_voltage is not None
            else config.GAS_ALARM_VOLTAGE_THRESHOLD
        )
        self._alarm_hysteresis_voltage = (
            alarm_hysteresis_voltage
            if alarm_hysteresis_voltage is not None
            else config.GAS_ALARM_HYSTERESIS_VOLTAGE
        )
        self._alarm_debounce_seconds = (
            alarm_debounce_seconds
            if alarm_debounce_seconds is not None
            else config.GAS_ALARM_DEBOUNCE_SECONDS
        )
        filter_window = filter_window if filter_window is not None else config.GAS_SAMPLE_FILTER_WINDOW
        self._samples: "deque[float]" = deque(maxlen=max(1, filter_window))

        self._lock = threading.Lock()
        self._latest = GasReading(
            gas_raw=None,
            gas_voltage=None,
            gas_alarm=False,
            health=SensorHealth.FAULT,
            timestamp=datetime.now(timezone.utc),
        )
        self._consecutive_failures = 0
        self._alarm_active = False
        self._above_threshold_since: datetime | None = None

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the background polling thread. Safe to call once; a no-op if already running."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="GasMonitor", daemon=True)
        self._thread.start()
        logger.info("Gas monitor started (poll interval=%.1fs)", self._poll_interval_seconds)

    def stop(self) -> None:
        """Signal the polling thread to exit and release the driver. Blocks briefly."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self._poll_interval_seconds + 1.0)
            self._thread = None
        self._driver.close()
        logger.info("Gas monitor stopped")

    def get_reading(self) -> GasReading:
        """Return the latest reading snapshot. Thread-safe."""
        with self._lock:
            return self._latest

    def get_gas_voltage(self) -> float | None:
        return self.get_reading().gas_voltage

    def get_gas_raw(self) -> int | None:
        return self.get_reading().gas_raw

    def is_gas_alarm_active(self) -> bool:
        return self.get_reading().gas_alarm

    def get_health(self) -> SensorHealth:
        return self.get_reading().health

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._poll_once()
            self._stop_event.wait(self._poll_interval_seconds)

    def _poll_once(self) -> None:
        try:
            voltage = self._driver.read_voltage(self._channel)
            raw = self._driver.read_raw(self._channel)
        except SensorReadError as exc:
            self._handle_failure(exc)
            return
        self._handle_success(voltage, raw)

    def _handle_success(self, voltage: float, raw: int) -> None:
        now = datetime.now(timezone.utc)
        with self._lock:
            was_fault = self._latest.health == SensorHealth.FAULT
            self._consecutive_failures = 0
            self._samples.append(voltage)
            filtered_voltage = sum(self._samples) / len(self._samples)

            alarm_changed = self._update_alarm_state(filtered_voltage, now)

            self._latest = GasReading(
                gas_raw=raw,
                gas_voltage=filtered_voltage,
                gas_alarm=self._alarm_active,
                health=SensorHealth.OK,
                timestamp=now,
            )
        logger.debug("Gas reading: raw=%s filtered_voltage=%.3fV", raw, filtered_voltage)
        if was_fault:
            logger.info("Gas sensor recovered")
        if alarm_changed:
            if self._alarm_active:
                logger.warning(
                    "GAS ALARM STARTED (voltage=%.3fV >= threshold=%.3fV)",
                    filtered_voltage,
                    self._alarm_threshold_voltage,
                )
            else:
                logger.info("GAS ALARM CLEARED (voltage=%.3fV)", filtered_voltage)

    def _update_alarm_state(self, filtered_voltage: float, now: datetime) -> bool:
        """Apply threshold + hysteresis + debounce. Caller must hold `_lock`.

        Returns True if the alarm state changed.
        """
        previous = self._alarm_active
        if not self._alarm_active:
            if filtered_voltage >= self._alarm_threshold_voltage:
                if self._above_threshold_since is None:
                    self._above_threshold_since = now
                elapsed = (now - self._above_threshold_since).total_seconds()
                if elapsed >= self._alarm_debounce_seconds:
                    self._alarm_active = True
                    self._above_threshold_since = None
            else:
                self._above_threshold_since = None
        else:
            clear_threshold = self._alarm_threshold_voltage - self._alarm_hysteresis_voltage
            if filtered_voltage < clear_threshold:
                self._alarm_active = False
        return previous != self._alarm_active

    def _handle_failure(self, exc: Exception) -> None:
        with self._lock:
            self._consecutive_failures += 1
            was_fault = self._latest.health == SensorHealth.FAULT
            if self._consecutive_failures >= self._max_consecutive_failures:
                new_health = SensorHealth.FAULT
                gas_raw = None
                gas_voltage = None
            else:
                new_health = SensorHealth.DEGRADED
                gas_raw = self._latest.gas_raw
                gas_voltage = self._latest.gas_voltage
            # Freeze the alarm flag while readings are unreliable - never
            # clear a real alarm just because the sensor started faulting.
            self._latest = GasReading(
                gas_raw=gas_raw,
                gas_voltage=gas_voltage,
                gas_alarm=self._alarm_active,
                health=new_health,
                timestamp=datetime.now(timezone.utc),
            )
        logger.warning(
            "Gas sensor read failed (%d/%d consecutive): %s",
            self._consecutive_failures,
            self._max_consecutive_failures,
            exc,
        )
        if new_health == SensorHealth.FAULT and not was_fault:
            logger.error(
                "Gas sensor marked FAULT after %d consecutive failures", self._consecutive_failures
            )
