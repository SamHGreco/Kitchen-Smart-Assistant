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
        sheet = Sheet(self, 'Settings')
        left = tk.Frame(sheet.body, bg=CARD)
        left.pack(side='left', fill='both', expand=True, padx=20, pady=15)
        label(left, 'Display', 20, True).pack(anchor='w', pady=(0, 10))
        unit = tk.StringVar(value=self.preferences['temperature_unit'])
        fmt = tk.StringVar(value=self.preferences['clock_format'])
        label(left, 'Temperature scale', 12, fg=MUTED).pack(anchor='w')
        row = tk.Frame(left, bg=CARD)
        row.pack(anchor='w', pady=5)
        for u in ('C', 'F'):
            tk.Radiobutton(
                row,
                text='Celsius' if u == 'C' else 'Fahrenheit',
                variable=unit,
                value=u,
                font=(FONT, 13),
                bg=CARD,
                padx=10,
                pady=8
            ).pack(side='left')
        label(left, 'Clock display', 12, fg=MUTED).pack(anchor='w', pady=(10, 0))
        row = tk.Frame(left, bg=CARD)
        row.pack(anchor='w', pady=5)
        for f in ('12h', '24h'):
            tk.Radiobutton(
                row,
                text='12-hour' if f == '12h' else '24-hour',
                variable=fmt,
                value=f,
                font=(FONT, 13),
                bg=CARD,
                padx=10,
                pady=8
            ).pack(side='left')
        lead = tk.StringVar(value=str(self.preferences['expiry_warning_days']))
        block = tk.Frame(left, bg=CARD)
        block.pack(fill='x', pady=(8, 0))
        block.columnconfigure(0, weight=1)
        touch_field(self, block, 'Warn this many days before expiration', lead, 0, numeric=True)
        right = tk.Frame(sheet.body, bg=look.PANEL)
        right.pack(side='right', fill='both', expand=True, padx=14, pady=8)
        label(right, 'Tools', 18, True, bg=look.PANEL).pack(anchor='w', padx=14, pady=(8, 4))
        actions = [
            ('Set date / time', self.show_clock),
            ('Wake / gas settings', self.show_wake_settings),
            ('Tare scale', lambda: ask_tare(self, sheet)),
            ('Calibrate scale', self.show_scale_calibration),
            ('Calibrate gas', self.show_gas_calibration),
            ('Preview sleeping screen', lambda: (sheet.close(), self.sleep())),
            ('Quit application', self.quit),
        ]
        tools = tk.Frame(right, bg=look.PANEL)
        tools.pack(fill='both', expand=True, padx=10)
        tools.columnconfigure(0, weight=1)
        tools.columnconfigure(1, weight=1)
        for index, (caption, action) in enumerate(actions):
            control = button(tools, caption, action, primary=caption == 'Tare scale')
            control.config(pady=7, padx=5, wraplength=135)
            control.grid(row=index // 2, column=index % 2, sticky='nsew', padx=3, pady=3)
        label(right, '', 10,
              fg=MUTED, bg=look.PANEL, wraplength=290, justify='left').pack(padx=14, pady=5)

        def save():
            try:
                days = int(lead.get())
                if not 0 <= days <= 365:
                    raise ValueError('Choose 0 to 365 warning days.')
                self.preferences.update(
                    temperature_unit=unit.get(),
                    clock_format=fmt.get(),
                    expiry_warning_days=days
                )
                if not self.demo:
                    save_preferences(self.preferences_path, self.preferences)
                self.worker.send('warning_days', days=days)
                sheet.close()
                self.last_clock_tick = 0
                self.last_sensor_tick = 0
            except (ValueError, OSError) as exc:
                self.message('Settings not saved', str(exc), danger=True)
        button(sheet.footer, 'Cancel', sheet.close).pack(side='left')
        button(sheet.footer, 'Save display settings', save, primary=True).pack(side='right')

    def show_clock(self):
        self.worker.send('clock_status')
        status = self.clock_status
        now = self.local_now()
        sheet = Sheet(self, 'Date & time' + (' - demo' if self.demo else ''))
        self.clock_sheet = sheet
        self.clock_vars = {
            'date_text': tk.StringVar(value=now.strftime('%Y-%m-%d')),
            'time_text': tk.StringVar(value=now.strftime('%H:%M:%S')),
            'zone': tk.StringVar(value=status.get('timezone') or 'UTC'),
            'ntp': tk.BooleanVar(value=bool(status.get('ntp', True)))
        }
        grid = tk.Frame(sheet.body, bg=CARD)
        grid.pack(fill='x', padx=8, pady=8)
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)
        touch_field(self, grid, 'Date', self.clock_vars['date_text'], 0, 0, calendar_field=True)
        touch_field(self, grid, 'Time (24-hour HH:MM:SS)', self.clock_vars['time_text'], 0, 1, numeric=True)
        touch_field(self, grid, 'Time zone (IANA name, e.g. Europe/London)', self.clock_vars['zone'], 1, span=2)
        tk.Checkbutton(
            sheet.body,
            text='Automatic network time (requires a time source)',
            variable=self.clock_vars['ntp'],
            bg=CARD,
            fg=INK,
            font=(FONT, 13),
            padx=15,
            pady=10,
            anchor='w'
        ).pack(fill='x')
        label(
            sheet.body,
            'Uncheck automatic time to set the entered date/time.\nManual mode disables network time.   ',
            11,
            fg=MUTED,
            justify='left'
        ).pack(anchor='w', padx=18, pady=5)
        self.clock_note = label(
            sheet.body,
            status.get('message', 'Reading clock status...'),
            11,
            fg=MUTED,
            wraplength=max(700, self.root.winfo_width() - 70),
            justify='left'
        )
        self.clock_note.pack(anchor='w', padx=18, pady=8)
        button(sheet.footer, 'Cancel', sheet.close).pack(side='left')
        self.clock_apply = button(sheet.footer, 'Apply clock settings', self.confirm_clock, primary=True)
        self.clock_apply.pack(side='right')
        if status.get('supported') is False:
            self.clock_apply.config(state='disabled')

    def confirm_clock(self):
        values = {k: v.get() for k, v in self.clock_vars.items()}
        confirm = Sheet(self, 'Confirm clock change')
        label(
            confirm.body,
            'This changes ' + ('only the demo clock.' if self.demo else "this Raspberry Pi's system clock settings."),
            20,
            True,
            wraplength=700
        ).pack(pady=25)
        mode = 'Network time will be enabled. Synchronization may take time.' if values['ntp'] else 'Network time will be disabled.\nDate: ' + values['date_text'] + '   Time: ' + values['time_text']
        label(
            confirm.body,
            mode + '\nTime zone: ' + values['zone'],
            15,
            wraplength=700,
            justify='left'
        ).pack(pady=15)

        def apply():
            confirm.close()
            self.clock_note.config(text='Applying clock settings...')
            self.clock_apply.config(state='disabled')
            self.worker.send('clock_set', **values)
        button(confirm.footer, 'Cancel', confirm.close).pack(side='left')
        button(confirm.footer, 'Apply', apply, primary=True).pack(side='right')

