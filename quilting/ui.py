"""Tkinter list/detail screens with shared control and field-binding conventions."""

import json
import sqlite3
import traceback
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import VERSION
from .database import Database
from .model import (
    ADD_ITEM, DROPDOWN_FIELDS, FABRIC_FIELDS, FILTER_FIELDS, LIST_COLUMNS, NUMERIC_COLUMNS,
    SORT_FIELDS, Field, FieldError, caption, display_measurement, normalize_sort, validate_fields,
)

HELP = {
    "FabricName": "Required. Identify the fabric. Each record describes one physical rectangle, "
                  "even when several rectangles have the same fabric name.",
    "Color": "Optional color description. Filters match text contained anywhere in this value.",
    "PatternName": "Optional fabric print or design name, not a quilt construction pattern.",
    "UsableWidth": "Required usable width in inches, excluding selvage and damaged edges. "
                   "Enter 42, 42.5, or 42 1/2. Fractions through 1/64 and up to six decimal places "
                   "are stored exactly. Width and length retain the orientation you assign.",
    "UsableLength": "Required usable length in inches. Use a whole number, decimal, or fraction "
                    "through 1/64. Do not include unit symbols.",
    "GrainDirection": "The direction of lengthwise grain relative to this rectangle's width and "
                      "length. Unknown is explicit; it does not mean rotation is safe.",
    "PrintDirection": "The orientation of a directional print relative to the rectangle. "
                      "Non-directional means rotation does not affect the print's orientation.",
    "StorageLocation": "Optional shelf, bin or other physical storage location.",
    "Status": "Available means this physical piece is usable. Retired removes it from available "
              "stock without deleting its history. Retiring does not represent a cutting transaction.",
    "Notes": "Optional notes, up to 4,000 characters. Press Home/End to navigate a long entry.",
    "MinimumWidth": "Inclusive minimum usable width, in inches. Blank means no minimum. "
                    "This filter does not automatically rotate rectangles.",
    "MinimumLength": "Inclusive minimum usable length, in inches. Blank means no minimum.",
    "SetName": "A unique name for a snapshot of all records in the current working list, "
                "not just highlighted rows. Applying a set clears other list restrictions.",
    "SavedSet": "Choose a saved selection set. Its membership is a snapshot of record IDs; "
                "later edits to those records do not remove them from the set.",
}


def display_timestamp(value):
    """Keep the date while displaying local time only to the minute."""
    return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M")


class Form(ttk.Frame):
    """All editable controls are declared and read through one verified registry."""

    def __init__(self, parent, fields, columns=2, style="TFrame", database=None, on_error=None):
        super().__init__(parent, padding=8, style=style)
        self.fields = tuple(fields)
        self.database, self.on_error = database, on_error
        self.variables, self.widgets = {}, {}
        self.previous_choices = {}
        label_style = "Entry.TLabel" if style == "Entry.TFrame" else "TLabel"
        for index, field in enumerate(self.fields):
            row, pair = divmod(index, columns)
            column = pair * 2
            ttk.Label(self, text=field.label, style=label_style).grid(
                row=row, column=column, sticky="w", padx=(4, 8), pady=4,
            )
            variable = tk.StringVar(master=self, value=field.default)
            if field.kind in ("choice", "dropdown"):
                widget = ttk.Combobox(self, textvariable=variable, values=field.choices,
                                      state="readonly", width=field.width, justify="left")
            else:
                widget = ttk.Entry(self, textvariable=variable, width=field.width, justify="left")
            widget.grid(row=row, column=column + 1, sticky="w", padx=(0, 20), pady=4)
            widget.bind("<F1>", lambda event, item=field: self.help(item))
            self.variables[field.name], self.widgets[field.name] = variable, widget
            if database is not None and field.name in DROPDOWN_FIELDS:
                widget.bind("<<ComboboxSelected>>", lambda event, name=field.name: self.choose_item(name))
                variable.trace_add("write", lambda *_, name=field.name: self.remember_choice(name))
            self.columnconfigure(column + 1, weight=1)
        if database is not None:
            self.defaults()
        self.assert_bindings()

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
        try:
            item = simpledialog.askstring("Add Item", f"{caption(name)}: Enter a new list item.",
                                          parent=self.winfo_toplevel())
            if item is not None:
                stored = self.database.add_dropdown_item(name, item)
                self.refresh_choices()
                self.variables[name].set(stored)
        except FieldError as error:
            if self.on_error is None:
                raise
            self.on_error(error)
        except (sqlite3.Error, OSError) as error:
            if self.on_error is None:
                raise
            self.on_error(FieldError("Database", name, detail=str(error)))

    def assert_bindings(self):
        names = {field.name for field in self.fields}
        if len(names) != len(self.fields) or set(self.variables) != names or set(self.widgets) != names:
            raise FieldError("Binding", "Form", detail="field, variable and widget registries differ")
        for name in names:
            if str(self.widgets[name].cget("textvariable")) != str(self.variables[name]):
                raise FieldError("Binding", name, detail="the control is not assigned to its variable")

    def values(self):
        self.assert_bindings()
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

    def help(self, field):
        messagebox.showinfo(
            field.label, HELP.get(field.name, f"Choose {field.label.lower()} for this operation."),
            parent=self,
        )
        return "break"


class RecordList(ttk.Frame):
    def __init__(self, parent, columns):
        super().__init__(parent, padding=(8, 0, 8, 8))
        self.columns = columns
        self.heading = ttk.Label(self, text="", wraplength=1100)
        self.heading.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(4, 3))
        self.tree = ttk.Treeview(self, columns=columns, show="headings", selectmode="extended")
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
                display_measurement(row[name]) if name in ("UsableWidth", "UsableLength")
                else display_timestamp(row[name]) if name in ("DateCreated", "DateModified")
                else row[name] for name in self.columns
            ]
            self.tree.insert("", "end", iid=str(row["ID"]), values=values)
        order = ", ".join(f"{caption(name)} {direction}" for name, direction in sort)
        self.heading.configure(text=f"{len(rows)} {noun} selected; Sort: {order}{context}")


class Application:
    def __init__(self, root, database):
        self.root, self.db = root, database
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
        self.pages = ttk.Notebook(root)
        self.pages.pack(fill="both", expand=True)
        body = ttk.Frame(self.pages)
        self.inventory_page = body
        self.setup_page = ttk.Frame(self.pages, padding=12)
        self.pages.add(body, text="Fabric Inventory")
        self.pages.add(self.setup_page, text="Setup/Utilities")
        ttk.Label(body, text=f"Fabric Inventory - v{VERSION}", font=("TkDefaultFont", 14, "bold"),
                  padding=8).pack(anchor="w")
        ttk.Label(body, text=f"Database: {self.db.path}", padding=(8, 0, 8, 4)).pack(anchor="w")
        self.form = Form(body, FABRIC_FIELDS, style="Entry.TFrame",
                         database=self.db, on_error=self.show_error)
        self.form.pack(fill="x")
        self.details = ttk.Label(body, text="New fabric rectangle", padding=(8, 4))
        self.details.pack(anchor="w")
        actions = ttk.Frame(body, padding=8)
        actions.pack(fill="x")
        self.add_button = self.button(actions, "Add", self.add)
        self.update_button = self.button(actions, "Update", self.update)
        self.button(actions, "Clear", self.clear)
        self.button(actions, "History", self.open_history)
        self.button(actions, "Screen Help", self.screen_help)
        ttk.Label(self.setup_page, text="Setup/Utilities", font=("TkDefaultFont", 14, "bold")).pack(anchor="w")
        ttk.Label(self.setup_page, text=f"Database: {self.db.path}", padding=(0, 8)).pack(anchor="w")
        utilities = ttk.Frame(self.setup_page)
        utilities.pack(fill="x", pady=8)
        self.button(utilities, "Dropdown", self.open_dropdowns)
        self.button(utilities, "Backup Database", self.backup)
        self.button(utilities, "Restore Database", self.restore)
        ttk.Label(self.setup_page, text="Restore creates a new database; it never replaces the open one. "
                  "Dropdown defaults apply to new forms, not existing inventory.", wraplength=800).pack(anchor="w")
        tools = ttk.Frame(body, padding=(8, 0))
        tools.pack(fill="x")
        self.list_buttons = []
        for label, action in (
            ("Select Highlighted", self.select_highlighted),
            ("Filter", self.open_filter),
            ("Set Selection", self.open_sets),
            ("Sort", self.open_sort),
            ("Reset Selection", self.reset_selection),
            ("Refresh", self.refresh_view),
        ):
            self.list_buttons.append(self.button(tools, label, action))
        self.list = RecordList(body, LIST_COLUMNS)
        self.list.pack(fill="both", expand=True)
        self.list.tree.bind("<<TreeviewSelect>>", self.command(self.on_select))
        self.status = ttk.Label(body, padding=(8, 4), text="Measurements are in inches. F1 shows field help.")
        self.status.pack(fill="x")
        self.initial_values = self.form.values()
        self.clear_details()
        self.refresh()

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
        for form in parent.winfo_children():
            if isinstance(form, Form):
                form.focus_field(error.field)
        if parent == self.root:
            self.form.focus_field(error.field)

    def callback_error(self, exception_type, error, trace):
        traceback.print_exception(exception_type, error, trace)
        self.show_error(FieldError("Unexpected", "Application", detail=str(error)))

    def button(self, parent, text, action):
        widget = ttk.Button(parent, text=text, command=self.command(action))
        widget.pack(side="left", padx=(0, 5))
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

    def dialog(self, title):
        window = tk.Toplevel(self.root)
        window.title(title)
        window.transient(self.root)
        window.grab_set()
        window.bind("<Escape>", lambda _: window.destroy())
        return window

    def open_filter(self):
        window = self.dialog("Filter Fabric Inventory")
        form = Form(window, FILTER_FIELDS, columns=1)
        form.pack(fill="both", expand=True)
        form.assign(self.filters)
        actions = ttk.Frame(window, padding=8)
        actions.pack(fill="x")

        def apply():
            values = form.values()
            validate_fields(FILTER_FIELDS, values)
            if self.allow_discard():
                self.filters = values
                window.destroy()
                self.refresh()

        self.button(actions, "Apply", apply)
        self.button(actions, "Clear Fields", form.defaults)
        self.button(actions, "Cancel", window.destroy)

    def open_dropdowns(self):
        window = self.dialog("Dropdown")
        window.geometry("760x520")
        names = {caption(name): name for name in DROPDOWN_FIELDS}
        fields = (
            Field("FieldName", "choice", choices=tuple(names), default=next(iter(names))),
            Field("ListItem"),
        )
        form = Form(window, fields)
        form.pack(fill="x")
        ttk.Label(window, text="Select a row and use Set Default. Blank is a valid default for an empty "
                  "add form. Defined grain, print and status choices cannot be extended.",
                  wraplength=720, padding=8).pack(anchor="w")
        actions = ttk.Frame(window, padding=8)
        actions.pack(fill="x")
        listing = RecordList(window, ("ID", "FieldName", "ListItem", "Def", "Use"))
        listing.pack(fill="both", expand=True)

        def field_name():
            return names[validate_fields(fields, form.values())["FieldName"]]

        def refresh():
            name = field_name()
            rows = self.db.dropdown_rows(name)
            for row in rows:
                row["FieldName"] = caption(row["FieldName"])
            listing.fill(rows, "dropdown records", (("Def", "desc"), ("ListItem", "asc"), ("ID", "asc")))
            self.form.refresh_choices()

        def add():
            self.db.add_dropdown_item(field_name(), form.values()["ListItem"])
            refresh()

        def set_default():
            selected = listing.tree.selection()
            if len(selected) != 1:
                raise FieldError("OneRecord", "Dropdown")
            self.db.set_dropdown_default(int(selected[0]))
            refresh()

        self.button(actions, "Add Item", add)
        self.button(actions, "Set Default", set_default)
        self.button(actions, "Close", window.destroy)
        form.widgets["FieldName"].bind("<<ComboboxSelected>>", self.command(refresh))
        refresh()

    def open_sort(self):
        window = self.dialog("Sort Fabric Inventory")
        fields = []
        for index in range(1, len(SORT_FIELDS) + 1):
            fields.extend((
                Field(f"SortField{index}", "choice", choices=("", *map(caption, SORT_FIELDS))),
                Field(f"Direction{index}", "choice", choices=("asc", "desc"), default="asc"),
            ))
        form = Form(window, fields)
        form.pack(fill="both", expand=True)
        lookup = {caption(name): name for name in SORT_FIELDS}
        for index, (name, direction) in enumerate(self.sort, 1):
            form.variables[f"SortField{index}"].set(caption(name))
            form.variables[f"Direction{index}"].set(direction)

        def apply():
            values = validate_fields(fields, form.values())
            requested = [
                (lookup[values[f"SortField{index}"]], values[f"Direction{index}"])
                for index in range(1, len(SORT_FIELDS) + 1) if values[f"SortField{index}"]
            ]
            order = normalize_sort(requested)
            if self.allow_discard():
                self.db.save_sort(order)
                self.sort = order
                window.destroy()
                self.refresh()

        actions = ttk.Frame(window, padding=8)
        actions.pack(fill="x")
        self.button(actions, "Apply", apply)
        self.button(actions, "Clear Fields", form.defaults)
        self.button(actions, "Cancel", window.destroy)

    def open_sets(self):
        window = self.dialog("Set Selection")
        rows = self.db.sets()
        choices = {f"{row['SetName']} ({row['RecordCount']} records; ID {row['ID']})": row["ID"] for row in rows}
        fields = (Field("SavedSet", "choice", choices=("", *choices)), Field("SetName"))
        form = Form(window, fields, columns=1)
        form.pack(fill="x")
        ttk.Label(window, text=f"{len(self.rows)} records in the current working list. "
                  "Save Current saves all of them.", padding=8).pack(anchor="w")

        def chosen():
            values = validate_fields(fields, form.values())
            if not values["SavedSet"]:
                raise FieldError("Required", "SavedSet")
            return choices[values["SavedSet"]]

        def save():
            self.db.save_set(form.values()["SetName"], [row["ID"] for row in self.rows])
            window.destroy()
            self.status.configure(text="Saved selection set.")

        def apply():
            set_id = chosen()
            ids = self.db.set_members(set_id)
            if self.allow_discard():
                self.filters = {field.name: "" for field in FILTER_FIELDS}
                self.selected_ids = ids
                self.selection_description = f"Selection set ID {set_id}"
                window.destroy()
                self.refresh()

        def delete():
            set_id = chosen()
            if messagebox.askyesno("Delete Selection Set", "Delete this set? Fabric records are kept.",
                                   parent=window):
                self.db.delete_set(set_id)
                window.destroy()
                self.status.configure(text="Deleted selection set. The current working list is unchanged.")

        actions = ttk.Frame(window, padding=8)
        actions.pack(fill="x")
        self.button(actions, "Save Current", save)
        self.button(actions, "Apply Saved", apply)
        self.button(actions, "Delete Saved", delete)
        self.button(actions, "Cancel", window.destroy)

    def open_history(self):
        if self.piece_id is None:
            raise FieldError("OneRecord", "Fabric Inventory")
        rows = self.db.history(self.piece_id)
        window = self.dialog(f"Fabric Piece {self.piece_id} - History")
        window.geometry("950x600")
        listing = RecordList(window, ("ID", "Action", "DateCreated"))
        listing.pack(fill="both", expand=True)
        listing.fill(rows, "history records", (("ID", "desc"),))
        text = tk.Text(window, height=14, wrap="word", state="disabled")
        text.pack(fill="both", expand=True, padx=8, pady=8)
        scroll = ttk.Scrollbar(text, orient="vertical", command=text.yview)
        scroll.pack(side="right", fill="y")
        text.configure(yscrollcommand=scroll.set)

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

    def screen_help(self):
        messagebox.showinfo(
            "Fabric Inventory Help",
            "Each record is one usable fabric rectangle. Dimensions are in inches, excluding selvage "
            "and damaged edges. Press F1 in a field for help.\n\n"
            "Highlight one row to fill the form. Add creates a separate piece from these values; "
            "Update changes the highlighted piece. Clear discards "
            "details and starts a new piece. History shows saved changes. Retire a piece instead of "
            "deleting it; record actual remaining dimensions when making an inventory correction.\n\n"
            "Select Highlighted restricts the working list to highlighted rows. Filter applies text, "
            "minimum-size and status criteria. Set Selection saves the whole working list, or recalls "
            "a snapshot and clears other restrictions. Sort supports multiple fields. Reset Selection "
            "shows all records, including retired ones. The initial view shows Available pieces.\n\n"
            "Setup/Utilities contains Dropdown defaults, Backup Database and Restore Database. "
            "Backup saves committed data to a new file. Restore creates a separate verified database "
            "and never changes your open database. Keep the live database on a local disk; "
            "coordinate restores and future upgrades with other users.\n\n"
            "This first milestone does not yet generate cutting plans or track cuts and remnants.",
            parent=self.root,
        )

    def close(self):
        if self.allow_discard():
            self.root.destroy()
