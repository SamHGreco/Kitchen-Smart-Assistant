#NOTE Stand in until hardware is implemented and other code is pulled in
#Displays interface
from __future__ import annotations
import time
import tkinter as tk
import UI_Theme as look
from zoneinfo import ZoneInfo
from UI_Widgets import label


# Checks wake conditions


class WakeController:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.last_activity = clock()
        self.alarm = False
        self.hold = False
        self.message = ''
        self.reason = ''

    def touch(self):
        self.last_activity = self.clock()

    def update(self, snapshot):
        fault = snapshot.sensor_fault is True or not snapshot.fresh
        active_alarm = snapshot.gas_alarm is True or snapshot.safety_state == 'ALARM'
        if active_alarm:
            self.alarm = True
        elif (snapshot.connected and not fault and
              (snapshot.gas_alarm is False or snapshot.safety_state in ('NORMAL', 'WARNING'))):
            self.alarm = False
        motion = snapshot.motion_detected is True and snapshot.fresh
        weight = snapshot.weight_detected is True and snapshot.fresh
        self.hold = self.alarm or fault or motion or weight
        self.message = ''
        if self.alarm:
            self.message = 'ENVIRONMENT ALARM - screen stays awake; monitoring continues.'
        elif fault:
            self.message = 'MONITORING FAULT - readings unavailable; check sensor connection.'
        if self.alarm and fault:
            self.message = 'ALARM / MONITORING FAULT - previous alarm is not confirmed clear.'
        self.reason = ('alarm' if self.alarm else 'sensor fault' if fault else
                       'motion' if motion else 'weight' if weight else '')
        if self.hold:
            self.touch()
        return self.hold

    def should_sleep(self, seconds, busy=False):
        return bool(seconds and not busy and not self.hold and
                    self.clock() - self.last_activity >= seconds)


class _WakeScreens:

    def sleep(self):
        self.update_sensors(allow_sleep=False)
        if self.pending or self.sheets or self.sleep_cover is not None:
            return
        if self.wake_control.hold:
            self.status.config(text='Sleep blocked: ' + self.wake_control.reason)
            return
        self.worker.set_enabled(False)
        self.sleep_cover = tk.Frame(self.root, bg=look.SLEEP_BG)
        self.sleep_cover.place(x=0, y=0, relwidth=1, relheight=1)
        self.sleep_cover.lift()
        self.sleep_cover.bind('<ButtonPress>', self.activity)
        self.sleep_time = label(self.sleep_cover, '', look.SLEEP_TIME_SIZE, True, fg=look.SLEEP_TIME_COLOR, bg=look.SLEEP_BG)
        self.sleep_time.place(relx=0.5, rely=look.SLEEP_TIME_Y, anchor='center')
        self.sleep_date = label(self.sleep_cover, '', look.SLEEP_DATE_SIZE, fg=look.SLEEP_DATE_COLOR, bg=look.SLEEP_BG)
        self.sleep_date.place(relx=0.5, rely=look.SLEEP_DATE_Y, anchor='center')
        label(self.sleep_cover, 'Tap to wake', look.SLEEP_HINT_SIZE, fg=look.SLEEP_HINT_COLOR, bg=look.SLEEP_BG).place(relx=0.5, rely=look.SLEEP_HINT_Y, anchor='center')
        self.update_sleep_clock()

    def update_sleep_clock(self, current=None):
        if self.sleep_cover is None:
            return
        if current is None:
            current = self.local_now()
        fmt = '%I:%M:%S %p' if self.preferences['clock_format'] == '12h' else '%H:%M:%S'
        self.sleep_time.config(text=current.strftime(fmt))
        self.sleep_date.config(text=current.strftime('%A, %d %B %Y'))

    def local_now(self):
        instant = self.worker.clock.now()
        try:
            return instant.astimezone(ZoneInfo(self.clock_status['timezone']))
        except Exception:
            return instant.astimezone()


    def poll_subsystem_events(self):
        if not callable(self.event_source):
            return
        try:
            for event in self.event_source():
                event_type = getattr(event, 'event_type', event)
                name = str(getattr(event_type, 'name', event_type)).upper()
                if name in WAKE_EVENT_NAMES:
                    self.wake(name.lower())
                if self.on_subsystem_event:
                    self.on_subsystem_event(event)
            self.event_error = ''
        except Exception as exc:
            self.event_error = 'Event interface error: ' + str(exc)
            self.system_note = self.event_error


WAKE_EVENT_NAMES = {
    'MOTION_DETECTED', 'WEIGHT_CHANGED', 'WAKE_REQUEST',
    'GAS_ALARM_STARTED', 'TEMP_ALARM_STARTED', 'HUMIDITY_ALARM_STARTED',
    'ENVIRONMENT_SENSOR_FAULT',
}
