"""One serial owner, acknowledged scanner stop, and exclusive weighing windows.

A Python Event alone cannot stop the physical scanner. The worker owns all UART
commands; the scale requests cancellation, then waits for that worker to finish
scan_once() (which acknowledges STOP) and release the shared lock.
"""
from __future__ import annotations

from contextlib import contextmanager
import logging
import math
import threading
import time

LOG = logging.getLogger(__name__)


class AnyEvent:
    """Event-like cancellation token; no extra polling thread is required."""
    def __init__(self, *events):
        self.events = tuple(event for event in events if event is not None)

    def is_set(self) -> bool:
        return any(event.is_set() for event in self.events)


class ScannerScaleGate:
    def __init__(self, *, serial_enabled=False, auto_pause=True,
                 pause_above_g=20.0, resume_below_g=5.0, empty_seconds=1.0,
                 stop_timeout=3.0, settle_seconds=0.2):
        values = (pause_above_g, resume_below_g, empty_seconds,
                  stop_timeout, settle_seconds)
        if any(not math.isfinite(float(v)) for v in values):
            raise ValueError('Scanner/scale limits must be finite.')
        if not 0 <= resume_below_g < pause_above_g or empty_seconds < 0:
            raise ValueError('Need 0 <= resume_below_g < pause_above_g.')
        if stop_timeout <= 0 or settle_seconds < 0:
            raise ValueError('Invalid scanner stop/settle timeout.')
        self.pause_requested = threading.Event()
        self.weight_present = threading.Event()
        self.uart_lock = threading.Lock()
        self.scale_lock = threading.Lock()
        self.state_lock = threading.Lock()
        self.quiet_confirmed = not serial_enabled
        self.auto_pause = bool(auto_pause)
        self.pause_above_g = float(pause_above_g)
        self.resume_below_g = float(resume_below_g)
        self.empty_seconds = float(empty_seconds)
        self.stop_timeout = float(stop_timeout)
        self.settle_seconds = float(settle_seconds)
        self.empty_since = None
        self._background_scan_window=None
        # With automatic detection enabled, require a valid empty-platform
        # reading before the first scan. Calibration is still available.
        if self.auto_pause:
            self.weight_present.set()

    def blocked(self) -> bool:
        return self.pause_requested.is_set() or self.weight_present.is_set()
    def set_background_scan_window(self,window):
        with self.state_lock:
            self._background_scan_window=window
    def _defer_background(self):
        with self.state_lock:
            window=self._background_scan_window
        return window is not None and window.remaining()>0
    @contextmanager
    def background_weighing(self):
        scale_acquired=self.scale_lock.acquire(blocking=False)
        uart_acquired=False
        try:
            if not scale_acquired or self._defer_background():
                yield False
                return
            uart_acquired=self.uart_lock.acquire(blocking=False)
            if not uart_acquired or self._defer_background():
                yield False
                return
            if not self.quiet_confirmed:
                raise RuntimeError(
                    'Scanner stop is unconfirmed.'
                    'Fix UART/restart, scale was not read'
                )
            time.sleep(self.settle_seconds)
            yield True
        finally:
            if uart_acquired:
                self.uart_lock.release()
            if scale_acquired:
                self.scale_lock.release()


    @contextmanager
    def scanner_setup(self):
        """Used only by the UART-owning worker during open/verify/stop."""
        with self.uart_lock:
            self.quiet_confirmed = False
            yield

    @contextmanager
    def scan_session(self):
        """Hold the lock through START, reading, and the acknowledged STOP."""
        acquired = self.uart_lock.acquire(blocking=False)
        try:
            yield bool(acquired and not self.blocked())
        finally:
            if acquired:
                self.uart_lock.release()

    @contextmanager
    def weighing(self):
        # Serialize both callers so one cannot clear another caller's request.
        with self.scale_lock:
            #LOG.warning("SCALE REQUESTED SCANNER PAUSE",stack_info=True)
            LOG.info("Scale reading requested; ensuring scanner is stopped")
            self.pause_requested.set()
            acquired = False
            try:
                acquired = self.uart_lock.acquire(timeout=self.stop_timeout)
                if not acquired:
                    raise TimeoutError('Scanner did not finish stopping; scale was not read.')
                if not self.quiet_confirmed:
                    raise RuntimeError('Scanner stop is unconfirmed. Fix UART/restart; scale was not read.')
                time.sleep(self.settle_seconds)
                yield
            finally:
                self.pause_requested.clear()
                if acquired:
                    self.uart_lock.release()

    def observe_weight(self, grams: float, stable: bool, *, now=None):
        if not self.auto_pause:
            return
        if not math.isfinite(grams):
            self.weight_fault()
            return
        now = time.monotonic() if now is None else now
        with self.state_lock:
            if abs(grams) >= self.pause_above_g:
                if not self.weight_present.is_set():
                    LOG.info('Scanner paused: weight detected (%.1f g).', grams)
                self.weight_present.set()
                self.empty_since = None
            elif stable and abs(grams) <= self.resume_below_g:
                if self.empty_since is None:
                    self.empty_since = now
                if now - self.empty_since >= self.empty_seconds:
                    if self.weight_present.is_set():
                        LOG.info('Platform empty: scanner may resume when the UI is ready.')
                    self.weight_present.clear()
            else:
                # Hysteresis: retain the current state between the thresholds.
                self.empty_since = None

    def weight_fault(self):
        if self.auto_pause:
            with self.state_lock:
                self.weight_present.set()
                self.empty_since = None
