"""Persisted MQ-4 gas-sensor calibration baseline.

A calibration records the gas-sensor voltage, temperature, and humidity at
the moment the user presses "Calibrate" (see
EnvironmentManager.calibrate_gas_sensor()). Stored as a small JSON file so
the baseline survives application restarts - this is not a second database,
just one small config-style file, consistent with "Do not create a second
database solely for gas calibration."

Writes are atomic (write to a temp file in the same directory, then os.replace)
so an interrupted write cannot corrupt the previously saved calibration.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GasCalibration:
    """A single saved gas-sensor calibration baseline."""

    gas_baseline_voltage: float
    temperature_baseline_c: float
    humidity_baseline_rh: float
    calibration_timestamp: datetime

    def to_json_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["calibration_timestamp"] = self.calibration_timestamp.isoformat()
        return data

    @classmethod
    def from_json_dict(cls, data: dict[str, Any]) -> "GasCalibration":
        return cls(
            gas_baseline_voltage=float(data["gas_baseline_voltage"]),
            temperature_baseline_c=float(data["temperature_baseline_c"]),
            humidity_baseline_rh=float(data["humidity_baseline_rh"]),
            calibration_timestamp=datetime.fromisoformat(data["calibration_timestamp"]),
        )


def load_calibration(path: Path) -> GasCalibration | None:
    """Load a saved calibration from `path`. Returns None if missing/unreadable/invalid."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.warning("Could not read gas calibration file %s: %s", path, exc)
        return None
    try:
        return GasCalibration.from_json_dict(json.loads(raw))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        logger.warning("Gas calibration file %s is invalid, ignoring: %s", path, exc)
        return None


def save_calibration(calibration: GasCalibration, path: Path) -> None:
    """Atomically write `calibration` to `path`, creating parent directories as needed.

    Writes to a temp file in the same directory first, then replaces the
    target file in a single filesystem operation, so a crash or power loss
    mid-write cannot leave a half-written/corrupt calibration file behind.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path_str = tempfile.mkstemp(dir=str(path.parent), prefix=".gas_calibration_", suffix=".tmp")
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
            json.dump(calibration.to_json_dict(), tmp_file, indent=2)
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
