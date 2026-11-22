import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from html.parser import HTMLParser
from unittest.mock import patch
from tkinter import ttk
from tkinter import font as tkfont

from quilting.database import Database
from quilting.helptext import DROPDOWN_COLUMNS, NAVIGATION
from quilting.model import (
    ADD_ITEM, FABRIC_FIELDS, LIST_COLUMNS, NUMERIC_COLUMNS, FieldError, validate_fields,
)
from quilting.ui import Application, Form, RecordList, display_back_measurement, display_timestamp
from tests.test_inventory import fabric
from tests.test_errors import error_values


class ReportCells(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cells = []
        self.in_cell = False

    def handle_starttag(self, tag, attrs):
        if tag == "td":
            self.in_cell = True
            self.cells.append("")

    def handle_endtag(self, tag):
        if tag == "td":
            self.in_cell = False

    def handle_data(self, data):
        if self.in_cell:
            self.cells[-1] += data


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
        self.default_confirm = patch("quilting.ui.messagebox.askyesnocancel", return_value=False).start()
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
            if isinstance(widget, tk.Text):
                continue
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

    def test_filter_color_dropdown_and_inclusive_size_fields(self):
        self.db.add_dropdown_item("Color", "Blue")
        self.db.add_dropdown_item("Color", "Red")
        selected = self.add_piece(Color="Blue", UsableWidth="10", UsableLength="20")
        self.add_piece(Color="Red", UsableWidth="10", UsableLength="20")
        self.add_piece(Color="Blue", UsableWidth="11", UsableLength="20")
        self.app.open_filter()
        window = self.dialog()
        form = next(child for child in window.winfo_children() if isinstance(child, Form))
        color = form.widgets["Color"]
        self.assertIsInstance(color, ttk.Combobox)
        self.assertIn("Blue", color.cget("values"))
        self.assertIn("", color.cget("values"))
        for minimum, maximum in (("MinimumWidth", "MaximumWidth"), ("MinimumLength", "MaximumLength")):
            self.assertEqual(form.widgets[minimum].grid_info()["row"], form.widgets[maximum].grid_info()["row"])
            self.assertLess(form.widgets[minimum].grid_info()["column"], form.widgets[maximum].grid_info()["column"])
        for name, value in (("Color", "Blue"), ("MinimumWidth", "10"), ("MaximumWidth", "10"),
                            ("MinimumLength", "20"), ("MaximumLength", "20")):
            form.variables[name].set(value)
        self.click(window, "Apply")
        self.assertEqual(self.app.list.tree.get_children(), (str(selected),))
        self.errors.assert_not_called()

    def test_notes_are_wide_two_line_scrollable_and_persist(self):
        self.root.deiconify()
        self.root.update()
        notes = self.app.form.widgets["Notes"]
        self.assertIsInstance(notes, tk.Text)
        self.assertEqual(notes.cget("height"), 2)
        self.assertGreater(notes.winfo_width(), self.app.form.winfo_width() * .7)
        scroll = next(w for w in notes.master.winfo_children() if isinstance(w, ttk.Scrollbar))
        value = "First line\nSecond line\nThird line"
        notes.insert("1.0", value)
        self.root.update()
        scroll.tk.call(scroll.cget("command"), "moveto", 1.0)
        self.root.update()
        self.assertGreater(notes.yview()[0], 0)
        self.assertEqual(self.app.form.values()["Notes"], value)
        self.app.form.assign(fabric(Notes=value))
        self.app.add()
        self.assertEqual(self.db.get_piece(self.app.piece_id)["Notes"], value)

    def test_list_names_are_visually_capped_without_changing_records(self):
        name = "A" * 50
        block_id = self.db.add_block({
            "BlockName": name, "Description": "", "FinishedWidth": "12", "FinishedLength": "12",
            "Scale": "100", "SeamAllowance": "1/4",
        })
        source_id = self.db.save_piece(fabric(UsableWidth="100", UsableLength="100"))
        from quilting.backs import generate_layouts, INCH
        layout = generate_layouts([self.db.get_piece(source_id)], 30 * INCH, 30 * INCH, 0, INCH)[0]
        back_id = self.db.save_back_draft(name, 30 * INCH, 30 * INCH, 0, INCH, layout)
        self.app.refresh_blocks()
        self.app.refresh_backs()
        for listing, record_id, field in ((self.app.block_list, block_id, "BlockName"),
                                          (self.app.back_list, back_id, "BackName")):
            self.assertEqual(listing.tree.item(str(record_id), "values")[listing.columns.index(field)], name[:25])
            self.assertTrue(all(not listing.tree.column(column, "stretch") for column in listing.columns))
        self.assertEqual(self.db.get_block(block_id)["BlockName"], name)
        self.assertEqual(self.db.get_quilt_back(back_id)["BackName"], name)

    def test_large_separate_margins_warn_and_generate(self):
        self.add_piece(UsableWidth="100", UsableLength="100")
        self.app.show_screen("Quilt Backs")
        self.app.back_form.assign({
            "BackName": "Back", "QuiltWidth": "30", "QuiltLength": "40",
            "Margin": "11", "SideMargin": "4", "SeamAllowance": "1",
        })
        with patch("quilting.ui.messagebox.showwarning") as warning:
            self.app.generate_back_plans()
            warning.assert_called_once()
        self.assertEqual((self.app.back_selected_layout.target_width, self.app.back_selected_layout.target_length),
                         (38_000_000, 62_000_000))
        self.app.save_back_draft()
        saved = self.db.get_quilt_back(self.app.back_selected_id)
        self.assertEqual((saved["Margin"], saved["SideMargin"]), (11_000_000, 4_000_000))
        self.app.back_form.variables["Margin"].set("10")
        self.app.back_form.variables["SideMargin"].set("10")
        with patch("quilting.ui.messagebox.showwarning") as warning:
            self.app.generate_back_plans()
            warning.assert_not_called()
            self.app.back_form.variables["SideMargin"].set("10.000001")
            self.app.generate_back_plans()
            warning.assert_called_once()
        self.errors.assert_not_called()

    def test_back_margin_fields_fit_and_follow_top_bottom_margin(self):
        self.root.deiconify()
        self.root.geometry("1000x650")
        self.app.show_screen("Quilt Backs")
        self.root.update()
        form = self.app.back_form
        top, side = form.widgets["Margin"], form.widgets["SideMargin"]
        self.assertEqual(form.labels["Margin"].cget("text"), "Top/Bottom Margin (in)")
        self.assertEqual(top.grid_info()["row"], side.grid_info()["row"])
        self.assertLess(top.grid_info()["column"], side.grid_info()["column"])
        for widget in form.widgets.values():
            self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(),
                                 self.root.winfo_rootx() + self.root.winfo_width())

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
                if isinstance(widget, tk.Text):
                    continue
                self.assertEqual(str(widget.cget("justify")), "left", name)
                self.assertEqual(str(widget.grid_info()["sticky"]), "w", name)
                if name in ("UsableWidth", "UsableLength", "MinimumWidth", "MaximumWidth",
                            "MinimumLength", "MaximumLength"):
                    self.assertEqual(widget.cget("width"), 6, name)
        self.root.deiconify()
        self.root.geometry("1600x900")
        self.root.update()
        verify(self.app.form)
        sizes = {name: widget.winfo_width() for name, widget in self.app.form.widgets.items() if name != "Notes"}
        self.root.geometry("1100x700")
        self.root.update()
        self.assertEqual(sizes, {name: widget.winfo_width() for name, widget in self.app.form.widgets.items()
                                 if name != "Notes"})
        self.app.open_filter()
        verify(next(child for child in self.dialog().winfo_children() if isinstance(child, Form)))

    def test_requested_screens_have_blue_entry_panels_below_intro_and_actions(self):
        style = ttk.Style(self.root)
        self.assertEqual(style.lookup("Entry.TFrame", "background"), "#c3dafd")
        for screen, page, form_name, action_name in (
            ("DropDown", self.app.dropdown_page, "dropdown_form", "Add"),
            ("HelpText", self.app.help_page, "help_form", "Update"),
            ("ErrorMessage", self.app.error_page, "error_form", "Select Highlighted"),
            ("Quilt Backs", self.app.backs_page, "back_form", "Set Sketch Color"),
        ):
            self.app.show_screen(screen)
            form = getattr(self.app, form_name)
            self.assertEqual(form.master.cget("style"), "Entry.TFrame", screen)
            self.assertTrue(all(
                label.cget("style") == "Entry.TLabel"
                for label in form.winfo_children() if isinstance(label, ttk.Label)
            ), screen)
            action = next(
                widget for widget in descendants(page)
                if isinstance(widget, ttk.Button) and widget.cget("text") == action_name
            )
            self.assertEqual(action.master.cget("style"), "Entry.TFrame", screen)
            self.assertNotEqual(form.master, page, screen)

    def test_back_sources_follow_inventory_working_selection_and_default_to_visible_sources(self):
        first = self.add_piece(FabricName="First", UsableWidth="100", UsableLength="100")
        second = self.add_piece(FabricName="Second", UsableWidth="100", UsableLength="100")
        self.app.selected_ids = [first]
        self.app.show_screen("Quilt Backs")
        self.assertEqual(self.app.back_stock.tree.get_children(), (str(first),))
        self.app.back_form.assign({
            "BackName": "Back", "QuiltWidth": "30", "QuiltLength": "30",
            "Margin": "0", "SideMargin": "0", "SeamAllowance": "1",
        })
        self.app.generate_back_plans()
        self.assertTrue(self.app.back_layouts)
        self.assertTrue(all(panel.source_id == first for layout in self.app.back_layouts
                            for panel in layout.panels))
        self.app.selected_ids = None
        self.app.refresh_back_stock()
        self.assertEqual(set(self.app.back_stock.tree.get_children()), {str(first), str(second)})

    def test_back_fabric_selection_is_independent_and_generation_uses_visible_sources(self):
        first = self.add_piece(FabricName="First", UsableWidth="100", UsableLength="100")
        second = self.add_piece(FabricName="Second", UsableWidth="100", UsableLength="100")
        retired = self.db.save_piece(fabric(
            FabricName="Retired", UsableWidth="100", UsableLength="100", Status="Retired",
        ))
        set_id = self.db.save_set("Sources", [first, second, retired])
        self.app.selected_ids = [first]
        self.app.show_screen("Quilt Backs")
        actions = self.app.back_stock.master.winfo_children()[0]
        stock_actions = next(w for w in descendants(actions)
                             if isinstance(w, ttk.Button) and w.cget("text") == "Refresh Fabric").master
        self.assertEqual([w.cget("text") for w in stock_actions.winfo_children()
                          if isinstance(w, ttk.Button)][-3:],
                         ["Refresh Fabric", "Use Named Selection", "Select Highlighted"])
        self.click(stock_actions, "Use Named Selection")
        dialog = self.app.dialogs[-1]
        form = self.app.dialog_forms[dialog][0]
        form.variables["SavedSet"].set(f"Sources (3 records; ID {set_id})")
        self.click(dialog, "Apply")
        self.assertEqual(set(self.app.back_stock.tree.get_children()), {str(first), str(second)})
        with self.assertRaises(FieldError):
            self.app.select_back_fabric()
        self.app.back_stock.tree.selection_set(str(second))
        self.click(stock_actions, "Select Highlighted")
        self.assertEqual(self.app.back_stock.tree.get_children(), (str(second),))
        self.assertEqual(self.app.selected_ids, [first])
        self.app.back_form.assign({
            "BackName": "Back", "QuiltWidth": "30.123456", "QuiltLength": "30",
            "Margin": "0", "SideMargin": "0", "SeamAllowance": "1",
        })
        self.app.generate_back_plans()
        self.assertTrue(self.app.back_layouts)
        self.assertTrue(all(panel.source_id == second for layout in self.app.back_layouts
                            for panel in layout.panels))
        self.app.save_back_draft()
        self.assertEqual(self.db.get_quilt_back(self.app.back_selected_id)["QuiltWidth"], 30_123_456)
        self.click(stock_actions, "Use Named Selection")
        self.click(self.app.dialogs[-1], "Apply")
        self.assertEqual(self.app.back_stock.tree.get_children(), (str(first),))
        self.assertEqual(self.app.selected_ids, [first])
        self.errors.assert_not_called()

    def test_back_layout_count_compact_fields_and_rounded_display(self):
        source = self.add_piece(FabricName="Precise", UsableWidth="100.123456", UsableLength="100")
        self.app.show_screen("Quilt Backs")
        self.assertEqual(self.app.back_candidates.heading.cget("text"), "0 ranked layout plans selected")
        for name in ("QuiltWidth", "QuiltLength", "Margin", "SideMargin", "SeamAllowance"):
            self.assertEqual(int(self.app.back_form.widgets[name].cget("width")), 8)
        self.assertEqual(self.app.back_form.grid_columnconfigure(1)["weight"], 0)
        values = self.app.back_stock.tree.item(str(source), "values")
        self.assertEqual(values[LIST_COLUMNS.index("UsableWidth")], "100.123")
        self.app.back_form.assign({
            "BackName": "Back", "QuiltWidth": "30", "QuiltLength": "30",
            "Margin": "0", "SideMargin": "0", "SeamAllowance": "1",
        })
        self.app.generate_back_plans()
        self.assertEqual(self.app.back_candidates.heading.cget("text"),
                         f"{len(self.app.back_layouts)} ranked layout plans selected")
        self.app.back_form.variables["QuiltWidth"].set("1000")
        self.app.generate_back_plans()
        self.assertEqual(self.app.back_candidates.heading.cget("text"), "0 ranked layout plans selected")
        self.assertEqual(self.db.get_piece(source)["UsableWidth"], 100_123_456)
        self.assertEqual(display_back_measurement(15_625), "0.016")
        self.assertEqual(display_back_measurement(1_234_500), "1.235")
        self.assertEqual(display_back_measurement(10_800_000_000), "10800")

    def test_quilt_back_saved_plans_have_isolated_ordered_working_list_tools(self):
        source_id = self.add_piece(
            FabricName="Backing", UsableWidth="100", UsableLength="100",
        )
        self.app.show_screen("Quilt Backs")
        self.app.back_form.assign({
            "BackName": "Back A", "QuiltWidth": "30", "QuiltLength": "30",
            "Margin": "0", "SideMargin": "0", "SeamAllowance": "1",
        })
        self.app.back_stock.tree.selection_set(str(source_id))
        self.app.generate_back_plans()
        layout = self.app.back_selected_layout
        self.db.save_back_draft("Back A", 30_000_000, 30_000_000, 0, 1_000_000, layout)
        self.db.save_back_draft("Back B", 30_000_000, 30_000_000, 0, 1_000_000, layout)
        self.app.refresh_backs()
        self.assertEqual(self.app.back_stock.tree.get_children(), (str(source_id),))
        candidate_ids = self.app.back_candidates.tree.get_children()
        self.assertTrue(candidate_ids)

        labels = [widget.cget("text") for widget in descendants(self.app.backs_page)
                  if isinstance(widget, ttk.Button)]
        start = len(labels) - 1 - labels[::-1].index("Select Highlighted")
        self.assertEqual(labels[start:start + 5], [
            "Select Highlighted", "Filter", "Set Selection", "Reset Selection", "Sort",
        ])
        self.click(self.app.backs_page, "Filter")
        form = self.app.dialog_forms[self.app.dialogs[-1]][0]
        form.variables["BackName"].set("back b")
        self.click(self.app.dialogs[-1], "Apply")
        self.assertEqual(
            [self.app.back_list.tree.item(item, "values")[1]
             for item in self.app.back_list.tree.get_children()],
            ["Back B"],
        )
        self.click(self.app.backs_page, "Reset Selection")
        back_b = next(row["ID"] for row in self.db.quilt_backs() if row["BackName"] == "Back B")
        self.app.back_list.tree.selection_set(str(back_b))
        saved_tools = next(w for w in descendants(self.app.backs_page)
                           if isinstance(w, ttk.Button) and w.cget("text") == "Filter").master
        self.click(saved_tools, "Select Highlighted")
        self.assertEqual(self.app.back_list.tree.get_children(), (str(back_b),))
        self.assertEqual(self.app.back_stock.tree.get_children(), (str(source_id),))
        self.assertEqual(self.app.back_candidates.tree.get_children(), candidate_ids)
        self.click(self.app.backs_page, "Reset Selection")
        self.click(self.app.backs_page, "Sort")
        form = self.app.dialog_forms[self.app.dialogs[-1]][0]
        form.defaults()
        form.variables["SortField1"].set("Back Name")
        form.variables["Direction1"].set("desc")
        self.click(self.app.dialogs[-1], "Apply")
        self.assertEqual(self.db.load_sort("QuiltBackSort"), (("BackName", "desc"), ("ID", "asc")))
        self.click(self.app.backs_page, "Set Selection")
        form = self.app.dialog_forms[self.app.dialogs[-1]][0]
        form.variables["SetName"].set("Two backs")
        self.click(self.app.dialogs[-1], "Save Current")
        self.assertEqual(len(self.db.sets("Quilt Backs")), 1)
        self.errors.assert_not_called()

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

    def test_utilities_are_on_setup_page_and_navigation_confirms_discard(self):
        inventory_labels = [widget.cget("text") for widget in descendants(self.app.inventory_page)
                            if isinstance(widget, ttk.Button)]
        setup_labels = [widget.cget("text") for widget in descendants(self.app.setup_page)
                        if isinstance(widget, ttk.Button)]
        for label in ("Backup Database", "Restore Database"):
            self.assertNotIn(label, inventory_labels)
            self.assertIn(label, setup_labels)
        self.app.form.variables["Notes"].set("Unsaved fabric note")
        self.confirm.return_value = False
        self.app.nav.buttons["Setup"].invoke()
        self.root.update()
        self.assertEqual(self.app.current, "Fabric")
        self.assertEqual(self.app.form.variables["Notes"].get(), "Unsaved fabric note")
        self.confirm.return_value = True
        self.app.nav.buttons["Setup"].invoke()
        self.app.nav.buttons["Fabric"].invoke()
        self.root.update()
        self.assertEqual(self.app.form.variables["Notes"].get(), "")

    def test_dropdown_add_item_cancel_validation_order_and_default_form_values(self):
        widget = self.app.form.widgets["Color"]
        for name in ("FabricName", "Color", "PatternName", "StorageLocation"):
            self.assertEqual(self.app.form.widgets[name].cget("values")[0], ADD_ITEM)
        def enter_item(response):
            self.app.form.variables["Color"].set(ADD_ITEM)
            widget.event_generate("<<ComboboxSelected>>")
            self.root.update()
            window = self.app.dialogs[-1]
            if response is None:
                self.click(window, "Cancel")
            else:
                self.app.dialog_forms[window][0].variables["ListItem"].set(response)
                self.click(window, "Add Item")
                if window.winfo_exists():
                    self.click(window, "Cancel")

        enter_item("Sage")
        self.assertEqual(self.app.form.variables["Color"].get(), "Sage")
        self.assertEqual(self.db.dropdown_choices("Color"), (ADD_ITEM, "Sage"))
        for response in (None, " ", "sAGE"):
            enter_item(response)
            self.assertEqual(self.app.form.variables["Color"].get(), "Sage")
        self.assertEqual(self.errors.call_count, 1)
        self.assertIn("List Item: A value is required", self.errors.call_args.args[1])
        row = next(row for row in self.db.dropdown_rows("Color") if row["ListItem"] == "Sage")
        self.db.set_dropdown_default(row["ID"])
        self.app.clear()
        self.assertEqual(self.app.form.variables["Color"].get(), "Sage")
        self.assertEqual(self.app.form.widgets["Color"].cget("values")[:2], ("Sage", ADD_ITEM))
        self.assertEqual(self.app.form.variables["FabricName"].get(), "Choose FabricName")

    def test_dropdown_setup_sets_default_without_changing_existing_record(self):
        piece_id = self.add_piece(Color="Blue")
        self.db.add_dropdown_item("Color", "Red")
        self.app.open_dropdowns()
        window = self.app.dropdown_page
        form = self.app.dropdown_form
        form.variables["FieldName"].set("Color")
        form.widgets["FieldName"].event_generate("<<ComboboxSelected>>")
        self.root.update()
        listing = next(child for child in window.winfo_children() if isinstance(child, RecordList))
        blue_id = next(row["ID"] for row in self.db.dropdown_rows("Color") if row["ListItem"] == "Blue")
        listing.tree.selection_set(str(blue_id))
        self.root.update()
        form.variables["Def"].set("Clear Default")
        self.click(window, "Update")
        red_id = next(row["ID"] for row in self.db.dropdown_rows("Color") if row["ListItem"] == "Red")
        listing.tree.selection_set(str(red_id))
        self.root.update()
        form.variables["Def"].set("Set Default")
        self.click(window, "Update")
        self.app.nav.buttons["Fabric"].invoke()
        self.assertEqual(self.db.get_piece(piece_id)["Color"], "Blue")
        self.app.clear()
        self.assertEqual(self.app.form.variables["Color"].get(), "Red")
        self.errors.assert_not_called()

    def test_add_item_can_replace_existing_defaults_or_cancel(self):
        self.db.add_dropdown_item("Color", "Blue", default=True)
        widget = self.app.form.widgets["Color"]
        self.app.form.variables["Color"].set(ADD_ITEM)
        widget.event_generate("<<ComboboxSelected>>")
        self.root.update()
        window = self.app.dialogs[-1]
        form = self.app.dialog_forms[window][0]
        form.variables["ListItem"].set("Sage")
        form.variables["Def"].set("Set Default")
        self.default_confirm.return_value = None
        self.click(window, "Add Item")
        self.assertTrue(window.winfo_exists())
        self.assertEqual(self.db.dropdown_default("Color"), "Blue")
        self.assertNotIn("Sage", self.db.dropdown_choices("Color"))
        self.default_confirm.return_value = True
        self.click(window, "Add Item")
        self.assertEqual(self.db.dropdown_default("Color"), "Sage")
        self.assertEqual(self.app.form.variables["Color"].get(), "Sage")
        self.errors.assert_not_called()

    def test_dropdown_add_update_delete_and_multiple_default_warning(self):
        warning = patch("quilting.ui.messagebox.showwarning").start()
        self.app.open_dropdowns()
        form = self.app.dropdown_form
        form.variables["FieldName"].set("Color")
        form.widgets["FieldName"].event_generate("<<ComboboxSelected>>")
        self.root.update()
        form.variables["ListItem"].set("Blue")
        self.click(self.app.dropdown_page, "Add")
        self.assertEqual(self.errors.call_count, 1)
        form.variables["Def"].set("Set Default")
        form.variables["Use"].set("Set Use")
        self.click(self.app.dropdown_page, "Add")
        form.variables["ListItem"].set("Green")
        form.variables["Def"].set("Set Default")
        form.variables["Use"].set("Set Use")
        self.click(self.app.dropdown_page, "Add")
        warning.assert_called_once()
        blue = next(row for row in self.db.dropdown_rows("Color") if row["ListItem"] == "Blue")
        self.app.dropdown_list.tree.selection_set(str(blue["ID"]))
        self.root.update()
        self.assertEqual(form.variables["Def"].get(), "Ignore for Update")
        form.variables["Use"].set("Clear Use")
        self.click(self.app.dropdown_page, "Update")
        self.assertEqual(self.db.get_dropdown(blue["ID"])["Use"], 0)
        self.assertNotIn("Blue", self.db.dropdown_choices("Color"))
        self.app.dropdown_list.tree.selection_set(str(blue["ID"]))
        self.root.update()
        self.click(self.app.dropdown_page, "Delete")
        with self.assertRaises(FieldError):
            self.db.get_dropdown(blue["ID"])

    def test_dropdown_draft_survives_cancelled_selection_and_scope_changes(self):
        self.db.add_dropdown_item("Color", "Blue")
        self.db.add_dropdown_item("Color", "Sage")
        self.app.open_dropdowns()
        form = self.app.dropdown_form
        form.variables["FieldName"].set("Color")
        form.widgets["FieldName"].event_generate("<<ComboboxSelected>>")
        self.root.update()
        blue = next(row for row in self.db.dropdown_rows("Color") if row["ListItem"] == "Blue")
        sage = next(row for row in self.db.dropdown_rows("Color") if row["ListItem"] == "Sage")
        self.app.dropdown_list.tree.selection_set(str(blue["ID"]))
        self.root.update()
        form.variables["ListItem"].set("Draft")
        self.confirm.return_value = False
        self.app.dropdown_list.tree.selection_set(str(sage["ID"]))
        self.root.update()
        self.assertEqual(self.app.dropdown_list.tree.selection(), (str(blue["ID"]),))
        form.variables["FieldName"].set("PatternName")
        form.widgets["FieldName"].event_generate("<<ComboboxSelected>>")
        self.root.update()
        self.assertEqual(form.variables["FieldName"].get(), "Color")
        self.assertEqual(form.variables["ListItem"].get(), "Draft")

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

    def test_navigation_order_alignment_and_help_coverage_on_every_screen(self):
        self.root.deiconify()
        piece_id = self.add_piece()

        def verify(parent, nav):
            self.root.update()
            self.assertEqual(tuple(nav.buttons), NAVIGATION)
            buttons = list(nav.buttons.values())
            positions = [button.winfo_rootx() for button in buttons]
            self.assertEqual(positions, sorted(positions))
            right = buttons[-1].winfo_rootx() + buttons[-1].winfo_width()
            self.assertLessEqual(parent.winfo_rootx() + parent.winfo_width() - right, 20)
            self.assertLess(nav.winfo_y(), 10)
            for widget in descendants(parent):
                if isinstance(widget, ttk.Button):
                    pair = self.db.help_pair(*widget.help_key())
                    self.assertTrue(all(pair), widget.cget("text"))
                if isinstance(widget, Form):
                    for field in widget.widgets.values():
                        self.assertTrue(all(self.db.help_pair(*field.help_key())))
                if isinstance(widget, RecordList):
                    screen = self.app.context(widget)
                    for name in widget.columns:
                        self.assertTrue(all(self.db.help_pair(screen, f"Column:{name}")))

        for screen in self.app.screens:
            self.app.show_screen(screen)
            verify(self.root, self.app.nav)
        self.app.show_screen("Fabric")
        for open_dialog in (self.app.open_filter, self.app.open_sort, self.app.open_sets,
                            lambda: (self.app.load_piece(piece_id), self.app.open_history()),
                            lambda: self.app.open_add_item(self.app.form, "Color"),
                            self.app.screen_help):
            open_dialog()
            window = self.app.dialogs[-1]
            verify(window, window.nav)
            window.destroy()
        self.errors.assert_not_called()

    def test_modal_navigation_cancellation_and_help_preserve_or_discard_the_right_work(self):
        piece_id = self.add_piece()
        self.app.form.variables["Notes"].set("Uncommitted fabric edit")
        self.app.open_filter()
        window = self.app.dialogs[-1]
        form = self.app.dialog_forms[window][0]
        form.variables["MinimumWidth"].set("invalid unfinished input")
        self.confirm.reset_mock()
        window.nav.buttons["Screen Help"].invoke()
        help_window = self.app.dialogs[-1]
        text = next(child for child in help_window.winfo_children() if isinstance(child, tk.Text))
        self.assertEqual(text.get("1.0", "end-1c"), self.db.help_pair("Filter", "ScreenHelp")[1])
        self.assertEqual(self.app.current, "Fabric")
        self.confirm.assert_not_called()
        help_window.destroy()
        self.assertEqual(self.root.grab_current(), window)
        self.confirm.return_value = False
        window.nav.buttons["Setup"].invoke()
        self.assertTrue(window.winfo_exists())
        self.assertEqual(self.root.grab_current(), window)
        self.assertEqual(form.values()["MinimumWidth"], "invalid unfinished input")
        self.assertEqual(self.app.form.values()["Notes"], "Uncommitted fabric edit")
        self.confirm.return_value = True
        self.confirm.reset_mock()
        window.nav.buttons["Setup"].invoke()
        self.root.update()
        self.confirm.assert_called_once()
        self.assertFalse(window.winfo_exists())
        self.assertIsNone(self.root.grab_current())
        self.assertEqual(self.app.dialogs, [])
        self.assertEqual(self.app.dialog_forms, {})
        self.assertEqual(self.app.current, "Setup")
        self.assertEqual(self.app.filters["MinimumWidth"], "")
        self.assertEqual(self.db.get_piece(piece_id)["Notes"], "")
        self.assertFalse(self.db.connection.in_transaction)
        self.app.show_screen("Fabric")
        self.assertFalse(self.app.dirty())
        self.assertEqual(self.app.piece_id, None)
        self.errors.assert_not_called()

    def test_navigation_closes_all_workflow_dialogs_including_nested_help(self):
        piece_id = self.add_piece()
        for open_dialog, target in (
                (self.app.open_filter, "DropDown"), (self.app.open_sort, "HelpText"),
                (self.app.open_sets, "Setup"),
                (lambda: self.app.open_add_item(self.app.form, "Color"), "DropDown"),
                (lambda: (self.app.load_piece(piece_id), self.app.open_history()), "Fabric")):
            self.app.show_screen("Fabric")
            open_dialog()
            operation = self.app.dialogs[-1]
            operation.nav.buttons["Screen Help"].invoke()
            help_window = self.app.dialogs[-1]
            help_window.nav.buttons[target].invoke()
            self.root.update()
            self.assertFalse(operation.winfo_exists())
            self.assertFalse(help_window.winfo_exists())
            self.assertIsNone(self.root.grab_current())
            self.assertEqual(self.app.current, target)
            self.assertFalse(self.db.connection.in_transaction)
        self.errors.assert_not_called()

    def test_help_editor_saves_multiline_text_updates_live_help_and_sorts(self):
        self.root.deiconify()
        self.app.show_screen("HelpText")
        row = next(row for row in self.app.help_rows
                   if (row["TableName"], row["FieldName"]) == ("Fabric", "Notes"))
        self.app.help_list.tree.selection_set(str(row["ID"]))
        self.root.update()
        full = self.app.help_form.widgets["FullText"]
        full.delete("1.0", "end")
        full.insert("1.0", "Custom fabric notes help.\nA second line.")
        self.app.help_form.variables["HoverText"].set("Custom tooltip")
        self.click(self.app.help_page, "Update")
        self.app.show_screen("Fabric")
        notes = self.app.form.widgets["Notes"]
        notes.tooltip.show()
        tip = notes.tooltip.window
        self.assertEqual(tip.winfo_children()[0].cget("text"), "Custom tooltip")
        self.assertIsNone(self.root.grab_current())
        notes.tooltip.hide()
        notes.focus_force()
        self.root.update()
        notes.event_generate("<F1>")
        self.root.update()
        help_window = self.app.dialogs[-1]
        help_text = next(child for child in help_window.winfo_children() if isinstance(child, tk.Text))
        self.assertEqual(help_text.get("1.0", "end-1c"), "Custom fabric notes help.\nA second line.")
        help_window.destroy()
        self.app.show_screen("HelpText")
        for _ in range(2):
            self.root.tk.call(self.app.help_list.tree.heading("TableName", "command"))
        self.assertEqual(self.db.load_sort("HelpTextSort"), (("TableName", "asc"), ("ID", "asc")))
        self.assertEqual(self.db.load_sort(), self.app.sort)
        self.errors.assert_not_called()

    def test_help_and_dropdown_drafts_cannot_survive_a_confirmed_screen_switch(self):
        self.app.show_screen("HelpText")
        first, second = self.app.help_list.tree.get_children()[:2]
        self.app.help_list.tree.selection_set(first)
        self.root.update()
        self.app.help_form.variables["FullText"].set("Uncommitted help")
        self.confirm.return_value = False
        self.app.help_list.tree.selection_set(second)
        self.root.update()
        self.assertEqual(self.app.help_list.tree.selection(), (first,))
        self.app.nav.buttons["DropDown"].invoke()
        self.assertEqual(self.app.current, "HelpText")
        self.confirm.return_value = True
        self.app.nav.buttons["DropDown"].invoke()
        self.assertEqual(self.app.help_form.values()["FullText"], "")
        self.app.dropdown_form.variables["ListItem"].set("Uncommitted choice")
        self.confirm.return_value = False
        self.app.nav.buttons["Fabric"].invoke()
        self.assertEqual(self.app.current, "DropDown")
        self.confirm.return_value = True
        self.app.nav.buttons["Fabric"].invoke()
        self.app.nav.buttons["DropDown"].invoke()
        self.assertEqual(self.app.dropdown_form.values()["ListItem"], "")
        self.assertNotIn("Uncommitted choice", self.db.dropdown_choices("FabricName"))
        self.errors.assert_not_called()

    def test_error_entry_add_update_delete_and_unsaved_navigation(self):
        self.app.show_screen("ErrorMessage")
        self.app.error_form.assign(error_values())
        self.click(self.app.error_page, "Add")
        message_id = self.app.error_id
        self.assertIsNotNone(message_id)
        self.app.error_form.variables["Description"].set("1. New fix\nSecond line.")
        self.click(self.app.error_page, "Update")
        self.assertEqual(self.db.get_error(message_id)["Description"], "1. New fix\nSecond line.")
        self.app.error_form.variables["LikelyCause"].set("Draft cause")
        self.confirm.return_value = False
        self.app.nav.buttons["Fabric"].invoke()
        self.assertEqual(self.app.current, "ErrorMessage")
        self.assertEqual(self.app.error_form.values()["LikelyCause"], "Draft cause")
        self.click(self.app.error_page, "Clear")
        self.assertEqual(self.app.error_id, message_id)
        self.confirm.return_value = True
        self.app.nav.buttons["Fabric"].invoke()
        self.assertEqual(self.app.error_form.values()["LikelyCause"], "")
        self.app.nav.buttons["ErrorMessage"].invoke()
        self.app.error_list.tree.selection_set(str(message_id))
        self.root.update()
        self.confirm.return_value = False
        self.click(self.app.error_page, "Delete")
        self.assertEqual(self.db.get_error(message_id)["ID"], message_id)
        self.confirm.return_value = True
        self.click(self.app.error_page, "Delete")
        with self.assertRaises(FieldError):
            self.db.get_error(message_id)
        self.assertIn("Error ID:", self.db.error_message(FieldError("Required", "ErrorText")))
        self.errors.assert_not_called()

    def test_error_filters_highlights_sets_sort_and_help_are_independent(self):
        first = self.db.save_error(error_values(ErrorText="100% cotton", Description="A"))
        second = self.db.save_error(error_values(ErrorText="100% cotton", Description="Z"))
        self.app.show_screen("ErrorMessage")
        buttons = [widget.cget("text") for widget in descendants(self.app.error_page)
                   if isinstance(widget, ttk.Button)]
        start = buttons.index("Select Highlighted")
        self.assertEqual(buttons[start:start + 5], [
            "Select Highlighted", "Filter", "Set Selection", "Reset Selection", "Sort"])
        self.click(self.app.error_page, "Filter")
        window = self.app.dialogs[-1]
        self.assertTrue(all(self.db.help_pair("Error Filter", "ScreenHelp")))
        self.app.dialog_forms[window][0].variables["ErrorText"].set("100% COTTON")
        self.click(window, "Apply")
        self.assertEqual(self.app.error_list.tree.get_children(), (str(first), str(second)))
        self.click(self.app.error_page, "Sort")
        window = self.app.dialogs[-1]
        self.assertTrue(all(self.db.help_pair("Error Sort", "ScreenHelp")))
        form = self.app.dialog_forms[window][0]
        form.defaults()
        form.variables["SortField1"].set("Description")
        form.variables["Direction1"].set("desc")
        self.click(window, "Apply")
        self.assertEqual(self.app.error_list.tree.get_children(), (str(second), str(first)))
        self.assertEqual(self.db.load_sort("ErrorMessageSort"), (("Description", "desc"), ("ID", "asc")))
        self.assertEqual(self.db.load_sort(), self.app.sort)
        self.click(self.app.error_page, "Set Selection")
        window = self.app.dialogs[-1]
        self.assertTrue(all(self.db.help_pair("Error Set", "ScreenHelp")))
        form = self.app.dialog_forms[window][0]
        form.variables["SetName"].set("Cotton errors")
        self.click(window, "Save Current")
        self.app.error_list.tree.selection_set(str(second))
        self.root.update()
        self.click(self.app.error_page, "Select Highlighted")
        self.assertEqual(self.app.error_list.tree.get_children(), (str(second),))
        self.click(self.app.error_page, "Reset Selection")
        self.click(self.app.error_page, "Set Selection")
        window = self.app.dialogs[-1]
        form = self.app.dialog_forms[window][0]
        form.variables["SavedSet"].set(form.widgets["SavedSet"].cget("values")[1])
        self.click(window, "Apply Saved")
        self.assertEqual(self.app.error_list.tree.get_children(), (str(second), str(first)))
        self.assertEqual(self.db.sets(), [])
        self.assertTrue(all(not value for value in self.app.error_filters.values()))
        self.errors.assert_not_called()

    def test_error_validation_and_canceled_highlight_preserve_form_and_list(self):
        self.app.show_screen("ErrorMessage")
        self.app.error_form.assign(error_values(Description=" "))
        self.click(self.app.error_page, "Add")
        self.errors.assert_called_once()
        self.errors.reset_mock()
        self.app.clear_error()
        first, second = self.app.error_list.tree.get_children()[:2]
        self.app.error_list.tree.selection_set(first)
        self.root.update()
        self.app.error_form.variables["Description"].set("Draft fix")
        self.confirm.return_value = False
        self.app.error_list.tree.selection_set(second)
        self.root.update()
        self.assertEqual(self.app.error_list.tree.selection(), (first,))
        self.assertEqual(self.app.error_form.values()["Description"], "Draft fix")
        self.app.open_filter()
        window = self.app.dialogs[-1]
        window.nav.buttons["Screen Help"].invoke()
        help_window = self.app.dialogs[-1]
        help_window.destroy()
        self.assertEqual(self.root.grab_current(), window)
        self.confirm.return_value = True
        window.nav.buttons["Setup"].invoke()
        self.root.update()
        self.assertFalse(window.winfo_exists())
        self.assertEqual(self.app.error_form.values()["Description"], "")
        self.assertIsNone(self.root.grab_current())
        self.errors.assert_not_called()

    def test_print_snapshots_all_displayed_rows_in_current_order_and_escapes_text(self):
        first = self.db.save_error(error_values(ErrorText="<script>bad()</script> & \"quote\"",
                                                Description="1. Example fix\nMore details"))
        second = self.db.save_error(error_values(ErrorText="Second", Description="Saved fix"))
        self.db.save_error(error_values(ErrorText="Not listed"))
        self.app.show_screen("ErrorMessage")
        self.app.error_selected_ids = [first, second]
        self.app.error_sort = (("ID", "desc"),)
        self.app.refresh_errors()
        self.app.error_list.tree.selection_set(str(first))
        self.root.update()
        self.app.error_form.variables["Description"].set("Uncommitted fix")
        self.db.save_error(error_values(ErrorText="Second", Description="Changed in database"),
                           second, error_values(ErrorText="Second", Description="Saved fix"))
        path = Path(self.temp.name) / "report.html"
        with patch("quilting.ui.filedialog.asksaveasfilename", return_value=str(path)), \
                patch("quilting.ui.webbrowser.open", return_value=True) as browser:
            self.app.print_errors()
        browser.assert_called_once_with(path.as_uri())
        report = path.read_text()
        parsed = ReportCells()
        parsed.feed(report)
        self.assertEqual(parsed.cells, [
            str(second), "Second", "1. Example cause", "Saved fix",
            str(first), '<script>bad()</script> & "quote"', "1. Example cause", "1. Example fix\nMore details",
        ])
        self.assertNotIn("<script>bad()", report)
        self.assertNotIn("Uncommitted fix", report)
        self.assertNotIn("Not listed", report)
        self.assertIn('window.print()', report)
        self.errors.assert_not_called()

    def test_print_empty_cancel_existing_file_and_browser_failure(self):
        self.app.show_screen("ErrorMessage")
        self.app.error_selected_ids = []
        self.app.refresh_errors()
        path = Path(self.temp.name) / "empty.html"
        with patch("quilting.ui.filedialog.asksaveasfilename", return_value=""), \
                patch("quilting.ui.webbrowser.open") as browser:
            self.app.print_errors()
            browser.assert_not_called()
        with patch("quilting.ui.filedialog.asksaveasfilename", return_value=str(path)), \
                patch("quilting.ui.webbrowser.open", return_value=False):
            self.click(self.app.error_page, "Print")
        self.errors.assert_called_once()
        self.assertIn("Open", self.errors.call_args.args[1])
        report = path.read_text()
        parsed = ReportCells()
        parsed.feed(report)
        self.assertEqual(parsed.cells, [])
        self.assertIn("<th>Error Text</th>", report)
        with patch("quilting.ui.filedialog.asksaveasfilename", return_value=str(path)), \
                patch("quilting.ui.webbrowser.open") as browser:
            with self.assertRaises(FileExistsError):
                self.app.print_errors()
            browser.assert_not_called()
        self.assertEqual(path.read_text(), report)


    def test_dropdown_list_controls_filter_sort_and_scope_saved_sets(self):
        self.app.show_screen("DropDown")
        labels = [widget.cget("text") for widget in descendants(self.app.dropdown_page)
                  if isinstance(widget, ttk.Button)]
        start = labels.index("Select Highlighted")
        self.assertEqual(labels[start:start + 5], [
            "Select Highlighted", "Filter", "Set Selection", "Reset Selection", "Sort",
        ])
        self.app.dropdown_form.variables["FieldName"].set("Color")
        self.db.add_dropdown_item("Color", "Blue")
        self.db.add_dropdown_item("Color", "Sage")
        sage = next(row["ID"] for row in self.db.dropdown_rows("Color") if row["ListItem"] == "Sage")
        self.app.refresh_dropdowns()
        self.click(self.app.dropdown_page, "Filter")
        form = self.app.dialog_forms[self.app.dialogs[-1]][0]
        form.variables["ListItem"].set("sa")
        self.click(self.app.dialogs[-1], "Apply")
        self.assertEqual(self.app.dropdown_list.tree.get_children(), (str(sage),))
        self.click(self.app.dropdown_page, "Set Selection")
        form = self.app.dialog_forms[self.app.dialogs[-1]][0]
        form.variables["SetName"].set("Sage choices")
        self.click(self.app.dialogs[-1], "Save Current")
        self.click(self.app.dropdown_page, "Reset Selection")
        self.app.dropdown_list.tree.selection_set(str(sage))
        self.click(self.app.dropdown_page, "Select Highlighted")
        self.assertEqual(self.app.dropdown_list.tree.get_children(), (str(sage),))
        self.click(self.app.dropdown_page, "Reset Selection")
        self.click(self.app.dropdown_page, "Sort")
        form = self.app.dialog_forms[self.app.dialogs[-1]][0]
        form.defaults()
        form.variables["SortField1"].set("List Item")
        form.variables["Direction1"].set("desc")
        self.click(self.app.dialogs[-1], "Apply")
        names = [self.app.dropdown_list.tree.item(item, "values")[3]
                 for item in self.app.dropdown_list.tree.get_children()]
        self.assertEqual(names, sorted(names, reverse=True))
        self.click(self.app.dropdown_page, "Set Selection")
        form = self.app.dialog_forms[self.app.dialogs[-1]][0]
        form.variables["SavedSet"].set(form.widgets["SavedSet"].cget("values")[1])
        self.click(self.app.dialogs[-1], "Apply Saved")
        self.assertEqual(self.app.dropdown_list.tree.get_children(), (str(sage),))
        self.assertEqual(self.db.sets("DropDown", "PatternName"), [])
        self.errors.assert_not_called()

    def test_quilt_back_plan_preview_cut_confirmation_and_inventory_adjustment(self):
        source_ids = [
            self.db.save_piece(fabric(
                FabricName=f"Red backing {index}", Color="Red", UsableWidth="42",
                UsableLength="60", GrainDirection="Along Width",
            ))
            for index in range(2)
        ]
        self.app.show_screen("Quilt Backs")
        self.app.back_form.assign({
            "BackName": "Guest back",
            "QuiltWidth": "50",
            "QuiltLength": "50",
            "Margin": "0",
            "SideMargin": "0",
            "SeamAllowance": "1",
        })
        self.app.back_stock.tree.selection_set(tuple(map(str, source_ids)))
        self.app.back_palette[source_ids[0]] = "Teal"
        self.app.generate_back_plans()
        self.assertTrue(self.app.back_layouts)
        self.assertEqual(self.app.back_selected_layout.panels[0].palette_color, "Teal")
        self.app.preview_back()
        preview = self.dialog()
        self.assertTrue(any(isinstance(widget, tk.Canvas) for widget in descendants(preview)))
        back_id = self.app.save_back_draft()
        back_id = int(back_id) if back_id else int(self.app.back_selected_id)
        self.assertEqual(self.db.get_quilt_back(back_id)["Status"], "Draft")
        self.assertTrue(all(self.db.get_piece(piece_id)["Status"] == "Available"
                            for piece_id in source_ids))
        report_path = Path(self.temp.name) / "back.html"
        with patch("quilting.ui.filedialog.asksaveasfilename", return_value=str(report_path)), \
                patch("quilting.ui.webbrowser.open", return_value=True):
            self.app.print_back_plan()
        report = report_path.read_text(encoding="utf-8")
        self.assertIn("<svg", report)
        self.assertIn("Inventory fabric", report)
        self.assertIn("Teal", report)
        self.app.open_back_cut()
        dialog_window = next(iter(self.app.dialog_forms))
        form = self.app.dialog_forms[dialog_window][0]
        first_source, second_source = source_ids
        form.variables[f"RemainingWidth{first_source}"].set("5")
        form.variables[f"RemainingLength{first_source}"].set("10")
        self.app.commit_back_cut(
            dialog_window, form, {source_id: {} for source_id in source_ids},
        )
        self.assertEqual(self.db.get_quilt_back(back_id)["Status"], "Cut")
        self.assertTrue(all(self.db.get_piece(piece_id)["Status"] == "Retired"
                            for piece_id in source_ids))
        self.app.mark_back_assembled()
        self.assertEqual(self.db.get_quilt_back(back_id)["Status"], "Assembled")
        self.errors.assert_not_called()

    def test_helptext_list_controls_filter_sort_and_named_selection(self):
        self.app.show_screen("HelpText")
        labels = [widget.cget("text") for widget in descendants(self.app.help_page)
                  if isinstance(widget, ttk.Button)]
        start = labels.index("Select Highlighted")
        self.assertEqual(labels[start:start + 5], [
            "Select Highlighted", "Filter", "Set Selection", "Reset Selection", "Sort",
        ])
        self.click(self.app.help_page, "Filter")
        form = self.app.dialog_forms[self.app.dialogs[-1]][0]
        form.variables["TableName"].set("History")
        self.click(self.app.dialogs[-1], "Apply")
        self.assertTrue(self.app.help_rows)
        self.assertTrue(all("history" in row["TableName"].lower() for row in self.app.help_rows))
        first = self.app.help_rows[0]["ID"]
        self.click(self.app.help_page, "Set Selection")
        form = self.app.dialog_forms[self.app.dialogs[-1]][0]
        form.variables["SetName"].set("History help")
        self.click(self.app.dialogs[-1], "Save Current")
        self.click(self.app.help_page, "Reset Selection")
        self.app.help_list.tree.selection_set(str(first))
        self.click(self.app.help_page, "Select Highlighted")
        self.assertEqual(self.app.help_list.tree.get_children(), (str(first),))
        self.click(self.app.help_page, "Reset Selection")
        self.click(self.app.help_page, "Sort")
        form = self.app.dialog_forms[self.app.dialogs[-1]][0]
        form.variables["SortField1"].set("Table Name")
        form.variables["Direction1"].set("desc")
        self.click(self.app.dialogs[-1], "Apply")
        tables = [row["TableName"] for row in self.app.help_rows]
        self.assertEqual(tables, sorted(tables, key=str.casefold, reverse=True))
        self.errors.assert_not_called()

    def test_history_list_controls_are_scoped_to_the_current_piece(self):
        piece_id = self.add_piece()
        self.app.form.variables["Notes"].set("updated history value")
        self.app.update()
        self.app.open_history()
        window = self.app.dialogs[-1]
        listing = next(child for child in window.winfo_children() if isinstance(child, RecordList))
        labels = [widget.cget("text") for widget in descendants(window)
                  if isinstance(widget, ttk.Button)]
        start = labels.index("Select Highlighted")
        self.assertEqual(labels[start:start + 5], [
            "Select Highlighted", "Filter", "Set Selection", "Reset Selection", "Sort",
        ])
        self.click(window, "Filter")
        form = self.app.dialog_forms[self.app.dialogs[-1]][0]
        form.variables["Action"].set("Updated")
        self.click(self.app.dialogs[-1], "Apply")
        self.assertEqual(len(listing.tree.get_children()), 1)
        updated_id = listing.tree.get_children()[0]
        self.click(window, "Set Selection")
        form = self.app.dialog_forms[self.app.dialogs[-1]][0]
        form.variables["SetName"].set("Updated only")
        self.click(self.app.dialogs[-1], "Save Current")
        self.click(window, "Reset Selection")
        self.assertEqual(len(listing.tree.get_children()), 2)
        listing.tree.selection_set(updated_id)
        self.click(window, "Select Highlighted")
        self.assertEqual(listing.tree.get_children(), (updated_id,))
        self.click(window, "Reset Selection")
        self.click(window, "Set Selection")
        form = self.app.dialog_forms[self.app.dialogs[-1]][0]
        form.variables["SavedSet"].set(form.widgets["SavedSet"].cget("values")[1])
        self.click(self.app.dialogs[-1], "Apply Saved")
        self.assertEqual(listing.tree.get_children(), (updated_id,))
        self.assertEqual(self.db.sets("History", piece_id)[0]["SetName"], "Updated only")
        other_piece = self.db.save_piece(fabric(FabricName="Other piece"))
        self.assertEqual(self.db.sets("History", other_piece), [])
        self.errors.assert_not_called()

    def test_dropdown_screen_shows_protection_and_limits_supported_keys(self):
        self.app.show_screen("DropDown")
        self.assertEqual(tuple(field.name for field in self.app.dropdown_form.fields),
                         ("TableName", "FieldName", "ListItem", "Def", "Use"))
        self.app.dropdown_form.variables["FieldName"].set("Color")
        self.app.dropdown_form.widgets["FieldName"].event_generate("<<ComboboxSelected>>")
        self.root.update()
        self.app.dropdown_form.variables["ListItem"].set("Blue")
        self.app.dropdown_form.variables["Def"].set("Clear Default")
        self.app.dropdown_form.variables["Use"].set("Set Use")
        self.click(self.app.dropdown_page, "Add")
        row = next(row for row in self.db.dropdown_rows("Color") if row["ListItem"] == "Blue")
        self.assertEqual((row["TableName"], row["FieldName"], row["ListItem"]),
                         ("FabricPiece", "Color", "Blue"))
        self.assertEqual(row["UserModified"], 1)
        self.assertEqual(self.app.dropdown_list.tree.item(str(row["ID"]), "values")[1:4],
                         ("FabricPiece", "Color", "Blue"))
        protected = next(row for row in self.db.dropdown_rows("Status", table_name="FabricPiece")
                         if row["ListItem"] == "Available")
        self.assertEqual(protected["UserModified"], 0)
        with self.assertRaises(FieldError):
            self.db.add_dropdown_choice("HelpText", "Update", "Apply help changes")
        expected_width = tkfont.nametofont("TkDefaultFont").measure("0" * 5) + 10
        for name in ("Def", "Use"):
            self.assertEqual(self.app.dropdown_list.tree.column(name, "width"), expected_width)
        for name in DROPDOWN_COLUMNS:
            self.assertFalse(self.app.dropdown_list.tree.column(name, "stretch"))
        self.click(self.app.dropdown_page, "Set Selection")
        form = self.app.dialog_forms[self.app.dialogs[-1]][0]
        form.variables["SetName"].set("Blue colors")
        self.click(self.app.dialogs[-1], "Save Current")
        selection = self.db.sets("DropDown", ("FabricPiece", "Color"))
        self.assertEqual(len(selection), 1)
        self.assertEqual(self.db.set_members(
            selection[0]["ID"], "DropDown", ("FabricPiece", "Color")), [row["ID"]])

    def test_protected_default_change_requires_warning_confirmation(self):
        warning = patch("quilting.ui.messagebox.showwarning").start()
        self.app.open_dropdowns()
        form = self.app.dropdown_form
        form.variables["FieldName"].set("Status")
        form.widgets["FieldName"].event_generate("<<ComboboxSelected>>")
        self.root.update()
        retired = next(row for row in self.db.dropdown_rows(
            "Status", table_name="FabricPiece") if row["ListItem"] == "Retired")
        self.app.dropdown_list.tree.selection_set(str(retired["ID"]))
        self.root.update()
        form.variables["Def"].set("Set Default")
        self.click(self.app.dropdown_page, "Update")
        self.confirm.assert_called()
        self.assertEqual(self.db.get_dropdown(retired["ID"])["Def"], 1)
        warning.assert_called_once()
        self.errors.assert_not_called()

    def test_error_message_entry_has_scrollable_fields_and_readonly_id(self):
        self.app.show_screen("ErrorMessage")
        page = self.app.error_page
        self.assertTrue(any(isinstance(w, ttk.Label) and w.cget("text") == "Error Message"
                            for w in page.winfo_children()))
        form = self.app.error_form
        self.assertEqual(form.labels["ErrorText"].grid_info()["row"], form.labels["LikelyCause"].grid_info()["row"])
        self.assertGreater(form.labels["Description"].grid_info()["row"], form.labels["LikelyCause"].grid_info()["row"])
        id_field = next(w for w in descendants(page)
                        if isinstance(w, ttk.Entry) and str(w.cget("textvariable")) == str(self.app.error_id_value))
        self.assertEqual(str(id_field.cget("state")), "readonly")
        self.assertEqual(id_field.master.master, form.master)
        self.assertLess(list(form.master.pack_slaves()).index(id_field.master),
                        list(form.master.pack_slaves()).index(form))
        self.assertEqual(self.app.error_id_value.get(), "")
        self.root.deiconify()
        self.root.update()
        for name, widget in form.widgets.items():
            self.assertEqual(widget.cget("height"), 3)
            scroll = next(w for w in widget.master.winfo_children() if isinstance(w, ttk.Scrollbar))
            value = "\n".join(f"{name} line {i}" for i in range(12))
            form.variables[name].set(value)
            self.root.update()
            scroll.tk.call(scroll.cget("command"), "moveto", 1.0)
            self.root.update()
            self.assertGreater(widget.yview()[0], 0)
            self.assertEqual(scroll.get(), widget.yview())
            self.assertEqual(form.values()[name], value)
        form.widgets["Description"].insert("end", "\nEdited")
        self.assertTrue(form.values()["Description"].endswith("\nEdited"))
        self.click(page, "Clear")
        message_id = self.app.error_list.tree.get_children()[0]
        self.app.error_list.tree.selection_set(message_id)
        self.root.update()
        self.assertEqual(self.app.error_id_value.get(), message_id)
        self.click(page, "Clear")
        self.assertEqual(self.app.error_id_value.get(), "")
        self.errors.assert_not_called()

if __name__ == "__main__":
    unittest.main()
