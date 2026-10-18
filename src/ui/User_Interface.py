#NOTE will need to relook at this when hardware is implemented
#Displays interface
from __future__ import annotations
import queue
import time
from Wake_Events import WakeController
import UI_Theme as look
from Background_Jobs import SensorJobs
from UI_Scale import ScaleTask, demo_read_scale, demo_tare
from Sensor_Interfaces import PlaceholderSensors, SensorSnapshot, DemoSensors
from UI_Widgets import BG, TEAL, RED, label


from UI_Home import _HomeScreens
from UI_Scan import _ScanScreens
from UI_Inventory import _InventoryScreens
from UI_Settings import _SettingsScreens
from UI_Calibration import _CalibrationScreens
from UI_Environment import _EnvironmentScreens
from Wake_Events import _WakeScreens

class PantryWindow(_CalibrationScreens, _HomeScreens, _ScanScreens, _InventoryScreens, _SettingsScreens, _EnvironmentScreens, _WakeScreens):

    def __init__(
        self,
        root,
        worker,
        preferences,
        preferences_path,
        *,
        demo=False,
        manual=False,
        sensors=None,
        fullscreen=False,
        read_scale=None,
        tare_scale=None,
        scale_controller=None,
        gas_calibration=None,
        drain_events=None,
        on_event=None
    ):
        self.root = root
        self.worker = worker
        self.preferences = preferences
        self.preferences_path = preferences_path
        self.demo = demo
        self.manual = manual
        self.sensors = sensors or (DemoSensors() if demo else PlaceholderSensors())
        self.wake_control = WakeController()
        self.sensor_jobs = SensorJobs()
        self.scale_task = ScaleTask(demo_read_scale if demo else read_scale,
                                    tare=demo_tare if demo else tare_scale)
        self.scale_controller = scale_controller
        if demo and scale_controller is None:
            from Scale_Calibration import DemoCalibration
            self.scale_controller = DemoCalibration()
        self.gas_calibration = gas_calibration
        self.event_source = drain_events
        self.on_subsystem_event = on_event
        self.event_error = ''
        self.weight_prompt = None
        self.tare_prompt = None
        self.sensor_settings_sheet = None
        self.monitor_message = ''
        self.sheets = []
        self.pending = None
        self.active_form = None
        self.selection_sheet = None
        self.selection_buttons = []
        self.scan_buttons = []
        self.requesting_selection = False
        self.form_buttons = []
        self.deferred = None
        self.rows = []
        self.total = 0
        self.page = 0
        self.last_product = None
        self.last_raw = ''
        self.last_count = 0
        self.paused = False
        self.ready = False
        self.serial_ready = False
        self.fatal = False
        self.closing = False
        self.sleep_cover = None
        self.last_activity = time.monotonic()
        self.clock_status = {}
        self.clock_sheet = None
        self.last_clock_tick = 0
        self.last_sensor_tick = 0
        self.expiry_alerts = []
        self.undated = 0
        self.alert_sheet = None
        self.alert_tree = None
        self.detail_sheet = None
        self.edit_sheet = None
        self.record_buttons = []
        self.record_note = None
        self.alert_ack = None
        self.sensor_snapshot = SensorSnapshot()
        self.system_note = ''
        self.fullscreen = fullscreen
        self.transaction = False
        root.title('Grocery Touch')
        root.configure(bg=BG)
        root.minsize(800, 480)
        root.attributes('-fullscreen', fullscreen)
        root.protocol('WM_DELETE_WINDOW', self.quit)
        root.bind('<F11>', self.toggle_fullscreen)
        root.bind('<Escape>', lambda e: root.attributes('-fullscreen', False))
        root.bind_all('<ButtonPress>', self.activity, add='+')
        root.bind_all('<KeyPress>', self.activity, add='+')
        self._build_home()
        self.safety_banner = label(root, '', 12, True, fg='white', bg=RED, anchor='w')
        self.update_sensors()
        root.bind('<Configure>', self.resize, add='+')
        root.after(80, self.poll)

    def safe_sensor_call(self, method, *args):
        try:
            getattr(self.sensors, method)(*args)
        except Exception as exc:
            self.system_note = 'Integration error: ' + str(exc)

    def set_transaction(self, value):
        if self.transaction != value:
            self.safe_sensor_call('set_transaction_active', value)
            self.transaction = value

    def wake(self, reason='touch'):
        self.wake_control.touch()
        self.last_activity = time.monotonic()
        if self.sleep_cover is not None:
            self.sleep_cover.destroy()
            self.sleep_cover = None
            self.resume_if_allowed()

    def activity(self, event=None):
        sleeping = self.sleep_cover is not None
        self.safe_sensor_call('notify_touch')
        self.wake('touch')
        if sleeping:
            return 'break'

    def place_safety_banner(self):
        offset = look.SAFETY_HEIGHT if self.monitor_message else 0
        for sheet in self.sheets:
            if not sheet.closed:
                sheet.frame.place_configure(y=offset, height=-offset)
        if offset:
            self.safety_banner.config(text='  ' + self.monitor_message)
            self.safety_banner.place(x=0, y=0, relwidth=1, height=look.SAFETY_HEIGHT)
            self.safety_banner.lift()
        else:
            self.safety_banner.place_forget()

    def resume_if_allowed(self):
        if self.closing:
            return
        if not self.sheets and self.deferred:
            pending = self.deferred
            self.deferred = None
            self.root.after_idle(lambda: self.handle_scan(pending))
            return
        self.worker.set_enabled(self.ready and self.serial_ready and (not self.fatal) and (not self.paused) and (not self.sheets) and (self.pending is None) and (self.sleep_cover is None))
        self.safe_sensor_call('set_ui_home', not bool(self.sheets))

    def toggle_pause(self):
        self.paused = not self.paused
        self.pause_button.config(text='Resume' if self.paused else 'Pause')
        self.status.config(text='Scanning paused' if self.paused else 'Ready to scan')
        self.resume_if_allowed()

    def poll(self):
        if not self.root.winfo_exists():
            return
        self.poll_subsystem_events()
        for _ in range(30):
            try:
                event = self.worker.events.get_nowait()
            except queue.Empty:
                break
            kind = event['kind']
            if kind == 'inventory':
                self.rows = event['rows']
                self.total = event['total']
                self.expiry_alerts = event.get('alerts', [])
                self.undated = event.get('undated', 0)
                self.refresh_table()
                self.refresh_alerts()
                code = self.last_product.get('item_upc') if self.last_product else None
                if code:
                    self.last_count = event.get('counts', {}).get(code, 0)
                    self.count_label.config(text=str(self.last_count))
            elif kind == 'clock':
                self.clock_status = event['status']
                self.last_clock_tick = 0
            elif kind == 'ready':
                self.ready = True
                self.serial_ready = event['serial_ready']
                self.status.config(text='DEMO / fictional records' if self.demo else 'Ready to scan' if self.serial_ready else 'Manual input ready')
                self.resume_if_allowed()
            elif kind == 'scan':
                self.handle_scan(event['pending'])
            elif kind == 'manual':
                self.close_operation_sheets()
                self.show_add_form(event['pending'])
            elif kind == 'selection':
                self.show_selection(event)
            elif kind == 'selected':
                self.pending = event['pending']
                if event['action'] == 'update':
                    self.edit_record(event['row'], selected=True)
                else:
                    self.remove_record(event['row'], selected=True)
            elif kind in ('saved', 'finished'):
                if kind == 'saved':
                    result = event['result']
                    p = result['values'].copy()
                    p['item_upc'] = result['code']
                    count = (self.pending.get('count', 0) if self.pending else 0) + p['quantity']
                    self.display_product(p, event['pending']['raw'] or 'Manual entry (no barcode)', count)
                    msg = f"Added {p['quantity']} package(s)."
                else:
                    msg = event['message']
                self.pending = None
                self.set_transaction(False)
                self.close_operation_sheets()
                self.status.config(text=msg)
                self.resume_if_allowed()
            elif kind == 'record_saved':
                if event.get('pending_finished'):
                    self.pending = None
                    self.set_transaction(False)
                self.close_operation_sheets()
                messages = {'dates': 'Dates updated.', 'update': 'One package updated.',
                            'remove': 'One package removed.'}
                self.status.config(text=messages[event['command']])
                if event['command'] == 'update' and event.get('row'):
                    row = event['row']
                    self.display_product(row, row['item_upc'] or 'Manual item', self.last_count)
                self.resume_if_allowed()
            elif kind == 'clock_saved':
                if self.clock_sheet and (not self.clock_sheet.closed):
                    self.clock_note.config(text=event['message'], fg=TEAL)
                    self.clock_apply.config(state='normal')
            elif kind == 'error':
                if event.get('command') in ('select', 'select_record'):
                    self.requesting_selection = False
                    for b in self.selection_buttons + self.scan_buttons:
                        if b.winfo_exists():
                            b.config(state='normal')
                    if not self.pending:
                        self.set_transaction(False)
                    self.message('Selection not completed', event['message'], danger=True)
                elif event.get('command') in ('dates', 'remove', 'update', 'update_selected', 'remove_selected') and self.edit_sheet and (not self.edit_sheet.closed):
                    self.record_note.config(text=event['message'], fg=RED)
                    for b in self.record_buttons:
                        b.config(state='normal')
                elif event.get('command') == 'new':
                    self.message('Product lookup failed', event['message'], danger=True)
                    self.cancel_pending()
                elif event.get('command') == 'save' and self.active_form:
                    self.form_note.config(text=event['message'], fg=RED)
                    for b in self.form_buttons:
                        b.config(state='normal')
                elif event.get('command') == 'clock_set' and self.clock_sheet and (not self.clock_sheet.closed):
                    self.clock_note.config(text=event['message'], fg=RED)
                    self.clock_apply.config(state='normal')
                else:
                    self.message('Action not completed', event['message'], danger=True)
            elif kind in ('fatal', 'scanner_error'):
                if kind == 'fatal':
                    self.fatal = True
                else:
                    self.serial_ready = False
                self.paused = True
                self.pause_button.config(text='Resume')
                self.worker.set_enabled(False)
                self.status.config(text='Needs attention')
                self.message('Setup needs attention', event['message'], danger=True)
            elif kind == 'stopped' and self.closing:
                self.root.destroy()
                return
        now = time.monotonic()
        if now - self.last_clock_tick >= 1:
            self.last_clock_tick = now
            dt = self.local_now()
            fmt = '%I:%M:%S %p' if self.preferences['clock_format'] == '12h' else '%H:%M:%S'
            self.clock_label.config(text=dt.strftime('%a %d %b %Y') + '\n' + dt.strftime(fmt))
            self.update_sleep_clock(dt)
        if now - self.last_sensor_tick >= 0.25:
            self.last_sensor_tick = now
            self.update_sensors()
        self.poll_sensor_jobs()
        if self.closing and (not self.worker.thread.is_alive()):
            self.root.destroy()
            return
        self.root.after(80, self.poll)

    def quit(self):
        if self.closing:
            return
        self.closing = True
        if self.tare_prompt is not None:
            self.tare_prompt.close()
        if self.weight_prompt is not None:
            self.weight_prompt.close()
        self.scale_task.cancel()
        self.worker.stop()
        self.set_transaction(False)
        self.status.config(text='Closing scanner safely...')
        if not self.worker.thread or not self.worker.thread.is_alive():
            self.root.destroy()

