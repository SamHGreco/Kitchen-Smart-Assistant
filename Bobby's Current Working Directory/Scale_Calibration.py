#This is a stand in

"""Scale calibration math; raw counts are never treated as grams."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import math
from statistics import median


def finite_number(value, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f'{name} must be a number.')
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{name} must be a number.') from exc
    if not math.isfinite(number):
        raise ValueError(f'{name} must be finite.')
    return number


def checked_samples(values, minimum: int = 5) -> list[int]:
    samples = list(values)
    if len(samples) < minimum:
        raise ValueError(f'Need at least {minimum} raw scale samples.')
    if any(type(value) is not int or not -8388607 < value < 8388607 for value in samples):
        raise ValueError('Invalid or saturated HX711 samples. Check wiring and load.')
    return samples


@dataclass(frozen=True)
class Calibration:
    zero_offset: float
    counts_per_gram: float
    known_mass_g: float
    calibrated_at: str

    @classmethod
    def from_dict(cls, values: dict) -> 'Calibration':
        zero = finite_number(values['zero_offset'], 'Zero offset')
        factor = finite_number(values['counts_per_gram'], 'Counts per gram')
        mass = finite_number(values['known_mass_g'], 'Known mass')
        if not -8388608 < zero < 8388607 or abs(factor) < 1e-9 or mass <= 0:
            raise ValueError('Invalid saved scale calibration. Keep the file and recalibrate.')
        return cls(zero, factor, mass, str(values['calibrated_at']))

    def as_dict(self) -> dict:
        return asdict(self)


def calculate(zero_samples, loaded_samples, known_mass_g, *,
              max_raw_spread=2000.0, stable_spread_g=5.0) -> Calibration:
    mass = finite_number(known_mass_g, 'Known mass in grams')
    if mass <= 0:
        raise ValueError('Known mass must be greater than zero.')
    zero = checked_samples(zero_samples)
    loaded = checked_samples(loaded_samples)
    noise = max(max(zero) - min(zero), max(loaded) - min(loaded))
    difference = median(loaded) - median(zero)
    if noise > max_raw_spread:
        raise ValueError('Scale is moving or noisy. Keep it still and repeat both steps.')
    if abs(difference) < max(100.0, noise * 10):
        raise ValueError('Known mass produced too little change. Check the load cell and wiring.')
    factor = difference / mass
    if noise / abs(factor) > stable_spread_g:
        raise ValueError('Calibration readings are not stable enough.')
    return Calibration(float(median(zero)), factor, mass,
                       datetime.now(timezone.utc).isoformat())


class DemoCalibration:
    """A visibly simulated calibration workflow; nothing is persisted."""
    def __init__(self):
        self.zero = None

    def capture_zero(self):
        self.zero = [100000] * 9
        return 'DEMO empty-platform reference captured.'

    def calibrate(self, known_mass_g):
        if self.zero is None:
            raise ValueError('Capture the empty-platform reference first.')
        mass = finite_number(known_mass_g, 'Known mass')
        result = calculate(self.zero, [int(100000 + mass * 400)] * 9, mass)
        self.zero = None
        return result.as_dict()
