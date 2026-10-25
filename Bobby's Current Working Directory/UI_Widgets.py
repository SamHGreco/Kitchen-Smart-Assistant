#Creates touch controls
#NOTE Not a fan of the "keyboard" that it has, might adjust if time allows
from __future__ import annotations
import calendar
import tkinter as tk
from datetime import date
from UI_Theme import BG, CARD, INK, MUTED, TEAL, PALE, LINE, RED, FONT
import UI_Theme as look

def label(parent, text='', size=12, bold=False, fg=INK, bg=CARD, **kwargs):
    return tk.Label(parent, text=text, font=(FONT, size, 'bold' if bold else 'normal'), fg=fg, bg=bg, **kwargs)

def button(parent, text, command, primary=False, danger=False, width=None):
    return tk.Button(
        parent,
        text=text,
        command=command,
        font=(FONT, look.BUTTON_SIZE, 'bold'),
        bg=RED if danger else TEAL if primary else PALE,
        fg='white' if primary or danger else INK,
        activebackground=look.PRESSED,
        activeforeground=INK,
        relief='flat',
        borderwidth=0,
        highlightthickness=1,
        highlightbackground=LINE,
        padx=look.BUTTON_PAD_X,
        pady=look.BUTTON_PAD_Y,
        width=width,
        takefocus=True,
        cursor='hand2'
    )

class Sheet:

    def __init__(self, app, title, on_cancel=None):
        self.app = app
        self.closed = False
        app.worker.set_enabled(False)
        if hasattr(app, 'safe_sensor_call'):
            app.safe_sensor_call('set_ui_home', False)
        self.frame = tk.Frame(app.root, bg=BG)
        self.frame.place(x=0, y=0, relwidth=1, relheight=1)
        self.frame.lift()
        app.sheets.append(self)
        header = tk.Frame(self.frame, bg=TEAL, height=56)
        header.pack(fill='x')
        header.pack_propagate(False)
        label(header, title, 17, True, 'white', TEAL).pack(side='left', padx=18)
        self.cancel_callback = on_cancel or self.close
        self.close_button = button(header, 'Close', self.cancel_callback)
        self.close_button.pack(side='right', padx=8, pady=5)
        self.footer = tk.Frame(self.frame, bg=BG)
        self.footer.pack(side='bottom', fill='x', padx=16, pady=8)
        self.body = tk.Frame(self.frame, bg=CARD, highlightthickness=1, highlightbackground=LINE)
        self.body.pack(fill='both', expand=True, padx=16, pady=(10, 0))
        if hasattr(app, 'place_safety_banner'):
            app.place_safety_banner()

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.frame.destroy()
        if self in self.app.sheets:
            self.app.sheets.remove(self)
        self.app.resume_if_allowed()

def edit_text(app, title, variable, *, numeric=False, maximum=1000):
    sheet = Sheet(app, title)
    value = tk.StringVar(value=variable.get())
    entry = tk.Entry(
        sheet.body,
        textvariable=value,
        font=(FONT, 21),
        relief='flat',
        bg=look.KEYBOARD_FIELD,
        fg=INK,
        insertbackground=INK
    )
    entry.pack(fill='x', padx=14, pady=12, ipady=8)
    entry.focus_set()
    entry.icursor('end')
    keys = tk.Frame(sheet.body, bg=CARD)
    keys.pack(fill='both', expand=True, padx=10, pady=2)
    lower = tk.BooleanVar(value=True)
    rows = ['1234567890', 'qwertyuiop', 'asdfghjkl', 'zxcvbnm', "-_/.:&'"] if not numeric else ['1234567890', '-/:.', '']
    for chars in rows:
        if not chars:
            continue
        row = tk.Frame(keys, bg=CARD)
        row.pack(fill='both', expand=True)
        for c in chars:

            def insert(char=c):
                if len(value.get()) < maximum:
                    entry.insert('insert', char if lower.get() else char.upper())
            b = button(row, c.upper() if c.isalpha() else c, insert)
            b.configure(padx=0, pady=5)
            b.pack(side='left', fill='both', expand=True, padx=2, pady=2)

    def back():
        pos = entry.index('insert')
        if pos > 0:
            entry.delete(pos - 1, pos)

    def done():
        if len(value.get()) <= maximum:
            variable.set(value.get())
            sheet.close()
    button(sheet.footer, 'Cancel', sheet.close).pack(side='left')
    button(sheet.footer, 'Clear', lambda: value.set('')).pack(side='left', padx=5)
    button(sheet.footer, 'Backspace', back).pack(side='left', padx=5)
    if not numeric:
        button(sheet.footer, 'Space', lambda: entry.insert('insert', ' ')).pack(side='left', padx=5)
        button(sheet.footer, 'Aa', lambda: lower.set(not lower.get())).pack(side='left')
    button(sheet.footer, 'Done', done, primary=True).pack(side='right')
    entry.bind('<Return>', lambda e: done())
    entry.bind('<Escape>', lambda e: sheet.close())
    return sheet

def date_picker(app, title, variable):
    sheet = Sheet(app, title)
    try:
        selected = date.fromisoformat(variable.get())
    except (ValueError, TypeError):
        selected = app.local_now().date()
    year, month = (selected.year, selected.month)
    navigation = tk.Frame(sheet.body, bg=CARD)
    navigation.pack(fill='x', padx=10, pady=5)
    heading = label(navigation, '', 17, True)
    heading.pack(side='left', expand=True)
    grid = tk.Frame(sheet.body, bg=CARD)
    grid.pack(fill='both', expand=True, padx=10, pady=5)

    def redraw():
        heading.config(text=f'{calendar.month_name[month]} {year}')
        for child in grid.winfo_children():
            child.destroy()
        for j, name in enumerate(('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')):
            label(grid, name, 11, True, fg=MUTED).grid(row=0, column=j, sticky='nsew')
            grid.columnconfigure(j, weight=1)
        weeks = calendar.monthcalendar(year, month)
        for i, week in enumerate(weeks, 1):
            grid.rowconfigure(i, weight=1)
            for j, day in enumerate(week):
                if day:

                    def choose(d=day):
                        variable.set(date(year, month, d).isoformat())
                        sheet.close()
                    b = button(
                        grid,
                        str(day),
                        choose,
                        primary=(year, month, day) == (selected.year, selected.month, selected.day)
                    )
                    b.config(padx=0, pady=2)
                    b.grid(row=i, column=j, sticky='nsew', padx=2, pady=2)

    def change(delta):
        nonlocal year, month
        total = year * 12 + month - 1 + delta
        year, idx = divmod(total, 12)
        month = idx + 1
        redraw()
    button(navigation, '<', lambda: change(-1)).pack(side='left', padx=4)
    button(navigation, '>', lambda: change(1)).pack(side='right', padx=4)
    button(sheet.footer, 'Cancel', sheet.close).pack(side='left')
    button(sheet.footer, 'Unknown / blank', lambda: (variable.set(''), sheet.close())).pack(side='left', padx=5)
    button(
        sheet.footer,
        'Today',
        lambda: (variable.set(app.local_now().date().isoformat()), sheet.close()),
        primary=True
    ).pack(side='right')
    redraw()
    return sheet

def touch_field(app, parent, caption, var, row, column=0, span=1, *, numeric=False, calendar_field=False):
    block = tk.Frame(parent, bg=CARD)
    block.grid(row=row, column=column, columnspan=span, sticky='nsew', padx=9, pady=3)
    label(block, caption, 10, True, fg=MUTED).pack(anchor='w')
    entry = tk.Entry(
        block,
        textvariable=var,
        readonlybackground=look.FIELD,
        fg=INK,
        font=(FONT, 14),
        relief='flat',
        state='readonly',
        cursor='hand2'
    )
    entry.pack(fill='x', ipady=8)

    def open_editor(e=None):
        if calendar_field:
            date_picker(app, caption, var)
        else:
            edit_text(app, caption, var, numeric=numeric)
        return 'break'
    entry.bind('<Button-1>', open_editor)
    entry.bind('<Return>', open_editor)
    return entry

def quantity_field(app, parent, var, row, column):
    block = tk.Frame(parent, bg=CARD)
    block.grid(row=row, column=column, sticky='nsew', padx=9, pady=3)
    label(block, 'Quantity (1-99)', 10, True, fg=MUTED).pack(anchor='w')
    line = tk.Frame(block, bg=CARD)
    line.pack(fill='x')

    def change(delta):
        try:
            number = int(var.get())
        except ValueError:
            number = 1
        var.set(str(max(1, min(99, number + delta))))
    minus = button(line, '-', lambda: change(-1))
    minus.config(pady=5, padx=18)
    minus.pack(side='left')
    plus = button(line, '+', lambda: change(1))
    plus.config(pady=5, padx=18)
    plus.pack(side='right')
    entry = tk.Entry(
        line,
        textvariable=var,
        readonlybackground=look.FIELD,
        fg=INK,
        font=(FONT, 14),
        justify='center',
        relief='flat',
        state='readonly'
    )
    entry.pack(side='left', fill='both', expand=True, padx=3)
    entry.bind('<Button-1>', lambda e: edit_text(app, 'Quantity', var, numeric=True))
    return entry
