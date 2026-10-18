#UI home screen
#NOTE will have to relook once hardware implemented
#Displays interface
from __future__ import annotations
import tkinter as tk
from tkinter import ttk
import UI_Theme as look
from UI_Widgets import BG, CARD, INK, MUTED, TEAL, PALE, LINE, RED, FONT, label, button, Sheet


class _HomeScreens:

    def _build_home(self):
        self.header = tk.Frame(self.root, bg=TEAL)
        label(self.header, look.APP_TITLE, 14, True, 'white', TEAL).pack(side='left', padx=(10, 8))
        self.add_button = button(self.header, 'Add', self.manual_add)
        self.add_button.pack(side='left', padx=3, pady=6)
        self.update_button = button(self.header, 'Update', lambda: self.browse_records('update'))
        self.update_button.pack(side='left', padx=3, pady=6)
        self.remove_button = button(self.header, 'Remove', lambda: self.browse_records('remove'))
        self.remove_button.pack(side='left', padx=3, pady=6)
        self.alert_button = button(self.header, 'Alerts (0)', self.show_alerts)
        self.alert_button.pack(side='left', padx=3, pady=6)
        button(self.header, 'Settings', self.show_settings).pack(side='left', padx=3, pady=6)
        for child in self.header.winfo_children():
            if isinstance(child, tk.Button):
                child.config(padx=8)
        self.clock_label = label(self.header, '', 11, True, 'white', TEAL, justify='right')
        self.clock_label.pack(side='right', padx=14)
        self.sensor_label = label(
            self.root,
            'Temperature --   |   Humidity --   |   Gas --   |   Not connected',
            10,
            fg=MUTED,
            bg=BG,
            anchor='w'
        )
        self.sensor_label.bind('<ButtonRelease-1>', lambda event: self.environment_alerts())
        self.expiry_banner = button(self.root, 'No date reminders', self.show_alerts)
        self.expiry_banner.config(font=(FONT, 11, 'bold'), pady=2, anchor='w')
        self.card = tk.Frame(self.root, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        self.card_left = tk.Frame(self.card, bg=CARD)
        self.card_left.pack(side='left', fill='both', expand=True, padx=16, pady=10)
        self.eyebrow = label(self.card_left, 'CURRENT SCAN', 10, True, fg=TEAL)
        self.eyebrow.pack(anchor='w')
        self.name_label = label(self.card_left, 'Ready for your next item', 23, True, justify='left', anchor='nw')
        self.name_label.pack(fill='both', expand=True, pady=4)
        self.info_label = label(self.card_left, 'Present one barcode at a time.', 11, fg=MUTED, anchor='w')
        self.info_label.pack(fill='x')
        self.card_right = tk.Frame(self.card, bg=look.PANEL, width=155)
        self.card_right.pack(side='right', fill='y', padx=10, pady=10)
        self.card_right.pack_propagate(False)
        self.count_label = label(self.card_right, '--', 27, True, TEAL, look.PANEL)
        self.count_label.pack(pady=(9, 0))
        label(self.card_right, 'IN INVENTORY', 9, True, MUTED, look.PANEL).pack()
        self.weight_label = label(self.card_right, 'Weight --', 12, True, INK, look.PANEL)
        self.weight_label.pack(pady=10)
        for child in (self.card, self.name_label, self.info_label):
            child.bind('<Button-1>', lambda e: self.show_current())
        self.list_heading = label(self.root, 'CURRENT INVENTORY', 11, True, fg=MUTED, bg=BG, anchor='w')
        style = ttk.Style(master=self.root)
        style.theme_use('clam')
        style.configure(
            'Pantry.Treeview',
            font=(FONT, look.TABLE_TEXT_SIZE),
            rowheight=look.TABLE_ROW_HEIGHT,
            background=CARD,
            foreground=INK,
            fieldbackground=CARD,
            borderwidth=0
        )
        style.configure(
            'Pantry.Treeview.Heading',
            font=(FONT, 10, 'bold'),
            background=PALE,
            foreground=INK,
            padding=6
        )
        style.map('Pantry.Treeview', background=[('selected', look.SELECTED)], foreground=[('selected', INK)])
        self.table = ttk.Treeview(
            self.root,
            columns=('item', 'brand', 'type', 'purchased', 'expires'),
            show='headings',
            style='Pantry.Treeview',
            selectmode='browse'
        )
        for key, title in [
            ('item', 'Item'),
            ('brand', 'Brand'),
            ('type', 'Type'),
            ('purchased', 'Purchased on'),
            ('expires', 'Expires on')
        ]:
            self.table.heading(key, text=title)
            self.table.column(key, anchor='w', minwidth=50)
        self.table.bind('<ButtonRelease-1>', self.row_details)
        for tag, bg, fg in [
            ('past', look.PAST_BG, look.PAST_TEXT),
            ('today', look.PAST_BG, look.PAST_TEXT),
            ('soon', look.SOON_BG, look.SOON_TEXT),
            ('invalid', look.INVALID_BG, look.INVALID_TEXT)
        ]:
            self.table.tag_configure(tag, background=bg, foreground=fg)
        self.footer = tk.Frame(self.root, bg=BG)
        self.status = label(self.footer, 'Starting...', 10, fg=MUTED, bg=BG, anchor='w')
        self.status.pack(side='left', fill='x', expand=True, padx=(12, 0))
        self.pause_button = button(self.footer, 'Pause', self.toggle_pause)
        self.pause_button.pack(side='right', padx=(4, 10), pady=4)
        self.next_button = button(self.footer, 'Next', lambda: self.change_page(1))
        self.next_button.pack(side='right', padx=3, pady=4)
        self.prev_button = button(self.footer, 'Prev', lambda: self.change_page(-1))
        self.prev_button.pack(side='right', padx=3, pady=4)
        self.manual_button = button(self.footer, 'Demo scan' if self.demo else 'Type code', self.typed_scan)
        self.manual_button.pack(side='right', padx=3, pady=4)

    def resize(self, event=None):
        if event and event.widget is not self.root:
            return
        w = max(800, self.root.winfo_width())
        h = max(480, self.root.winfo_height())
        areas = look.home_rects(w, h, bool(self.monitor_message))
        widgets = {'header': self.header, 'sensors': self.sensor_label,
                   'expiry': self.expiry_banner, 'product': self.card,
                   'heading': self.list_heading, 'table': self.table, 'footer': self.footer}
        for name, widget in widgets.items():
            x, y, width, height = areas[name]
            widget.place(x=x, y=y, width=width, height=height)
        size = look.PRODUCT_SIZE_SMALL if w < 950 else look.PRODUCT_SIZE_LARGE
        self.name_label.config(wraplength=max(150, areas['product'][2] - 205),
                               font=(FONT, size, 'bold'))
        for key, fraction in zip(self.table['columns'], look.TABLE_FRACTIONS):
            self.table.column(key, width=int((areas['table'][2] - 4) * fraction))
        new_size = max(1, int((areas['table'][3] - 30) // look.TABLE_ROW_HEIGHT))
        if new_size != getattr(self, 'page_size', None):
            self.page_size = new_size
            self.refresh_table()
        self.place_safety_banner()

    def toggle_fullscreen(self, event=None):
        self.fullscreen = not bool(self.root.attributes('-fullscreen'))
        self.root.attributes('-fullscreen', self.fullscreen)

    def refresh_table(self):
        size = getattr(self, 'page_size', 3)
        maximum = max(0, (len(self.rows) - 1) // size)
        self.page = min(self.page, maximum)
        for iid in self.table.get_children():
            self.table.delete(iid)
        start = self.page * size
        for i, row in enumerate(self.rows[start:start + size], start):
            self.table.insert(
                '',
                'end',
                iid=str(i),
                values=(row['item_name'], row['brand_name'] or '--', row['item_category'], row['purchased_on'] or '--', row['expires_on'] or '--'),
                tags=(row.get('state', 'unknown'),)
            )
        shown = f'{self.total} packages'
        if self.total > len(self.rows):
            shown += ' (latest 200 shown)'
        self.list_heading.config(text='CURRENT INVENTORY  /  ' + shown + '  /  tap a row for details')
        self.prev_button.config(state='normal' if self.page > 0 else 'disabled')
        self.next_button.config(state='normal' if self.page < maximum else 'disabled')

    def change_page(self, delta):
        self.page = max(0, self.page + delta)
        self.refresh_table()

    def row_details(self, event=None):
        selection = self.table.selection()
        if selection:
            self.show_record(self.rows[int(selection[0])])

    def message(self, title, text, danger=False):
        sheet = Sheet(self, title)
        t = tk.Text(
            sheet.body,
            wrap='word',
            font=(FONT, 15),
            bg=CARD,
            fg=RED if danger else INK,
            relief='flat',
            padx=16,
            pady=16
        )
        t.insert('1.0', text)
        t.configure(state='disabled')
        t.pack(fill='both', expand=True)
        button(sheet.footer, 'OK', sheet.close, primary=True).pack(side='right')
        button(sheet.footer, 'Down', lambda: t.yview_scroll(4, 'units')).pack(side='right', padx=4)
        button(sheet.footer, 'Up', lambda: t.yview_scroll(-4, 'units')).pack(side='right', padx=4)
        return sheet

    def show_current(self):
        if not self.last_product:
            return
        p = self.last_product
        self.message('Last scanned item', f"{p['item_name']}\n\nBrand: {p['brand_name'] or '--'}\nType: {p['item_category']}\nBarcode: {self.last_raw}\nWeight: {(p['item_weight'] if p['item_weight'] is not None else '--')} g\nIn inventory: {self.last_count}")

    def display_product(self, p, raw, count):
        self.last_product = p
        self.last_raw = raw
        self.last_count = count
        name = p['item_name'] if p else 'Product not found'
        self.name_label.config(text=name if len(name) <= 105 else name[:102] + '...')
        desc = ' | '.join((x for x in (p.get('brand_name', ''), p.get('item_category', '')) if x)) if p else 'Enter the details to learn this barcode.'
        self.info_label.config(text=desc[:85])
        self.count_label.config(text=str(count))
        weight = p.get('item_weight') if p else None
        self.weight_label.config(text=f'{weight:g} g' if isinstance(weight, (int, float)) else 'Weight --')

    def show_alerts(self):
        sheet = Sheet(self, 'Date reminders and alerts')
        self.alert_sheet = sheet
        self.alert_info = label(sheet.body, '', 11, fg=MUTED, justify='left', wraplength=700)
        self.alert_info.pack(fill='x', padx=12, pady=10)
        frame = tk.Frame(sheet.body, bg=CARD)
        frame.pack(fill='both', expand=True, padx=8, pady=5)
        self.alert_tree = ttk.Treeview(
            frame,
            columns=('item', 'date', 'status'),
            show='headings',
            style='Pantry.Treeview',
            selectmode='browse'
        )
        for key, title, width in [('item', 'Item', 320), ('date', 'Expires on', 120), ('status', 'Reminder', 230)]:
            self.alert_tree.heading(key, text=title)
            self.alert_tree.column(key, width=width, minwidth=70, anchor='w')
        scrollbar = ttk.Scrollbar(frame, orient='vertical', command=self.alert_tree.yview)
        scrollbar.pack(side='right', fill='y')
        self.alert_tree.configure(yscrollcommand=scrollbar.set)
        self.alert_tree.pack(side='left', fill='both', expand=True)
        for tag, bg in [('past', look.PAST_BG), ('today', look.PAST_BG), ('soon', look.SOON_BG), ('invalid', look.INVALID_BG)]:
            self.alert_tree.tag_configure(tag, background=bg)

        def details():
            selected = self.alert_tree.selection()
            if selected:
                for row in self.expiry_alerts:
                    if f"{row['kind']}:{row['inventory_id']}" == selected[0]:
                        self.show_record(row)
                        return
        button(sheet.footer, 'Environment', self.environment_alerts).pack(side='left')
        button(sheet.footer, 'Up', lambda: self.alert_tree.yview_scroll(-3, 'units')).pack(side='left', padx=4)
        button(sheet.footer, 'Down', lambda: self.alert_tree.yview_scroll(3, 'units')).pack(side='left', padx=4)
        button(sheet.footer, 'Selected item', details, primary=True).pack(side='right', padx=4)
        button(sheet.footer, 'Close', sheet.close).pack(side='right', padx=4)
        self.refresh_alerts()
        self.worker.send('refresh')

    def refresh_alerts(self):
        count = len(self.expiry_alerts)
        self.alert_button.config(text=f'Alerts ({count})')
        past = sum((row['state'] == 'past' for row in self.expiry_alerts))
        today = sum((row['state'] == 'today' for row in self.expiry_alerts))
        soon = sum((row['state'] == 'soon' for row in self.expiry_alerts))
        invalid = sum((row['state'] == 'invalid' for row in self.expiry_alerts))
        parts = []
        if past:
            parts.append(f'{past} past date')
        if today:
            parts.append(f'{today} due today')
        if soon:
            parts.append(f'{soon} due soon')
        if invalid:
            parts.append(f'{invalid} dates to check')
        text = '  |  '.join(parts) if parts else 'No date reminders'
        if self.undated:
            text += f'  |  {self.undated} without dates'
        color = look.PAST_BG if past or today else look.SOON_BG if count else PALE
        self.expiry_banner.config(text='DATE REMINDERS  /  ' + text, bg=color, fg=INK)
        if self.alert_sheet and (not self.alert_sheet.closed):
            selected = self.alert_tree.selection()
            for iid in self.alert_tree.get_children():
                self.alert_tree.delete(iid)
            for index, row in enumerate(self.expiry_alerts):
                iid = f"{row['kind']}:{row['inventory_id']}"
                self.alert_tree.insert(
                    '',
                    'end',
                    iid=iid,
                    values=(row['item_name'], row['expires_on'] or '--', row['label']),
                    tags=(row['state'],)
                )
            if selected and selected[0] in self.alert_tree.get_children():
                self.alert_tree.selection_set(selected[0])
            self.alert_info.config(text=f'{count} date reminders. {self.undated} packages have no date.\nDates are reminders, not a food-safety assessment. Check Environment for sensor status.')

