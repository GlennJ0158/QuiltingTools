import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk
from tkinter import font as tkfont
from unittest.mock import patch

from quilting.database import Database
from quilting.ui import Application, Form, RecordList
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
        for widget in descendants(window):
            if isinstance(widget, (ttk.Button, ttk.Entry, tk.Text)):
                self.assertTrue(all(self.db.help_pair(*widget.help_key())), str(widget))
        form = next(child for child in window.winfo_children() if isinstance(child, Form))
        form.assign(part())
        self.click(window, "Add")
        self.click(window, "Close")
        self.click(self.app.block_page, "Sketch")
        window = self.app.dialogs[-1]
        for widget in descendants(window):
            if isinstance(widget, (ttk.Button, ttk.Entry, tk.Canvas)):
                self.assertTrue(all(self.db.help_pair(*widget.help_key())), str(widget))
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

    def test_create_from_template_uses_block_form_dimensions(self):
        self.app.block_form.assign(block(FinishedWidth="12", FinishedLength="10"))
        self.click(self.app.block_page, "Create from Template")
        window = self.app.dialogs[-1]
        chooser = next(widget for widget in descendants(window) if isinstance(widget, ttk.Combobox))
        for widget in descendants(window):
            if isinstance(widget, (ttk.Button, ttk.Combobox)):
                self.assertTrue(all(self.db.help_pair(*widget.help_key())), str(widget))
                widget.tooltip.show()
                widget.tooltip.hide()
        chooser.set("Flying Geese")
        chooser.event_generate("<<ComboboxSelected>>")
        self.click(window, "Create")
        saved = self.db.get_block(self.app.block_id)
        self.assertEqual(saved["BlockName"], "Flying Geese")
        self.assertEqual(saved["FinishedWidth"], 12_000_000)
        self.assertEqual(saved["FinishedLength"], 10_000_000)
        self.assertEqual(self.app.block_list.tree.selection(), (str(self.app.block_id),))
        self.errors.assert_not_called()

    def test_spiral_parts_allow_user_to_edit_center_value_range(self):
        block_id = self.db.create_block_template("Log Cabin (Spiral)", block())
        self.app.refresh_blocks(block_id)
        self.click(self.app.block_page, "Parts")
        window = self.app.dialogs[-1]
        form = next(child for child in window.winfo_children() if isinstance(child, Form))
        listing = next(child for child in window.winfo_children() if isinstance(child, RecordList))
        center = next(row for row in self.db.block_parts(block_id) if row["PartName"] == "Center")
        listing.tree.selection_set(str(center["ID"]))
        self.root.update()
        form.variables["PartColor"].set("Blue")
        form.variables["MinimumColorValue"].set("3")
        form.variables["MaximumColorValue"].set("6")
        self.click(window, "Update")
        saved = next(row for row in self.db.block_parts(block_id) if row["ID"] == center["ID"])
        self.assertEqual((saved["PartColor"], saved["MinimumColorValue"], saved["MaximumColorValue"]),
                         ("Blue", 3, 6))
        self.errors.assert_not_called()

    def test_eligible_fabrics_dialog_observes_part_range_and_working_selection(self):
        block_id = self.db.create_block_template("Log Cabin (Spiral)", block())
        self.db.approve_block(block_id, 1)
        ids = [self.db.save_piece(fabric(FabricName=f"Value {value}", ColorValue=value))
               for value in ("1", "4", "5", "7", "10", "")]
        self.app.selected_ids = ids[:-2]
        self.app.show_screen("Quilt")
        quilt = self.db.add_quilt("Test")
        self.db.set_quilt_use(quilt, 1, block_id, 1)
        self.app.refresh_quilts()
        self.app.load_quilt(quilt)
        self.root.deiconify()
        self.root.update()
        page = self.app.quilt_page
        self.assertTrue(page.winfo_ismapped())
        choice = next(label for label, saved_id in self.app.approved_blocks.items() if saved_id == block_id)
        self.app.quilt_form.variables["ApprovedBlock"].set(choice)
        self.click(self.app.quilt_page, "Eligible Fabrics")
        window = self.app.dialogs[-1]
        self.root.update()
        self.assertEqual((window.winfo_rootx(), window.winfo_rooty()),
                         (page.winfo_rootx(), page.winfo_rooty()))
        form = next(child for child in window.winfo_children() if isinstance(child, Form))
        listing = next(child for child in window.winfo_children() if isinstance(child, RecordList))
        for side, expected in (("Inner top log", ids[:2]), ("Inner right log", [ids[3]]),
                               ("Center", ids[:4])):
            label = next(value for value in form.widgets["BlockPartChoice"].cget("values") if side in value)
            form.variables["BlockPartChoice"].set(label)
            form.widgets["BlockPartChoice"].event_generate("<<ComboboxSelected>>")
            self.root.update()
            self.assertEqual(set(listing.tree.get_children()), set(map(str, expected)))
        for widget in descendants(window):
            if isinstance(widget, (ttk.Button, ttk.Entry)):
                self.assertTrue(all(self.db.help_pair(*widget.help_key())), str(widget))
        self.errors.assert_not_called()

    def test_four_patch_maps_used_colors_and_saves_part_assignments(self):
        block_id = self.db.create_block_template("Four Patch", block())
        self.db.approve_block(block_id, 1)
        parts = self.db.block_parts(block_id)
        self.assertEqual(len(parts), 2)
        self.assertEqual(sum(p["NumberInBlock"] for p in parts), 4)
        red_a = self.db.save_piece(fabric(FabricName="Red A", Color="Red", UsableWidth="12", UsableLength="12"))
        red_b = self.db.save_piece(fabric(FabricName="Red B", Color="Red", UsableWidth="12", UsableLength="12"))
        yellow = self.db.save_piece(fabric(FabricName="Yellow", Color="Yellow", UsableWidth="12", UsableLength="12"))
        quilt = self.db.add_quilt("Four patch quilt")
        self.app.show_screen("Quilt")
        self.app.refresh_quilts()
        self.app.load_quilt(quilt)
        self.root.deiconify()
        self.root.update()
        page = self.app.quilt_page
        self.assertTrue(page.winfo_ismapped())
        choice = next(label for label, saved_id in self.app.approved_blocks.items() if saved_id == block_id)
        self.app.quilt_form.variables["ApprovedBlock"].set(choice)
        self.click(self.app.quilt_page, "Set Block Quantity")
        self.assertEqual(set(self.app.quilt_form.widgets["PartColor"].cget("values")), {"Red", "Yellow"})
        self.assertIn("Unmapped colors: Red, Yellow", self.app.quilt_summary.cget("text"))
        for color in ("Red", "Yellow"):
            self.app.quilt_form.variables["PartColor"].set(color)
            self.app.quilt_form.variables["InventoryColor"].set(color)
            self.click(self.app.quilt_page, "Map Color")
        self.click(self.app.quilt_page, "Eligible Fabrics")
        window = self.app.dialogs[-1]
        form = next(child for child in window.winfo_children() if isinstance(child, Form))
        listing = next(child for child in window.winfo_children() if isinstance(child, RecordList))
        for color, piece_id in (("Red", red_b), ("Yellow", yellow)):
            label = next(value for value in form.widgets["BlockPartChoice"].cget("values")
                         if f"; {color};" in value)
            form.variables["BlockPartChoice"].set(label)
            form.widgets["BlockPartChoice"].event_generate("<<ComboboxSelected>>")
            self.root.update()
            listing.tree.selection_set(str(piece_id))
            self.click(window, "Assign Fabric to Part")
            self.assertEqual(listing.tree.set(str(piece_id), "Assigned"), "Yes")
        self.assertTrue(self.app.unfinished())
        self.click(window, "Save Selection and Return")
        self.assertFalse(window.winfo_exists())
        expected = {p["ID"]: [red_b if p["PartColor"] == "Red" else yellow] for p in parts}
        self.assertEqual(self.db.quilt_part_fabrics(quilt), expected)
        self.assertIn("Parts without fabric assignments", self.app.quilt_summary.cget("text"))
        plan = self.db.get_quilt_plan(self.db.create_quilt_plan(quilt, self.app.quilt_revision))
        self.assertEqual({source["source"]["ID"] for source in plan["PlanData"]["sources"]}, {red_b, yellow})
        self.assertNotIn(red_a, {source["source"]["ID"] for source in plan["PlanData"]["sources"]})
        self.app.selected_ids = [red_a, yellow]
        self.click(self.app.quilt_page, "Eligible Fabrics")
        window = self.app.dialogs[-1]
        form = next(child for child in window.winfo_children() if isinstance(child, Form))
        listing = next(child for child in window.winfo_children() if isinstance(child, RecordList))
        label = next(value for value in form.widgets["BlockPartChoice"].cget("values") if "; Red;" in value)
        form.variables["BlockPartChoice"].set(label)
        form.widgets["BlockPartChoice"].event_generate("<<ComboboxSelected>>")
        self.root.update()
        self.assertEqual(listing.tree.set(str(red_b), "Assigned"), "Yes")
        self.assertIn("Outside available", listing.tree.set(str(red_b), "Eligibility"))
        listing.tree.selection_set(str(red_b))
        self.click(window, "Remove Assignment")
        self.click(window, "Save Selection and Return")
        self.assertNotIn(next(p["ID"] for p in parts if p["PartColor"] == "Red"),
                         self.db.quilt_part_fabrics(quilt))
        existing_plans = len(self.db.quilt_plans(quilt))
        with patch("quilting.quilt_ui.messagebox.askyesno", return_value=False) as warning:
            self.click(self.app.quilt_page, "Plan Quilt")
        self.assertIn("Parts without assignments: 1", warning.call_args.args[1])
        self.assertEqual(len(self.db.quilt_plans(quilt)), existing_plans)
        self.errors.assert_not_called()

    def test_assignment_cancel_and_navigation_guard_discard_unsaved_changes(self):
        block_id = self.db.create_block_template("Four Patch", block())
        self.db.approve_block(block_id, 1)
        source = self.db.save_piece(fabric(Color="Red"))
        quilt = self.db.add_quilt("Test")
        self.db.set_quilt_use(quilt, 1, block_id, 1)
        self.app.show_screen("Quilt")
        self.app.refresh_quilts()
        self.app.load_quilt(quilt)
        self.app.quilt_form.variables["ApprovedBlock"].set(next(
            name for name, value in self.app.approved_blocks.items() if value == block_id))
        self.click(self.app.quilt_page, "Eligible Fabrics")
        self.assertEqual(self.app.quilt_initial["ApprovedBlock"],
                         self.app.quilt_form.variables["ApprovedBlock"].get())
        window = self.app.dialogs[-1]
        listing = next(child for child in window.winfo_children() if isinstance(child, RecordList))
        listing.tree.selection_set(str(source))
        self.click(window, "Assign Fabric to Part")
        with patch("quilting.quilt_ui.messagebox.askyesno", return_value=False):
            self.click(window, "Cancel")
            self.assertTrue(window.winfo_exists())
            self.app.show_screen("Fabric")
            self.assertEqual(self.app.current, "Quilt")
        self.click(window, "Cancel")
        self.assertEqual(self.db.quilt_part_fabrics(quilt), {})
        self.errors.assert_not_called()

    def test_scale_displays_plain_percentage_without_changing_values_or_range(self):
        scales = ("1", "100", "500", "500.25", "10000", "0.1", "123.123456789012345")
        ids = [self.db.add_block(block(BlockName=f"Scale {scale}", Scale=scale)) for scale in scales]
        self.app.refresh_blocks()
        self.assertEqual(self.app.block_list.tree.heading("Scale")["text"], "Scale (%)")
        for block_id, scale in zip(ids, scales):
            with self.subTest(scale=scale):
                self.assertEqual(self.app.block_list.tree.set(str(block_id), "Scale"), f"{scale}%")
                self.app.block_list.tree.selection_set(str(block_id))
                self.root.update()
                self.assertEqual(self.app.block_form.variables["Scale"].get(), scale)
        self.assertEqual(self.app.block_form.labels["Scale"].cget("text"), "Scale (%)")
        self.assertGreaterEqual(
            self.app.block_list.tree.column("Scale", "width"),
            tkfont.nametofont("TkDefaultFont").measure("123.123456789012345%"),
        )
        self.assertEqual([row["ID"] for row in self.db.blocks(sort=(("Scale", "asc"),))],
                         [ids[i] for i in (5, 0, 1, 6, 2, 3, 4)])
        self.errors.assert_not_called()

    def test_stale_block_error_gives_refresh_steps_and_preserves_unsaved_input(self):
        block_id = self.db.add_block(block())
        self.app.refresh_blocks(block_id)
        other = Database(self.db.path)
        try:
            other.update_block(block_id, 1, block(BlockName="Changed elsewhere"))
        finally:
            other.close()
        self.app.block_form.variables["Description"].set("Unsaved work")
        self.click(self.app.block_page, "Update")
        message = self.errors.call_args.args[1]
        self.assertIn("Error ID: 7", message)
        self.assertIn("choose Refresh", message)
        self.assertIn("Select the block again", message)
        self.assertEqual(self.app.block_form.variables["Description"].get(), "Unsaved work")
        self.assertEqual(self.db.get_block(block_id)["BlockName"], "Changed elsewhere")
        self.click(self.app.block_page, "Refresh")
        self.app.block_list.tree.selection_set(str(block_id))
        self.root.update()
        self.app.block_form.variables["Description"].set("Re-entered")
        self.click(self.app.block_page, "Update")
        self.assertEqual(self.db.get_block(block_id)["Description"], "Re-entered")

    def test_approved_block_error_explains_new_version(self):
        block_id = self.db.create_block_template("Flying Geese", block())
        self.db.approve_block(block_id, 1)
        self.app.refresh_blocks(block_id)
        self.app.block_form.variables["Description"].set("Requested edit")
        self.click(self.app.block_page, "Update")
        message = self.errors.call_args.args[1]
        self.assertIn("Error ID: 7", message)
        self.assertIn("Approved", message)
        self.assertIn("New Version", message)
        self.assertEqual(self.app.block_form.variables["Description"].get(), "Requested edit")
        self.click(self.app.block_page, "New Version")
        self.assertNotEqual(self.app.block_id, block_id)
        self.assertEqual(self.db.get_block(self.app.block_id)["Status"], "Draft")
        self.app.block_form.variables["Description"].set("New draft edit")
        self.click(self.app.block_page, "Update")
        self.assertEqual(self.db.get_block(self.app.block_id)["Description"], "New draft edit")

    def test_opening_parts_does_not_replace_loaded_revision_after_external_change(self):
        block_id = self.db.add_block(block())
        self.app.refresh_blocks(block_id)
        other = Database(self.db.path)
        try:
            other.update_block(block_id, 1, block(BlockName="Changed elsewhere"))
        finally:
            other.close()
        self.click(self.app.block_page, "Parts")
        window = self.app.dialogs[-1]
        form = next(child for child in window.winfo_children() if isinstance(child, Form))
        form.assign(part())
        self.click(window, "Add")
        self.assertIn("choose Refresh", self.errors.call_args.args[1])
        self.assertEqual(self.db.block_parts(block_id), [])
        self.assertEqual(form.variables["PartName"].get(), part()["PartName"])
        self.assertEqual(self.db.get_block(block_id)["BlockName"], "Changed elsewhere")

    def test_approve_with_unsaved_block_details_explains_how_to_proceed(self):
        block_id = self.db.create_block_template("Flying Geese", block())
        self.app.refresh_blocks(block_id)
        self.app.block_form.variables["Description"].set("Unsaved")
        self.click(self.app.block_page, "Approve")
        message = self.errors.call_args.args[1]
        self.assertIn("unsaved details", message)
        self.assertIn("Choose Update", message)
        self.assertEqual(self.db.get_block(block_id)["Status"], "Draft")

    def test_print_sketch_escapes_text_and_includes_cut_outlines(self):
        block_id = self.db.add_block(block(BlockName="<Block>"))
        self.db.save_block_part(block_id, 1, part(PartName="<Panel>", PartWidth="5.01"))
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
        self.assertIn("~5 9/16 x 10 1/2", report)
        self.assertIn("~ marks cut dimensions rounded up", report)
        self.assertIn("Parts overlap", report)
        self.errors.assert_not_called()

    def test_compare_selected_sketches_without_editing_blocks(self):
        ids = [self.db.add_block(block(BlockName=name)) for name in ("Alpha", "Beta", "Gamma", "Delta")]
        self.db.save_block_part(ids[0], 1, part(PartColor="Red"))
        self.db.save_block_part(ids[1], 1, part(PartColor="Blue"))
        before = [dict(self.db.get_block(block_id)) for block_id in ids]
        self.app.refresh_blocks()
        self.app.block_list.tree.selection_set(tuple(map(str, ids)))
        self.root.update()
        self.click(self.app.block_page, "Sketch")
        window = self.app.dialogs[-1]
        self.assertEqual(window.title(), "Compare Block Sketches")
        cards = [widget for widget in descendants(window) if isinstance(widget, ttk.LabelFrame)]
        self.assertEqual(len(cards), 4)
        self.assertTrue(all(any(f"ID {block_id}" in card.cget("text") for card in cards)
                            for block_id in ids))
        sketches = [next(widget for widget in descendants(card) if isinstance(widget, tk.Canvas))
                    for card in cards]
        self.assertTrue(any(sketches[0].itemcget(item, "fill") == "red"
                            for item in sketches[0].find_withtag("all")))
        self.assertTrue(any(sketches[1].itemcget(item, "fill") == "blue"
                            for item in sketches[1].find_withtag("all")))
        self.assertTrue(any("Parts overlap" in widget.cget("text") for widget in descendants(cards[0])
                            if isinstance(widget, ttk.Label)))
        scroll = next(widget for widget in descendants(window)
                      if isinstance(widget, tk.Canvas) and widget not in sketches)
        self.assertGreater(scroll.bbox("all")[3], sketches[0].winfo_height())
        self.assertFalse(any(isinstance(widget, Form) for widget in descendants(window)))
        self.click(window, "Close")
        self.assertEqual([dict(self.db.get_block(block_id)) for block_id in ids], before)
        self.assertEqual(set(self.app.block_list.tree.selection()), set(map(str, ids)))
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
        self.assertIn("Cutting list: Entire Quilt", report)
        self.assertIn("4 Red Rectangle", report)
        self.app.quilt_report_format.set("By Block")
        path_by_block = Path(self.temp.name) / "quilt-by-block.html"
        with patch("quilting.quilt_ui.filedialog.asksaveasfilename", return_value=str(path_by_block)), \
                patch("quilting.quilt_ui.webbrowser.open", return_value=True):
            self.click(self.app.quilt_page, "Print Quilt Plan")
        report = path_by_block.read_text()
        self.assertIn("Cutting list: By Block", report)
        self.assertIn("quantity 2", report)
        self.assertIn("Panel (part ID", report)
        self.assertIn("<polygon", report)
        self.assertEqual(self.db.get_piece(source_id), before)
        form.variables["Quantity"].set("3")
        self.click(self.app.quilt_page, "Plan Quilt")
        self.errors.assert_called_once()
        self.assertIn("Save block quantities", self.errors.call_args.args[1])

    def test_quilt_planning_respects_fabric_working_selection(self):
        block_id = self.db.add_block(block())
        self.db.save_block_part(block_id, 1, part())
        placements = self.db.block_placements(block_id)
        self.db.save_block_placement(block_id, 2, placements[1]["ID"], 5_000_000, 0, 0, False)
        self.db.approve_block(block_id, 3)
        first = self.db.save_piece(fabric(FabricName="First", Color="Red", UsableWidth="12", UsableLength="22"))
        self.db.save_piece(fabric(FabricName="Second", Color="Red", UsableWidth="12", UsableLength="22"))
        quilt = self.db.add_quilt("Test")
        self.db.set_quilt_use(quilt, 1, block_id, 2)
        self.db.add_quilt_mapping(quilt, 2, "Red", "Red")
        self.app.selected_ids = [first]
        self.app.show_screen("Quilt")
        self.app.load_quilt(quilt)
        self.app.generate_quilt_plan()
        data = self.db.get_quilt_plan(self.app.quilt_plan_id)["PlanData"]
        self.assertEqual([entry["source"]["ID"] for entry in data["sources"]], [first])
        self.assertEqual(data["missing"], [])
        self.app.selected_ids = []
        self.app.generate_quilt_plan()
        data = self.db.get_quilt_plan(self.app.quilt_plan_id)["PlanData"]
        self.assertEqual(data["sources"], [])
        self.assertEqual(data["missing"][0]["count"], 4)
