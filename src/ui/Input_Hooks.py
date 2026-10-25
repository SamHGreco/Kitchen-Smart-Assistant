"""This might work, but will have to test when integrating"""
from __future__ import annotations
from dataclasses import replace
from datetime import datetime, timezone
from threading import RLock
import math
import time
from Scale_Interface import ScaleReading
from Sensor_Interfaces import PlaceholderSensors, SensorSnapshot, TeamSensors


class InputBridge(PlaceholderSensors):
    def __init__(self, *, max_age_seconds=5):
        self.lock = RLock()
        self.max_age = float(max_age_seconds)
        if not math.isfinite(self.max_age) or self.max_age <= 0:
            raise ValueError('max_age_seconds must be positive value.')
        self.environment = None
        self.motion = None
        self.scale = None
        self.weight_until = 0.0
        self.adapter = TeamSensors(self, None, None, None, max_age_seconds=self.max_age)

    def publish_environment(self, status):
        """EnvironmentStatus, including sample timestamp."""
        stamp = getattr(status, 'timestamp', None)
        self._check_stamp(stamp)
        with self.lock:
            self.environment = status

    def publish_motion(self, detected: bool, timestamp: datetime):
        if type(detected) is not bool:
            raise ValueError('Motion must be True or False.')
        self._check_stamp(timestamp)
        with self.lock:
            self.motion = detected, timestamp

    def publish_scale(self, reading: ScaleReading, *, activity=False):
        if not isinstance(reading, ScaleReading) or reading.unit != 'g':
            raise ValueError('Publish ScaleReading in grams (if this is how we want to).')
        if (type(reading.grams) not in (int, float) or type(reading.sampled_at) not in (int, float)
                or type(reading.stable) is not bool or type(activity) is not bool
                or not math.isfinite(reading.grams) or not math.isfinite(reading.sampled_at)):
            raise ValueError('Scale reading and timestamp must be finite value.')
        with self.lock:
            self.scale = reading
            if activity:
                self.weight_until = time.monotonic() + 2

    @staticmethod
    def _check_stamp(stamp):
        if not isinstance(stamp, datetime) or stamp.tzinfo is None:
            raise ValueError('Use a timezone based sensor sample timestamp (seems simple, not married to this).')

    def get_status(self):
        with self.lock:
            return self.environment

    def read_scale(self):
        with self.lock:
            if self.scale is None:
                raise ValueError('No scale reading published.')
            return self.scale

    def snapshot(self):
        with self.lock:
            result = self.adapter.snapshot() if self.environment is not None else SensorSnapshot()
            fault = result.sensor_fault
            notes = [result.note]
            if self.motion is not None:
                detected, stamp = self.motion
                fresh = -1 <= (datetime.now(timezone.utc) - stamp).total_seconds() <= self.max_age
                fault |= not fresh
                result = replace(result, motion_detected=detected if fresh else None)
                if not fresh:
                    notes.append('Motion stale')
            if self.scale is not None:
                fresh = -1 <= time.time() - self.scale.sampled_at <= self.max_age
                fault |= not fresh
                result = replace(result, weight_g=self.scale.grams if fresh else None,
                                 weight_detected=fresh and time.monotonic() < self.weight_until)
                if not fresh:
                    notes.append('Scale stale')
            return replace(result, sensor_fault=fault, note=' / '.join(notes))
