#Settings page
#NOTE will have to relook at this

#Displays interface
from __future__ import annotations
import tkinter as tk
import UI_Theme as look
from UI_Scale import ask_tare
from Input_Validation import save_preferences
from UI_Widgets import CARD, INK, MUTED, FONT, label, button, Sheet, touch_field


class _SettingsScreens:

    def show_settings(self):
        sheet = Sheet(self, 'Settings', compact=True)
        label(sheet.body, 'Settings', 16, True).pack(anchor='w', padx=14, pady=(8, 5))
        content = tk.Frame(sheet.body, bg=CARD)
        content.pack(fill='both', expand=True, padx=10, pady=4)
        content.columnconfigure(0, weight=3, uniform='settings')
        content.columnconfigure(1, weight=2, uniform='settings')
        tools = tk.Frame(content, bg=CARD)
        tools.grid(row=0, column=0, sticky='nsew', padx=(0, 12))
        tools.columnconfigure(0, weight=1)
        tools.columnconfigure(1, weight=1)
        actions = (
            ('Display Settings', self.show_display_settings),
            ('Calibrate', self.show_calibration),
            ('Environmental Status', self.environment_alerts),
            ('Preview sleep', lambda: (sheet.close(), self.sleep())),
        )
        for index, (caption, action) in enumerate(actions):
            control = button(tools, caption, action, primary=index < 2)
            control.config(padx=8, pady=15, wraplength=160)
            control.grid(row=index // 2, column=index % 2,
                         sticky='nsew', padx=4, pady=6)
        reminders = tk.Frame(content, bg=CARD)
        reminders.grid(row=0, column=1, sticky='nsew')
        label(reminders, 'Food-age reminders', 13, True).pack(anchor='w', pady=(5, 2))
        lead = tk.StringVar(value=str(self.preferences['expiry_warning_days']))
        form = tk.Frame(reminders, bg=CARD)
        form.pack(fill='x')
        form.columnconfigure(0, weight=1)
        touch_field(self, form, 'Days before expiration (0-365)', lead, 0, numeric=True)
        note = label(reminders, 'Saved separately from display settings.', 10,
                     fg=MUTED, wraplength=240, justify='left')
        note.pack(anchor='w', padx=9, pady=5)

        def save_reminders():
            try:
                days = int(lead.get())
                if not 0 <= days <= 365:
                    raise ValueError('Choose 0 to 365 warning days.')
                updated = dict(self.preferences, expiry_warning_days=days)
                if not self.demo:
                    save_preferences(self.preferences_path, updated)
                self.preferences.update(updated)
                self.worker.send('warning_days', days=days)
                note.config(text='Reminder setting saved.', fg=look.TEAL)
            except (ValueError, OSError) as exc:
                note.config(text=str(exc), fg=look.RED)
        button(reminders, 'Save reminders', save_reminders).pack(anchor='w', padx=9, pady=5)
        button(sheet.footer, 'Quit application', self.quit, danger=True).pack(side='right')

    def show_clock(self):
        # Keep the legacy entry point, but open the combined display page.
        self.show_display_settings()

    def confirm_clock(self):
        values = {k: v.get() for k, v in self.clock_vars.items()}
        owner = self.clock_sheet
        note, apply_button = self.clock_note, self.clock_apply
        confirm = Sheet(self, 'Confirm date/time', compact=True)
        label(confirm.body, 'Confirm date/time', 17, True).pack(anchor='w', padx=18, pady=(16, 8))
        label(confirm.body, 'This changes ' + ('only the demo clock.' if self.demo else
              "this Raspberry Pi's system clock settings."), 13, True,
              wraplength=680).pack(anchor='w', padx=18, pady=6)
        mode = ('Network time will be enabled. Entered date/time will not be used.'
                if values['ntp'] else 'Network time will be disabled.\n'
                'Date: ' + values['date_text'] + '   Time: ' + values['time_text'])
        label(confirm.body, mode + '\nTime zone: ' + values['zone'], 12,
              wraplength=680, justify='left').pack(anchor='w', padx=18, pady=10)

        def apply():
            if owner.closed or self.closing:
                confirm.close()
                return
            confirm.close()
            note.config(text='Applying clock settings...')
            apply_button.config(state='disabled')
            self.worker.send('clock_set', **values)
        confirm.close_button.config(text='Cancel')
        button(confirm.footer, 'Apply', apply, primary=True).pack(side='right')

    def show_display_settings(self):
        self.worker.send('clock_status')
        status = self.clock_status
        now = self.local_now()
        sheet = Sheet(self, 'Display Settings', compact=True)
        self.clock_sheet = sheet
        label(sheet.body, 'Display Settings', 16, True).pack(anchor='w', padx=14, pady=(8, 4))
        content = tk.Frame(sheet.body, bg=CARD)
        content.pack(fill='both', expand=True, padx=12, pady=2)
        content.columnconfigure(0, weight=1, uniform='display')
        content.columnconfigure(1, weight=1, uniform='display')
        left = tk.Frame(content, bg=CARD)
        right = tk.Frame(content, bg=CARD)
        left.grid(row=0, column=0, sticky='nsew', padx=(0, 12))
        right.grid(row=0, column=1, sticky='nsew')
        unit = tk.StringVar(value=self.preferences['temperature_unit'])
        fmt = tk.StringVar(value=self.preferences['clock_format'])
        idle = tk.StringVar(value=str(self.preferences['idle_seconds']))
        self.display_vars = {'temperature_unit': unit, 'clock_format': fmt, 'idle_seconds': idle}
        for caption, variable, choices in (
            ('Temperature scale', unit, (('C', 'Celsius'), ('F', 'Fahrenheit'))),
            ('Clock display', fmt, (('12h', '12-hour'), ('24h', '24-hour'))),
        ):
            label(left, caption, 11, True, fg=MUTED).pack(anchor='w', pady=(5, 0))
            row = tk.Frame(left, bg=CARD)
            row.pack(fill='x', pady=(0, 5))
            for value, text in choices:
                tk.Radiobutton(row, text=text, variable=variable, value=value,
                               font=(FONT, 12), bg=CARD, padx=5, pady=5).pack(side='left')
        form = tk.Frame(left, bg=CARD)
        form.pack(fill='x')
        form.columnconfigure(0, weight=1)
        touch_field(self, form, 'Sleep after seconds (0 = never)', idle, 0, numeric=True)
        self.sleep_note = label(left, 'Save display applies these three settings.\n'
                                'Sleep uses the black clock screen, not backlight power-off.',
                                10, fg=MUTED, wraplength=320, justify='left')
        self.sleep_note.pack(anchor='w', padx=9, pady=6)

        self.clock_vars = {
            'date_text': tk.StringVar(value=now.strftime('%Y-%m-%d')),
            'time_text': tk.StringVar(value=now.strftime('%H:%M:%S')),
            'zone': tk.StringVar(value=status.get('timezone') or 'UTC'),
            'ntp': tk.BooleanVar(value=bool(status.get('ntp', True))),
        }
        form = tk.Frame(right, bg=CARD)
        form.pack(fill='x')
        form.columnconfigure(0, weight=1)
        form.columnconfigure(1, weight=1)
        touch_field(self, form, 'Date (YYYY-MM-DD)', self.clock_vars['date_text'],
                    0, 0, calendar_field=True)
        touch_field(self, form, 'Time (HH:MM:SS, 24h)', self.clock_vars['time_text'],
                    0, 1, numeric=True)
        touch_field(self, form, 'Time zone (e.g. America/New_York)',
                    self.clock_vars['zone'], 1, span=2)
        tk.Checkbutton(right, text='Automatic network time',
                       variable=self.clock_vars['ntp'], bg=CARD, fg=INK,
                       font=(FONT, 11), anchor='w', pady=4).pack(fill='x', padx=5)
        label(right, 'Uncheck automatic time to use the entered date/time.',
              10, fg=MUTED, wraplength=320, justify='left').pack(anchor='w', padx=9)
        self.clock_note = label(right, status.get('message') or 'Apply date/time requires confirmation.',
                                10, fg=MUTED, wraplength=320, justify='left')
        self.clock_note.pack(anchor='w', padx=9, pady=5)

        def save_display():
            try:
                seconds = int(idle.get())
                if not 0 <= seconds <= 3600:
                    raise ValueError('Sleep seconds must be 0 to 3600.')
                if unit.get() not in ('C', 'F') or fmt.get() not in ('12h', '24h'):
                    raise ValueError('Choose a temperature scale and clock format.')
                updated = dict(self.preferences, temperature_unit=unit.get(),
                               clock_format=fmt.get(), idle_seconds=seconds)
                old_seconds = self.preferences['idle_seconds']
                # Existing UI API: no sensor polling, driver, or gas settings changed.
                self.sensors.set_sleep_timeout(seconds)
                try:
                    if not self.demo:
                        save_preferences(self.preferences_path, updated)
                except OSError:
                    self.sensors.set_sleep_timeout(old_seconds)
                    raise
                self.preferences.update(updated)
                self.wake_control.touch()
                self.last_clock_tick = self.last_sensor_tick = 0
                self.sleep_note.config(text='Display settings saved. Date/time was not changed.',
                                       fg=look.TEAL)
            except (ValueError, TypeError, OSError, RuntimeError) as exc:
                self.sleep_note.config(text='Not saved: ' + str(exc), fg=look.RED)

        button(sheet.footer, 'Save display', save_display, primary=True).pack(side='left')
        self.clock_apply = button(sheet.footer, 'Apply date/time', self.confirm_clock, primary=True)
        self.clock_apply.pack(side='right')
        if status.get('supported') is False:
            self.clock_apply.config(state='disabled')

