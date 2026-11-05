"""Deterministic tests; never access physical GPIO, UART or sensor libraries."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import json

import pytest

from app.shared.models import ActivityType, UIState
from app.shared.motion_scan import MotionScanWindow
from app.shared.scanner_scale_gate import ScannerScaleGate
from power.sleep_manager import PowerManager
from power.wake_logic import should_request_sleep
from Sensor_Interfaces import TeamSensors, PlaceholderSensors
from UI_Environment import _EnvironmentScreens
from Wake_Events import WakeController
from Input_Validation import DEFAULT_PREFERENCES, read_preferences
from App_Worker import Worker
from product_id.barcode_reader import AtomicBarcodeReader, ScanCancelled, ScannerError


class Clock:
    now = 0.0

    def __call__(self):
        return self.now

    def step(self, seconds):
        self.now += seconds


def window_pair():
    clock = Clock()
    return MotionScanWindow(clock=clock), clock


def heartbeat(window, clock, seconds, motion=True):
    end = clock.now + seconds
    while clock.now < end:
        clock.step(min(0.25, end - clock.now))
        window.observe(motion, healthy=True)


def test_no_scan_without_motion():
    window, clock = window_pair()
    assert window.permit() is None
    window.observe(False, healthy=True)
    assert window.remaining() == 0
    assert window.permit() is None


def test_held_high_opens_only_one_three_second_window():
    window, clock = window_pair()
    assert window.observe(True, healthy=True)
    permit = window.permit()
    assert permit.remaining() == 3
    heartbeat(window, clock, 2.9)
    assert permit.remaining() == pytest.approx(0.1)
    heartbeat(window, clock, 0.1)
    assert permit.is_set()
    heartbeat(window, clock, 30)
    assert window.permit() is None
    assert 'clear' in window.status()


def test_clear_then_new_motion_rearms():
    window, clock = window_pair()
    window.observe(True, healthy=True)
    heartbeat(window, clock, 3.1)
    window.observe(False, healthy=True)
    assert window.observe(True, healthy=True)
    assert window.remaining() == pytest.approx(3)


def test_new_edges_inside_window_do_not_extend_or_queue():
    window, clock = window_pair()
    window.observe(True, healthy=True)
    heartbeat(window, clock, 1)
    window.observe(False, healthy=True)
    assert not window.observe(True, healthy=True)
    assert window.remaining() == 2
    heartbeat(window, clock, 3)
    assert window.remaining() == 0


def test_new_generation_cannot_extend_an_old_permit():
    window, clock = window_pair()
    window.observe(True, healthy=True)
    old = window.permit()
    heartbeat(window, clock, 3)
    window.observe(False, healthy=True)
    window.observe(True, healthy=True)
    assert old.is_set()
    assert window.permit().remaining() == 3
    window.finish(old)
    assert window.remaining() == pytest.approx(3)


def test_consumed_barcode_window_requires_new_edge():
    window, clock = window_pair()
    window.observe(True, healthy=True)
    window.finish(window.permit())
    assert not window.observe(True, healthy=True)
    assert window.remaining() == 0
    window.observe(False, healthy=True)
    assert window.observe(True, healthy=True)


@pytest.mark.parametrize('motion', [True, False, None, 1, 'True'])
def test_fault_never_triggers_scanning(motion):
    window, clock = window_pair()
    window.observe(True, healthy=True)
    window.observe(motion, healthy=False)
    assert window.remaining() == 0
    assert 'unavailable' in window.status()
    assert not window.observe(True, healthy=True)
    window.observe(False, healthy=True)
    assert window.observe(True, healthy=True)


def test_missing_motion_never_triggers():
    window, clock = window_pair()
    assert not window.observe(None, healthy=True)
    assert window.permit() is None


def test_stale_ui_observations_cancel_scan_and_require_clear():
    window, clock = window_pair()
    window.observe(True, healthy=True)
    permit = window.permit()
    clock.step(1.6)
    assert permit.is_set()
    assert 'unavailable' in window.status()
    assert not window.observe(True, healthy=True)
    window.observe(False, healthy=True)
    assert window.observe(True, healthy=True)


def test_motion_during_form_is_not_queued_for_later():
    window, clock = window_pair()
    assert not window.observe(True, healthy=True, allow_trigger=False)
    assert not window.observe(True, healthy=True, allow_trigger=True)
    assert window.remaining() == 0
    window.observe(False, healthy=True)
    assert window.observe(True, healthy=True)


def test_weight_interlock_prevents_window_opening():
    gate = ScannerScaleGate(auto_pause=True)
    worker = Worker({}, scanner_gate=gate)
    assert not worker.observe_motion(True, healthy=True)
    assert worker.motion_window.remaining() == 0
    gate.weight_present.clear()
    assert not worker.observe_motion(True, healthy=True)
    worker.observe_motion(False, healthy=True)
    assert worker.observe_motion(True, healthy=True)


def test_disabling_ui_cancels_window_without_retrigger():
    worker = Worker({})
    worker.observe_motion(True, healthy=True)
    worker.set_enabled(False)
    assert worker.motion_window.remaining() == 0
    worker.set_enabled(True)
    assert worker.motion_window.remaining() == 0
    assert not worker.observe_motion(True, healthy=True)


def test_worker_stop_cancels_window():
    worker = Worker({})
    worker.observe_motion(True, healthy=True)
    worker.stop()
    assert worker.motion_window.remaining() == 0
    assert worker.stopping.is_set()


class ReaderDouble:
    def __init__(self, clock, window, action='timeout'):
        self.clock, self.window, self.action = clock, window, action
        self.calls = []

    def scan_once(self, timeout, cancel):
        self.calls.append(timeout)
        if self.action == 'barcode':
            return '012345678905'
        if self.action == 'failure':
            raise ScannerError('STOP not acknowledged')
        if self.action == 'interruption':
            heartbeat(self.window, self.clock, 0.5)
            raise ScanCancelled('Scale interruption, STOP acknowledged')
        heartbeat(self.window, self.clock, timeout)
        return None


def make_worker(action):
    window, clock = window_pair()
    gate = ScannerScaleGate(serial_enabled=True, auto_pause=False, settle_seconds=0)
    worker = Worker({}, serial_enabled=True, scanner_gate=gate, motion_window=window)
    worker.reader = ReaderDouble(clock, window, action)
    return worker, clock


def test_worker_never_calls_reader_while_no_motion():
    worker, clock = make_worker('timeout')
    assert worker.scan_hardware_once() is None
    assert worker.reader.calls == []


def test_worker_uses_remaining_window_not_fresh_three_seconds():
    worker, clock = make_worker('timeout')
    worker.observe_motion(True, healthy=True)
    heartbeat(worker.motion_window, clock, 1.25)
    worker.scan_hardware_once()
    assert worker.reader.calls == [1.75]
    assert worker.scanner_gate.quiet_confirmed
    assert worker.scan_hardware_once() is None
    assert len(worker.reader.calls) == 1


def test_worker_scale_interruption_preserves_original_deadline():
    worker, clock = make_worker('interruption')
    worker.observe_motion(True, healthy=True)
    with pytest.raises(ScanCancelled):
        worker.scan_hardware_once()
    assert worker.scanner_gate.quiet_confirmed
    heartbeat(worker.motion_window, clock, 0.75)
    worker.reader.action = 'timeout'
    worker.scan_hardware_once()
    assert worker.reader.calls == [3.0, 1.75]


def test_barcode_consumes_window():
    worker, clock = make_worker('barcode')
    worker.observe_motion(True, healthy=True)
    assert worker.scan_hardware_once() == '012345678905'
    assert worker.motion_window.remaining() == 0
    assert worker.scan_hardware_once() is None
    assert len(worker.reader.calls) == 1


def test_failed_stop_does_not_mark_scanner_quiet():
    worker, clock = make_worker('failure')
    worker.observe_motion(True, healthy=True)
    with pytest.raises(ScannerError):
        worker.scan_hardware_once()
    assert not worker.scanner_gate.quiet_confirmed
    with pytest.raises(RuntimeError):
        with worker.scanner_gate.weighing():
            pytest.fail('Must not weigh without STOP acknowledgement')


def test_actual_reader_sends_stop_at_motion_deadline(monkeypatch):
    """Real reader/protocol parser with deterministic serial transport, no GPIO."""
    import product_id.barcode_reader as barcode
    window, clock = window_pair()
    monkeypatch.setattr(barcode.time, 'monotonic', clock)
    writes = []
    data = bytearray()

    class Serial:
        def write(self, value):
            writes.append((clock.now, value))
            if value == bytes.fromhex('32 75 02'):
                data.extend(bytes.fromhex('33 75 02 00 00'))
            return len(value)

        def read(self, size=1):
            if data:
                out = bytes(data[:size])
                del data[:size]
                return out
            clock.step(0.05)
            window.observe(True, healthy=True)
            return b''

        def flush(self):
            pass

        def reset_input_buffer(self):
            data.clear()

    gate = ScannerScaleGate(serial_enabled=True, auto_pause=False)
    worker = Worker({}, scanner_gate=gate, motion_window=window)
    worker.reader = AtomicBarcodeReader('fake', transport=Serial())
    window.observe(True, healthy=True)
    try:
        worker.scan_hardware_once()
    except ScanCancelled:
        pass
    assert [value for when, value in writes] == [
        bytes.fromhex('32 75 01'), bytes.fromhex('32 75 02')]
    assert 2.99 <= writes[1][0] <= 3.06
    assert gate.quiet_confirmed
    window.observe(True, healthy=True)
    worker.scan_hardware_once()
    assert len(writes) == 2  # no second START for held motion


def age(power, seconds):
    with power._lock:
        power._last_activity_time = datetime.now(timezone.utc) - timedelta(seconds=seconds)


def test_zero_never_sleeps_in_pure_logic():
    assert not should_request_sleep(UIState.HOME, False, False, 9999, 0)


def test_live_timeout_overrides_old_sixty_second_default():
    power = PowerManager(inactivity_timeout_seconds=60)
    power.set_inactivity_timeout(15)
    age(power, 16)
    power._evaluate_sleep()
    assert not power.is_display_awake()


def test_saving_longer_timeout_applies_without_restart():
    power = PowerManager(inactivity_timeout_seconds=5)
    power.set_inactivity_timeout(120)
    age(power, 70)
    power._evaluate_sleep()
    assert power.is_display_awake()


def test_zero_disables_active_manager_sleep():
    power = PowerManager(inactivity_timeout_seconds=60)
    power.set_inactivity_timeout(0)
    age(power, 10000)
    power._evaluate_sleep()
    assert power.is_display_awake()


@pytest.mark.parametrize('seconds', [-1, 3601, float('nan'), float('inf'), True])
def test_invalid_timeout_is_rejected(seconds):
    power = PowerManager()
    with pytest.raises(ValueError):
        power.set_inactivity_timeout(seconds)


def test_continuous_presence_holds_sleep_then_full_timer_after_clear():
    power = PowerManager(inactivity_timeout_seconds=10)
    power.set_sleep_inhibited(True)
    age(power, 999)
    power._evaluate_sleep()
    assert power.is_display_awake()
    power.set_sleep_inhibited(False)
    power._evaluate_sleep()
    assert power.is_display_awake()
    age(power, 11)
    power._evaluate_sleep()
    assert not power.is_display_awake()


def test_alarm_and_transaction_still_block_sleep_after_setting_change():
    power = PowerManager()
    power.set_inactivity_timeout(1)
    power.set_safety_alarm_active(True)
    age(power, 100)
    power._evaluate_sleep()
    assert power.is_display_awake()
    power.set_safety_alarm_active(False)
    power.set_transaction_active(True)
    power._evaluate_sleep()
    assert power.is_display_awake()


def adapter(power):
    return TeamSensors(None, power, ActivityType, UIState)


def screen(tmp_path, power=None):
    s = _EnvironmentScreens()
    s.preferences = dict(DEFAULT_PREFERENCES, gas_draft={'invalid': 'do not change me'})
    s.preferences_path = tmp_path/'prefs.json'
    s.demo = False
    s.sensors = adapter(power or PowerManager())
    s.wake_control = WakeController()
    return s


def test_save_changes_runtime_and_disk_without_touching_gas(tmp_path):
    power = PowerManager()
    s = screen(tmp_path, power)
    s.save_sleep_duration(45)
    assert power._inactivity_timeout_seconds == 45
    assert s.preferences['idle_seconds'] == 45
    loaded = read_preferences(s.preferences_path)
    assert loaded['idle_seconds'] == 45
    assert loaded['gas_draft'] == {'invalid': 'do not change me'}
    # Same adapter call used at GUI startup, with persisted preferences.
    restarted = PowerManager()
    adapter(restarted).set_sleep_timeout(loaded['idle_seconds'])
    assert restarted._inactivity_timeout_seconds == 45


def test_save_error_rolls_back_runtime_and_in_memory_preferences(tmp_path, monkeypatch):
    import UI_Environment
    power = PowerManager()
    s = screen(tmp_path, power)
    def fail(*_):
        raise OSError('Read-only disk')
    monkeypatch.setattr(UI_Environment, 'save_preferences', fail)
    with pytest.raises(OSError):
        s.save_sleep_duration(30)
    assert power._inactivity_timeout_seconds == 60
    assert s.preferences['idle_seconds'] == 60


@pytest.mark.parametrize('seconds', [-1, 3601, 3.5, True])
def test_ui_rejects_invalid_sleep_preference(tmp_path, seconds):
    s = screen(tmp_path)
    with pytest.raises(ValueError):
        s.save_sleep_duration(seconds)
    assert not s.preferences_path.exists()


def test_demo_settings_do_not_write_a_real_preference_file(tmp_path):
    s = screen(tmp_path)
    s.demo = True
    s.sensors = PlaceholderSensors()
    s.save_sleep_duration(0)
    assert s.preferences['idle_seconds'] == 0
    assert not s.preferences_path.exists()
