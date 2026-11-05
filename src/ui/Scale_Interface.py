#Stand in for now
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from threading import Event, RLock, Thread
import time
from typing import Callable, Protocol
from Calibration_Storage import read_json, write_json
from Scale_Calibration import Calibration, calculate, checked_samples, finite_number

class ScalePollDeferred(RuntimeError):
    """A routine sample is postponed for scanning, not a sensor failure"""
@dataclass(frozen=True)
class ScaleReading:
    grams: float
    stable: bool
    sampled_at: float
    unit: str = 'g'


class RawScale(Protocol):
    def read_raw(self, samples: int = 9, timeout: float = 3.0) -> list[int]: ...
    def close(self) -> None: ...


class ScaleService:
    def __init__(self, driver: RawScale, calibration_path: str | Path, *,
                 capacity_g: float, stable_spread_g: float = 5.0,
                 activity_delta_g: float = 10.0, max_raw_spread: float = 2000.0,
                 notify_weight: Callable[[], None] | None = None,
                 poll_interval_seconds: float = 2.0):
        self.poll_interval = finite_number(poll_interval_seconds, 'Scale poll interval')
        if self.poll_interval < 0.5:
            raise ValueError('Scale poll interval must be at least 0.5 seconds.')
        self.driver = driver
        self.path = Path(calibration_path)
        self.capacity = finite_number(capacity_g, 'Scale capacity')
        self.stable_spread = finite_number(stable_spread_g, 'Stable spread')
        self.activity_delta = finite_number(activity_delta_g, 'Activity change')
        self.max_raw_spread = finite_number(max_raw_spread, 'Maximum raw spread')
        if min(self.capacity, self.stable_spread, self.activity_delta, self.max_raw_spread) <= 0:
            raise ValueError('Scale limits must be positive.')
        saved = read_json(self.path)
        self.calibration = Calibration.from_dict(saved) if saved else None
        self.offset = self.calibration.zero_offset if self.calibration else 0.0
        self.notify_weight = notify_weight
        self.lock = RLock()
        self.cache_lock = RLock()
        self.stopping = Event()
        self.thread = None
        self.pending_zero = None
        self.pending_at = 0.0
        self.last_weight = None
        self.activity_until = 0.0
        self.cached = self._unavailable('Scale not sampled yet.')
        self._deferred_since=None
        self._deferred_until=0.0

    @staticmethod
    def _unavailable(note: str) -> dict:
        return dict(grams=None, detected=False, stable=False, fault=True,
                    timestamp=datetime.now(timezone.utc), note=note)

    #def _samples(self) -> list[int]:
    #    return checked_samples(self.driver.read_raw(samples=9, timeout=3.0))
    def _samples(self, *, background=False) -> list[int]:
        if background:
            values=self.driver.read_raw_background(
                samples=9, timeout=3.0)
        else:
            values=self.driver.read_raw(samples=9,timeout=3.0)        
        #reader=(
         #   getattr(self.driver,'read_raw_background',self.driver.read_raw)
          #  if background else self.driver.read_raw
        #)
        return checked_samples(values)

    def read(self) -> ScaleReading:
        return self._read_measurement (background=False)
        #with self.lock:
         #   if self.calibration is None:
          #      raise ValueError('Scale needs calibration: Settings > Calibrate scale.')
           # values = self._samples()
            #factor = self.calibration.counts_per_gram
            #grams = (median(values) - self.offset) / factor
            #if abs(grams) > self.capacity:
            #    raise ValueError('Reading exceeds configured scale capacity. Remove the load.')
            #stable = (max(values) - min(values)) / abs(factor) <= self.stable_spread
            #return ScaleReading(float(grams), stable, time.time())
    def read_background(self)->ScaleReading:
        """Routine presence polling can defer, user-requested reads can't"""
        return self._read_measurement(background=True)
    def _read_measurement(self, *, background=False)->ScaleReading:
        with self.lock:
            if self.calibration is None:
                raise ValueError(
                    'Scale needs calibration: Settings > Calibrate > Calibrate Scale.'
                )
            values = self._samples(background=background)
            factor=self.calibration.counts_per_gram
            grams=(median(values)-self.offset)/factor

            if abs(grams)>self.capacity:
                raise ValueError(
                    'Reading exceeds maximum scale capacity, remove item.'
                )
            stable=(
                (max(values)-min(values))/abs(factor)
                <=self.stable_spread
            )
            return ScaleReading(float(grams),stable,time.time())
    def capture_zero(self) -> str:
        with self.lock:
            values = self._samples()
            if max(values) - min(values) > self.max_raw_spread:
                raise ValueError('Empty platform is not stable. Wait and try again.')
            self.pending_zero = values
            self.pending_at = time.monotonic()
            return 'Empty-platform reference captured. Place the known mass, then save.'

    def calibrate(self, known_mass_g) -> dict:
        mass = finite_number(known_mass_g, 'Known mass')
        if not 0 < mass <= self.capacity:
            raise ValueError('Known mass must be positive and within configured capacity.')
        with self.lock:
            if self.pending_zero is None or time.monotonic() - self.pending_at > 300:
                raise ValueError('Capture the empty-platform reference first (valid for 5 minutes).')
            calibration = calculate(self.pending_zero, self._samples(), mass,
                                    max_raw_spread=self.max_raw_spread,
                                    stable_spread_g=self.stable_spread)
            write_json(self.path, calibration.as_dict())
            self.calibration = calibration
            self.offset = calibration.zero_offset
            self.pending_zero = None
            self.last_weight = None
            self._clear_cache('Calibration saved. Waiting for the next reading.')
            return calibration.as_dict()

    def tare(self) -> None:
        with self.lock:
            if self.calibration is None:
                raise ValueError('Calibrate the scale before taring it.')
            values = self._samples()
            if (max(values) - min(values)) / abs(self.calibration.counts_per_gram) > self.stable_spread:
                raise ValueError('Load is moving. Tare was not changed.')
            self.offset = float(median(values))
            self.last_weight = None
            self.activity_until = 0
            self._clear_cache('Tare complete. Waiting for the next reading.')

    def _clear_cache(self, note):
        with self.cache_lock:
            self.cached = self._unavailable(note)
            self._deferred_since=None
            self._deferred_until=0.0

    def snapshot(self) -> dict:
        with self.cache_lock:
            snapshot = self.cached.copy()
        snapshot['detected'] = time.monotonic() < self.activity_until
        return snapshot
    def background_read_deferred(self)->bool:
        with self.cache_lock:
            since = self._deferred_since
            until = self._deferred_until
            fault = self.cached.get('fault')
        now=time.monotonic()
        return(not fault and since is not None and 0 <=now-since <= 12.0 and now <= until)
    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stopping.clear()
        self.thread = Thread(target=self._run, name='scale-monitor', daemon=True)
        self.thread.start()

    def _run(self) -> None:
        while not self.stopping.is_set():
            try:
                with self.lock:
                    reading = self.read_background()
                    changed = (reading.stable and self.last_weight is not None and
                               abs(reading.grams - self.last_weight) >= self.activity_delta)
                    if reading.stable and (self.last_weight is None or changed):
                        self.last_weight = reading.grams
                    if changed:
                        self.activity_until = time.monotonic() + 2.0
                    with self.cache_lock:
                        self.cached = dict(grams=reading.grams, stable=reading.stable,
                                           fault=False, detected=changed,
                                           timestamp=datetime.fromtimestamp(reading.sampled_at, timezone.utc),
                                           note='Scale live')
                        self._deferred_since=None
                        self._deferred_until=0.0
                if changed and self.notify_weight:
                    self.notify_weight()
            except ScalePollDeferred:
                now=time.monotonic()
                with self.cache_lock:
                    if not self.cached.get('fault'):
                        if self._deferred_since is None:
                            self._deferred_since=now
                        self._deferred_until=now+max(3.0,self.poll_interval+2.0)
                self.stopping.wait(0.05)
                continue
            except Exception as exc:
                self._clear_cache(str(exc))
            self.stopping.wait(self.poll_interval)

    def stop(self) -> None:
        self.stopping.set()
        if self.thread:
            self.thread.join(timeout=7)
            if self.thread.is_alive():
                raise RuntimeError('Scale driver did not stop; hardware close was not attempted.')
        with self.lock:
            self.driver.close()
