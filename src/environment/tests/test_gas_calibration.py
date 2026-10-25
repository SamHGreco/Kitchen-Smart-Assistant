from datetime import datetime, timezone

import pytest

from environment.gas_calibration import GasCalibration, load_calibration, save_calibration


def _make_calibration(voltage: float = 1.0, temp: float = 22.0, humidity: float = 45.0) -> GasCalibration:
    return GasCalibration(
        gas_baseline_voltage=voltage,
        temperature_baseline_c=temp,
        humidity_baseline_rh=humidity,
        calibration_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_save_then_load_roundtrip(tmp_path):
    path = tmp_path / "gas_calibration.json"
    calibration = _make_calibration()

    save_calibration(calibration, path)
    loaded = load_calibration(path)

    assert loaded == calibration


def test_load_missing_file_returns_none(tmp_path):
    path = tmp_path / "does_not_exist.json"
    assert load_calibration(path) is None


def test_load_corrupt_json_returns_none(tmp_path):
    path = tmp_path / "gas_calibration.json"
    path.write_text("{not valid json", encoding="utf-8")
    assert load_calibration(path) is None


def test_save_overwrites_previous(tmp_path):
    path = tmp_path / "gas_calibration.json"
    save_calibration(_make_calibration(voltage=1.0), path)
    save_calibration(_make_calibration(voltage=2.5), path)

    loaded = load_calibration(path)

    assert loaded.gas_baseline_voltage == 2.5


def test_save_creates_parent_directory(tmp_path):
    path = tmp_path / "nested" / "dir" / "gas_calibration.json"
    save_calibration(_make_calibration(), path)

    assert path.exists()
    assert load_calibration(path) is not None


def test_save_leaves_no_temp_file_behind(tmp_path):
    path = tmp_path / "gas_calibration.json"
    save_calibration(_make_calibration(), path)

    remaining = list(tmp_path.iterdir())
    assert remaining == [path]
