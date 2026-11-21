"""Tkinter list/detail screens with shared control and field-binding conventions."""

import json
import re
import sqlite3
import traceback
import tkinter as tk
import webbrowser
from datetime import datetime
from html import escape
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk

from . import VERSION
from .backs import (
    INCH, PALETTE, escaped_legend, generate_layouts, layout_from_record, layout_svg,
    palette_suggestion, ratio_label,
)
from .database import (
    DROPDOWN_COLUMNS, DROPDOWN_FILTER_FIELDS, DROPDOWN_SCOPE_FIELDS, HELP_FILTER_FIELDS,
    HISTORY_FILTER_FIELDS, HISTORY_COLUMNS, Database,
)
from .block_ui import BlockScreenMixin
from .quilt_ui import QuiltScreenMixin
from .errors import ERROR_COLUMNS, ERROR_FIELDS, ERROR_FILTER_FIELDS
from .helptext import (
    BACK_COLUMNS, BACK_FILTER_FIELDS, BACK_LAYOUT_COLUMNS, HELP_COLUMNS, HELP_FIELDS, NAVIGATION, SCREEN_FIELDS,
)
from .model import (
    ADD_ITEM, DROPDOWN_FIELDS, FABRIC_FIELDS, FILTER_FIELDS, LIST_COLUMNS, NUMERIC_COLUMNS,
    SORT_FIELDS, Field, FieldError, caption, display_measurement, measurement, normalize_sort,
    validate_fields,
)


class ToolTip:
    """Look up current database text on hover; never retain a grab or stale window."""

    def __init__(self, widget, text):
        self.widget, self.text = widget, text
        self.window = self.timer = None
        widget.bind("<Enter>", self.schedule, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")
        widget.bind("<Unmap>", self.hide, add="+")
        widget.bind("<Destroy>", self.hide, add="+")

    def schedule(self, event=None):
        self.hide()
        self.timer = self.widget.after(450, self.show)

    def show(self):
        self.timer = None
        text = self.text()
        if not text:
            return
        self.window = tk.Toplevel(self.widget)
        self.window.overrideredirect(True)
        self.window.geometry(f"+{self.widget.winfo_pointerx() + 12}+{self.widget.winfo_pointery() + 18}")
        ttk.Label(self.window, text=text, wraplength=480, padding=8, relief="solid").pack()

    def hide(self, event=None):
        if self.timer is not None:
            self.widget.after_cancel(self.timer)
            self.timer = None
        if self.window is not None:
            self.window.destroy()
            self.window = None


def display_timestamp(value):
    """Keep the date while displaying local time only to the minute."""
    return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M")


def nonnegative_measurement(value, field):
    text = value.strip()
    if re.fullmatch(r"0(?:\.0{1,6})?", text):
        return 0
    return measurement(text, field)


class Form(ttk.Frame):
    """All editable controls are declared and read through one verified registry."""

    def __init__(self, parent, fields, columns=2, style="TFrame", database=None,
                 memo_height=None, memo_width=None):
        super().__init__(parent, padding=8, style=style)
        self.fields = tuple(fields)
        self.database = database
        self.variables, self.widgets = {}, {}
        self.previous_choices = {}
        owner = self.winfo_toplevel().help_owner
        label_style = "Entry.TLabel" if style == "Entry.TFrame" else "TLabel"
        for index, field in enumerate(self.fields):
            row, pair = divmod(index, columns)
            column = pair * 2
            label = ttk.Label(self, text=field.label, style=label_style)
            label.grid(row=row, column=column, sticky="w", padx=(4, 8), pady=4)
            owner.attach_help(label, field.name)
            variable = tk.StringVar(master=self, value=field.default)
            if field.kind == "memo":
                widget = tk.Text(
                    self, width=memo_width or field.width,
                    height=memo_height or (3 if field.name == "HoverText" else 6),
                    wrap="word", undo=True,
                )
                variable.trace_add("write", lambda *_, name=field.name: self.assign_text(name))
                widget.bind("<<Modified>>", lambda event, name=field.name: self.read_text(name))
            elif field.kind in ("choice", "dropdown"):
                widget = ttk.Combobox(self, textvariable=variable, values=field.choices,
                                      state="readonly", width=field.width, justify="left")
            else:
                widget = ttk.Entry(self, textvariable=variable, width=field.width, justify="left")
            widget.grid(row=row, column=column + 1, sticky="w", padx=(0, 20), pady=4)
            self.variables[field.name], self.widgets[field.name] = variable, widget
            owner.attach_help(widget, field.name)
            if database is not None and field.name in DROPDOWN_FIELDS:
                widget.bind("<<ComboboxSelected>>", lambda event, name=field.name: self.choose_item(name))
                variable.trace_add("write", lambda *_, name=field.name: self.remember_choice(name))
            self.columnconfigure(column + 1, weight=1)
        if database is not None:
            self.defaults()
        self.assert_bindings()

    def assign_text(self, name):
        widget = self.widgets[name]
        value = self.variables[name].get()
        if widget.get("1.0", "end-1c") != value:
            widget.delete("1.0", "end")
            widget.insert("1.0", value)
            widget.edit_reset()
        widget.edit_modified(False)

    def read_text(self, name):
        widget = self.widgets[name]
        if widget.edit_modified():
            self.variables[name].set(widget.get("1.0", "end-1c"))
            widget.edit_modified(False)

    def remember_choice(self, name):
        value = self.variables[name].get()
        if value != ADD_ITEM:
            self.previous_choices[name] = value

    def refresh_choices(self):
        if self.database is not None:
            for name in self.variables:
                if name in DROPDOWN_FIELDS:
                    self.widgets[name].configure(values=self.database.dropdown_choices(name))

    def choose_item(self, name):
        if self.variables[name].get() != ADD_ITEM:
            return
        previous = self.previous_choices.get(name, "")
        # Never leave the action sentinel in an inventory form, including after Cancel or an error.
        self.variables[name].set(previous)
        self.winfo_toplevel().help_owner.open_add_item(self, name)

    def assert_bindings(self):
        names = {field.name for field in self.fields}
        if len(names) != len(self.fields) or set(self.variables) != names or set(self.widgets) != names:
            raise FieldError("Binding", "Form", detail="field, variable and widget registries differ")
        for name in names:
            if isinstance(self.widgets[name], tk.Text):
                continue
            if str(self.widgets[name].cget("textvariable")) != str(self.variables[name]):
                raise FieldError("Binding", name, detail="the control is not assigned to its variable")

    def values(self):
        self.assert_bindings()
        for field in self.fields:
            if field.kind == "memo":
                self.read_text(field.name)
        return {name: variable.get() for name, variable in self.variables.items()}

    def assign(self, values):
        self.assert_bindings()
        self.refresh_choices()
        if set(values) != set(self.variables):
            raise FieldError("Binding", "Form", detail="loaded values do not match the form fields")
        for name, value in values.items():
            self.variables[name].set(value)

    def defaults(self):
        self.assign({
            field.name: self.database.dropdown_default(field.name)
            if self.database is not None and field.name in DROPDOWN_FIELDS else field.default
            for field in self.fields
        })

    def focus_field(self, name):
        if name in self.widgets:
            self.widgets[name].focus_set()


class RecordList(ttk.Frame):
    def __init__(self, parent, columns):
        super().__init__(parent, padding=(8, 0, 8, 8))
        self.columns = columns
        self.heading = ttk.Label(self, text="", wraplength=1100)
        self.heading.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(4, 3))
        self.tree = ttk.Treeview(self, columns=columns, show="headings", selectmode="extended")
        owner = self.winfo_toplevel().help_owner
        self.tree.help_column = columns[0]
        owner.attach_help(self.tree, lambda: f"Column:{self.tree.help_column}")

        def column_help(event):
            column = self.tree.identify_column(event.x)
            if column:
                name = columns[int(column[1:]) - 1]
                if name != self.tree.help_column:
                    self.tree.help_column = name
                    self.tree.tooltip.schedule()

        self.tree.bind("<Motion>", column_help, add="+")
        for name in columns:
            anchor = "e" if name in NUMERIC_COLUMNS else "w"
            label = caption(name) + (" (in)" if name in ("UsableWidth", "UsableLength") else "")
            self.tree.heading(name, text=label, anchor=anchor)
            self.tree.column(name, anchor=anchor, width=150, minwidth=100, stretch=True)
        self.tree.column("ID", width=70, minwidth=60, stretch=False)
        vertical = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=1, column=0, sticky="nsew")
        vertical.grid(row=1, column=1, sticky="ns")
        horizontal.grid(row=2, column=0, sticky="ew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.bind("<Configure>", lambda event: self.heading.configure(wraplength=max(1, event.width - 24)))

    def fill(self, rows, noun, sort, context=""):
        self.tree.delete(*self.tree.get_children())
        for row in rows:
            values = [
                display_measurement(row[name]) if name in (
                    "UsableWidth", "UsableLength", "BackWidth", "BackLength", "FinishedWidth", "FinishedLength",
                )
                else display_timestamp(row[name]) if name in ("DateCreated", "DateModified")
                else row[name] for name in self.columns
            ]
            self.tree.insert("", "end", iid=str(row["ID"]), values=values)
        order = ", ".join(f"{caption(name)} {direction}" for name, direction in sort)
        self.heading.configure(text=f"{len(rows)} {noun} selected; Sort: {order}{context}")


class Application(BlockScreenMixin, QuiltScreenMixin):
    def __init__(self, root, database):
        self.root, self.db = root, database
        root.help_owner = self
        self.current = "Fabric"
        self.dialogs, self.dialog_forms = [], {}
        self.help_id = None
        self.filters = {field.name: "" for field in FILTER_FIELDS}
        self.filters["Status"] = "Available"
        self.selected_ids = None
        self.selection_description = ""
        self.sort = self.db.load_sort()
        self.piece_id = self.revision = None
        self.last_selection = ()
        root.title(f"Quilting Tools v{VERSION} - Fabric Inventory")
        root.geometry("1250x800")
        root.minsize(1000, 650)
        root.report_callback_exception = self.callback_error
        root.protocol("WM_DELETE_WINDOW", self.command(self.close))
        style = ttk.Style(root)
        style.configure("Entry.TFrame", background="#c3dafd")
        style.configure("Entry.TLabel", background="#c3dafd")
        self.nav = self.navigation(root)
        self.pages = ttk.Frame(root)
        self.pages.pack(fill="both", expand=True)
        body = ttk.Frame(self.pages)
        self.inventory_page = body
        self.dropdown_page = ttk.Frame(self.pages, padding=8)
        self.backs_page = ttk.Frame(self.pages, padding=8)
        self.block_page = ttk.Frame(self.pages, padding=8)
        self.quilt_page = ttk.Frame(self.pages, padding=8)
        self.help_page = ttk.Frame(self.pages, padding=8)
        self.error_page = ttk.Frame(self.pages, padding=8)
        self.setup_page = ttk.Frame(self.pages, padding=12)
        self.screens = {"Fabric": body, "Quilt Backs": self.backs_page, "QuiltBlock": self.block_page,
                        "Quilt": self.quilt_page, "DropDown": self.dropdown_page,
                        "HelpText": self.help_page, "ErrorMessage": self.error_page, "Setup": self.setup_page}
        for name, page in self.screens.items():
            page.help_screen = name
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=f"Fabric Inventory - v{VERSION}", font=("TkDefaultFont", 14, "bold"),
                  padding=8).pack(anchor="w")
        ttk.Label(body, text=f"Database: {self.db.path}", padding=(8, 0, 8, 4)).pack(anchor="w")
        entry = ttk.Frame(body, style="Entry.TFrame")
        entry.pack(fill="x")
        self.form = Form(entry, FABRIC_FIELDS, style="Entry.TFrame", database=self.db)
        self.form.pack(fill="x")
        self.details = ttk.Label(entry, text="New fabric rectangle", padding=(8, 4), style="Entry.TLabel")
        self.details.pack(anchor="w")
        actions = ttk.Frame(entry, padding=8, style="Entry.TFrame")
        actions.pack(fill="x")
        self.add_button = self.button(actions, "Add", self.add)
        self.update_button = self.button(actions, "Update", self.update)
        self.button(actions, "Clear", self.clear)
        self.button(actions, "History", self.open_history)
        ttk.Label(self.setup_page, text="Setup/Utilities", font=("TkDefaultFont", 14, "bold")).pack(anchor="w")
        ttk.Label(self.setup_page, text=f"Database: {self.db.path}", padding=(0, 8)).pack(anchor="w")
        utilities = ttk.Frame(self.setup_page)
        utilities.pack(fill="x", pady=8)
        self.button(utilities, "Backup Database", self.backup)
        self.button(utilities, "Restore Database", self.restore)
        ttk.Label(self.setup_page, text="Restore creates a new database; it never replaces the open one. "
                  "Dropdown defaults apply to new forms, not existing inventory.", wraplength=800).pack(anchor="w")
        self.list_buttons = []
        for label, action in (
            ("Select Highlighted", self.select_highlighted),
            ("Filter", self.open_filter),
            ("Set Selection", self.open_sets),
            ("Reset Selection", self.reset_selection),
            ("Sort", self.open_sort),
            ("Refresh", self.refresh_view),
        ):
            self.list_buttons.append(self.button(actions, label, action))
        self.list = RecordList(body, LIST_COLUMNS)
        self.list.pack(fill="both", expand=True)
        self.list.tree.bind("<<TreeviewSelect>>", self.command(self.on_select))
        self.status = ttk.Label(body, padding=(8, 4), text="Measurements are in inches. F1 shows field help.")
        self.status.pack(fill="x")
        self.initial_values = self.form.values()
        self.clear_details()
        self.refresh()
        self.build_dropdowns()
        self.build_helptext()
        self.build_errors()
        self.build_backs()
        self.build_blocks()
        self.build_quilts()

    def context(self, widget):
        while widget is not None:
            if hasattr(widget, "help_screen"):
                return widget.help_screen
            widget = widget.master
        return self.current

    def attach_help(self, widget, name):
        def key():
            return self.context(widget), name() if callable(name) else name

        widget.help_key = key
        widget.tooltip = ToolTip(widget, lambda: self.db.help_pair(*key())[0])

        def show(event):
            self.command(lambda: self.show_help(*key()))()
            return "break"

        widget.bind("<F1>", show, add="+")

    def navigation(self, parent):
        bar = ttk.Frame(parent, padding=(8, 4))
        bar.pack(fill="x", side="top")
        bar.title = ttk.Label(bar, text="", font=("TkDefaultFont", 14, "bold"))
        bar.title.pack(side="left")
        buttons = ttk.Frame(bar)
        buttons.pack(side="right")
        bar.buttons = {}
        for label in NAVIGATION:
            action = (lambda parent=parent: self.screen_help(parent)) if label == "Screen Help" else (
                lambda name=label: self.show_screen(name))
            bar.buttons[label] = self.button(buttons, label, action)
        return bar

    def unfinished(self):
        forms = []
        if self.current == "Fabric":
            forms.append((self.form, self.initial_values))
        elif self.current == "DropDown":
            forms.append((self.dropdown_form, self.dropdown_initial))
        elif self.current == "Quilt Backs":
            forms.append((self.back_form, self.back_initial))
        elif self.current == "QuiltBlock":
            forms.append((self.block_form, self.block_initial))
        elif self.current == "Quilt":
            forms.extend(((self.quilt_form, self.quilt_initial),
                          (self.quilt_name_form, self.quilt_name_initial)))
        elif self.current == "HelpText":
            forms.append((self.help_form, self.help_initial))
        elif self.current == "ErrorMessage":
            forms.append((self.error_form, self.error_initial))
        forms.extend(self.dialog_forms.values())
        return any(form.values() != initial for form, initial in forms)

    def allow_navigation(self):
        return not self.unfinished() or messagebox.askyesno(
            "Unsaved Changes", "Discard unsaved work and close unfinished operations?",
            parent=self.root.grab_current() or self.root,
        )

    def show_screen(self, name):
        if name not in self.screens:
            raise FieldError("Choice", "Screen")
        if not self.allow_navigation():
            return
        for window in list(reversed(self.dialogs)):
            window.destroy()
        self.list.tree.selection_remove(self.list.tree.selection())
        self.last_selection = ()
        self.clear_details()
        self.clear_dropdown_details()
        self.clear_help()
        self.clear_error()
        self.clear_block()
        self.quilt_form.defaults()
        self.quilt_initial = self.quilt_form.values()
        self.quilt_name_form.defaults()
        self.quilt_name_initial = self.quilt_name_form.values()
        if name == "Fabric":
            self.refresh()
        elif name == "DropDown":
            self.refresh_dropdowns()
        elif name == "Quilt Backs":
            self.refresh_back_stock()
            self.refresh_backs()
        elif name == "QuiltBlock":
            self.refresh_blocks()
        elif name == "Quilt":
            self.refresh_quilts()
            if self.quilt_id is not None:
                self.load_quilt(self.quilt_id)
        elif name == "HelpText":
            self.refresh_help()
        elif name == "ErrorMessage":
            self.refresh_errors()
        self.screens[self.current].pack_forget()
        self.current = name
        self.screens[name].pack(fill="both", expand=True)
        self.nav.title.configure(text="Quilt Backs" if name == "Quilt Backs" else "")
        self.root.title(f"Quilting Tools v{VERSION} - {name}")

    def command(self, action):
        def run(*_):
            try:
                action()
            except FieldError as error:
                self.show_error(error)
            except (sqlite3.Error, OSError) as error:
                self.show_error(FieldError("Database", "Database", detail=str(error)))
        return run

    def show_error(self, error):
        try:
            text = self.db.error_message(error)
        except (sqlite3.Error, FieldError, KeyError, ValueError) as catalog_error:
            traceback.print_exception(catalog_error)
            text = f"{caption(error.field)}: {error}\n\nError catalog failure: {catalog_error}"
        parent = self.root.grab_current() or self.root
        messagebox.showerror("Quilting Tools", text, parent=parent)
        container = self.screens[self.current] if parent == self.root else parent
        for form in container.winfo_children():
            if isinstance(form, Form):
                form.focus_field(error.field)

    def callback_error(self, exception_type, error, trace):
        traceback.print_exception(exception_type, error, trace)
        self.show_error(FieldError("Unexpected", "Application", detail=str(error)))

    def button(self, parent, text, action):
        widget = ttk.Button(parent, text=text, command=self.command(action))
        widget.pack(side="left", padx=(0, 5))
        self.attach_help(widget, f"Button:{text}")
        return widget

    def dirty(self):
        return self.form.values() != self.initial_values

    def allow_discard(self):
        return not self.dirty() or messagebox.askyesno(
            "Unsaved Changes", "Discard the unsaved fabric details?", parent=self.root,
        )

    def clear_details(self):
        self.piece_id = self.revision = None
        self.form.defaults()
        self.initial_values = self.form.values()
        self.details.configure(text="New fabric rectangle")
        self.add_button.state(["!disabled"])
        self.update_button.state(["disabled"])

    def load_piece(self, piece_id):
        row = self.db.get_piece(piece_id)
        self.form.assign({
            field.name: display_measurement(row[field.name]) if field.kind == "length" else row[field.name]
            for field in FABRIC_FIELDS
        })
        self.piece_id, self.revision = piece_id, row["Revision"]
        self.initial_values = self.form.values()
        self.details.configure(
            text=f"ID: {piece_id}    Revision: {self.revision}    "
                 f"Created: {display_timestamp(row['DateCreated'])}    "
                 f"Modified: {display_timestamp(row['DateModified'])}",
        )
        self.add_button.state(["!disabled"])
        self.update_button.state(["!disabled"])

    def on_select(self):
        selected = self.list.tree.selection()
        if selected == self.last_selection:
            return
        if not self.allow_discard():
            self.list.tree.selection_set(self.last_selection)
            return
        if len(selected) == 1:
            self.load_piece(int(selected[0]))
        else:
            self.clear_details()
            if selected:
                self.details.configure(text=f"{len(selected)} highlighted; choose one record to edit.")
                self.add_button.state(["disabled"])
        self.last_selection = selected

    def refresh(self, prefer_id=None):
        rows = self.db.pieces(self.filters, self.selected_ids, self.sort)
        keep = (str(prefer_id),) if prefer_id is not None else self.list.tree.selection()
        self.rows = rows
        context = f"; {self.selection_description}" if self.selection_description else ""
        active_filters = [f"{caption(name)}={value}" for name, value in self.filters.items() if value]
        if active_filters:
            context += "; Filter: " + ", ".join(active_filters)
        self.list.fill(rows, "fabric pieces", self.sort, context)
        self.last_selection = ()
        self.clear_details()
        visible = set(self.list.tree.get_children())
        kept = tuple(item for item in keep if item in visible)
        if kept:
            self.list.tree.selection_set(kept)
            self.list.tree.see(kept[0])
            self.on_select()

    def refresh_view(self):
        if self.allow_discard():
            self.clear_details()
            self.refresh()

    def clear(self):
        if self.allow_discard():
            self.list.tree.selection_remove(self.list.tree.selection())
            self.last_selection = ()
            self.clear_details()

    def add(self):
        if len(self.list.tree.selection()) > 1:
            raise FieldError("OneRecord", "Fabric Inventory")
        piece_id = self.db.save_piece(self.form.values())
        self.initial_values = self.form.values()
        self.refresh(prefer_id=piece_id)
        self.saved_status(piece_id, "Added")

    def update(self):
        if self.piece_id is None or self.list.tree.selection() != (str(self.piece_id),):
            raise FieldError("OneRecord", "Fabric Inventory")
        piece_id = self.db.save_piece(self.form.values(), self.piece_id, self.revision)
        self.initial_values = self.form.values()
        self.refresh(prefer_id=piece_id)
        self.saved_status(piece_id, "Saved")

    def saved_status(self, piece_id, verb):
        suffix = "" if self.list.tree.exists(str(piece_id)) else " (outside the current working selection)"
        self.status.configure(text=f"{verb} fabric piece {piece_id}{suffix}.")

    def select_highlighted(self):
        ids = [int(item) for item in self.list.tree.selection()]
        if not ids:
            raise FieldError("NoHighlight", "Fabric Inventory")
        if self.allow_discard():
            self.selected_ids = ids
            self.selection_description = "Highlighted-record restriction"
            self.refresh()

    def reset_selection(self):
        if self.allow_discard():
            self.filters = {field.name: "" for field in FILTER_FIELDS}
            self.selected_ids, self.selection_description = None, ""
            self.refresh()

    def dialog(self, title, screen):
        window = tk.Toplevel(self.root)
        window.help_owner, window.help_screen = self, screen
        window.title(title)
        window.transient(self.root)
        window.minsize(520, 200)
        window.nav = self.navigation(window)
        self.dialogs.append(window)
        window.grab_set()
        window.bind("<Destroy>", lambda event: self.dialog_closed(window) if event.widget == window else None)
        window.bind("<Escape>", lambda _: window.destroy())
        return window

    def dialog_closed(self, window):
        self.dialogs.remove(window)
        self.dialog_forms.pop(window, None)
        if self.dialogs:
            self.dialogs[-1].grab_set()

    def watch_dialog(self, window, form):
        self.dialog_forms[window] = form, form.values()

    def open_filter(self, screen=None, state=None, scope=None, refresh=None):
        screen = screen or self.current
        if screen in ("DropDown", "HelpText", "History", "Quilt Backs"):
            state = self.working_list_state(screen, state)
            fields = self.working_list_fields(screen)
            title = f"Filter {screen}"
            window = self.dialog(title, f"{screen} Filter")
            form = Form(window, fields, columns=1)
            form.pack(fill="both", expand=True)
            form.assign(state["filters"])
            self.watch_dialog(window, form)
            actions = ttk.Frame(window, padding=8)
            actions.pack(fill="x")

            def apply_working_list():
                values = validate_fields(fields, form.values())
                if self.allow_working_list_change(screen):
                    state["filters"] = values
                    window.destroy()
                    (refresh or {"DropDown": self.refresh_dropdowns,
                                 "HelpText": self.refresh_help}[screen])()

            self.button(actions, "Apply", apply_working_list)
            self.button(actions, "Clear Fields", form.defaults)
            self.button(actions, "Cancel", window.destroy)
            return
        errors = screen == "ErrorMessage"
        fields = ERROR_FILTER_FIELDS if errors else FILTER_FIELDS
        window = self.dialog("Filter Error Messages" if errors else "Filter Fabric Inventory",
                             "Error Filter" if errors else "Filter")
        form = Form(window, fields, columns=1)
        form.pack(fill="both", expand=True)
        form.assign(self.error_filters if errors else self.filters)
        self.watch_dialog(window, form)
        actions = ttk.Frame(window, padding=8)
        actions.pack(fill="x")

        def apply():
            values = form.values()
            validate_fields(fields, values)
            if (self.allow_error_discard if errors else self.allow_discard)():
                if errors:
                    self.error_filters = values
                else:
                    self.filters = values
                window.destroy()
                (self.refresh_errors if errors else self.refresh)()

        self.button(actions, "Apply", apply)
        self.button(actions, "Clear Fields", form.defaults)
        self.button(actions, "Cancel", window.destroy)

    def open_dropdowns(self):
        self.show_screen("DropDown")

    def open_add_item(self, source, name):
        window = self.dialog(f"Add Item - {caption(name)}", "Add Item")
        form = Form(window, (Field("ListItem", required=True),), columns=1)
        form.pack(fill="x")
        self.watch_dialog(window, form)

        def add():
            item = validate_fields(form.fields, form.values())["ListItem"]
            stored = self.db.add_dropdown_item(name, item)
            source.refresh_choices()
            source.variables[name].set(stored)
            window.destroy()

        actions = ttk.Frame(window, padding=8)
        actions.pack(fill="x")
        self.button(actions, "Add Item", add)
        self.button(actions, "Cancel", window.destroy)
        form.focus_field("ListItem")

    def new_list_state(self, sort=None, fields=()):
        return {
            "filters": {field.name: "" for field in fields},
            "selected_ids": None,
            "selection_description": "",
            "sort": sort,
        }

    @staticmethod
    def list_context(state):
        context = f"; {state['selection_description']}" if state["selection_description"] else ""
        filters = [f"{caption(name)}={value}" for name, value in state["filters"].items() if value]
        if filters:
            context += "; Filter: " + ", ".join(filters)
        return context

    def add_working_list_tools(self, parent, screen, state=None, scope=None, refresh=None, rows=None):
        self.button(parent, "Select Highlighted", lambda: self.select_working_list(
            screen, state, scope, refresh))
        self.button(parent, "Filter", lambda: self.open_filter(screen, state, scope, refresh))
        self.button(parent, "Set Selection", lambda: self.open_sets(
            screen, state, scope, refresh, rows))
        self.button(parent, "Reset Selection", lambda: self.reset_working_list(
            screen, state, refresh))
        self.button(parent, "Sort", lambda: self.open_sort(screen, state, refresh))

    def working_list_state(self, screen, state=None):
        if state is not None:
            return state
        if screen == "DropDown":
            return self.dropdown_states[self.dropdown_key()]
        if screen == "HelpText":
            return self.help_state
        if screen == "Quilt Backs":
            return self.back_state
        raise FieldError("Choice", "Screen")

    def working_list_fields(self, screen):
        return {
            "DropDown": DROPDOWN_FILTER_FIELDS,
            "HelpText": HELP_FILTER_FIELDS,
            "History": HISTORY_FILTER_FIELDS,
            "Quilt Backs": BACK_FILTER_FIELDS,
        }[screen]

    def working_list_sort(self, screen, state):
        if state["sort"] is None:
            return {
                "DropDown": self.db.load_sort("DropDownSort"),
                "HelpText": self.db.load_sort("HelpTextSort"),
                "History": self.db.load_sort("HistorySort"),
                "Quilt Backs": self.db.load_sort("QuiltBackSort"),
            }[screen]
        return state["sort"]

    def allow_working_list_change(self, screen):
        if screen == "HelpText":
            return self.help_form.values() == self.help_initial or messagebox.askyesno(
                "Unsaved Changes", "Discard unsaved help text?", parent=self.root.grab_current() or self.root,
            )
        if screen == "DropDown":
            return self.allow_dropdown_discard()
        return True

    def select_working_list(self, screen, state=None, scope=None, refresh=None):
        state = self.working_list_state(screen, state)
        listing = {"DropDown": self.dropdown_list, "HelpText": self.help_list,
                   "Quilt Backs": self.back_list}.get(screen)
        if screen == "History" and refresh is None:
            raise FieldError("Choice", "Screen")
        selected = listing.tree.selection() if listing is not None else state["tree"].selection()
        if not selected:
            raise FieldError("NoHighlight", screen)
        if self.allow_working_list_change(screen):
            state["selected_ids"] = [int(item) for item in selected]
            state["selection_description"] = "Highlighted-record restriction"
            (refresh or {"DropDown": self.refresh_dropdowns, "HelpText": self.refresh_help}[screen])()

    def reset_working_list(self, screen, state=None, refresh=None):
        state = self.working_list_state(screen, state)
        if self.allow_working_list_change(screen):
            state["filters"] = {field.name: "" for field in self.working_list_fields(screen)}
            state["selected_ids"] = None
            state["selection_description"] = ""
            (refresh or {"DropDown": self.refresh_dropdowns,
                         "HelpText": self.refresh_help}[screen])()

    def build_dropdowns(self):
        window = self.dropdown_page
        ttk.Label(window, text="DropDown", font=("TkDefaultFont", 14, "bold")).pack(anchor="w")
        self.dropdown_owner_fields = DROPDOWN_SCOPE_FIELDS
        all_fields = tuple(dict.fromkeys(
            name for names in self.dropdown_owner_fields.values() for name in names
        ))
        fields = (
            Field("TableName", "choice", choices=tuple(self.dropdown_owner_fields), default="FabricPiece"),
            Field("FieldName", "choice", choices=all_fields, default="FabricName"),
            Field("ListItem"),
            Field("Def", "choice", choices=("", "Set Default", "Clear Default", "Ignore for Update")),
            Field("Use", "choice", choices=("", "Set Use", "Clear Use", "Ignore for Update")),
        )
        ttk.Label(window, text="Choose a database table or screen, then a field or button. "
                  "FabricPiece choices continue to populate fabric forms.", wraplength=900, padding=8).pack(anchor="w")
        entry = ttk.Frame(window, style="Entry.TFrame")
        entry.pack(fill="x")
        self.dropdown_form = Form(entry, fields, columns=3, style="Entry.TFrame")
        self.dropdown_form.pack(fill="x")
        actions = ttk.Frame(entry, padding=8, style="Entry.TFrame")
        actions.pack(fill="x")
        self.button(actions, "Add", self.add_dropdown)
        self.button(actions, "Update", self.update_dropdown)
        self.button(actions, "Delete", self.delete_dropdown)
        tools = ttk.Frame(window, padding=(8, 0))
        tools.pack(fill="x")
        self.add_working_list_tools(tools, "DropDown")
        self.dropdown_list = RecordList(window, DROPDOWN_COLUMNS)
        tree = self.dropdown_list.tree
        char_width = tkfont.nametofont("TkDefaultFont").measure("0" * 5) + 10
        for name, width in (
            ("TableName", 150), ("FieldName", 160), ("ListItem", 220),
            ("Def", char_width), ("Use", char_width),
        ):
            tree.column(name, width=width, minwidth=width, stretch=False)
        for name in DROPDOWN_COLUMNS:
            tree.column(name, stretch=False)
        self.dropdown_list.pack(fill="both", expand=True)
        self.dropdown_states = {
            (table_name, field_name): self.new_list_state(
                self.db.load_sort("DropDownSort"), DROPDOWN_FILTER_FIELDS,
            )
            for table_name, names in self.dropdown_owner_fields.items()
            for field_name in names
        }
        self.dropdown_form.widgets["TableName"].bind(
            "<<ComboboxSelected>>", self.command(self.dropdown_table_changed))
        self.dropdown_form.widgets["FieldName"].bind(
            "<<ComboboxSelected>>", self.command(self.dropdown_field_changed))
        tree.bind("<<TreeviewSelect>>", self.command(self.on_dropdown_select))
        self.dropdown_row = None
        self.dropdown_selection = ()
        self.dropdown_initial = self.dropdown_form.values()
        self.dropdown_table_changed()

    def dropdown_table(self):
        table_name = self.dropdown_form.variables["TableName"].get()
        if table_name not in self.dropdown_owner_fields:
            raise FieldError("Choice", "TableName")
        return table_name

    def dropdown_field(self):
        field_name = self.dropdown_form.variables["FieldName"].get()
        if field_name not in self.dropdown_owner_fields[self.dropdown_table()]:
            raise FieldError("Choice", "FieldName")
        return field_name

    def dropdown_key(self):
        return self.dropdown_table(), self.dropdown_field()

    def dropdown_table_changed(self):
        if not self.allow_dropdown_discard():
            self.dropdown_form.variables["TableName"].set(self.dropdown_initial["TableName"])
            return
        table_name = self.dropdown_table()
        fields = self.dropdown_owner_fields[table_name]
        field_name = self.dropdown_form.variables["FieldName"].get()
        self.dropdown_form.widgets["FieldName"].configure(values=fields)
        if field_name not in fields:
            field_name = fields[0]
            self.dropdown_form.variables["FieldName"].set(field_name)
        self.dropdown_initial["TableName"] = table_name
        self.dropdown_initial["FieldName"] = field_name
        self.refresh_dropdowns()

    def dropdown_field_changed(self):
        if not self.allow_dropdown_discard():
            self.dropdown_form.variables["FieldName"].set(self.dropdown_initial["FieldName"])
            return
        self.refresh_dropdowns()

    def allow_dropdown_discard(self):
        values = self.dropdown_form.values()
        return all(values[name] == self.dropdown_initial[name] for name in ("ListItem", "Def", "Use")) or (
            messagebox.askyesno("Unsaved Changes", "Discard unsaved dropdown details?",
                                parent=self.root.grab_current() or self.root))

    def clear_dropdown_details(self):
        self.dropdown_row = None
        self.dropdown_selection = ()
        self.dropdown_list.tree.selection_remove(self.dropdown_list.tree.selection())
        for name in ("ListItem", "Def", "Use"):
            self.dropdown_form.variables[name].set("")
        self.dropdown_initial = self.dropdown_form.values()

    def on_dropdown_select(self):
        selected = self.dropdown_list.tree.selection()
        if selected == self.dropdown_selection:
            return
        if not self.allow_dropdown_discard():
            self.dropdown_list.tree.selection_set(self.dropdown_selection)
            return
        if len(selected) != 1:
            self.clear_dropdown_details()
            self.dropdown_list.tree.selection_set(selected)
            self.dropdown_selection = selected
            return
        self.dropdown_row = self.db.get_dropdown(int(selected[0]))
        self.dropdown_selection = selected
        self.dropdown_form.variables["ListItem"].set(self.dropdown_row["ListItem"])
        self.dropdown_form.variables["Def"].set("Ignore for Update")
        self.dropdown_form.variables["Use"].set("Ignore for Update")
        self.dropdown_initial = self.dropdown_form.values()

    def refresh_dropdowns(self):
        table_name, field_name = self.dropdown_key()
        state = self.dropdown_states[table_name, field_name]
        order = self.working_list_sort("DropDown", state)
        rows = self.db.dropdown_rows(
            field_name, state["filters"], state["selected_ids"], order, table_name, include_inactive=True,
        )
        context = self.list_context(state)
        self.clear_dropdown_details()
        self.dropdown_list.fill(
            rows, "dropdown records", order, context)
        self.form.refresh_choices()
        self.dropdown_initial["TableName"] = table_name
        self.dropdown_initial["FieldName"] = self.dropdown_form.values()["FieldName"]

    def add_dropdown(self):
        self.save_dropdown()

    def update_dropdown(self):
        self.save_dropdown(self.require_dropdown())

    def require_dropdown(self):
        if self.dropdown_row is None or self.dropdown_list.tree.selection() != (str(self.dropdown_row["ID"]),):
            raise FieldError("OneRecord", "Dropdown")
        return self.dropdown_row["ID"]

    def save_dropdown(self, item_id=None):
        table_name, field_name = self.dropdown_key()
        values = self.dropdown_form.values()
        flags = {"Set Default": 1, "Clear Default": 0, "Set Use": 1, "Clear Use": 0,
                 "Ignore for Update": None, "": None}
        if values["Def"] not in ("", "Set Default", "Clear Default", "Ignore for Update"):
            raise FieldError("Choice", "Def")
        if values["Use"] not in ("", "Set Use", "Clear Use", "Ignore for Update"):
            raise FieldError("Choice", "Use")
        _, warning = self.db.save_dropdown(
            table_name, field_name, values["ListItem"], flags[values["Def"]], flags[values["Use"]],
            item_id, self.dropdown_row if item_id is not None else None,
        )
        self.refresh_dropdowns()
        if warning:
            messagebox.showwarning(
                "Multiple Defaults", "This list has more than one default. "
                "Only the first active default alphabetically is used; clear the others.",
                parent=self.root,
            )

    def delete_dropdown(self):
        item_id = self.require_dropdown()
        if not self.allow_dropdown_discard():
            return
        if messagebox.askyesno("Delete Dropdown Item", "Delete the highlighted dropdown item?",
                               parent=self.root):
            self.db.delete_dropdown(item_id, self.dropdown_row)
            self.refresh_dropdowns()

    def build_helptext(self):
        ttk.Label(self.help_page, text="HelpText", font=("TkDefaultFont", 14, "bold")).pack(anchor="w")
        entry = ttk.Frame(self.help_page, style="Entry.TFrame")
        entry.pack(fill="x")
        self.help_form = Form(entry, HELP_FIELDS, columns=1, style="Entry.TFrame")
        self.help_form.pack(fill="x")
        for name in ("TableName", "FieldName"):
            self.help_form.widgets[name].configure(state="readonly")
        self.help_state = self.new_list_state(
            self.db.load_sort("HelpTextSort"), HELP_FILTER_FIELDS,
        )
        actions = ttk.Frame(entry, padding=8, style="Entry.TFrame")
        actions.pack(fill="x")
        self.help_update = self.button(actions, "Update", self.update_help)
        self.button(actions, "Clear", lambda: self.clear_help() if self.allow_navigation() else None)
        tools = ttk.Frame(self.help_page, padding=(8, 0))
        tools.pack(fill="x")
        self.add_working_list_tools(tools, "HelpText")
        self.help_list = RecordList(self.help_page, HELP_COLUMNS)
        self.help_list.pack(fill="both", expand=True)
        self.help_list.tree.configure(selectmode="browse")
        self.help_list.tree.bind("<<TreeviewSelect>>", self.command(self.on_help_select))
        for name in HELP_COLUMNS:
            self.help_list.tree.heading(name, command=self.command(lambda name=name: self.sort_help(name)))
        self.clear_help()
        self.refresh_help()

    def clear_help(self):
        self.help_id = None
        self.help_selection = ()
        self.help_list.tree.selection_remove(self.help_list.tree.selection())
        self.help_form.defaults()
        self.help_initial = self.help_form.values()
        self.help_update.state(["disabled"])

    def on_help_select(self):
        selected = self.help_list.tree.selection()
        if selected == self.help_selection:
            return
        if self.help_form.values() != self.help_initial and not self.allow_navigation():
            self.help_list.tree.selection_set(self.help_selection)
            return
        if not selected:
            self.clear_help()
            return
        row = next(row for row in self.help_rows if str(row["ID"]) == selected[0])
        self.help_id = row["ID"]
        self.help_selection = selected
        self.help_form.assign({field.name: row[field.name] for field in HELP_FIELDS})
        self.help_initial = self.help_form.values()
        self.help_update.state(["!disabled"])

    def refresh_help(self):
        keep = self.help_id
        self.help_rows = self.db.help_rows(
            self.help_state["filters"], self.help_state["selected_ids"], self.help_state["sort"],
        )
        self.help_list.fill(
            self.help_rows, "help records", self.help_state["sort"], self.list_context(self.help_state),
        )
        self.help_selection = ()
        if keep is not None and self.help_list.tree.exists(str(keep)):
            self.help_list.tree.selection_set(str(keep))
            self.on_help_select()
        else:
            self.clear_help()

    def update_help(self):
        if self.help_id is None:
            raise FieldError("OneRecord", "HelpText")
        self.db.save_help(self.help_id, self.help_form.values(), self.help_initial)
        self.help_initial = self.help_form.values()
        self.refresh_help()

    def sort_help(self, name):
        if not self.allow_navigation():
            return
        order = self.db.load_sort("HelpTextSort")
        direction = "desc" if order[0] == (name, "asc") else "asc"
        self.db.save_sort(((name, direction),), "HelpTextSort")
        self.help_state["sort"] = self.db.load_sort("HelpTextSort")
        self.help_form.assign(self.help_initial)
        self.refresh_help()

    def build_errors(self):
        self.error_filters = {field.name: "" for field in ERROR_FILTER_FIELDS}
        self.error_selected_ids = None
        self.error_selection_description = ""
        self.error_sort = self.db.load_sort("ErrorMessageSort")
        ttk.Label(self.error_page, text="ErrorMessage - Troubleshooting Reference",
                  font=("TkDefaultFont", 14, "bold")).pack(anchor="w")
        ttk.Label(self.error_page, text="Reference edits do not change runtime error dialogs. "
                  "Numbered fixes correspond to numbered likely causes; braces mark variable details.",
                  wraplength=1100).pack(anchor="w")
        self.error_form = Form(
            self.error_page, ERROR_FIELDS, columns=3, style="Entry.TFrame", memo_height=1, memo_width=28,
        )
        self.error_form.pack(fill="x")
        self.error_details = ttk.Label(self.error_page, padding=4)
        self.error_details.pack(anchor="w")
        actions = ttk.Frame(self.error_page, padding=8)
        actions.pack(fill="x")
        self.button(actions, "Add", self.add_error)
        self.error_update = self.button(actions, "Update", self.update_error)
        self.error_delete = self.button(actions, "Delete", self.delete_error)
        self.button(actions, "Clear", self.clear_error_entry)
        tools = ttk.Frame(self.error_page, padding=(8, 0))
        tools.pack(fill="x")
        for label, action in (
            ("Select Highlighted", self.select_errors), ("Filter", self.open_filter),
            ("Set Selection", self.open_sets), ("Reset Selection", self.reset_errors),
            ("Sort", self.open_sort), ("Refresh", self.refresh_error_view),
            ("Print", self.print_errors),
        ):
            self.button(tools, label, action)
        self.error_list = RecordList(self.error_page, ERROR_COLUMNS)
        self.error_list.pack(fill="both", expand=True)
        self.error_list.tree.bind("<<TreeviewSelect>>", self.command(self.on_error_select))
        self.clear_error()
        self.refresh_errors()

    def build_backs(self):
        entry = ttk.Frame(self.backs_page, style="Entry.TFrame")
        entry.pack(fill="x")
        self.back_form = Form(entry, SCREEN_FIELDS["Quilt Backs"], columns=5, style="Entry.TFrame")
        self.back_form.pack(fill="x")
        self.back_initial = self.back_form.values()
        stock_actions = ttk.Frame(entry, padding=(8, 0), style="Entry.TFrame")
        stock_actions.pack(fill="x")
        ttk.Label(stock_actions, text="Available source rectangles", style="Entry.TLabel").pack(side="left", padx=(0, 10))
        self.button(stock_actions, "Set Sketch Color", self.set_back_palette)
        self.button(stock_actions, "Refresh Fabric", self.refresh_back_stock)
        self.back_stock = RecordList(self.backs_page, LIST_COLUMNS)
        self.back_stock.tree.configure(height=5)
        self.back_stock.pack(fill="both", expand=True)
        actions = ttk.Frame(self.backs_page, padding=(8, 0))
        actions.pack(fill="x")
        self.button(actions, "Generate Plans", self.generate_back_plans)
        self.button(actions, "Preview Sketch", self.preview_back)
        self.button(actions, "Save Draft", self.save_back_draft)
        self.back_print_button = self.button(actions, "Print Plan", self.print_back_plan)
        self.back_candidates = RecordList(self.backs_page, BACK_LAYOUT_COLUMNS)
        self.back_candidates.tree.configure(height=4)
        for column in ("Parts", "Seams", "FabricArea"):
            self.back_candidates.tree.column(column, anchor="e")
        self.back_candidates.pack(fill="both", expand=True)
        self.back_candidates.tree.bind(
            "<<TreeviewSelect>>", self.command(self.on_back_candidate_select),
        )
        self.back_state = self.new_list_state(self.db.load_sort("QuiltBackSort"), BACK_FILTER_FIELDS)
        tools = ttk.Frame(self.backs_page, padding=(8, 0))
        tools.pack(fill="x")
        ttk.Label(tools, text="Saved plans").pack(side="left", padx=(0, 10))
        self.add_working_list_tools(
            tools, "Quilt Backs", refresh=self.refresh_backs,
            rows=lambda: self.db.quilt_backs(
                self.back_state["filters"], self.back_state["selected_ids"], self.back_state["sort"]),
        )
        self.back_list = RecordList(self.backs_page, BACK_COLUMNS)
        self.back_list.tree.configure(height=3)
        self.back_list.pack(fill="both", expand=True)
        self.back_list.tree.bind("<<TreeviewSelect>>", self.command(self.on_back_select))
        final_actions = ttk.Frame(self.backs_page, padding=(8, 0))
        final_actions.pack(fill="x")
        self.back_confirm_button = self.button(final_actions, "Confirm Cuts", self.open_back_cut)
        self.back_assembled_button = self.button(final_actions, "Mark Assembled", self.mark_back_assembled)
        self.back_status = ttk.Label(self.backs_page, text="Choose available rectangles to generate plans.")
        self.back_status.pack(fill="x", padx=8, pady=4)
        self.back_layouts = []
        self.back_selected_layout = None
        self.back_selected_id = None
        self.back_palette = {}
        self.back_initial = self.back_form.values()
        self.refresh_back_stock()
        self.refresh_backs()
        self.back_confirm_button.state(["disabled"])
        self.back_assembled_button.state(["disabled"])

    def refresh_back_stock(self):
        rows = self.available_inventory()
        self.back_stock.fill(rows, "available fabric rectangles", self.sort)

    def available_inventory(self):
        return [row for row in self.db.pieces(self.filters, self.selected_ids, self.sort)
                if row["Status"] == "Available"]

    def refresh_backs(self, prefer_id=None):
        selected = self.back_list.tree.selection()
        keep = (str(prefer_id),) if prefer_id is not None else selected
        state = self.back_state
        rows = self.db.quilt_backs(state["filters"], state["selected_ids"], state["sort"])
        self.back_list.fill(rows, "saved quilt backs", state["sort"], self.list_context(state))
        kept = tuple(item for item in keep if self.back_list.tree.exists(item))
        if kept:
            self.back_list.tree.selection_set(kept)
            self.back_list.tree.see(kept[0])
        self.on_back_select()

    def generate_back_plans(self):
        selected = self.back_stock.tree.selection()
        values = self.back_form.values()
        quilt_width = measurement(values["QuiltWidth"], "QuiltWidth")
        quilt_length = measurement(values["QuiltLength"], "QuiltLength")
        margin = nonnegative_measurement(values["Margin"], "Margin") if values["Margin"] else 0
        seam_allowance = (
            nonnegative_measurement(values["SeamAllowance"], "SeamAllowance")
            if values["SeamAllowance"] else 0
        )
        pieces = [self.db.get_piece(int(piece_id)) for piece_id in selected] if selected else self.available_inventory()
        self.back_selected_id = None
        self.back_list.tree.selection_remove(self.back_list.tree.selection())
        self.back_confirm_button.state(["disabled"])
        self.back_assembled_button.state(["disabled"])
        self.back_layouts = generate_layouts(
            pieces, quilt_width, quilt_length, margin, seam_allowance, self.back_palette,
        )
        self.back_candidates.fill([
            {
                "ID": index,
                "Layout": layout.direction.title(),
                "Parts": len(layout.panels),
                "Seams": layout.seam_count,
                "Grain": (
                    "Unknown" if layout.grain_unknown else
                    "Consistent" if layout.grain_consistent else "Mixed"
                ),
                "Minimum": ratio_label(layout.ratio_tier),
                "FabricArea": f"{layout.stock_area / (INCH * INCH):,.1f} sq in",
            }
            for index, layout in enumerate(self.back_layouts, 1)
        ], "ranked layout plans", (("ID", "asc"),))
        self.back_selected_layout = self.back_layouts[0] if self.back_layouts else None
        if self.back_layouts:
            self.back_candidates.tree.selection_set("1")
            self.back_status.configure(
                text=f"{len(self.back_layouts)} candidate plans. "
                     f"Best: {ratio_label(self.back_layouts[0].ratio_tier)}; "
                     f"{len(self.back_layouts[0].panels)} panels; "
                     f"{'grain consistent' if self.back_layouts[0].grain_consistent else 'grain differs'}."
            )
        else:
            self.back_status.configure(text="No feasible plan from the selected available rectangles.")

    def on_back_candidate_select(self):
        selected = self.back_candidates.tree.selection()
        if len(selected) == 1:
            index = int(selected[0]) - 1
            if 0 <= index < len(self.back_layouts):
                self.back_selected_layout = self.back_layouts[index]

    def set_back_palette(self):
        selected = self.back_stock.tree.selection()
        if len(selected) != 1:
            raise FieldError("OneRecord", "FabricPiece")
        piece = self.db.get_piece(int(selected[0]))
        initial = self.back_palette.get(piece["ID"], palette_suggestion(piece["Color"]))
        window = self.dialog("Set Sketch Color", "Quilt Backs")
        window.geometry("480x180")
        ttk.Label(
            window,
            text=f"{piece['FabricName']} — {piece['Color'] or '(no color recorded)'}",
            padding=10,
        ).pack(anchor="w")
        color = tk.StringVar(master=window, value=initial)
        ttk.Combobox(
            window, textvariable=color, values=tuple(PALETTE), state="readonly",
        ).pack(anchor="w", padx=10, pady=8)
        self.button(window, "Apply", lambda: self.apply_back_palette(window, piece["ID"], color.get()))
        self.button(window, "Cancel", window.destroy)

    def apply_back_palette(self, window, piece_id, color):
        if color not in PALETTE:
            raise FieldError("Choice", "PaletteColor")
        self.back_palette[piece_id] = color
        window.destroy()

    def preview_back(self):
        layout = self.back_selected_layout
        if layout is None:
            raise FieldError("NoHighlight", "QuiltBackPlan")
        window = self.dialog("Quilt Back Sketch", "Quilt Backs")
        window.geometry("1000x700")
        canvas = tk.Canvas(window, background="white", highlightthickness=0)
        canvas.pack(fill="both", expand=True, padx=12, pady=12)
        self.root.update_idletasks()
        scale = min(780 / layout.target_width, 500 / layout.target_length)
        offset_x, offset_y = 20, 20
        for panel in layout.panels:
            x = offset_x + panel.x * scale
            y = offset_y + panel.y * scale
            width = panel.finished_width * scale
            height = panel.finished_length * scale
            canvas.create_rectangle(
                x, y, x + width, y + height,
                fill=PALETTE.get(panel.palette_color, PALETTE["Gray"]), outline="#222", width=2,
            )
            canvas.create_text(x + width / 2, y + height / 2, text=f"Part {panel.number}")
            if panel.grain_axis == "x":
                canvas.create_line(x + width * .3, y + height * .7,
                                   x + width * .7, y + height * .7, arrow=tk.LAST, width=3)
            elif panel.grain_axis == "y":
                canvas.create_line(x + width * .7, y + height * .3,
                                   x + width * .7, y + height * .7, arrow=tk.LAST, width=3)
            else:
                canvas.create_text(x + width / 2, y + height * .72, text="Grain unknown")
        legend = "   ".join(
            f"Part {panel.number}: {panel.palette_color} = {panel.source_name} "
            f"({panel.source_color or 'no color recorded'}); grain {panel.grain_axis or 'unknown'}"
            for panel in layout.panels
        )
        ttk.Label(window, text=legend, wraplength=960, padding=8).pack(anchor="w")
        self.button(window, "Print Plan", self.print_back_plan)
        self.button(window, "Close", window.destroy)

    def save_back_draft(self):
        layout = self.back_selected_layout
        if layout is None:
            raise FieldError("NoHighlight", "QuiltBackPlan")
        values = self.back_form.values()
        back_id = self.db.save_back_draft(
            values["BackName"],
            measurement(values["QuiltWidth"], "QuiltWidth"),
            measurement(values["QuiltLength"], "QuiltLength"),
            nonnegative_measurement(values["Margin"], "Margin") if values["Margin"] else 0,
            nonnegative_measurement(values["SeamAllowance"], "SeamAllowance")
            if values["SeamAllowance"] else 0,
            layout,
        )
        self.back_initial = self.back_form.values()
        self.refresh_backs(back_id)
        self.back_status.configure(text=f"Draft {back_id} saved. Inventory has not changed.")

    def on_back_select(self):
        selected = self.back_list.tree.selection()
        was_saved = self.back_selected_id is not None
        self.back_selected_id = int(selected[0]) if len(selected) == 1 else None
        if self.back_selected_id is None:
            if was_saved:
                self.back_selected_layout = None
            self.back_confirm_button.state(["disabled"])
            self.back_assembled_button.state(["disabled"])
            return
        back = self.db.get_quilt_back(self.back_selected_id)
        self.back_selected_layout = layout_from_record(back)
        self.back_confirm_button.state(["!disabled"] if back["Status"] == "Draft" else ["disabled"])
        self.back_assembled_button.state(["!disabled"] if back["Status"] == "Cut" else ["disabled"])
        self.back_status.configure(
            text=f"Back {back['ID']}: {back['BackName']} — {back['Status']}; "
                 f"{display_measurement(back['BackWidth'])} × "
                 f"{display_measurement(back['BackLength'])} in.",
        )

    def open_back_cut(self):
        if self.back_selected_id is None:
            raise FieldError("OneRecord", "QuiltBack")
        back = self.db.get_quilt_back(self.back_selected_id)
        if back["Status"] != "Draft":
            raise FieldError("Conflict", "QuiltBackID")
        sources = {}
        for panel in back["Panels"]:
            sources.setdefault(panel["FabricPieceID"], []).append(panel)
        fields = []
        for source_id in sources:
            fields.extend((
                Field(f"RemainingWidth{source_id}", "length", width=8),
                Field(f"RemainingLength{source_id}", "length", width=8),
            ))
        window = self.dialog("Record Actual Cuts and Remainders", "Quilt Backs")
        window.geometry("760x420")
        ttk.Label(
            window, text="Leave both remainder fields blank if the source was consumed. "
                         "Otherwise enter the measured reusable remainder in the source's recorded orientation.",
            wraplength=700, padding=8,
        ).pack(anchor="w")
        for source_id, panels in sources.items():
            panel = panels[0]
            planned = ", ".join(
                f"Part {item['PanelNumber']}: {display_measurement(item['CutWidth'])} × "
                f"{display_measurement(item['CutLength'])} in"
                for item in panels
            )
            ttk.Label(
                window,
                text=f"Source {source_id}: {panel['FabricName']} "
                     f"({panel['InventoryColor'] or 'no color recorded'}), "
                     f"{display_measurement(panel['SourceWidth'])} × "
                     f"{display_measurement(panel['SourceLength'])} in. Planned cuts: {planned}",
                padding=(8, 4),
            ).pack(anchor="w")
        form = Form(window, tuple(fields), columns=2)
        form.pack(fill="x")
        self.watch_dialog(window, form)
        self.button(window, "Confirm Cuts", lambda: self.commit_back_cut(window, form, sources))
        self.button(window, "Cancel", window.destroy)

    def commit_back_cut(self, window, form, sources):
        values = form.values()
        remnants = {}
        for source_id in sources:
            width = values[f"RemainingWidth{source_id}"]
            length = values[f"RemainingLength{source_id}"]
            remnants[source_id] = None if not width and not length else (width, length)
        back = self.db.confirm_back_cut(self.back_selected_id, remnants)
        window.destroy()
        self.refresh_back_stock()
        self.refresh_backs(back["ID"])
        self.back_status.configure(
            text=f"Back {back['ID']} cuts recorded. Sources were retired; entered remnants were added."
        )

    def mark_back_assembled(self):
        if self.back_selected_id is None:
            raise FieldError("OneRecord", "QuiltBack")
        back = self.db.mark_quilt_back_assembled(self.back_selected_id)
        self.refresh_backs(back["ID"])

    def print_back_plan(self):
        if self.back_selected_layout is None and self.back_selected_id is not None:
            back = self.db.get_quilt_back(self.back_selected_id)
            layout = layout_from_record(back)
            title = back["BackName"]
            quilt_width, quilt_length = back["QuiltWidth"], back["QuiltLength"]
        else:
            layout = self.back_selected_layout
            if layout is None:
                raise FieldError("NoHighlight", "QuiltBackPlan")
            if self.back_selected_id is not None:
                back = self.db.get_quilt_back(self.back_selected_id)
                title = back["BackName"]
                quilt_width, quilt_length = back["QuiltWidth"], back["QuiltLength"]
            else:
                values = self.back_form.values()
                title = values["BackName"] or "Quilt Back Draft"
                quilt_width = measurement(values["QuiltWidth"], "QuiltWidth")
                quilt_length = measurement(values["QuiltLength"], "QuiltLength")
        destination = filedialog.asksaveasfilename(
            parent=self.root, title="Save Quilt Back Plan (new file only)",
            defaultextension=".html", initialfile="QuiltBackPlan.html",
            filetypes=(("HTML plan", "*.html"),),
        )
        if not destination:
            return
        assembly_order = (
            "single panel; no seams" if layout.direction == "single"
            else "left to right" if layout.direction == "vertical"
            else "top to bottom"
        )
        report = (
            '<!doctype html><html><head><meta charset="utf-8"><title>' + escape(title)
            + "</title><style>body{font-family:sans-serif}table{border-collapse:collapse}"
            "th,td{border:1px solid #888;padding:6px;text-align:left}"
            "@media print{button{display:none}}</style></head><body>"
            f"<h1>{escape(title)}</h1><p>Quilt: {quilt_width / INCH:g} × "
            f"{quilt_length / INCH:g} in. Back target: {layout.target_width / INCH:g} × "
            f"{layout.target_length / INCH:g} in. Uniform seam allowance: "
            f"{layout.seam_allowance / INCH:g} in.</p>"
            f"<p>Assembly order: {assembly_order}. "
            "Join adjacent edges using the stated uniform seam allowance.</p>"
            f"{layout_svg(layout)}{escaped_legend(layout)}"
            '<button onclick="window.print()">Print</button>'
            '<script>window.addEventListener("load",()=>window.print());</script></body></html>'
        )
        path = Path(destination).resolve()
        with path.open("x", encoding="utf-8") as output:
            output.write(report)
        if not webbrowser.open(path.as_uri()):
            raise FieldError("Database", "Print", detail=f"No browser opened. Open {path} manually and choose Print.")

    def allow_error_discard(self):
        return self.error_form.values() == self.error_initial or messagebox.askyesno(
            "Unsaved Changes", "Discard unsaved error-message details?",
            parent=self.root.grab_current() or self.root,
        )

    def clear_error(self):
        self.error_id = None
        self.error_selection = ()
        self.error_list.tree.selection_remove(self.error_list.tree.selection())
        self.error_form.defaults()
        self.error_initial = self.error_form.values()
        self.error_details.configure(text="New error message")
        self.error_update.state(["disabled"])
        self.error_delete.state(["disabled"])

    def clear_error_entry(self):
        if self.allow_error_discard():
            self.clear_error()

    def on_error_select(self):
        selected = self.error_list.tree.selection()
        if selected == self.error_selection:
            return
        if not self.allow_error_discard():
            self.error_list.tree.selection_set(self.error_selection)
            return
        if len(selected) != 1:
            self.clear_error()
            self.error_list.tree.selection_set(selected)
            self.error_selection = selected
            return
        row = self.db.get_error(int(selected[0]))
        self.error_id = row["ID"]
        self.error_selection = selected
        self.error_form.assign({field.name: row[field.name] for field in ERROR_FIELDS})
        self.error_initial = self.error_form.values()
        self.error_details.configure(text=f"ID: {self.error_id}")
        self.error_update.state(["!disabled"])
        self.error_delete.state(["!disabled"])

    def refresh_errors(self, prefer_id=None):
        self.error_rows = self.db.error_rows(
            self.error_filters, self.error_selected_ids, self.error_sort,
        )
        context = f"; {self.error_selection_description}" if self.error_selection_description else ""
        filters = [f"{caption(name)}={value}" for name, value in self.error_filters.items() if value]
        if filters:
            context += "; Filter: " + ", ".join(filters)
        self.clear_error()
        self.error_list.fill(self.error_rows, "error messages", self.error_sort, context)
        if prefer_id is not None and self.error_list.tree.exists(str(prefer_id)):
            self.error_list.tree.selection_set(str(prefer_id))
            self.error_list.tree.see(str(prefer_id))
            self.on_error_select()
        elif prefer_id is not None:
            self.error_details.configure(text=f"Saved message {prefer_id} (outside the current working selection)")

    def refresh_error_view(self):
        if self.allow_error_discard():
            self.refresh_errors()

    def add_error(self):
        message_id = self.db.save_error(self.error_form.values())
        self.refresh_errors(message_id)

    def require_error(self):
        if self.error_id is None or self.error_list.tree.selection() != (str(self.error_id),):
            raise FieldError("OneRecord", "ErrorMessage")
        return self.error_id

    def update_error(self):
        message_id = self.require_error()
        self.db.save_error(self.error_form.values(), message_id, self.error_initial)
        self.refresh_errors(message_id)

    def delete_error(self):
        message_id = self.require_error()
        if not self.allow_error_discard():
            return
        if messagebox.askyesno("Delete Error Message",
                              f"Delete reference message {message_id}? Runtime error dialogs are unchanged.",
                              parent=self.root):
            self.db.delete_error(message_id, self.error_initial)
            self.refresh_errors()

    def select_errors(self):
        ids = [int(item) for item in self.error_list.tree.selection()]
        if not ids:
            raise FieldError("NoHighlight", "ErrorMessage")
        if self.allow_error_discard():
            self.error_selected_ids = ids
            self.error_selection_description = "Highlighted-record restriction"
            self.refresh_errors()

    def reset_errors(self):
        if self.allow_error_discard():
            self.error_filters = {field.name: "" for field in ERROR_FILTER_FIELDS}
            self.error_selected_ids = None
            self.error_selection_description = ""
            self.refresh_errors()

    def print_errors(self):
        destination = filedialog.asksaveasfilename(
            parent=self.root, title="Save Error Message Print Report (new file only)", defaultextension=".html",
            initialfile="ErrorMessages.html", filetypes=(("HTML report", "*.html"),),
        )
        if not destination:
            return
        # Snapshot displayed values, not a fresh database query or just the highlights.
        rows = "".join(
            "<tr>" + "".join(f"<td>{escape(str(value))}</td>" for value in self.error_list.tree.item(item, "values"))
            + "</tr>" for item in self.error_list.tree.get_children()
        )
        headings = "".join(f"<th>{escape(caption(name))}</th>" for name in ERROR_COLUMNS)
        report = (
            '<!doctype html><html><head><meta charset="utf-8"><title>Error Messages</title>'
            "<style>body{font-family:sans-serif}table{border-collapse:collapse;width:100%}"
            "th,td{border:1px solid #888;padding:6px;text-align:left;vertical-align:top}"
            "td{white-space:pre-wrap;overflow-wrap:anywhere}thead{display:table-header-group}"
            "@media print{button{display:none}}</style></head><body>"
            '<h1>Error Messages</h1><p>' + escape(self.error_list.heading.cget("text"))
            + '</p><button onclick="window.print()">Print</button>'
            f"<table><thead><tr>{headings}</tr></thead><tbody>{rows}</tbody></table>"
            '<script>window.addEventListener("load",()=>window.print());</script></body></html>'
        )
        path = Path(destination).resolve()
        with path.open("x", encoding="utf-8") as output:
            output.write(report)
        if not webbrowser.open(path.as_uri()):
            raise FieldError("Database", "Print",
                             detail=f"No browser opened. Open {path} manually and choose Print.")

    def open_sort(self, screen=None, state=None, refresh=None):
        screen = screen or self.current
        if screen in ("DropDown", "HelpText", "History", "Quilt Backs"):
            state = self.working_list_state(screen, state)
            columns = {
                "DropDown": DROPDOWN_COLUMNS,
                "HelpText": HELP_COLUMNS,
                "History": HISTORY_COLUMNS,
                "Quilt Backs": BACK_COLUMNS,
            }[screen]
            sort_key = {"DropDown": "DropDownSort", "HelpText": "HelpTextSort",
                        "History": "HistorySort", "Quilt Backs": "QuiltBackSort"}[screen]
            order = self.working_list_sort(screen, state)
            title = f"Sort {screen}"
            window = self.dialog(title, f"{screen} Sort")
            fields = []
            for index in range(1, len(columns) + 1):
                fields.extend((
                    Field(f"SortField{index}", "choice", choices=("", *map(caption, columns))),
                    Field(f"Direction{index}", "choice", choices=("asc", "desc"), default="asc"),
                ))
            form = Form(window, fields)
            form.pack(fill="both", expand=True)
            lookup = {caption(name): name for name in columns}
            for index, (name, direction) in enumerate(order, 1):
                form.variables[f"SortField{index}"].set(caption(name))
                form.variables[f"Direction{index}"].set(direction)
            self.watch_dialog(window, form)
            actions = ttk.Frame(window, padding=8)
            actions.pack(fill="x")

            def apply_working_sort():
                values = validate_fields(fields, form.values())
                requested = [
                    (lookup[values[f"SortField{index}"]], values[f"Direction{index}"])
                    for index in range(1, len(columns) + 1) if values[f"SortField{index}"]
                ]
                order = normalize_sort(requested, columns)
                if self.allow_working_list_change(screen):
                    self.db.save_sort(order, sort_key)
                    state["sort"] = order
                    window.destroy()
                    (refresh or {"DropDown": self.refresh_dropdowns,
                                 "HelpText": self.refresh_help}[screen])()

            self.button(actions, "Apply", apply_working_sort)
            self.button(actions, "Clear Fields", form.defaults)
            self.button(actions, "Cancel", window.destroy)
            return
        errors = screen == "ErrorMessage"
        columns = ERROR_COLUMNS if errors else SORT_FIELDS
        window = self.dialog("Sort Error Messages" if errors else "Sort Fabric Inventory",
                             "Error Sort" if errors else "Sort")
        fields = []
        for index in range(1, len(columns) + 1):
            fields.extend((
                Field(f"SortField{index}", "choice", choices=("", *map(caption, columns))),
                Field(f"Direction{index}", "choice", choices=("asc", "desc"), default="asc"),
            ))
        form = Form(window, fields)
        form.pack(fill="both", expand=True)
        lookup = {caption(name): name for name in columns}
        for index, (name, direction) in enumerate(self.error_sort if errors else self.sort, 1):
            form.variables[f"SortField{index}"].set(caption(name))
            form.variables[f"Direction{index}"].set(direction)
        self.watch_dialog(window, form)

        def apply():
            values = validate_fields(fields, form.values())
            requested = [
                (lookup[values[f"SortField{index}"]], values[f"Direction{index}"])
                for index in range(1, len(columns) + 1) if values[f"SortField{index}"]
            ]
            order = normalize_sort(requested, columns)
            if (self.allow_error_discard if errors else self.allow_discard)():
                self.db.save_sort(order, "ErrorMessageSort" if errors else "FabricInventorySort")
                if errors:
                    self.error_sort = order
                else:
                    self.sort = order
                window.destroy()
                (self.refresh_errors if errors else self.refresh)()

        actions = ttk.Frame(window, padding=8)
        actions.pack(fill="x")
        self.button(actions, "Apply", apply)
        self.button(actions, "Clear Fields", form.defaults)
        self.button(actions, "Cancel", window.destroy)

    def open_sets(self, screen=None, state=None, scope=None, refresh=None, rows=None):
        screen = screen or self.current
        if screen in ("DropDown", "HelpText", "History", "Quilt Backs"):
            state = self.working_list_state(screen, state)
            refresh = refresh or {"DropDown": self.refresh_dropdowns,
                                  "HelpText": self.refresh_help}.get(screen)
            if screen == "DropDown":
                scope = scope or self.dropdown_key()
                list_rows = rows or (lambda: self.db.dropdown_rows(
                    scope[1], state["filters"], state["selected_ids"], state["sort"],
                    scope[0],
                ))
            elif screen == "HelpText":
                scope = None
                list_rows = rows or (lambda: self.db.help_rows(
                    state["filters"], state["selected_ids"], state["sort"],
                ))
            elif screen == "Quilt Backs":
                scope = None
                list_rows = rows or (lambda: self.db.quilt_backs(
                    state["filters"], state["selected_ids"], state["sort"],
                ))
            else:
                scope = str(scope)
                list_rows = rows
            choices = {
                f"{row['SetName']} ({row['RecordCount']} records; ID {row['ID']})": row["ID"]
                for row in self.db.sets(screen, scope)
            }
            title = f"{screen} Selection Sets"
            window = self.dialog(title, f"{screen} Set")
            fields = (Field("SavedSet", "choice", choices=("", *choices)), Field("SetName"))
            form = Form(window, fields, columns=1)
            form.pack(fill="x")
            self.watch_dialog(window, form)
            ttk.Label(window, text=f"{len(list_rows())} records in the current working list. "
                      "Save Current saves all of them.", padding=8).pack(anchor="w")
            actions = ttk.Frame(window, padding=8)
            actions.pack(fill="x")

            def chosen():
                values = validate_fields(fields, form.values())
                if not values["SavedSet"]:
                    raise FieldError("Required", "SavedSet")
                return choices[values["SavedSet"]]

            def save_working_set():
                self.db.save_set(form.values()["SetName"], [row["ID"] for row in list_rows()],
                                 screen, scope)
                window.destroy()

            def apply_working_set():
                set_id = chosen()
                ids = self.db.set_members(set_id, screen, scope)
                if self.allow_working_list_change(screen):
                    state["filters"] = {field.name: "" for field in self.working_list_fields(screen)}
                    state["selected_ids"] = ids
                    state["selection_description"] = f"Selection set ID {set_id}"
                    window.destroy()
                    refresh()

            def delete_working_set():
                set_id = chosen()
                if messagebox.askyesno("Delete Selection Set", "Delete this set? Source records are kept.",
                                       parent=window):
                    self.db.delete_set(set_id, screen, scope)
                    window.destroy()

            self.button(actions, "Save Current", save_working_set)
            self.button(actions, "Apply Saved", apply_working_set)
            self.button(actions, "Delete Saved", delete_working_set)
            self.button(actions, "Cancel", window.destroy)
            return
        errors = screen == "ErrorMessage"
        window = self.dialog("Error Message Sets" if errors else "Set Selection",
                             "Error Set" if errors else "Set Selection")
        rows = self.db.sets(screen)
        choices = {f"{row['SetName']} ({row['RecordCount']} records; ID {row['ID']})": row["ID"] for row in rows}
        fields = (Field("SavedSet", "choice", choices=("", *choices)), Field("SetName"))
        form = Form(window, fields, columns=1)
        form.pack(fill="x")
        self.watch_dialog(window, form)
        ttk.Label(window, text=f"{len(self.error_rows if errors else self.rows)} records in the current working list. "
                  "Save Current saves all of them.", padding=8).pack(anchor="w")

        def chosen():
            values = validate_fields(fields, form.values())
            if not values["SavedSet"]:
                raise FieldError("Required", "SavedSet")
            return choices[values["SavedSet"]]

        def save():
            self.db.save_set(form.values()["SetName"],
                             [row["ID"] for row in (self.error_rows if errors else self.rows)], screen)
            window.destroy()
            (self.error_details if errors else self.status).configure(text="Saved selection set.")

        def apply():
            set_id = chosen()
            ids = self.db.set_members(set_id, screen)
            if (self.allow_error_discard if errors else self.allow_discard)():
                if errors:
                    self.error_filters = {field.name: "" for field in ERROR_FILTER_FIELDS}
                    self.error_selected_ids = ids
                    self.error_selection_description = f"Selection set ID {set_id}"
                else:
                    self.filters = {field.name: "" for field in FILTER_FIELDS}
                    self.selected_ids = ids
                    self.selection_description = f"Selection set ID {set_id}"
                window.destroy()
                (self.refresh_errors if errors else self.refresh)()

        def delete():
            set_id = chosen()
            if messagebox.askyesno("Delete Selection Set", "Delete this set? Source records are kept.",
                                   parent=window):
                self.db.delete_set(set_id, screen)
                window.destroy()
                (self.error_details if errors else self.status).configure(
                    text="Deleted selection set. The current working list is unchanged.")

        actions = ttk.Frame(window, padding=8)
        actions.pack(fill="x")
        self.button(actions, "Save Current", save)
        self.button(actions, "Apply Saved", apply)
        self.button(actions, "Delete Saved", delete)
        self.button(actions, "Cancel", window.destroy)

    def open_history(self):
        if self.piece_id is None:
            raise FieldError("OneRecord", "Fabric Inventory")
        piece_id = self.piece_id
        window = self.dialog(f"Fabric Piece {piece_id} - History", "History")
        window.geometry("950x600")
        state = self.new_list_state(self.db.load_sort("HistorySort"), HISTORY_FILTER_FIELDS)
        listing = RecordList(window, ("ID", "Action", "DateCreated"))
        state["tree"] = listing.tree
        rows = []

        def refresh_history():
            nonlocal rows
            keep = listing.tree.selection()
            rows = self.db.history(
                piece_id, state["filters"], state["selected_ids"], state["sort"],
            )
            listing.fill(rows, "history records", state["sort"], self.list_context(state))
            visible = set(listing.tree.get_children())
            kept = tuple(item for item in keep if item in visible)
            if kept:
                listing.tree.selection_set(kept)
                listing.tree.see(kept[0])
            else:
                text.configure(state="normal")
                text.delete("1.0", "end")
                text.configure(state="disabled")

        tools = ttk.Frame(window, padding=(8, 0))
        tools.pack(fill="x")
        self.add_working_list_tools(
            tools, "History", state, piece_id, refresh_history, lambda: rows,
        )
        listing.pack(fill="both", expand=True)
        text = tk.Text(window, height=14, wrap="word", state="disabled")
        text.pack(fill="both", expand=True, padx=8, pady=8)
        scroll = ttk.Scrollbar(text, orient="vertical", command=text.yview)
        scroll.pack(side="right", fill="y")
        text.configure(yscrollcommand=scroll.set)
        self.attach_help(text, "HistoryValues")
        refresh_history()

        def show():
            selected = listing.tree.selection()
            if len(selected) != 1:
                return
            row = next(row for row in rows if row["ID"] == int(selected[0]))
            lines = []
            for key, label in (("BeforeValues", "Before"), ("AfterValues", "After")):
                snapshot = json.loads(row[key]) if row[key] is not None else None
                lines.append(label + ":")
                if snapshot is None:
                    lines.append("  (new piece)")
                else:
                    for name, value in snapshot.items():
                        if name in ("UsableWidth", "UsableLength"):
                            value = display_measurement(value) + " in"
                        elif name in ("DateCreated", "DateModified"):
                            value = display_timestamp(value)
                        lines.append(f"  {caption(name)}: {value}")
            text.configure(state="normal")
            text.delete("1.0", "end")
            text.insert("1.0", "\n".join(lines))
            text.configure(state="disabled")

        listing.tree.bind("<<TreeviewSelect>>", self.command(show))
        self.button(window, "Close", window.destroy)

    def backup(self):
        if self.dirty() and not messagebox.askokcancel(
                "Backup Database", "The backup includes saved records only. Continue?", parent=self.root):
            return
        destination = filedialog.asksaveasfilename(
            parent=self.root, title="Save Database Backup (new file only)", defaultextension=".db",
            initialfile=f"QuiltingInventory_Backup_{datetime.now():%Y%m%d_%H%M%S}.db",
            filetypes=(("SQLite database", "*.db"),),
        )
        if destination:
            result = self.db.backup(destination)
            messagebox.showinfo("Backup Complete", f"Verified backup saved to:\n{result}", parent=self.root)

    def restore(self):
        source = filedialog.askopenfilename(
            parent=self.root, title="Choose a Quilting Tools Backup",
            filetypes=(("SQLite database", "*.db"), ("All files", "*")),
        )
        if not source:
            return
        destination = filedialog.asksaveasfilename(
            parent=self.root, title="Restore to a New Database (existing files are never replaced)",
            defaultextension=".db", initialfile="QuiltingInventory_Restored.db",
        )
        if destination:
            result = Database.restore_to_new(source, destination)
            messagebox.showinfo(
                "Restore Complete",
                f"Verified database created at:\n{result}\n\nThe current database has not changed. "
                f'Close this application, then run:\npython QuiltingTools.py --database "{result}"',
                parent=self.root,
            )

    def show_help(self, screen, name):
        _, full = self.db.help_pair(screen, name)
        window = self.dialog(f"{screen} - {caption(name)}", "Screen Help")
        window.geometry("800x520")
        text = tk.Text(window, wrap="word", padx=12, pady=12)
        text.pack(fill="both", expand=True)
        scroll = ttk.Scrollbar(text, orient="vertical", command=text.yview)
        scroll.pack(side="right", fill="y")
        text.configure(yscrollcommand=scroll.set)
        text.insert("1.0", full)
        text.configure(state="disabled")
        self.attach_help(text, "HelpContent")
        self.button(window, "Close", window.destroy)

    def screen_help(self, parent=None):
        parent = parent or self.root.grab_current() or self.root
        self.show_help(self.context(parent), "ScreenHelp")

    def close(self):
        if self.allow_navigation():
            self.root.destroy()
