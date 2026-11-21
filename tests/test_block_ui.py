import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

from quilting.database import Database
from quilting.ui import Application, Form
from tests.test_blocks import block, part
from tests.test_ui import descendants
from tests.test_inventory import fabric


@unittest.skipUnless(os.environ.get("DISPLAY") or os.name == "nt", "GUI tests require a display")
class BlockUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "blocks.db")
        self.root = tk.Tk()
        self.root.withdraw()
        self.errors = patch("quilting.ui.messagebox.showerror").start()
        self.confirm = patch("quilting.block_ui.messagebox.askyesno", return_value=True).start()
        self.app = Application(self.root, self.db)
        self.app.show_screen("QuiltBlock")
        self.root.update()

    def tearDown(self):
        self.root.destroy()
        self.db.close()
        self.temp.cleanup()
        patch.stopall()

    def click(self, parent, label):
        next(w for w in descendants(parent) if isinstance(w, ttk.Button) and w.cget("text") == label).invoke()
        self.root.update()

    def test_create_parts_position_approve_and_create_new_version(self):
        self.app.block_form.assign(block())
        self.click(self.app.block_page, "Add")
        block_id = self.app.block_id
        self.click(self.app.block_page, "Parts")
        window = self.app.dialogs[-1]
        form = next(child for child in window.winfo_children() if isinstance(child, Form))
        form.assign(part())
        self.click(window, "Add")
        self.click(window, "Close")
        self.click(self.app.block_page, "Sketch")
        window = self.app.dialogs[-1]
        form = next(child for child in window.winfo_children() if isinstance(child, Form))
        choice = form.widgets["Placement"].cget("values")[1]
        form.variables["Placement"].set(choice)
        form.widgets["Placement"].event_generate("<<ComboboxSelected>>")
        self.root.update()
        form.variables["PositionX"].set("5")
        self.click(window, "Save Placement")
        self.click(window, "Close")
        self.click(self.app.block_page, "Approve")
        self.assertEqual(self.db.get_block(block_id)["Status"], "Approved")
        self.click(self.app.block_page, "New Version")
        self.assertEqual(self.db.get_block(self.app.block_id)["ParentID"], block_id)
        self.errors.assert_not_called()

    def test_filter_and_sort_use_independent_block_working_list(self):
        first = self.db.add_block(block(BlockName="Alpha"))
        self.db.add_block(block(BlockName="Beta"))
        self.app.refresh_blocks()
        self.click(self.app.block_page, "Filter")
        window = self.app.dialogs[-1]
        form = next(child for child in window.winfo_children() if isinstance(child, Form))
        form.variables["BlockName"].set("alp")
        self.click(window, "Apply")
        self.assertEqual(self.app.block_list.tree.get_children(), (str(first),))
        self.click(self.app.block_page, "Reset Selection")
        self.assertEqual(len(self.app.block_list.tree.get_children()), 2)
        self.errors.assert_not_called()

    def test_print_sketch_escapes_text_and_includes_cut_outlines(self):
        block_id = self.db.add_block(block(BlockName="<Block>"))
        self.db.save_block_part(block_id, 1, part(PartName="<Panel>"))
        self.app.refresh_blocks(block_id)
        self.click(self.app.block_page, "Sketch")
        window = self.app.dialogs[-1]
        path = Path(self.temp.name) / "sketch.html"
        with patch("quilting.block_ui.filedialog.asksaveasfilename", return_value=str(path)), \
                patch("quilting.block_ui.webbrowser.open", return_value=True) as browser:
            self.click(window, "Print Sketch")
        browser.assert_called_once_with(path.as_uri())
        report = path.read_text()
        self.assertIn("&lt;Block&gt;", report)
        self.assertIn("&lt;Panel&gt;", report)
        self.assertIn("Cutting outlines", report)
        self.assertIn("5.500000 x 10.500000", report)
        self.assertIn("Parts overlap", report)
        self.errors.assert_not_called()

    def test_quilt_workflow_saves_allocations_and_prints_without_consuming_inventory(self):
        block_id = self.db.add_block(block())
        self.db.save_block_part(block_id, 1, part())
        placements = self.db.block_placements(block_id)
        self.db.save_block_placement(block_id, 2, placements[1]["ID"], 5_000_000, 0, 0, False)
        self.db.approve_block(block_id, 3)
        source_id = self.db.save_piece(fabric(Color="Red", UsableWidth="12", UsableLength="22"))
        before = self.db.get_piece(source_id)
        self.app.show_screen("Quilt")
        self.app.quilt_name_form.variables["QuiltName"].set("Test Quilt")
        self.click(self.app.quilt_page, "Add Quilt")
        form = self.app.quilt_form
        form.variables["ApprovedBlock"].set(next(iter(self.app.approved_blocks)))
        form.variables["Quantity"].set("2")
        self.click(self.app.quilt_page, "Set Block Quantity")
        form.variables["PartColor"].set("Red")
        form.variables["InventoryColor"].set("Red")
        self.click(self.app.quilt_page, "Map Color")
        self.click(self.app.quilt_page, "Plan Quilt")
        self.assertIn("All required parts allocated", self.app.quilt_text.get("1.0", "end"))
        path = Path(self.temp.name) / "quilt.html"
        with patch("quilting.quilt_ui.filedialog.asksaveasfilename", return_value=str(path)), \
                patch("quilting.quilt_ui.webbrowser.open", return_value=True):
            self.click(self.app.quilt_page, "Print Quilt Plan")
        report = path.read_text()
        self.assertIn("<polygon", report)
        self.assertIn("part instance 1", report)
        self.assertEqual(self.db.get_piece(source_id), before)
        form.variables["Quantity"].set("3")
        self.click(self.app.quilt_page, "Plan Quilt")
        self.errors.assert_called_once()
        self.assertIn("Save block quantities", self.errors.call_args.args[1])
