"""A fixed three-second scan window for each new, healthy PIR motion event.

No GPIO or UART access here. The UI supplies cached motion observations; only
Worker owns the serial port. A held-high PIR never extends a window. A permit
captures one generation, so a later event cannot extend an in-flight scan.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
import math
import threading
import time

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScanPermit:
    window: "MotionScanWindow"
    generation: int

    def remaining(self) -> float:
        return self.window.remaining(self.generation)

    def is_set(self) -> bool:
        """Event-like cancellation interface consumed by read_barcode()."""
        return self.remaining() <= 0


class MotionScanWindow:
    def __init__(self, duration_seconds=3.0, *, stale_seconds=1.5,
                 clock=time.monotonic):
        if (not math.isfinite(duration_seconds) or duration_seconds <= 0 or
                not math.isfinite(stale_seconds) or stale_seconds <= 0):
            raise ValueError('Motion window and stale timeout must be positive and finite.')
        self.duration_seconds = float(duration_seconds)
        self.stale_seconds = float(stale_seconds)
        self.clock = clock
        self._lock = threading.Lock()
        self._generation = 0
        self._deadline = 0.0
        self._scan_started=False
        self._last_observation = None
        self._healthy = False
        # At first startup a healthy HIGH may trigger. After a fault or stale
        # input, require a healthy LOW before any new HIGH can trigger.
        self._armed = True
        self._motion = None

    def observe(self, motion, *, healthy, allow_trigger=True) -> bool:
        """Return True only when this observation opens a NEW window.

        Windows are not queued while a form, manual pause, or detected weight
        blocks scanning. Temporary scale acquisitions may shorten a window;
        resuming them never extends its original deadline.
        """
        now = self.clock()
        opened = False
        with self._lock:
            if (self._last_observation is not None and
                    now - self._last_observation > self.stale_seconds):
                self._armed = False
                self._deadline = 0.0
            self._last_observation = now
            if not healthy or type(motion) is not bool:
                self._healthy = False
                self._armed = False
                self._motion = None
                self._deadline = 0.0
                self._scan_started=False
                self._generation += 1
                return False
            self._healthy = True
            self._motion = motion
            if not motion:
                self._armed = True
            elif self._armed:
                self._armed = False
                # Even a LOW/HIGH transition within an existing window does
                # not reset its timer or queue a second window.
                if allow_trigger and now >= self._deadline:
                    self._generation += 1
                    self._deadline = now + self.duration_seconds
                    self._scan_started=False
                    opened = True
            if not allow_trigger:
                self._deadline = 0.0
        if opened:
            LOG.info('Scanner motion window opened (%.1f s).', self.duration_seconds)
        return opened

    def _remaining_locked(self, now, generation=None):
        if (not self._healthy or self._last_observation is None or
                now - self._last_observation > self.stale_seconds or
                (generation is not None and generation != self._generation)):
            return 0.0
        return max(0.0, self._deadline - now)

    def remaining(self, generation=None) -> float:
        with self._lock:
            return self._remaining_locked(self.clock(), generation)

    def permit(self):
        with self._lock:
            now=self.clock()
            if self._remaining_locked(now) <= 0:
                return None
            if not self._scan_started:
                self._dealine=now+self.duration_seconds
                self._scan_started=True
            return ScanPermit(self, self._generation)

    def finish(self, permit=None):
        """Consume/cancel a window without manufacturing another motion edge."""
        with self._lock:
            if permit is None or permit.generation == self._generation:
                self._deadline = 0.0
                self._scan_started=False                
                self._generation += 1

    def status(self) -> str:
        with self._lock:
            now = self.clock()
            if (not self._healthy or self._last_observation is None or
                    now - self._last_observation > self.stale_seconds):
                return 'Scanner asleep: motion input unavailable.'
            if self._remaining_locked(now) > 0:
                return 'Scanner active: 3-second motion window.'
            if self._motion:
                return 'Scanner asleep: wait for motion to clear.'
            return 'Scanner asleep: waiting for new motion.'
