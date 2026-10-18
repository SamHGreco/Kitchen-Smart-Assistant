#Runs background tasks
#NOTE will need to relook when hardware implemented and code pulled in

import queue
import threading
import time
import uuid
from zoneinfo import ZoneInfo
from dataclasses import asdict
from Barcode_Reader import AtomicBarcodeReader, ScanCancelled
from Inventory_Database import Store
from System_Clock import SystemClock, MockClock

class Worker:

    def __init__(
        self,
        settings,
        *,
        serial_enabled=False,
        demo=False,
        reader_factory=None,
        clock=None,
        warning_days=3
    ):
        self.settings = settings
        self.serial_enabled = serial_enabled
        self.demo = demo
        self.reader_factory = reader_factory or AtomicBarcodeReader
        self.clock = clock or (MockClock() if demo else SystemClock())
        self.clock_status = {}
        self.warning_days = warning_days
        self.commands = queue.Queue(maxsize=32)
        self.events = queue.Queue()
        self.enabled = threading.Event()
        self.cancel_scan = threading.Event()
        self.stopping = threading.Event()
        self.thread = None
        self.pending = None
        self.reader = None
        self.scanner_failed = False
        self.next_scan = 0
        self.next_refresh = 0

    def start(self):
        self.thread = threading.Thread(target=self.run, name='grocery-io', daemon=False)
        self.thread.start()

    def send(self, kind, **data):
        self.cancel_scan.set()
        self.commands.put_nowait((kind, data))

    def set_enabled(self, enabled):
        if enabled:
            self.enabled.set()
        else:
            self.enabled.clear()
            self.cancel_scan.set()

    def stop(self):
        self.stopping.set()
        self.cancel_scan.set()

    def emit(self, kind, **data):
        self.events.put({'kind': kind, **data})

    def today(self):
        now = self.clock.now()
        zone = self.clock_status.get('timezone')
        if zone:
            try:
                return now.astimezone(ZoneInfo(zone)).date()
            except (ValueError, KeyError):
                pass
        return now.astimezone().date()

    def refresh(self, store):
        self.emit('inventory', **store.report(self.today(), self.warning_days))
        self.next_refresh = time.monotonic() + 30

    def update_clock(self):
        self.clock_status = self.clock.status()
        self.emit('clock', status=self.clock_status)

    def new_scan(self, store, raw):
        if self.pending:
            raise ValueError('Finish or cancel the current item first.')
        result = store.lookup(raw)
        self.pending = {**result, 'token': uuid.uuid4().hex}
        self.enabled.clear()
        self.emit('scan', pending=self.pending.copy())

    def require_pending(self, payload):
        if not self.pending or self.pending['token'] != payload.get('token'):
            raise ValueError('That request is stale or was already completed.')

    def process(self, store, command, payload):
        if command == 'lookup':
            self.new_scan(store, payload['raw'])
        elif command == 'manual':
            if self.pending:
                raise ValueError('Finish or cancel the current item first.')
            self.pending = {'token': uuid.uuid4().hex, 'code': None, 'product': None, 'raw': '', 'count': 0}
            self.enabled.clear()
            self.emit('manual', pending=self.pending.copy())
        elif command == 'new':
            self.require_pending(payload)
            if self.pending.get('mode') in ('update', 'remove'):
                raise ValueError('Finish or cancel the current selection first.')
            product = store.products.find_product(self.pending['code'])
            self.pending['product'] = asdict(product) if product else None
            self.emit('manual', pending=self.pending.copy())
        elif command in ('save', 'cancel', 'returning'):
            self.require_pending(payload)
            if command == 'save':
                if self.pending.get('mode') in ('update', 'remove'):
                    raise ValueError('Use the selected package action, not Add.')
                result = store.add(self.pending, payload['data'])
                self.emit('saved', result=result, pending=self.pending.copy())
            else:
                message = 'Returning item: inventory unchanged.' if command == 'returning' else 'Cancelled. Inventory unchanged.'
                self.emit('finished', message=message)
            self.pending = None
            self.next_scan = time.monotonic() + 3
            self.refresh(store)
        elif command == 'select':
            action = payload['action']
            if action not in ('update', 'remove'):
                raise ValueError('Choose Update or Remove.')
            if self.pending:
                self.require_pending(payload)
                if self.pending.get('mode'):
                    raise ValueError('Finish or cancel the current selection first.')
            else:
                if payload.get('token'):
                    raise ValueError('That request is stale or was already completed.')
                self.pending = {'token': uuid.uuid4().hex, 'code': None,
                                'product': None, 'raw': '', 'count': 0}
            rows = store.matching_items(self.pending['code'])
            self.pending['mode'] = action
            self.enabled.clear()
            self.emit('selection', pending=self.pending.copy(), action=action, rows=rows)
        elif command == 'select_record':
            self.require_pending(payload)
            if self.pending.get('mode') not in ('update', 'remove'):
                raise ValueError('Choose Update or Remove first.')
            row = store.get_item(payload['record_kind'], payload['record_id'])
            if self.pending['code'] and row['item_upc'] != self.pending['code']:
                raise ValueError('That package does not match the scanned barcode.')
            self.pending['selected'] = (row['kind'], row['inventory_id'])
            self.emit('selected', pending=self.pending.copy(), row=row,
                      action=self.pending['mode'])
        elif command in ('update_selected', 'remove_selected'):
            self.require_pending(payload)
            expected = 'update' if command == 'update_selected' else 'remove'
            if self.pending.get('mode') != expected or not self.pending.get('selected'):
                raise ValueError('Select the package before saving.')
            kind, record_id = self.pending['selected']
            row = store.get_item(kind, record_id)
            if expected == 'update':
                row = store.update_item(kind, record_id, payload['data'])
            else:
                store.remove(kind, record_id)
            self.pending = None
            self.next_scan = time.monotonic() + 3
            self.emit('record_saved', command=expected, row=row, pending_finished=True)
            self.refresh(store)
        elif command in ('dates', 'remove', 'update'):
            if self.pending:
                raise ValueError('Finish or cancel the current scan first.')
            if command == 'dates':
                store.dates(
                    payload['record_kind'],
                    payload['record_id'],
                    payload['purchased_on'],
                    payload['expires_on']
                )
            elif command == 'update':
                store.update_item(payload['record_kind'], payload['record_id'], payload['data'])
            else:
                store.remove(payload['record_kind'], payload['record_id'])
            self.emit('record_saved', command=command)
            self.refresh(store)
        elif command == 'refresh':
            self.refresh(store)
        elif command == 'warning_days':
            days = payload['days']
            if type(days) is not int or not 0 <= days <= 365:
                raise ValueError('Warning days must be between 0 and 365.')
            self.warning_days = days
            self.refresh(store)
        elif command == 'clock_status':
            self.update_clock()
        elif command == 'clock_set':
            try:
                self.clock.apply(**payload)
            finally:
                self.update_clock()
                self.refresh(store)
            self.emit(
                'clock_saved',
                message='Demo clock updated.' if self.demo else 'System clock settings applied.'
            )
        else:
            raise ValueError('Unknown application command.')

    def run(self):
        try:
            with Store(self.settings) as store:
                try:
                    self.update_clock()
                except Exception as exc:
                    self.emit(
                        'clock',
                        status={'supported': False, 'timezone': None, 'ntp': None, 'synchronized': None, 'message': str(exc)}
                    )
                self.refresh(store)
                if self.serial_enabled:
                    try:
                        review = self.settings.get('hardware_review', {})
                        keys = (
                            'gpio15_conflict_resolved',
                            'uart_voltage_compatibility_confirmed',
                            'power_budget_and_connector_orientation_confirmed'
                        )
                        if not all((review.get(key) is True for key in keys)):
                            raise ValueError('Complete the config.pi.json hardware-review checks before serial access.')
                        serial = self.settings.get('serial', {})
                        self.reader = self.reader_factory(serial.get('port', '/dev/serial0'), int(serial.get('baud', 115200)))
                        self.reader.open()
                        self.reader.stop_decode()
                        self.reader.verify_configuration()
                    except Exception as exc:
                        self.scanner_failed = True
                        self.enabled.clear()
                        self.emit('scanner_error', message=str(exc))
                self.emit('ready', serial_ready=self.serial_enabled and (not self.scanner_failed))
                while not self.stopping.is_set():
                    try:
                        command, payload = self.commands.get(timeout=0.05)
                    except queue.Empty:
                        command = None
                    if command:
                        try:
                            self.process(store, command, payload)
                        except Exception as exc:
                            self.emit('error', message=str(exc), command=command)
                    if time.monotonic() >= self.next_refresh:
                        self.refresh(store)
                    if command or not self.enabled.is_set() or (not self.reader) or self.scanner_failed or self.pending:
                        continue
                    if time.monotonic() < self.next_scan:
                        continue
                    self.cancel_scan.clear()
                    if not self.enabled.is_set() or not self.commands.empty() or self.stopping.is_set():
                        continue
                    try:
                        raw = self.reader.scan_once(timeout=2, cancel=self.cancel_scan)
                    except Exception as exc:
                        if isinstance(exc, ScanCancelled) or exc.__class__.__name__ == 'ScanCancelled':
                            continue
                        self.scanner_failed = True
                        self.enabled.clear()
                        self.emit('scanner_error', message=str(exc))
                        continue
                    if raw:
                        try:
                            self.new_scan(store, raw)
                        except Exception as exc:
                            self.next_scan = time.monotonic() + 2
                            self.emit('error', message=str(exc), command='scan')
        except Exception as exc:
            self.emit('fatal', message=str(exc))
        finally:
            if self.reader:
                try:
                    self.reader.close()
                except Exception as exc:
                    self.emit('error', message='Reader shutdown: ' + str(exc), command='shutdown')
            self.emit('stopped')
