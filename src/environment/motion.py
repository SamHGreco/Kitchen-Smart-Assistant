"""PIR motion detection subsystem logic.

Wraps a `PIRDriver` (real or mock) and polls it on a background thread,
applying a hold-time debounce so brief dropouts between PIR pulses don't
cause the reported motion state to flicker. Motion is reported True
immediately on detection (no delay) so wake-on-motion stays responsive; only
the False transition is debounced. This is the only module other subsystem
code should use for motion detection - never the hardware driver directly.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

from app import config
from app.shared.exceptions import SensorReadError
from app.shared.models import SensorHealth
from environment.hardware.pir_driver import MockPIRDriver, PIRDriver, RealPIRDriver

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MotionReading:
    """Latest motion-sensor snapshot, safe to hand to other code."""

    motion_detected: bool
    health: SensorHealth
    timestamp: datetime


def _create_driver() -> PIRDriver:
    if config.HARDWARE_MODE:
        return RealPIRDriver(config.PIR_GPIO_PIN)
    return MockPIRDriver()


class MotionMonitor:
    """Polls the PIR sensor on a background thread and exposes a debounced
    motion state.

    Public API (safe for other subsystems/threads to call):
        start(), stop(), get_reading(), is_motion_detected(), get_health()
    """

    def __init__(
        self,
        driver: PIRDriver | None = None,
        poll_interval_seconds: float | None = None,
        debounce_seconds: float | None = None,
        max_consecutive_failures: int | None = None,
    ) -> None:
        self._driver = driver if driver is not None else _create_driver()
        self._poll_interval_seconds = (
            poll_interval_seconds
            if poll_interval_seconds is not None
            else config.PIR_POLL_INTERVAL_SECONDS
        )
        self._debounce_seconds = (
            debounce_seconds if debounce_seconds is not None else config.PIR_DEBOUNCE_SECONDS
        )
        self._max_consecutive_failures = (
            max_consecutive_failures
            if max_consecutive_failures is not None
            else config.PIR_MAX_CONSECUTIVE_FAILURES
        )

        self._lock = threading.Lock()
        self._latest = MotionReading(
            motion_detected=False, health=SensorHealth.FAULT, timestamp=datetime.now(timezone.utc)
        )
        self._consecutive_failures = 0
        self._motion_detected = False
        self._last_raw_true_time: datetime | None = None

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the background polling thread. Safe to call once; a no-op if already running."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="MotionMonitor", daemon=True)
        self._thread.start()
        logger.info("Motion monitor started (poll interval=%.2fs)", self._poll_interval_seconds)

    def stop(self) -> None:
        """Signal the polling thread to exit and release the driver. Blocks briefly."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self._poll_interval_seconds + 1.0)
            self._thread = None
        self._driver.close()
        logger.info("Motion monitor stopped")

    def get_reading(self) -> MotionReading:
        """Return the latest reading snapshot. Thread-safe."""
        with self._lock:
            return self._latest

    def is_motion_detected(self) -> bool:
        return self.get_reading().motion_detected

    def get_health(self) -> SensorHealth:
        return self.get_reading().health

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._poll_once()
            self._stop_event.wait(self._poll_interval_seconds)

    def _poll_once(self) -> None:
        try:
            raw_motion = self._driver.read()
        except SensorReadError as exc:
            self._handle_failure(exc)
            return
        self._handle_success(raw_motion)

    def _handle_success(self, raw_motion: bool) -> None:
        now = datetime.now(timezone.utc)
        with self._lock:
            was_fault = self._latest.health == SensorHealth.FAULT
            self._consecutive_failures = 0
            motion_changed = self._update_motion_state(raw_motion, now)
            self._latest = MotionReading(
                motion_detected=self._motion_detected, health=SensorHealth.OK, timestamp=now
            )
        if was_fault:
            logger.info("Motion sensor recovered")
        if motion_changed:
            if self._motion_detected:
                logger.info("Motion detected")
            else:
                logger.info("Motion cleared")

    def _update_motion_state(self, raw_motion: bool, now: datetime) -> bool:
        """Apply the clear-side debounce. Caller must hold `_lock`.

        Returns True if the debounced motion state changed.
        """
        previous = self._motion_detected
        if raw_motion:
            self._last_raw_true_time = now
            self._motion_detected = True
        elif self._motion_detected and self._last_raw_true_time is not None:
            elapsed = (now - self._last_raw_true_time).total_seconds()
            if elapsed >= self._debounce_seconds:
                self._motion_detected = False
        return previous != self._motion_detected

    def _handle_failure(self, exc: Exception) -> None:
        with self._lock:
            self._consecutive_failures += 1
            was_fault = self._latest.health == SensorHealth.FAULT
            new_health = (
                SensorHealth.FAULT
                if self._consecutive_failures >= self._max_consecutive_failures
                else SensorHealth.DEGRADED
            )
            # Freeze the motion flag while readings are unreliable rather than
            # fabricating a cleared (or detected) state.
            self._latest = MotionReading(
                motion_detected=self._motion_detected,
                health=new_health,
                timestamp=datetime.now(timezone.utc),
            )
        logger.warning(
            "PIR read failed (%d/%d consecutive): %s",
            self._consecutive_failures,
            self._max_consecutive_failures,
            exc,
        )
        if new_health == SensorHealth.FAULT and not was_fault:
            logger.error(
                "Motion sensor marked FAULT after %d consecutive failures", self._consecutive_failures
            )
