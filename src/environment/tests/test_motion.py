import time

from app.shared.models import SensorHealth
from environment.hardware.pir_driver import MockPIRDriver
from environment.motion import MotionMonitor


def _wait_until(predicate, timeout=2.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def test_motion_detected_immediately():
    driver = MockPIRDriver()
    monitor = MotionMonitor(driver=driver, poll_interval_seconds=0.02, debounce_seconds=0.15)
    monitor.start()
    try:
        assert _wait_until(lambda: monitor.get_health() == SensorHealth.OK)
        driver.trigger_motion(True)
        assert _wait_until(lambda: monitor.is_motion_detected() is True, timeout=0.5)
    finally:
        monitor.stop()


def test_clear_is_debounced_to_avoid_flicker():
    driver = MockPIRDriver()
    monitor = MotionMonitor(driver=driver, poll_interval_seconds=0.02, debounce_seconds=0.2)
    monitor.start()
    try:
        driver.trigger_motion(True)
        assert _wait_until(lambda: monitor.is_motion_detected() is True)

        driver.trigger_motion(False)
        time.sleep(0.05)
        assert monitor.is_motion_detected() is True, "should still be true inside debounce window"
        assert _wait_until(lambda: monitor.is_motion_detected() is False, timeout=1.0)
    finally:
        monitor.stop()


def test_fault_freezes_motion_state():
    driver = MockPIRDriver()
    monitor = MotionMonitor(
        driver=driver, poll_interval_seconds=0.02, debounce_seconds=0.1, max_consecutive_failures=3
    )
    monitor.start()
    try:
        assert _wait_until(lambda: monitor.get_health() == SensorHealth.OK)
        driver.force_failure(True)
        assert _wait_until(lambda: monitor.get_health() == SensorHealth.FAULT)
        assert monitor.is_motion_detected() is False
    finally:
        monitor.stop()
