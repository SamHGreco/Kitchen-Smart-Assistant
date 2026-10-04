"""
Raw-to-grams conversion for the scale subsystem.

Defines calibration parameters (zero offset, scale factor) for converting
raw HX711 readings to grams, and functions to apply or derive those
parameters from a known reference weight.
"""

from dataclasses import dataclass


@dataclass
class CalibrationParams:
    """Raw-to-grams conversion parameters for a single scale."""

    zero_offset: int = 0         # raw reading with no load
    scale_factor: float = 1.0    # raw units per gram


def apply_calibration(raw_reading: int, params: CalibrationParams) -> float:
    """Converts a raw HX711 reading to grams using the given calibration."""
    return (raw_reading - params.zero_offset) / params.scale_factor


def calibrate_from_known_weight(
        raw_zero: int, raw_with_known_weight: int, known_weight_grams: float
            ) -> CalibrationParams:
    """
    Derives calibration parameters from a raw zero reading and a raw
    reading taken with a known reference weight on the scale.
    """
    # TODO: validate against the physical load cell with a known reference
    # weight; confirm resulting readings are stable and repeatable before
    # relying on this calibration.
    raw_delta = raw_with_known_weight - raw_zero
    if raw_delta <= 0:
        raise ValueError("No change in raw reading or negative change; check wiring/placement")
    scale_factor = raw_delta / known_weight_grams
    return CalibrationParams(zero_offset=raw_zero, scale_factor=scale_factor)
