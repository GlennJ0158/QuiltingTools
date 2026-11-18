import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch
from tkinter import ttk

from quilting.database import Database
from quilting.model import (
    ADD_ITEM, FABRIC_FIELDS, LIST_COLUMNS, NUMERIC_COLUMNS, FieldError, validate_fields,
)
from quilting.ui import Application, Form, RecordList, display_timestamp
from tests.test_inventory import fabric


def descendants(parent):
    for child in parent.winfo_children():
        yield child
        yield from descendants(child)


@unittest.skipUnless(os.environ.get("DISPLAY") or os.name == "nt", "GUI tests require a display (xvfb-run)")
class ScreenTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "test.db")
        self.root = tk.Tk()
        self.root.withdraw()
        self.errors = patch("quilting.ui.messagebox.showerror").start()
        self.confirm = patch("quilting.ui.messagebox.askyesno", return_value=True).start()
        self.app = Application(self.root, self.db)
        self.root.update()

    def tearDown(self):
        self.root.destroy()
        self.db.close()
        self.temp.cleanup()
        patch.stopall()

    def click(self, parent, label):
        button = next(widget for widget in descendants(parent)
                      if isinstance(widget, ttk.Button) and widget.cget("text") == label)
        button.invoke()
        self.root.update()

    def dialog(self):
        return next(widget for widget in self.root.winfo_children() if isinstance(widget, tk.Toplevel))

    def add_piece(self, **overrides):
        self.app.clear()
        self.app.form.assign(fabric(**overrides))
        self.app.add()
        self.root.update()
        return self.app.piece_id

    def test_form_round_trip_assigns_every_field_and_preserves_exact_lengths(self):
        values = fabric(
            FabricName="Green cotton", Color="Sage", PatternName="Vines", UsableWidth="40 1/64",
            UsableLength="64.123456", GrainDirection="Along Width", PrintDirection="Non-directional",
            StorageLocation="Bin A", Notes="All fields assigned.",
        )
        self.app.form.assign(values)
        self.app.add()
        self.root.update()
        self.assertEqual(self.db.get_piece(self.app.piece_id)["UsableWidth"], 40_015_625)
        self.assertEqual(validate_fields(FABRIC_FIELDS, self.app.form.values()),
                         validate_fields(FABRIC_FIELDS, values))
        self.app.form.variables["Notes"].set("Updated notes")
        self.app.update()
        self.root.update()
        self.assertEqual(self.db.get_piece(self.app.piece_id)["Notes"], "Updated notes")
        self.errors.assert_not_called()

    def test_binding_audit_detects_unassigned_and_misassigned_controls(self):
        for field in FABRIC_FIELDS:
            widget = self.app.form.widgets[field.name]
            original = widget.cget("textvariable")
            widget.configure(textvariable="")
            with self.subTest(field=field.name), self.assertRaises(FieldError):
                self.app.form.values()
            widget.configure(textvariable=original)
        del self.app.form.variables["Color"]
        with self.assertRaises(FieldError):
            self.app.form.values()

    def test_numeric_headings_and_cells_align_right_all_others_left(self):
        for name in LIST_COLUMNS:
            expected = "e" if name in NUMERIC_COLUMNS else "w"
            self.assertEqual(str(self.app.list.tree.column(name, "anchor")), expected, name)
            self.assertEqual(str(self.app.list.tree.heading(name, "anchor")), expected, name)
        labels = [button.cget("text") for button in self.app.list_buttons]
        self.assertEqual(labels.index("Select Highlighted") + 1, labels.index("Filter"))
        self.add_piece()
        self.app.open_history()
        history = next(child for child in self.dialog().winfo_children() if isinstance(child, RecordList))
        for name in history.columns:
            expected = "e" if name == "ID" else "w"
            self.assertEqual(str(history.tree.column(name, "anchor")), expected)
            self.assertEqual(str(history.tree.heading(name, "anchor")), expected)

    def test_highlight_filter_and_reset_change_working_count_not_inventory(self):
        first = self.add_piece(UsableWidth="9")
        second = self.add_piece(UsableWidth="100")
        self.app.list.tree.selection_set(str(first))
        self.root.update()
        self.app.select_highlighted()
        self.root.update()
        self.assertEqual(self.app.list.tree.get_children(), (str(first),))
        self.assertTrue(self.app.list.heading.cget("text").startswith("1 fabric pieces selected; Sort:"))
        self.app.reset_selection()
        self.root.update()
        self.app.open_filter()
        window = self.dialog()
        form = next(child for child in window.winfo_children() if isinstance(child, Form))
        form.variables["MinimumWidth"].set("10")
        self.click(window, "Apply")
        self.assertEqual(self.app.list.tree.get_children(), (str(second),))
        self.assertEqual(len(self.db.pieces()), 2)
        self.app.reset_selection()
        self.root.update()
        self.assertEqual(len(self.app.rows), 2)
        self.errors.assert_not_called()

    def test_bad_filter_is_reported_without_changing_working_list(self):
        self.add_piece()
        self.app.open_filter()
        window = self.dialog()
        form = next(child for child in window.winfo_children() if isinstance(child, Form))
        form.variables["MinimumWidth"].set("not a length")
        self.click(window, "Apply")
        self.errors.assert_called_once()
        self.assertIn("Minimum Width:", self.errors.call_args.args[1])
        self.assertEqual(len(self.app.rows), 1)
        self.assertEqual(self.app.filters["MinimumWidth"], "")
        self.assertTrue(window.winfo_exists())

    def test_sort_dialog_persists_numeric_order(self):
        smaller = self.add_piece(UsableWidth="9")
        larger = self.add_piece(UsableWidth="100")
        self.app.open_sort()
        window = self.dialog()
        form = next(child for child in window.winfo_children() if isinstance(child, Form))
        form.defaults()
        form.variables["SortField1"].set("Usable Width")
        form.variables["Direction1"].set("desc")
        self.click(window, "Apply")
        self.assertEqual(self.app.list.tree.get_children(), (str(larger), str(smaller)))
        self.assertEqual(self.db.load_sort(), (("UsableWidth", "desc"), ("ID", "asc")))
        self.errors.assert_not_called()

    def test_selection_set_can_be_saved_and_recalled_in_ui(self):
        first = self.add_piece()
        self.app.open_sets()
        window = self.dialog()
        form = next(child for child in window.winfo_children() if isinstance(child, Form))
        form.variables["SetName"].set("First project")
        self.click(window, "Save Current")
        self.add_piece(FabricName="Another piece")
        self.app.open_sets()
        window = self.dialog()
        form = next(child for child in window.winfo_children() if isinstance(child, Form))
        form.variables["SavedSet"].set(form.widgets["SavedSet"].cget("values")[1])
        self.click(window, "Apply Saved")
        self.assertEqual(self.app.list.tree.get_children(), (str(first),))
        self.assertEqual(self.app.filters["Status"], "")
        self.errors.assert_not_called()

    def test_canceled_discard_preserves_edited_record_and_highlight(self):
        first = self.add_piece()
        second = self.add_piece()
        self.app.form.variables["Notes"].set("Unsaved work")
        self.confirm.return_value = False
        self.app.list.tree.selection_set(str(first))
        self.root.update()
        self.assertEqual(self.app.piece_id, second)
        self.assertEqual(self.app.list.tree.selection(), (str(second),))
        self.assertEqual(self.app.form.variables["Notes"].get(), "Unsaved work")
        self.app.close()
        self.assertTrue(self.root.winfo_exists())
        self.errors.assert_not_called()

    def test_retiring_piece_removes_it_from_available_view_but_keeps_history(self):
        piece_id = self.add_piece()
        self.app.form.variables["Status"].set("Retired")
        self.app.update()
        self.root.update()
        self.assertEqual(self.app.rows, [])
        self.assertIn("outside the current working selection", self.app.status.cget("text"))
        self.assertEqual(self.db.get_piece(piece_id)["Status"], "Retired")
        self.assertEqual(len(self.db.history(piece_id)), 2)
        self.app.reset_selection()
        self.root.update()
        self.assertEqual(self.app.list.tree.get_children(), (str(piece_id),))

    def test_all_entry_fields_are_left_aligned_and_do_not_stretch(self):
        def verify(form):
            for name, widget in form.widgets.items():
                self.assertEqual(str(widget.cget("justify")), "left", name)
                self.assertEqual(str(widget.grid_info()["sticky"]), "w", name)
                if name in ("UsableWidth", "UsableLength", "MinimumWidth", "MinimumLength"):
                    self.assertEqual(widget.cget("width"), 6, name)
        self.root.deiconify()
        self.root.geometry("1600x900")
        self.root.update()
        verify(self.app.form)
        sizes = {name: widget.winfo_width() for name, widget in self.app.form.widgets.items()}
        self.root.geometry("1100x700")
        self.root.update()
        self.assertEqual(sizes, {name: widget.winfo_width() for name, widget in self.app.form.widgets.items()})
        self.app.open_filter()
        verify(next(child for child in self.dialog().winfo_children() if isinstance(child, Form)))

    def test_add_from_highlighted_piece_creates_new_identity_update_changes_only_new_piece(self):
        first = self.add_piece(Color="Sage", StorageLocation="Bolt 1")
        original = self.db.get_piece(first)
        self.assertFalse(self.app.add_button.instate(["disabled"]))
        self.app.form.variables["UsableLength"].set("30")
        self.click(self.app.inventory_page, "Add")
        second = self.app.piece_id
        self.assertNotEqual(first, second)
        self.assertEqual(self.db.get_piece(first), original)
        self.assertEqual(self.db.get_piece(second)["Color"], "Sage")
        self.assertEqual(self.db.get_piece(second)["UsableLength"], 30_000_000)
        self.app.form.variables["Notes"].set("Second rectangle only")
        self.click(self.app.inventory_page, "Update")
        self.assertEqual(self.db.get_piece(first), original)
        self.assertEqual(self.db.get_piece(second)["Notes"], "Second rectangle only")
        self.assertEqual(len(self.db.history(first)), 1)
        self.assertEqual(len(self.db.history(second)), 2)
        self.errors.assert_not_called()

    def test_utilities_are_on_setup_page_and_do_not_discard_inventory_edits(self):
        inventory_labels = [widget.cget("text") for widget in descendants(self.app.inventory_page)
                            if isinstance(widget, ttk.Button)]
        setup_labels = [widget.cget("text") for widget in descendants(self.app.setup_page)
                        if isinstance(widget, ttk.Button)]
        for label in ("Backup Database", "Restore Database"):
            self.assertNotIn(label, inventory_labels)
            self.assertIn(label, setup_labels)
        self.assertIn("Dropdown", setup_labels)
        self.app.form.variables["Notes"].set("Unsaved fabric note")
        self.app.pages.select(self.app.setup_page)
        self.root.update()
        self.app.pages.select(self.app.inventory_page)
        self.root.update()
        self.assertEqual(self.app.form.variables["Notes"].get(), "Unsaved fabric note")

    def test_dropdown_add_item_cancel_validation_order_and_default_form_values(self):
        widget = self.app.form.widgets["Color"]
        for name in ("FabricName", "Color", "PatternName", "StorageLocation"):
            self.assertEqual(self.app.form.widgets[name].cget("values")[1], ADD_ITEM)
        with patch("quilting.ui.simpledialog.askstring", return_value="Sage"):
            self.app.form.variables["Color"].set(ADD_ITEM)
            widget.event_generate("<<ComboboxSelected>>")
            self.root.update()
        self.assertEqual(self.app.form.variables["Color"].get(), "Sage")
        self.assertEqual(self.db.dropdown_choices("Color"), ("", ADD_ITEM, "Sage"))
        for response in (None, " ", "sAGE"):
            with patch("quilting.ui.simpledialog.askstring", return_value=response):
                self.app.form.variables["Color"].set(ADD_ITEM)
                widget.event_generate("<<ComboboxSelected>>")
                self.root.update()
            self.assertEqual(self.app.form.variables["Color"].get(), "Sage")
        self.assertEqual(self.errors.call_count, 1)
        self.assertIn("Color: A value is required", self.errors.call_args.args[1])
        row = next(row for row in self.db.dropdown_rows("Color") if row["ListItem"] == "Sage")
        self.db.set_dropdown_default(row["ID"])
        self.app.clear()
        self.assertEqual(self.app.form.variables["Color"].get(), "Sage")
        self.assertEqual(self.app.form.widgets["Color"].cget("values")[:2], ("Sage", ADD_ITEM))

    def test_dropdown_setup_sets_default_without_changing_existing_record(self):
        piece_id = self.add_piece(Color="Blue")
        self.db.add_dropdown_item("Color", "Red")
        self.app.open_dropdowns()
        window = self.dialog()
        form = next(child for child in window.winfo_children() if isinstance(child, Form))
        form.variables["FieldName"].set("Color")
        form.widgets["FieldName"].event_generate("<<ComboboxSelected>>")
        self.root.update()
        listing = next(child for child in window.winfo_children() if isinstance(child, RecordList))
        red_id = next(row["ID"] for row in self.db.dropdown_rows("Color") if row["ListItem"] == "Red")
        listing.tree.selection_set(str(red_id))
        self.click(window, "Set Default")
        self.click(window, "Close")
        self.assertEqual(self.app.form.variables["Color"].get(), "Blue")
        self.assertEqual(self.db.get_piece(piece_id)["Color"], "Blue")
        self.app.clear()
        self.assertEqual(self.app.form.variables["Color"].get(), "Red")
        self.errors.assert_not_called()

    def test_metadata_and_history_times_have_minute_precision_only(self):
        piece_id = self.add_piece()
        row = self.db.get_piece(piece_id)
        self.assertIn("Created: " + display_timestamp(row["DateCreated"]), self.app.details.cget("text"))
        self.assertNotIn(row["DateCreated"], self.app.details.cget("text"))
        self.assertRegex(self.app.details.cget("text"), r"Created: \d{4}-\d\d-\d\d \d\d:\d\d    Modified:")
        self.app.open_history()
        window = self.dialog()
        listing = next(child for child in window.winfo_children() if isinstance(child, RecordList))
        item = listing.tree.get_children()[0]
        self.assertRegex(listing.tree.set(item, "DateCreated"), r"^\d{4}-\d\d-\d\d \d\d:\d\d$")
        listing.tree.selection_set(item)
        self.root.update()
        text = next(child for child in window.winfo_children() if isinstance(child, tk.Text))
        self.assertNotIn(row["DateCreated"], text.get("1.0", "end"))
        self.assertIn(display_timestamp(row["DateCreated"]), text.get("1.0", "end"))


if __name__ == "__main__":
    unittest.main()
