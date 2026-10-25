#Inventory page, will have to look back at this 
#Displays interface
from __future__ import annotations
import tkinter as tk
from UI_Scale import ask_scale
from Input_Validation import entry_values
from UI_Widgets import BG, CARD, MUTED, RED, label, button, Sheet, touch_field


class _InventoryScreens:

    def show_record(self, row):
        body = f"{row['item_name']}\n\nBrand: {row['brand_name'] or '--'}\nType: {row['item_category']}\nWeight: {(row['item_weight'] if row['item_weight'] is not None else '--')} g\nPurchased: {row['purchased_on'] or 'Unknown'}\nExpires: {row['expires_on'] or 'Unknown'}\nReminder: {row.get('label', 'No date')}\nEach row is one physical package."
        self.detail_sheet = self.message('Inventory item', body)
        button(self.detail_sheet.footer, 'Update item', lambda: self.edit_record(row)).pack(side='left', padx=3)
        button(
            self.detail_sheet.footer,
            'Remove one',
            lambda: self.remove_record(row),
            danger=True
        ).pack(side='left', padx=3)

    def edit_record(self, row, selected=False):
        cancel = self.cancel_pending if selected else None
        sheet = Sheet(self, 'Update this package', cancel)
        self.edit_sheet = sheet
        names = ('item_name', 'brand_name', 'item_category', 'item_weight', 'purchased_on', 'expires_on')
        values = {key: tk.StringVar(value='' if row.get(key) is None else str(row[key])) for key in names}
        self.edit_values = values
        form = tk.Frame(sheet.body, bg=CARD)
        form.pack(fill='both', expand=True, padx=6, pady=4)
        form.columnconfigure(0, weight=1)
        form.columnconfigure(1, weight=1)
        touch_field(self, form, 'Item name', values['item_name'], 0, span=2)
        touch_field(self, form, 'Brand', values['brand_name'], 1, 0)
        category = touch_field(self, form, 'Item type', values['item_category'], 1, 1)
        category.bind('<Button-1>', lambda e: self.category_picker(values['item_category']))
        touch_field(self, form, 'Weight in grams', values['item_weight'], 2, 0, numeric=True)
        label(form, f"Package {row['kind']}:{row['inventory_id']}\nQuantity stays at one.",
              12, fg=MUTED, justify='left').grid(row=2, column=1, sticky='w', padx=12)
        touch_field(self, form, 'Purchased on', values['purchased_on'], 3, 0, calendar_field=True)
        touch_field(self, form, 'Expires on', values['expires_on'], 3, 1, calendar_field=True)
        self.record_note = label(sheet.footer, 'Only this package changes. Catalogue stays unchanged.',
                                 10, fg=MUTED, bg=BG, wraplength=390, justify='left')
        self.record_note.pack(side='left', expand=True, fill='x')
        cancel_button = button(sheet.footer, 'Cancel', cancel or sheet.close)
        cancel_button.pack(side='right', padx=4)

        def save():
            data = {key: value.get() for key, value in values.items()}
            data['quantity'] = '1'
            try:
                entry_values(data)
            except ValueError as exc:
                self.record_note.config(text=str(exc), fg=RED)
                return
            for b in self.record_buttons:
                b.config(state='disabled')
            self.record_note.config(text='Saving...', fg=MUTED)
            if selected:
                self.worker.send('update_selected', token=self.pending['token'], data=data)
            else:
                self.worker.send('update', record_kind=row['kind'], record_id=row['inventory_id'], data=data)
        save_button = button(sheet.footer, 'Save', save, primary=True)
        save_button.pack(side='right', padx=4)
        weigh = button(sheet.footer, "Weigh", lambda: ask_scale(self, sheet, values["item_weight"]))
        weigh.pack(side="right", padx=4)
        self.record_note.config(wraplength=245)
        self.record_buttons = [save_button, cancel_button, weigh, sheet.close_button]
        ask_scale(self, sheet, values["item_weight"])

    def edit_dates(self, row):
        sheet = Sheet(self, "Edit this package's dates")
        self.edit_sheet = sheet
        purchased = tk.StringVar(value=row['purchased_on'] or '')
        expires = tk.StringVar(value=row['expires_on'] or '')
        label(sheet.body, row['item_name'], 18, True, wraplength=700, justify='left').pack(anchor='w', padx=16, pady=15)
        form = tk.Frame(sheet.body, bg=CARD)
        form.pack(fill='x', padx=8, pady=8)
        form.columnconfigure(0, weight=1)
        form.columnconfigure(1, weight=1)
        touch_field(self, form, 'Purchased on', purchased, 0, 0, calendar_field=True)
        touch_field(self, form, 'Expires on', expires, 0, 1, calendar_field=True)
        label(
            sheet.body,
            'Use the date on this package. Leave unknown dates blank.',
            12,
            fg=MUTED
        ).pack(anchor='w', padx=17, pady=10)
        self.record_note = label(sheet.footer, 'No changes saved yet.', 10, fg=MUTED, bg=BG, wraplength=390)
        self.record_note.pack(side='left', expand=True, fill='x')
        cancel = button(sheet.footer, 'Cancel', sheet.close)
        cancel.pack(side='right', padx=4)

        def save():
            for b in self.record_buttons:
                b.config(state='disabled')
            self.record_note.config(text='Saving...')
            self.worker.send(
                'dates',
                record_kind=row['kind'],
                record_id=row['inventory_id'],
                purchased_on=purchased.get(),
                expires_on=expires.get()
            )
        save_button = button(sheet.footer, 'Save', save, primary=True)
        save_button.pack(side='right', padx=4)
        self.record_buttons = [save_button, cancel, sheet.close_button]

    def remove_record(self, row, selected=False):
        cancel_action = self.cancel_pending if selected else None
        sheet = Sheet(self, 'Remove one package?', cancel_action)
        self.edit_sheet = sheet
        label(sheet.body, row['item_name'], 20, True, wraplength=700, justify='left').pack(padx=20, pady=30)
        label(
            sheet.body,
            f"Package {row['kind']}:{row['inventory_id']} | Expires: {row['expires_on'] or '--'}\n"
            'This marks one package as removed. Its date reminder will also be removed.',
            15,
            justify='left'
        ).pack(padx=20, pady=10)
        self.record_note = label(sheet.footer, '', 10, fg=MUTED, bg=BG, wraplength=390)
        self.record_note.pack(side='left', expand=True, fill='x')
        cancel = button(sheet.footer, 'Cancel', cancel_action or sheet.close)
        cancel.pack(side='right', padx=4)

        def remove():
            for b in self.record_buttons:
                b.config(state='disabled')
            if selected:
                self.worker.send('remove_selected', token=self.pending['token'])
            else:
                self.worker.send('remove', record_kind=row['kind'], record_id=row['inventory_id'])
        remove_button = button(sheet.footer, 'Remove one', remove, danger=True)
        remove_button.pack(side='right', padx=4)
        self.record_buttons = [remove_button, cancel, sheet.close_button]

