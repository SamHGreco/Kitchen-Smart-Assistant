#NOTE will need to look back at this once things are configured

#Displays interface
from __future__ import annotations
import math
import queue
import time
import tkinter as tk
from dataclasses import asdict
from Input_Validation import save_preferences
from Sensor_Interfaces import SensorSnapshot, GasSettings, DemoSensors
from UI_Widgets import BG, CARD, MUTED, TEAL, RED, label, button, Sheet, touch_field


class _EnvironmentScreens:
#added for save sleep button functionality, live motion forwarding, and persistence
    def save_sleep_duration(self, seconds):
        """Apply and persist ONLY sleep. Gas drafts never block this action."""
        if type(seconds) is not int or not 0 <= seconds <= 3600:
            raise ValueError('Sleep seconds must be 0 to 3600.')
        old_seconds = self.preferences['idle_seconds']
        updated = dict(self.preferences, idle_seconds=seconds)
        self.sensors.set_sleep_timeout(seconds)
        try:
            if not self.demo:
                save_preferences(self.preferences_path, updated)
        except OSError:
            self.sensors.set_sleep_timeout(old_seconds)
            raise
        self.preferences.update(updated)
        self.wake_control.touch()

    def show_environment_alert(self, s):
        sheet = self.message(
            'Environment alert',
            s.alert_message or 'An environmental alert has been detected.',
            danger=True
        )
        self.alert_ack = s.alert_id or s.alert_message
        label(sheet.footer, 'Dismisses notice; does not reset alarm.', 10, fg=RED, bg=BG).pack(side='left')

    def update_sensors(self, allow_sleep=True):
        try:
            self.sensor_snapshot = self.sensors.snapshot()
        except Exception as exc:
            self.sensor_snapshot = SensorSnapshot(
                sensor_fault=True, fresh=False, note='Sensor interface error: ' + str(exc))
        s = self.sensor_snapshot
        unit = self.preferences['temperature_unit']
        temp = s.temperature_c
        if isinstance(temp, (int, float)) and math.isfinite(temp):
            temp = temp * 9 / 5 + 32 if unit == 'F' else temp
            ts = f'{temp:.1f} {unit}'
        else:
            ts = '--'
        def show(n, suffix):
            return f'{n:.1f}{suffix}' if isinstance(n, (int, float)) and math.isfinite(n) else '--'
        note = s.note
        self.sensor_label.config(text=f"Temp {ts}   |   Humidity {show(s.humidity_percent, '%')}   |   Gas {show(s.gas_voltage, ' V')}   |   {note}")
        self.update_header_status()
        self.refresh_environment_panel()
        if self.wake_control.update(s):
            self.wake(self.wake_control.reason)
        motion_healthy = s.fresh and (
            s.motion_health == 'OK' or
            (self.demo and s.connected and not s.sensor_fault)
        )
        self.worker.observe_motion(
            s.motion_detected, healthy=motion_healthy,
            allow_trigger=(self.ready and self.serial_ready and not self.fatal
                           and not self.paused and not self.sheets
                           and self.pending is None and self.sleep_cover is None
                           and not self.closing)
        )
        message = self.wake_control.message
        if message != self.monitor_message:
            self.monitor_message = message
            self.resize()
        self.place_safety_banner()
        busy = self.paused or self.pending is not None or bool(self.sheets) or self.sensor_jobs.busy
#updated sleep function
        self.safe_sensor_call('set_sleep_inhibited', self.wake_control.hold or busy)
#zero means no sleep
        wants_sleep = bool(self.preferences['idle_seconds']) and (
            s.display_awake is False if s.display_awake is not None else
            self.wake_control.should_sleep(self.preferences['idle_seconds'], busy))
        if (allow_sleep and not busy and not self.wake_control.hold and
                self.sleep_cover is None and wants_sleep):
            self.sleep()

    @staticmethod
    def gas_display(s):
        # The controller owns the threshold, debounce, and latched alarm.
        if s.gas_alarm is True:
            return 'ALERT'
        if (s.gas_alarm is False and s.fresh and s.gas_health == 'OK'
                and s.gas_voltage is not None):
            return 'SAFE'
        return '--'

    def system_display_state(self, s):
        # Most urgent fault first; detailed health remains on the live page.
        if s.gas_health in ('FAULT', 'DEGRADED'):
            return 'Gas Error'
        #if s.temp_humidity_health in ('FAULT', 'DEGRADED'):
        #    return 'Temp/Humidity Error'
        if s.temp_humidity_health =='FAULT': #new since degraded is a consistently repeated action
            return 'Temp/Humidity Error'
        if s.motion_health in ('FAULT', 'DEGRADED'):
            return 'Motion Error'
        if (self.ready and self.serial_ready
                and 'motion input unavailable' in self.worker.motion_window.status().lower()):
            return 'Motion Error'
        if self._scanner_error:
            return 'Scanner Error'
        # TeamSensors.weight_snapshot is a cached getter, not a new HX711 read.
        weight_snapshot = getattr(self.sensors, 'weight_snapshot', None)
        if callable(weight_snapshot):
            try:
                w = weight_snapshot()
                if w.get('fault'):
                    note = str(w.get('note') or '').strip()
                    stamp = w.get('timestamp')
                    age = (
                        time.time() - stamp.timestamp()
                        if stamp is not None else float('inf')
                    )

                    calibration_pending = (
                        note == 'Calibration saved. Waiting for the next reading.'
                        and 0 <= age <= 5.0
                        and s.connected
                        and s.fresh
                    )

                    if calibration_pending:
                        if s.gas_alarm is True:
                            return 'Gas Alert'
                        if s.temp_alarm is True or s.humidity_alarm is True:
                            return 'Temp/Humidity Alert'
                        return 'Scale updating'

                    return 'Scale Error'

            except Exception as exc:
                print(
                    f'SCALE HEADER ERROR: {type(exc).__name__}: {exc}',
                    flush=True
                )
                return 'Scale Error'
        if 'Scale interface error' in s.note or (s.sensor_fault and s.fresh):
            print(
                "SCALE HEADER [status]: ",
                f"note={s.note!r}; sensor_fault={s.sensor_fault}; "
                f"fresh={s.fresh}",
                flush=True
            )
            return 'Scale Error'
        if not s.connected or not s.fresh or s.sensor_fault:
            return 'Monitoring Error'
        if s.gas_alarm is True:
            return 'Gas Alert'
        if s.temp_alarm is True or s.humidity_alarm is True:
            return 'Temp/Humidity Alert'
        if s.temp_humidity_health == 'DEGRADED': #to catch the degraded state
            return 'Temp/Humidity retrying'
        return 'NORMAL'

    def update_alert_badge(self):
        # Count date reminders plus one for a current environmental alarm.
        total = len(self.expiry_alerts) + int(bool(self.sensor_snapshot.alert_id))
        self.alert_button.config(text=f'Alerts ({total})')

    def update_header_status(self):
        s = self.sensor_snapshot
        unit = self.preferences['temperature_unit']
        temp = s.temperature_c
        if isinstance(temp, (int, float)) and math.isfinite(temp):
            temp = temp * 9 / 5 + 32 if unit == 'F' else temp
            temp_text = f'{temp:.1f} {unit}'
        else:
            temp_text = '--'
        hum = s.humidity_percent
        hum_text = f'{hum:.1f}%' if isinstance(hum, (int, float)) and math.isfinite(hum) else '--'
        state = self.system_display_state(s)
        self.header_status.config(
            text=f'Temp: {temp_text}\nHumidity: {hum_text}\n'
                 f'Gas: {self.gas_display(s)}\nState: {state}',
            fg='#ffe0e0' if state != 'NORMAL' or self.gas_display(s) == 'ALERT' else 'white'
        )
        self.update_alert_badge()

    def environment_alerts(self):
        # This panel stays open and redraws from the existing 250-ms UI cache.
        sheet = Sheet(self, 'Environmental Status - Live')
        self.environment_status_sheet = sheet
        self.environment_status_label = label(
            sheet.body, '', 11, fg=MUTED, justify='left', anchor='nw',
            wraplength=700
        )
        self.environment_status_label.pack(fill='both', expand=True, padx=18, pady=12)
        button(sheet.footer, 'Close', sheet.close, primary=True).pack(side='right')
        self.refresh_environment_panel()

    def refresh_environment_panel(self):
        sheet = self.environment_status_sheet
        if sheet is None or sheet.closed:
            return
        s = self.sensor_snapshot
        def show(value):
            return '--' if value is None else str(value)
        def measured(value, suffix):
            return f'{value:.1f}{suffix}' if isinstance(value, (int, float)) and math.isfinite(value) else '--'
        text = (
            f'System: {self.system_display_state(s)}     Environmental state: {s.safety_state or "Unavailable"}\n'
            f'Temperature: {measured(s.temperature_c, " C")}     Humidity: {measured(s.humidity_percent, "%")}\n'
            f'Gas: {self.gas_display(s)}     Voltage: {measured(s.gas_voltage, " V")}     ADC raw: {show(s.gas_raw)}\n'
            f'Scale: {measured(s.weight_g, " g")}     Motion detected: {show(s.motion_detected)}\n'
            f'Temp/Humidity health: {show(s.temp_humidity_health)}     Gas health: {show(s.gas_health)}\n'
            f'Motion health: {show(s.motion_health)}     Monitoring fresh: {show(s.fresh)}\n'
            f'Temp alarm: {show(s.temp_alarm)}     Humidity alarm: {show(s.humidity_alarm)}\n'
            f'Note: {s.note}\n'
            f'Updated on screen: {self.local_now().strftime("%H:%M:%S")}\n'
            '-- means unavailable, never confirmed safe.'
        )
        self.environment_status_label.config(text=text,
                                             fg=RED if self.gas_display(s) == 'ALERT' else MUTED)

    def poll_sensor_jobs(self):
        jobs = self.sensor_jobs
        if not jobs.busy:
            return
        try:
            value, error = jobs.events.get_nowait()
        except queue.Empty:
            if time.monotonic() - jobs.started > jobs.warn_after and not jobs.warned:
                jobs.warned = True
                self.system_note = 'Sensor setting request delayed; monitoring must remain independent.'
                if self.sensor_settings_sheet and not self.sensor_settings_sheet.closed:
                    self.gas_note.config(text='Controller has not replied. Do not assume the setting changed.', fg=RED)
            return
        jobs.busy = False
        handler = jobs.handler
        jobs.handler = None
        if handler:
            handler(value, error)

    def show_wake_settings(self):
        sheet = Sheet(self, 'Wake / gas settings')
        self.sensor_settings_sheet = sheet
        left = tk.Frame(sheet.body, bg=CARD)
        left.pack(side='left', fill='both', expand=True, padx=12, pady=8)
        right = tk.Frame(sheet.body, bg=CARD)
        right.pack(side='right', fill='both', expand=True, padx=12, pady=8)
        label(left, 'Wake on any one input', 17, True).pack(anchor='w')
        label(left, 'Motion  /  Weight  /  Touch  /  Alarm', 11, fg=MUTED).pack(anchor='w', pady=5)
        form = tk.Frame(left, bg=CARD)
        form.pack(fill='x')
        form.columnconfigure(0, weight=1)
        idle = tk.StringVar(value=str(self.preferences['idle_seconds']))
        touch_field(self, form, 'Sleep after seconds (0 = never)', idle, 0, numeric=True)
        self.sleep_note = label(left, 'Save sleep applies now and after restart.',
              11, fg=MUTED, wraplength=300, justify='left')
        self.sleep_note.pack(anchor='w', pady=8)
        label(left, 'Black screen only',
              10, fg=MUTED, wraplength=320, justify='left').pack(anchor='w')
        if self.demo:
            button(left, 'Demo wake tests', self.show_wake_tests).pack(fill='x', pady=8)
        else:
            label(left, '',
                  10, fg=MUTED, wraplength=300, justify='left').pack(anchor='w', pady=6)
        self.gas_note = label(right, 'No gas controller connected.', 10, fg=MUTED, wraplength=330, justify='left')
        self.gas_note.pack(anchor='w')
        self.gas_fields = {}
        form = tk.Frame(right, bg=CARD)
        form.pack(fill='x', pady=3)
        form.columnconfigure(0, weight=1)
        draft = self.preferences.get('gas_draft') or {}
        for row, (key, title) in enumerate((
                ('threshold_voltage', 'Gas threshold (V, not PPM)'),
                ('hysteresis_voltage', 'Hysteresis (V)'),
                ('debounce_seconds', 'Debounce (seconds)'))):
            value = tk.StringVar(value=str(draft.get(key, '')))
            self.gas_fields[key] = value
            touch_field(self, form, title, value, row, numeric=True)
        label(right, 'Gas changes require Apply',
              10, fg=RED, wraplength=330, justify='left').pack(anchor='w', pady=3)

        def complete(value, error):
            if sheet.closed:
                return
            if error:
                self.gas_note.config(text=error, fg=RED)
            else:
                for key, number in asdict(value).items():
                    self.gas_fields[key].set(f'{number:g}')
                self.gas_note.config(text=('DEMO values only.' if self.demo else 'Controller readback shown. Persistence is owned by controller.'), fg=TEAL)
            self.gas_apply.config(state='normal' if self.sensors.gas_settings_available else 'disabled')
#sleep duration update
        def save_sleep():
            try:
                seconds = int(idle.get())
                self.save_sleep_duration(seconds)
                message = ('Automatic sleep disabled (0 = never).' if seconds == 0 else
                           f'Sleep saved: {seconds} seconds after activity clears.')
                self.sleep_note.config(text=message, fg=TEAL)
            except (ValueError, TypeError, OSError, RuntimeError) as exc:
                self.sleep_note.config(text='Sleep not saved: ' + str(exc), fg=RED)

        def apply_gas():
            try:
                values = GasSettings.read({key: value.get() for key, value in self.gas_fields.items()})
                self.sensor_jobs.start(lambda: self.sensors.apply_gas_settings(values), complete)
                self.gas_apply.config(state='disabled')
                self.gas_note.config(text='Applying to controller; waiting for readback...', fg=MUTED)
            except (ValueError, TypeError, RuntimeError) as exc:
                self.gas_note.config(text=str(exc), fg=RED)

        button(sheet.footer, 'Close', sheet.close).pack(side='left')
        button(sheet.footer, 'Save sleep', save_sleep, primary=True).pack(side='left', padx=5)
        self.gas_apply = button(sheet.footer, 'Apply gas', apply_gas, primary=True)
        self.gas_apply.pack(side='right')
        self.gas_apply.config(state='disabled')
        if self.sensors.reset_available:
            button(sheet.footer, 'Reset alarm', self.request_alarm_reset).pack(side='right', padx=5)
        if self.sensors.gas_settings_available:
            try:
                self.sensor_jobs.start(self.sensors.get_gas_settings, complete)
                self.gas_note.config(text='Reading controller settings...', fg=MUTED)
            except RuntimeError as exc:
                self.gas_note.config(text=str(exc), fg=RED)

    def request_alarm_reset(self):
        def done(result, error):
            self.update_sensors()
            if self.sensor_settings_sheet and not self.sensor_settings_sheet.closed:
                message = error or ('Reset refused by controller.' if result is False else
                                    'Reset request returned. Live status decides whether alarm clears.')
                self.gas_note.config(text=message, fg=RED if error or result is False else TEAL)
        try:
            self.sensor_jobs.start(self.sensors.reset_alarm, done)
        except RuntimeError as exc:
            self.system_note = str(exc)

    def show_wake_tests(self):
        if not self.demo or not isinstance(self.sensors, DemoSensors):
            return
        sheet = Sheet(self, 'Demo wake tests - NO live sensors')
        label(sheet.body, 'Each test sleeps first, then changes a simulated input after 3 seconds.',
              13, wraplength=700, justify='left').pack(padx=16, pady=12)
        row = tk.Frame(sheet.body, bg=CARD)
        row.pack(fill='x', padx=16, pady=8)
        for name, title in (('motion', 'Motion wake'), ('weight', 'Weight wake'), ('high_gas', 'Gas alarm wake')):
            button(row, title, lambda n=name: self.sleep_then_demo(n), primary=True).pack(side='left', expand=True, fill='x', padx=4)
        label(sheet.body, 'Hold input keeps it awake. Clear inputs starts the idle timer.\nA gas alarm remains latched until its input is low AND Reset alarm is requested.',
              12, wraplength=700, justify='left').pack(padx=16, pady=12)

        def clear():
            for key in ('motion', 'weight', 'high_gas', 'fault'):
                self.sensors.set_input(key, False)
            self.update_sensors()
        button(sheet.footer, 'Clear demo inputs', clear).pack(side='left')
        button(sheet.footer, 'Reset alarm', self.request_alarm_reset).pack(side='left', padx=5)
        button(sheet.footer, 'Touch wake test', lambda: self.sleep_then_demo(None)).pack(side='right')

    def sleep_then_demo(self, name):
        if not self.demo:
            return
        for key in ('motion', 'weight', 'high_gas', 'fault'):
            self.sensors.set_input(key, False)
        self.sensors.reset_alarm()
        for sheet in list(reversed(self.sheets)):
            sheet.close()
        self.update_sensors(allow_sleep=False)
        self.sleep()
        if name:
            self.root.after(3000, lambda: self.sensors.set_input(name, True))

