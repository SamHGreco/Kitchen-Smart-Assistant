import time

from app.shared.models import ActivityType, UIState
from power.sleep_manager import PowerManager


def _wait_until(predicate, timeout=2.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def test_starts_awake():
    power = PowerManager(inactivity_timeout_seconds=1.0, poll_interval_seconds=0.02)
    assert power.is_display_awake() is True


def test_sleeps_after_inactivity_timeout_on_home_screen():
    power = PowerManager(inactivity_timeout_seconds=0.2, poll_interval_seconds=0.02)
    power.set_ui_state(UIState.HOME)
    power.start()
    try:
        assert _wait_until(lambda: power.is_display_awake() is False)
    finally:
        power.stop()


def test_transaction_active_blocks_sleep():
    power = PowerManager(inactivity_timeout_seconds=0.2, poll_interval_seconds=0.02)
    power.set_ui_state(UIState.HOME)
    power.set_transaction_active(True)
    power.start()
    try:
        time.sleep(0.4)
        assert power.is_display_awake() is True
    finally:
        power.stop()


def test_non_home_screen_blocks_sleep():
    power = PowerManager(inactivity_timeout_seconds=0.2, poll_interval_seconds=0.02)
    power.set_ui_state(UIState.OTHER)
    power.start()
    try:
        time.sleep(0.4)
        assert power.is_display_awake() is True
    finally:
        power.stop()


def test_activity_resets_timer_and_wakes_display():
    power = PowerManager(inactivity_timeout_seconds=0.2, poll_interval_seconds=0.02)
    power.set_ui_state(UIState.HOME)
    power.start()
    try:
        assert _wait_until(lambda: power.is_display_awake() is False)
        power.notify_activity(ActivityType.WEIGHT)
        assert power.is_display_awake() is True
    finally:
        power.stop()


def test_safety_alarm_forces_awake_and_blocks_sleep():
    power = PowerManager(inactivity_timeout_seconds=0.2, poll_interval_seconds=0.02)
    power.set_ui_state(UIState.HOME)
    power.set_safety_alarm_active(True)
    power.start()
    try:
        time.sleep(0.4)
        assert power.is_display_awake() is True
    finally:
        power.stop()
