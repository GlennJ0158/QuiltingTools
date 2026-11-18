import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch
from tkinter import ttk

from quilting.database import Database
from quilting.model import (
    FABRIC_FIELDS, LIST_COLUMNS, NUMERIC_COLUMNS, FieldError, validate_fields,
)
from quilting.ui import Application, Form, RecordList
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


if __name__ == "__main__":
    unittest.main()
