"""Adapt the existing calibrated UI scale service to the scanner interlock."""
from __future__ import annotations
import time
import logging
from Scale_Interface import ScaleService, ScalePollDeferred
from scale.hx711_driver import HX711Driver, ClockTimingError
LOG = logging.getLogger(__name__)

class GuardedRawScale:
    def __init__(self, driver, gate):
        self.driver, self.gate = driver, gate

    @staticmethod
    def _validate_request(samples, timeout):
        if type(samples) is not int or not 5 <= samples <= 100 or timeout <= 0:
            raise ValueError('Invalid raw scale sample request.')

    def read_raw(self, samples=9, timeout=3.0):
        self._validate_request(samples, timeout)
        # Explicit weighing still requests STOP and waits for acknowledgement.
        with self.gate.weighing():
            return self._read_values(samples, timeout)

    def read_raw_background(self, samples=9, timeout=3.0):
        self._validate_request(samples, timeout)
        with self.gate.background_weighing() as allowed:
            if not allowed:
                raise ScalePollDeferred(
                    'Waiting for the scanner window to finish.'
                )
            return self._read_values(samples, timeout)

    def _read_values(self, samples, timeout):
        deadline = time.monotonic() + timeout
        values = []
        #rety_used=False
        #discard_next=True

        #while len(values)<samples:
         #   remaining=deadline-time.monotonic()
          #  if remaining <= 0:
          #      raise TimeoutError('Scale sample group timed out.')
          #  try:
          #      value=self.driver.raw_read(retries=1,timeout_seconds=remaining)
          #  except ClockTimingError:
          #      if retry_used or time.monotonic() >=deadline:
          #          raise
          #      retry_used=True
          #      values.clear()
          #      discard_next=True
          #      LOG.warning('HX711 timing overrun, retrying sample once')
          #      continue
          #  if time.monotonic() >= deadline:
          #      raise TimeoutError('Scale sample timed out')
          #  if discard_next:
          #      discard_next=False
          #  else:
          #      values.append(value)
       # if retry_used:
       #     LOG.info('HX711 recovered')
       # return values

        # Discard the first conversion; it may predate the scanner stopping.
        for index in range(samples + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Scale sample group timed out.')

            value = self.driver.raw_read(
                retries=1,
                timeout_seconds=remaining
            )
            if index:
                values.append(value)

        return values

    def close(self):
        self.driver.close()


class CoordinatedScale(ScaleService):
    def __init__(self, *args, gate, **kwargs):
        self.gate = gate
        super().__init__(*args, **kwargs)

    def read(self):
        return self._read_and_observe(super().read)
    def read_background(self):
        return self._read_and_observe(super().read_background)
    def _read_and_observe(self,read):
        with self.lock:
            try:
                reading = read()
                self.gate.observe_weight(reading.grams, reading.stable)
                return reading
            except ScalePollDeferred:
                raise
            except Exception:
                self.gate.weight_fault()
                raise

    def tare(self):
        super().tare()
        # Wait for fresh stable empty readings, rather than rearming instantly.
        self.gate.weight_fault()


def build_scale(settings, gate):
    options = settings['scale']
    pins = settings['gpio']
    capacity = options.get('capacity_g')
    if capacity is None:
        raise ValueError('Set scale.capacity_g to the actual load-cell rating in config.pi.json.')
    path = settings['_config_file'].parent / options.get('calibration_file', 'scale_calibration.json')
    driver = GuardedRawScale(HX711Driver(pins['scale_data'], pins['scale_clock']), gate)
    try:
        return CoordinatedScale(
            driver, path, gate=gate, capacity_g=capacity,
            stable_spread_g=options.get('stable_spread_g', 5.0),
            activity_delta_g=options.get('activity_delta_g', 10.0),
            max_raw_spread=options.get('max_raw_spread', 2000.0),
            poll_interval_seconds=options.get('poll_interval_seconds', 2.0),
        )
    except BaseException:
        driver.close()
        raise
