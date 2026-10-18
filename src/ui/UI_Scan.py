#Displays interface
from __future__ import annotations
import tkinter as tk
from tkinter import ttk
from UI_Scale import ask_scale, check_scale_quantity
from Input_Validation import CATEGORIES, entry_values
from UI_Widgets import BG, CARD, MUTED, RED, FONT, label, button, Sheet, edit_text, touch_field, quantity_field


class _ScanScreens:

    def typed_scan(self):
        if not self.ready or self.pending or self.requesting_selection:
            return
        self.worker.set_enabled(False)
        if self.demo:
            self.worker.send('lookup', raw='123456789012')
            return
        sheet = Sheet(self, 'Enter a complete barcode')
        value = tk.StringVar()
        label(sheet.body, 'Keep every leading zero. No quotes.', 16).pack(pady=30)
        entry = tk.Entry(sheet.body, textvariable=value, font=(FONT, 24), justify='center')
        entry.pack(fill='x', padx=30, ipady=10)
        button(sheet.body, 'Open keypad', lambda: edit_text(self, 'Barcode', value, numeric=True)).pack(pady=16)

        def go():
            if value.get().strip():
                sheet.close()
                self.worker.send('lookup', raw=value.get())
        button(sheet.footer, 'Cancel', sheet.close).pack(side='left')
        button(sheet.footer, 'Look up', go, primary=True).pack(side='right')

    def manual_add(self):
        if not self.ready or self.pending or self.requesting_selection:
            return
        self.worker.set_enabled(False)
        self.worker.send('manual')

    def handle_scan(self, pending):
        self.pending = pending
        self.set_transaction(True)
        self.safe_sensor_call('notify_barcode')
        self.display_product(pending['product'], pending['raw'], pending['count'])
        if self.sheets:
            self.deferred = pending
            return
        if pending['count'] > 0:
            sheet = Sheet(self, 'Matching item found', self.cancel_pending)
            self.active_form = sheet
            name = pending['product']['item_name'] if pending['product'] else 'This barcode is in inventory'
            label(sheet.body, name[:180], 21, True,
                  wraplength=max(700, self.root.winfo_width() - 100),
                  justify='left').pack(anchor='w', padx=20, pady=22)
            label(sheet.body, 'Add, delete or update?', 20, True).pack(anchor='w', padx=20, pady=8)
            label(sheet.body,
                  f"Already recorded: {pending['count']} package(s).\n"
                  'Add = another package. Update or Delete = choose an existing package.',
                  13, fg=MUTED, wraplength=700,
                  justify='left').pack(anchor='w', padx=20, pady=12)

            def add():
                for b in self.scan_buttons:
                    b.config(state='disabled')
                self.worker.send('new', token=pending['token'])
            cancel = button(sheet.footer, 'Cancel', self.cancel_pending)
            cancel.pack(side='left')
            delete = button(sheet.footer, 'Delete', lambda: self.browse_records('remove'), danger=True)
            delete.pack(side='right', padx=4)
            update = button(sheet.footer, 'Update', lambda: self.browse_records('update'))
            update.pack(side='right', padx=4)
            add_button = button(sheet.footer, 'Add', add, primary=True)
            add_button.pack(side='right', padx=4)
            self.scan_buttons = [cancel, delete, update, add_button, sheet.close_button]
        else:
            self.show_add_form(pending)

    def browse_records(self, action):
        if not self.ready or self.requesting_selection:
            return
        self.requesting_selection = True
        self.worker.set_enabled(False)
        self.set_transaction(True)
        for b in self.scan_buttons:
            if b.winfo_exists():
                b.config(state='disabled')
        self.worker.send('select', action=action, token=self.pending['token'] if self.pending else None)

    def close_operation_sheets(self):
        if self.weight_prompt is not None:
            self.weight_prompt.close()
        for attr in ('edit_sheet', 'detail_sheet', 'selection_sheet', 'active_form'):
            sheet = getattr(self, attr)
            setattr(self, attr, None)
            if sheet is not None:
                sheet.close()
        self.scan_buttons = []
        self.selection_buttons = []
        self.record_buttons = []

    def show_selection(self, event):
        self.requesting_selection = False
        self.pending = event['pending']
        self.set_transaction(True)
        self.close_operation_sheets()
        action = event['action']
        rows = event['rows']
        sheet = Sheet(self, 'Choose a package to ' + action, self.cancel_pending)
        self.selection_sheet = sheet
        label(sheet.body, f'{len(rows)} active package(s). Select one row, then tap Continue.',
              12, fg=MUTED, wraplength=700).pack(anchor='w', padx=12, pady=12)
        if not rows:
            label(sheet.body, 'Item does not exist in inventory.' if self.pending['code']
                  else 'No active items in inventory.', 18, True).pack(pady=25)
        frame = tk.Frame(sheet.body, bg=CARD)
        frame.pack(fill='both', expand=True, padx=8, pady=6)
        tree = ttk.Treeview(frame, columns=('id', 'name', 'weight', 'expires'),
                            show='headings', style='Pantry.Treeview', selectmode='browse')
        for key, title, width in [('id', 'Package ID', 100), ('name', 'Item', 340),
                                  ('weight', 'Grams', 90), ('expires', 'Expires on', 130)]:
            tree.heading(key, text=title)
            tree.column(key, width=width, minwidth=60, anchor='w')
        scrollbar = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
        scrollbar.pack(side='right', fill='y')
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side='left', fill='both', expand=True)
        row_by_id = {}
        for row in rows:
            iid = f"{row['kind']}:{row['inventory_id']}"
            row_by_id[iid] = row
            tree.insert('', 'end', iid=iid, values=(iid, row['item_name'],
                        row['item_weight'] if row['item_weight'] is not None else '--',
                        row['expires_on'] or '--'))
        self.selection_tree = tree

        def choose():
            selected = tree.selection()
            if not selected:
                return
            row = row_by_id[selected[0]]
            for b in self.selection_buttons:
                b.config(state='disabled')
            self.worker.send('select_record', token=self.pending['token'],
                             record_kind=row['kind'], record_id=row['inventory_id'])
        cancel = button(sheet.footer, 'Cancel', self.cancel_pending)
        cancel.pack(side='left')
        button(sheet.footer, 'Up', lambda: tree.yview_scroll(-3, 'units')).pack(side='left', padx=4)
        button(sheet.footer, 'Down', lambda: tree.yview_scroll(3, 'units')).pack(side='left', padx=4)
        go = button(sheet.footer, 'Continue', choose, primary=True)
        go.config(state='disabled')
        go.pack(side='right')
        tree.bind('<<TreeviewSelect>>', lambda e: go.config(state='normal' if tree.selection() else 'disabled'))
        self.selection_buttons = [cancel, go, sheet.close_button]

    def finish_pending(self, kind):
        if self.pending:
            self.worker.send(kind, token=self.pending['token'])

    def cancel_pending(self):
        self.finish_pending('cancel')

    def show_add_form(self, pending):
        self.pending = pending
        self.set_transaction(True)
        sheet = Sheet(self, 'Add item' if pending.get('product') else 'Manual add item', self.cancel_pending)
        self.active_form = sheet
        product = pending.get('product') or {}
        self.form_values = {k: tk.StringVar(value=str(product.get(k) if product.get(k) is not None else '')) for k in ('item_name', 'brand_name', 'item_category', 'item_weight')}
        self.form_values.update(
            quantity=tk.StringVar(value='1'),
            purchased_on=tk.StringVar(value=self.local_now().date().isoformat()),
            expires_on=tk.StringVar(value='')
        )
        self.form_values['item_category'].set(product.get('item_category', 'Unclassified'))
        form = tk.Frame(sheet.body, bg=CARD)
        form.pack(fill='both', expand=True, padx=6, pady=4)
        form.columnconfigure(0, weight=1)
        form.columnconfigure(1, weight=1)
        touch_field(self, form, 'Item name', self.form_values['item_name'], 0, span=2)
        touch_field(self, form, 'Brand (optional)', self.form_values['brand_name'], 1, 0)
        category = touch_field(self, form, 'Item type', self.form_values['item_category'], 1, 1)
        category.bind('<Button-1>', lambda e: self.category_picker(self.form_values['item_category']))
        quantity_field(self, form, self.form_values['quantity'], 2, 0)
        touch_field(self, form, 'Weight in grams (optional)', self.form_values['item_weight'], 2, 1, numeric=True)
        touch_field(
            self,
            form,
            'Purchased on (editable)',
            self.form_values['purchased_on'],
            3,
            0,
            calendar_field=True
        )
        touch_field(self, form, 'Expires on (optional)', self.form_values['expires_on'], 3, 1, calendar_field=True)
        self.form_note = label(
            sheet.footer,
            'Nothing is saved until Add.',
            10,
            fg=MUTED,
            bg=BG,
            wraplength=390,
            justify='left'
        )
        self.form_note.pack(side='left', fill='x', expand=True)
        cancel = button(sheet.footer, 'Cancel', self.cancel_pending)
        cancel.pack(side='right', padx=4)
        save = button(sheet.footer, 'Add', self.submit_form, primary=True)
        save.pack(side='right', padx=4)
        weigh = button(sheet.footer, "Weigh", lambda: ask_scale(self, sheet, self.form_values["item_weight"], self.form_values["quantity"]))
        weigh.pack(side="right", padx=4)
        self.form_note.config(wraplength=245)
        self.form_buttons = [save, cancel, weigh, sheet.close_button]
        ask_scale(self, sheet, self.form_values["item_weight"], self.form_values["quantity"])

    def submit_form(self):
        try:
            check_scale_quantity(self.active_form, self.form_values)
            values = {k: v.get() for k, v in self.form_values.items()}
            entry_values(values)
        except ValueError as exc:
            self.form_note.config(text=str(exc), fg=RED)
            return
        for b in self.form_buttons:
            b.config(state='disabled')
        self.form_note.config(text='Saving...', fg=MUTED)
        self.worker.send('save', token=self.pending['token'], data=values)

    def category_picker(self, var):
        sheet = Sheet(self, 'Choose an item type')
        for i, cat in enumerate(CATEGORIES):
            b = button(sheet.body, cat, lambda c=cat: (var.set(c), sheet.close()))
            b.grid(row=i // 2, column=i % 2, sticky='nsew', padx=8, pady=5)
            sheet.body.rowconfigure(i // 2, weight=1)
            sheet.body.columnconfigure(i % 2, weight=1)
        button(
            sheet.footer,
            'Custom type',
            lambda: (sheet.close(), edit_text(self, 'Item type', var))
        ).pack(side='left')
        button(sheet.footer, 'Cancel', sheet.close).pack(side='right')
        return 'break'

