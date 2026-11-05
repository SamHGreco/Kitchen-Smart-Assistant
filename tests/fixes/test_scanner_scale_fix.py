from __future__ import annotations
from collections import deque
from pathlib import Path
from threading import Event, Thread
import time

import pytest
from app.shared.scanner_scale_gate import AnyEvent, ScannerScaleGate
from product_id.barcode_reader import AtomicBarcodeReader, ScanCancelled, ScannerError
from App_Worker import Worker
from scale.coordinated_scale import GuardedRawScale, CoordinatedScale
from Scale_Interface import ScaleReading
from Scale_Calibration import Calibration
from Calibration_Storage import write_json
from tools.bootstrap_data import bootstrap
from Inventory_Database import Store


class SerialDouble:
    def __init__(self, barcode=b'012345678905\r\n', fail_stop=False):
        self.data = bytearray()
        self.writes = []
        self.barcode = barcode
        self.fail_stop = fail_stop

    def read(self, size=1):
        result = bytes(self.data[:size])
        del self.data[:size]
        if not result:
            time.sleep(0.001)
        return result

    def write(self, data):
        self.writes.append(data)
        if data == bytes.fromhex('32 75 01'):
            self.data.extend(self.barcode)
        elif data == bytes.fromhex('32 75 02') and not self.fail_stop:
            self.data.extend(bytes.fromhex('33 75 02 00 00'))
        return len(data)

    def flush(self):
        pass

    def reset_input_buffer(self):
        self.data.clear()

    def close(self):
        pass


def reader(transport):
    return AtomicBarcodeReader('FAKE', transport=transport, response_timeout=0.02)


def test_scan_issues_start_then_acknowledged_stop():
    serial = SerialDouble()
    assert reader(serial).scan_once() == '012345678905'
    assert serial.writes == [bytes.fromhex('32 75 01'), bytes.fromhex('32 75 02')]


def test_cancel_before_scan_does_not_trigger():
    serial = SerialDouble()
    cancel = Event()
    cancel.set()
    with pytest.raises(ScanCancelled):
        reader(serial).scan_once(cancel=cancel)
    assert serial.writes == [bytes.fromhex('32 75 02')]


def test_bad_stop_is_not_treated_as_success():
    with pytest.raises(ScannerError):
        reader(SerialDouble(fail_stop=True)).scan_once()


def test_any_event_accepts_scale_and_ui_cancellation():
    a, b = Event(), Event()
    combined = AnyEvent(a, None, b)
    assert not combined.is_set()
    b.set()
    assert combined.is_set()


def test_weight_requires_empty_confirmation_then_uses_hysteresis():
    gate = ScannerScaleGate(auto_pause=True, settle_seconds=0)
    assert gate.blocked()  # unknown weight at startup
    gate.observe_weight(0, True, now=0)
    assert gate.blocked()
    gate.observe_weight(0, True, now=1)
    assert not gate.blocked()
    gate.observe_weight(25, False, now=2)
    assert gate.blocked()  # do not wait for stability before pausing
    gate.observe_weight(10, True, now=3)
    assert gate.blocked()
    gate.observe_weight(0, False, now=4)
    gate.observe_weight(0, True, now=5)
    assert gate.blocked()
    gate.observe_weight(0, True, now=6)
    assert not gate.blocked()


def test_weight_fault_reblocks_scanner():
    gate = ScannerScaleGate(auto_pause=True, empty_seconds=0)
    gate.observe_weight(0, True)
    assert not gate.blocked()
    gate.weight_fault()
    assert gate.blocked()


def test_no_auto_mode_still_pauses_during_weighing():
    gate = ScannerScaleGate(auto_pause=False, settle_seconds=0)
    gate.observe_weight(500, True)
    assert not gate.blocked()
    with gate.weighing():
        assert gate.blocked()
        with gate.scan_session() as allowed:
            assert not allowed
    assert not gate.blocked()


def test_unconfirmed_scanner_prevents_weighing():
    gate = ScannerScaleGate(serial_enabled=True, auto_pause=False, settle_seconds=0)
    with pytest.raises(RuntimeError, match='unconfirmed'):
        with gate.weighing():
            pytest.fail('Must not enter hardware measurement')
    assert not gate.pause_requested.is_set()


def test_pause_has_bounded_wait():
    gate = ScannerScaleGate(auto_pause=False, stop_timeout=0.02, settle_seconds=0)
    with gate.uart_lock:
        with pytest.raises(TimeoutError):
            with gate.weighing():
                pytest.fail('Must not read scale while UART lock is held')
    assert not gate.pause_requested.is_set()


def test_inflight_scan_is_stopped_before_scale_lock_is_granted():
    gate = ScannerScaleGate(serial_enabled=True, auto_pause=False, settle_seconds=0)
    serial = SerialDouble(barcode=b'')
    worker = Worker({}, serial_enabled=True, scanner_gate=gate)
    worker.reader = reader(serial)
    worker.observe_motion(True, healthy=True)
    started = Event()
    errors = []

    def scan():
        started.set()
        try:
            worker.scan_hardware_once()
        except ScanCancelled:
            pass
        except Exception as exc:
            errors.append(exc)

    thread = Thread(target=scan)
    thread.start()
    assert started.wait(1)
    deadline = time.monotonic() + 1
    while bytes.fromhex('32 75 01') not in serial.writes and time.monotonic() < deadline:
        time.sleep(0.001)
    with gate.weighing():
        assert bytes.fromhex('32 75 02') in serial.writes
        assert gate.quiet_confirmed
        assert not gate.uart_lock.acquire(blocking=False)
    thread.join(1)
    assert not thread.is_alive()
    assert not errors


def test_worker_retains_unknown_state_after_failed_stop():
    gate = ScannerScaleGate(serial_enabled=True, auto_pause=False, settle_seconds=0)
    worker = Worker({}, serial_enabled=True, scanner_gate=gate)
    worker.reader = reader(SerialDouble(fail_stop=True))
    worker.observe_motion(True, healthy=True)
    with pytest.raises(ScannerError):
        worker.scan_hardware_once()
    assert not gate.quiet_confirmed


def test_guarded_scale_discards_first_conversion():
    gate = ScannerScaleGate(auto_pause=False, settle_seconds=0)
    class Driver:
        def __init__(self):
            self.next_value = 100
        def raw_read(self, **kwargs):
            assert gate.pause_requested.is_set()
            value = self.next_value
            self.next_value += 1
            return value
    scale = GuardedRawScale(Driver(), gate)
    assert scale.read_raw(samples=5) == [101, 102, 103, 104, 105]


class RawDouble:
    def __init__(self, values):
        self.values = values
    def read_raw(self, **kwargs):
        return list(self.values)
    def close(self):
        pass


def test_calibration_median_and_weight_presence(tmp_path):
    gate = ScannerScaleGate(auto_pause=True, empty_seconds=0, settle_seconds=0)
    raw = RawDouble([100000] * 9)
    service = CoordinatedScale(raw, tmp_path/'cal.json', gate=gate, capacity_g=5000)
    with pytest.raises(ValueError, match='calibration'):
        service.read()
    service.capture_zero()
    raw.values = [300000] * 9
    service.calibrate(500)
    assert service.read().grams == 500
    assert gate.weight_present.is_set()
    raw.values = [100000] * 9
    assert service.read().grams == 0
    assert not gate.weight_present.is_set()
    raw.values = [200000, 200000, 200000, 200000, 200000, 200000, 200000, 200000, 205000]
    reading = service.read()
    assert reading.grams == 250  # not the maximum/outlier
    assert not reading.stable


def test_inventory_uses_configured_file_not_global_default(tmp_path):
    settings = {key: tmp_path/(key+'.db') for key in ('catalog', 'products', 'inventory', 'manual')}
    bootstrap(settings, empty_catalog=True)
    with Store(settings) as store:
        actual = store.conn.execute('PRAGMA database_list').fetchone()['file']
        assert Path(actual) == settings['inventory']
        assert store.count() == 0


def test_bootstrap_preserves_existing_catalog(tmp_path):
    settings = {key: tmp_path/(key+'.db') for key in ('catalog', 'products', 'inventory', 'manual')}
    bootstrap(settings, empty_catalog=True)
    before = settings['catalog'].read_bytes()
    bootstrap(settings, empty_catalog=True)
    assert settings['catalog'].read_bytes() == before


def test_new_launcher_supplies_calibration_and_gate_without_pausing_environment(monkeypatch, tmp_path):
    import app.main as main
    from types import SimpleNamespace
    calls = {}
    class Power:
        def start(self): pass
        def stop(self): pass
    class Environment:
        def __init__(self, **kwargs): calls['environment'] = kwargs
        def start(self): pass
        def stop(self): pass
    class Scale:
        def start(self): pass
        def stop(self): pass
        def read(self): pass
        def tare(self): pass
        def snapshot(self): return {}
    scale = Scale()
    settings = {
        'hardware_review': {key: True for key in ('scale_wiring_and_capacity_confirmed',
            'power_budget_and_connector_orientation_confirmed', 'sensor_wiring_confirmed',
            'alarm_outputs_confirmed', 'gas_warmup_complete', 'gas_voltage_thresholds_reviewed')},
        'gpio': {'dht11':26,'motion':17,'buzzer':22,'alarm_led':27},
        'gas': {'ads_address':72,'ads_channel':0,'startup_thresholds':{
            'threshold_voltage':1.5,'hysteresis_voltage':0.15,'debounce_seconds':3}},
    }
    monkeypatch.setattr(main.config, 'HARDWARE_MODE', True)
    monkeypatch.setattr(main, 'parse_args', lambda: SimpleNamespace(mockhardware=False,
        no_environment=False, silent=False, serial=False, config='unused', size='800x480', fullscreen=False))
    monkeypatch.setattr(main, 'load_config', lambda _: settings)
    monkeypatch.setattr(main, 'preload_hardware_libraries', lambda: None)
    monkeypatch.setattr(main, 'PowerManager', Power)
    monkeypatch.setattr(main, 'EnvironmentManager', Environment)
    monkeypatch.setattr(main, 'build_scale', lambda settings, gate: scale)
    monkeypatch.setattr(main, 'run_app', lambda settings, **kwargs: calls.update(ui=kwargs))
    main.main()
    assert 'scale_busy' not in calls['environment']
    assert calls['ui']['scale_controller'] is scale
    assert calls['ui']['scanner_gate'] is not None
