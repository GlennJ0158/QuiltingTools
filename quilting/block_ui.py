"""Quilt block list, part maintenance and placement editor."""

import tkinter as tk
import webbrowser
from decimal import Decimal
from html import escape
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

from .blocks import (
    BLOCK_COLUMNS, BLOCK_FIELDS, BLOCK_FILTER_FIELDS, PART_FIELDS, cutting_shape, placed_shape, validate_layout,
)
from .block_templates import BLOCK_TEMPLATES
from .model import Field, FieldError, UNITS_PER_INCH, caption, display_measurement, normalize_sort, validate_fields


def draw_block_sketch(canvas, block, parts, placements):
    scale = float(Decimal(block["Scale"]) / 100)
    width = block["FinishedWidth"] / UNITS_PER_INCH * scale
    length = block["FinishedLength"] / UNITS_PER_INCH * scale
    canvas.delete("all")
    factor = min((max(canvas.winfo_width(), 100) - 30) / width,
                 (max(canvas.winfo_height(), 100) - 30) / length)
    canvas.create_rectangle(15, 15, 15 + width * factor, 15 + length * factor, outline="black")
    for placement in placements:
        part = parts[placement["BlockPartID"]]
        geom = placed_shape(part, placement, scale)
        points = [coord for x, y in geom.exterior.coords for coord in (15 + x * factor, 15 + y * factor)]
        canvas.create_polygon(*points, fill=part["PartColor"].lower(), outline="black")
        center = geom.representative_point()
        canvas.create_text(15 + center.x * factor, 15 + center.y * factor,
                           text=f"{part['ID']}/{placement['Instance']}")


class BlockScreenMixin:
    def build_blocks(self):
        from .ui import Form, RecordList

        self.block_state = self.new_list_state(self.db.load_sort("QuiltBlockSort"), BLOCK_FILTER_FIELDS)
        self.block_id = self.block_revision = None
        self.block_selection = ()
        ttk.Label(self.block_page, text="Quilt Blocks", font=("TkDefaultFont", 14, "bold")).pack(anchor="w")
        entry = ttk.Frame(self.block_page, style="Entry.TFrame")
        entry.pack(fill="x")
        self.block_form = Form(
            entry, BLOCK_FIELDS, columns=3, style="Entry.TFrame",
            database=self.db, dropdown_scope="QuiltBlock",
        )
        self.block_form.pack(fill="x")
        actions = ttk.Frame(entry, padding=4, style="Entry.TFrame")
        actions.pack(fill="x")
        for label, action in (("Add", self.add_block), ("Update", self.update_block),
                              ("Create from Template", self.create_block_template),
                              ("Delete", self.delete_block), ("Clear", self.clear_block_entry),
                              ("New Version", self.copy_block), ("Parts", self.open_parts),
                              ("Sketch", self.open_block_sketch), ("Approve", self.approve_block)):
            self.button(actions, label, action)
        tools = ttk.Frame(entry, padding=4, style="Entry.TFrame")
        tools.pack(fill="x")
        for label, action in (("Select Highlighted", self.block_highlight), ("Filter", self.block_filter),
                              ("Set Selection", self.block_sets), ("Sort", self.block_sort),
                              ("Reset Selection", self.block_reset), ("Refresh", self.refresh_blocks_safe)):
            self.button(tools, label, action)
        self.block_list = RecordList(self.block_page, BLOCK_COLUMNS, name_limit="BlockName")
        font = tkfont.nametofont("TkHeadingFont")
        for name in ("FinishedWidth", "FinishedLength", "Scale", "Status", "Revision"):
            width = font.measure(caption(name) + "00") + 12
            self.block_list.tree.column(name, width=width, minwidth=width, stretch=False)
        self.block_list.compact_columns("BlockName")
        self.block_list.pack(fill="both", expand=True)
        self.block_list.tree.bind("<<TreeviewSelect>>", self.command(self.select_block))
        self.block_initial = self.block_form.values()
        self.refresh_blocks()

    def allow_block_discard(self):
        return self.block_form.values() == self.block_initial or messagebox.askyesno(
            "Unsaved Changes", "Discard unsaved block details?", parent=self.root.grab_current() or self.root)

    def clear_block(self):
        self.block_id = self.block_revision = None
        self.block_selection = ()
        self.block_form.defaults()
        self.block_initial = self.block_form.values()
        self.block_list.tree.selection_remove(self.block_list.tree.selection())

    def clear_block_entry(self):
        if self.allow_block_discard():
            self.clear_block()

    def refresh_blocks_safe(self):
        if self.allow_block_discard():
            self.refresh_blocks()

    def refresh_blocks(self, prefer=None):
        state = self.block_state
        rows = self.db.blocks(state["filters"], state["selected_ids"], state["sort"])
        self.clear_block()
        self.block_list.fill(rows, "blocks", state["sort"], self.list_context(state))
        if prefer is not None and self.block_list.tree.exists(str(prefer)):
            self.block_list.tree.selection_set(str(prefer))
            self.select_block()

    def select_block(self):
        selected = self.block_list.tree.selection()
        if selected == self.block_selection:
            return
        if not self.allow_block_discard():
            self.block_list.tree.selection_set(self.block_selection)
            return
        if len(selected) != 1:
            self.clear_block()
            self.block_list.tree.selection_set(selected)
            self.block_selection = selected
            return
        row = self.db.get_block(int(selected[0]))
        values = {field.name: row[field.name] for field in BLOCK_FIELDS}
        for name in ("FinishedWidth", "FinishedLength", "SeamAllowance"):
            values[name] = display_measurement(values[name]) if values[name] else "0"
        self.block_form.assign(values)
        self.block_initial = self.block_form.values()
        self.block_id, self.block_revision = row["ID"], row["Revision"]
        self.block_selection = selected

    def require_block(self):
        if self.block_id is None or self.block_list.tree.selection() != (str(self.block_id),):
            raise FieldError("OneRecord", "QuiltBlock")
        return self.block_id

    def add_block(self):
        self.refresh_blocks(self.db.add_block(self.block_form.values()))

    def create_block_template(self):
        if self.block_id is not None and not self.allow_block_discard():
            return
        window = self.dialog("Create Block from Template", "QuiltBlock")
        content = ttk.Frame(window, padding=8)
        content.pack(fill="both", expand=True)
        ttk.Label(
            content, text="Set finished width and length on the Quilt Block form before creating a template."
        ).pack(anchor="w", pady=(0, 8))
        selected = tk.StringVar(value=next(iter(BLOCK_TEMPLATES)))
        chooser = ttk.Combobox(
            content, textvariable=selected, values=tuple(BLOCK_TEMPLATES), state="readonly",
        )
        chooser.pack(fill="x")
        self.attach_help(chooser, "TemplateName")
        description = ttk.Label(content, text=BLOCK_TEMPLATES[selected.get()], wraplength=480)
        description.pack(anchor="w", pady=8)
        chooser.bind("<<ComboboxSelected>>", lambda _: description.configure(
            text=BLOCK_TEMPLATES[selected.get()]))

        def create():
            block_id = self.db.create_block_template(selected.get(), self.block_form.values())
            window.destroy()
            self.refresh_blocks(block_id)

        controls = ttk.Frame(content)
        controls.pack(fill="x", pady=(4, 0))
        self.button(controls, "Create", create)
        self.button(controls, "Cancel", window.destroy)

    def update_block(self):
        block_id = self.require_block()
        self.db.update_block(block_id, self.block_revision, self.block_form.values())
        self.refresh_blocks(block_id)

    def delete_block(self):
        block_id = self.require_block()
        if self.allow_block_discard() and messagebox.askyesno(
                "Delete Block", "Delete this draft and all its parts?", parent=self.root):
            self.db.delete_block(block_id, self.block_revision)
            self.refresh_blocks()

    def copy_block(self):
        block_id = self.require_block()
        if self.allow_block_discard():
            self.refresh_blocks(self.db.copy_block(block_id))

    def block_highlight(self):
        ids = [int(item) for item in self.block_list.tree.selection()]
        if not ids:
            raise FieldError("NoHighlight", "QuiltBlock")
        if self.allow_block_discard():
            self.block_state["selected_ids"] = ids
            self.block_state["selection_description"] = "Highlighted-record restriction"
            self.refresh_blocks()

    def block_reset(self):
        if self.allow_block_discard():
            self.block_state["filters"] = {field.name: "" for field in BLOCK_FILTER_FIELDS}
            self.block_state["selected_ids"] = None
            self.block_state["selection_description"] = ""
            self.refresh_blocks()

    def block_filter(self):
        from .ui import Form
        window = self.dialog("Filter Quilt Blocks", "QuiltBlock Filter")
        form = Form(window, BLOCK_FILTER_FIELDS, columns=1, database=self.db,
                    dropdown_scope="QuiltBlock Filter")
        form.pack(fill="x")
        form.assign(self.block_state["filters"])
        self.watch_dialog(window, form)
        actions = ttk.Frame(window, padding=8)
        actions.pack(fill="x")

        def apply():
            clean = validate_fields(BLOCK_FILTER_FIELDS, form.values())
            if self.allow_block_discard():
                self.block_state["filters"] = clean
                window.destroy()
                self.refresh_blocks()
        self.button(actions, "Apply", apply)
        self.button(actions, "Clear Fields", form.defaults)
        self.button(actions, "Cancel", window.destroy)

    def block_sort(self):
        from .ui import Form
        window = self.dialog("Sort Quilt Blocks", "QuiltBlock Sort")
        fields = tuple(field for index in range(1, len(BLOCK_COLUMNS) + 1) for field in (
            Field(f"SortField{index}", "choice", choices=("", *map(caption, BLOCK_COLUMNS))),
            Field(f"Direction{index}", "choice", choices=("asc", "desc"), default="asc")))
        form = Form(window, fields)
        form.pack(fill="x")
        lookup = {caption(name): name for name in BLOCK_COLUMNS}
        for index, (name, direction) in enumerate(self.block_state["sort"], 1):
            form.variables[f"SortField{index}"].set(caption(name))
            form.variables[f"Direction{index}"].set(direction)
        self.watch_dialog(window, form)
        actions = ttk.Frame(window, padding=8)
        actions.pack(fill="x")

        def apply():
            values = validate_fields(fields, form.values())
            order = normalize_sort([(lookup[values[f"SortField{i}"]], values[f"Direction{i}"])
                                    for i in range(1, len(BLOCK_COLUMNS) + 1)
                                    if values[f"SortField{i}"]], BLOCK_COLUMNS)
            if self.allow_block_discard():
                self.db.save_sort(order, "QuiltBlockSort")
                self.block_state["sort"] = order
                window.destroy()
                self.refresh_blocks()
        self.button(actions, "Apply", apply)
        self.button(actions, "Clear Fields", form.defaults)
        self.button(actions, "Cancel", window.destroy)

    def block_sets(self):
        from .ui import Form
        window = self.dialog("Quilt Block Sets", "QuiltBlock Set")
        choices = {f"{row['SetName']} (ID {row['ID']})": row["ID"] for row in self.db.sets("QuiltBlock")}
        fields = (Field("SavedSet", "choice", choices=("", *choices)), Field("SetName"))
        form = Form(window, fields, columns=1)
        form.pack(fill="x")
        self.watch_dialog(window, form)
        actions = ttk.Frame(window, padding=8)
        actions.pack(fill="x")

        def chosen():
            value = validate_fields(fields, form.values())["SavedSet"]
            if not value:
                raise FieldError("Required", "SavedSet")
            return choices[value]

        def save():
            rows = self.db.blocks(self.block_state["filters"], self.block_state["selected_ids"],
                                  self.block_state["sort"])
            self.db.save_set(form.values()["SetName"], [row["ID"] for row in rows], "QuiltBlock")
            window.destroy()

        def apply():
            ids = self.db.set_members(chosen(), "QuiltBlock")
            if self.allow_block_discard():
                self.block_state["selected_ids"] = ids
                self.block_state["filters"] = {field.name: "" for field in BLOCK_FILTER_FIELDS}
                self.block_state["selection_description"] = "Saved selection set"
                window.destroy()
                self.refresh_blocks()

        def delete():
            set_id = chosen()
            if messagebox.askyesno("Delete Set", "Delete this set? Blocks are kept.", parent=window):
                self.db.delete_set(set_id, "QuiltBlock")
                window.destroy()
        for label, action in (("Save Current", save), ("Apply Saved", apply),
                              ("Delete Saved", delete), ("Cancel", window.destroy)):
            self.button(actions, label, action)

    def open_parts(self):
        from .ui import Form, RecordList
        block_id = self.require_block()
        if not self.allow_block_discard():
            return
        self.block_form.assign(self.block_initial)
        window = self.dialog("Block Parts", "Block Parts")
        form = Form(window, PART_FIELDS, columns=3, style="Entry.TFrame",
                    database=self.db, dropdown_scope="Block Parts")
        form.pack(fill="x")
        self.watch_dialog(window, form)
        controls = ttk.Frame(window, padding=4)
        controls.pack(fill="x")
        listing = RecordList(window, ("ID", "PartName", "Shape", "PartColor", "NumberInBlock"))
        listing.pack(fill="both", expand=True)
        previous_selection = ()

        def refresh():
            nonlocal previous_selection
            previous_selection = ()
            rows = self.db.block_parts(block_id)
            listing.fill(rows, "part definitions", (("ID", "asc"),))
            form.defaults()
            self.dialog_forms[window] = (form, form.values())
            self.block_revision = self.db.get_block(block_id)["Revision"]

        def select():
            nonlocal previous_selection
            selected = listing.tree.selection()
            if selected == previous_selection:
                return
            if len(selected) != 1:
                return
            if form.values() != self.dialog_forms[window][1] and not messagebox.askyesno(
                    "Unsaved Changes", "Discard unsaved part details?", parent=window):
                listing.tree.selection_set(previous_selection)
                return
            row = next(row for row in self.db.block_parts(block_id) if row["ID"] == int(selected[0]))
            values = {field.name: row[field.name] for field in PART_FIELDS}
            for name in ("PartWidth", "PartLength", "SideA", "SideB", "SideC", "Diameter"):
                values[name] = display_measurement(values[name]) if values[name] is not None else ""
            values["NumberInBlock"] = str(values["NumberInBlock"])
            form.assign(values)
            self.dialog_forms[window] = (form, form.values())
            previous_selection = selected

        def save(update=False):
            selected = listing.tree.selection()
            if update and len(selected) != 1:
                raise FieldError("OneRecord", "BlockPart")
            self.db.save_block_part(block_id, self.block_revision, form.values(),
                                    int(selected[0]) if update else None)
            refresh()

        def delete():
            selected = listing.tree.selection()
            if len(selected) != 1:
                raise FieldError("OneRecord", "BlockPart")
            if (form.values() != self.dialog_forms[window][1] and not messagebox.askyesno(
                    "Unsaved Changes", "Discard unsaved part details?", parent=window)):
                return
            if messagebox.askyesno("Delete Part", "Delete this part and its placements?", parent=window):
                self.db.delete_block_part(block_id, self.block_revision, int(selected[0]))
                refresh()

        def clear():
            if form.values() == self.dialog_forms[window][1] or messagebox.askyesno(
                    "Unsaved Changes", "Discard unsaved part details?", parent=window):
                refresh()

        def close():
            if form.values() == self.dialog_forms[window][1] or messagebox.askyesno(
                    "Unsaved Changes", "Discard unsaved part details?", parent=window):
                window.destroy()

        listing.tree.bind("<<TreeviewSelect>>", self.command(select))
        for label, action in (("Add", lambda: save()), ("Update", lambda: save(True)), ("Delete", delete),
                              ("Clear", clear), ("Close", close)):
            self.button(controls, label, action)
        window.protocol("WM_DELETE_WINDOW", self.command(close))
        window.bind("<Escape>", lambda _: self.command(close)())
        refresh()

    def open_block_sketch(self):
        from .ui import Form
        selected_ids = self.block_list.tree.selection()
        if len(selected_ids) > 1:
            if self.allow_block_discard():
                self.open_block_comparison([int(item) for item in selected_ids])
            return
        block_id = self.require_block()
        if not self.allow_block_discard():
            return
        self.block_form.assign(self.block_initial)
        window = self.dialog("Block Sketch", "Block Sketch")
        window.geometry("1000x700")
        block = self.db.get_block(block_id)
        scale = float(Decimal(block["Scale"]) / 100)
        width = block["FinishedWidth"] / UNITS_PER_INCH * scale
        length = block["FinishedLength"] / UNITS_PER_INCH * scale
        canvas = tk.Canvas(window, width=600, height=450, background="white")
        canvas.pack(fill="both", expand=True)
        self.attach_help(canvas, "BlockSketch")
        fields = (Field("Placement", "choice"), Field("PositionX", required=True, default="0"),
                  Field("PositionY", required=True, default="0"),
                  Field("Rotation", required=True, default="0"),
                  Field("Mirror", "choice", choices=("No", "Yes"), default="No"))
        form = Form(window, fields, columns=3, database=self.db, dropdown_scope="Block Sketch")
        form.pack(fill="x")
        self.watch_dialog(window, form)
        status = ttk.Label(window)
        status.pack(anchor="w")
        dimensions = ttk.Label(window, text="Select a placement to see cut dimensions.")
        dimensions.pack(anchor="w")
        actions = ttk.Frame(window, padding=4)
        actions.pack(fill="x")
        last_placement = ""

        def draw():
            parts = {p["ID"]: p for p in self.db.block_parts(block_id)}
            placements = self.db.block_placements(block_id)
            draw_block_sketch(canvas, block, parts, placements)
            choices = {f"{parts[p['BlockPartID']]['PartName']} / part {p['BlockPartID']} / instance {p['Instance']}":
                       p for p in placements}
            form.widgets["Placement"].configure(values=tuple(choices))
            issues = validate_layout(block, list(parts.values()), placements)
            status.configure(text="; ".join(issues) if issues else "Layout is valid.")
            return choices

        def selected():
            choices = draw()
            if form.variables["Placement"].get() not in choices:
                raise FieldError("Required", "Placement")
            return choices[form.variables["Placement"].get()]

        def load():
            nonlocal last_placement
            choice = form.variables["Placement"].get()
            if (form.values() != self.dialog_forms[window][1]
                    and choice != last_placement and last_placement
                    and not messagebox.askyesno("Unsaved Changes", "Discard unsaved placement details?",
                                               parent=window)):
                form.variables["Placement"].set(last_placement)
                return
            p = selected()
            part = next(part for part in self.db.block_parts(block_id) if part["ID"] == p["BlockPartID"])
            cut = cutting_shape(part, scale, block["SeamAllowance"])
            minx, miny, maxx, maxy = cut.bounds
            dimensions.configure(text=f"Cut outline bounding size: {maxx - minx:.6f} x "
                                 f"{maxy - miny:.6f} in (uniform seam offset)")
            for name, value in (("PositionX", display_measurement(p["X"]) if p["X"] else "0"),
                                ("PositionY", display_measurement(p["Y"]) if p["Y"] else "0"),
                                ("Rotation", str(p["Rotation"])),
                                ("Mirror", "Yes" if p["Mirrored"] else "No")):
                form.variables[name].set(value)
            self.dialog_forms[window] = (form, form.values())
            last_placement = choice

        def save():
            from .ui import nonnegative_measurement
            p = selected()
            values = form.values()
            if values["Mirror"] not in ("Yes", "No"):
                raise FieldError("Choice", "Mirror")
            try:
                rotation = int(values["Rotation"])
            except ValueError as error:
                raise FieldError("Choice", "Rotation") from error
            self.db.save_block_placement(
                block_id, self.block_revision, p["ID"],
                nonnegative_measurement(values["PositionX"], "PositionX"),
                nonnegative_measurement(values["PositionY"], "PositionY"),
                rotation, values["Mirror"] == "Yes")
            self.block_revision = self.db.get_block(block_id)["Revision"]
            self.dialog_forms[window] = (form, form.values())
            draw()

        def close():
            if form.values() == self.dialog_forms[window][1] or messagebox.askyesno(
                    "Unsaved Changes", "Discard unsaved placement details?", parent=window):
                window.destroy()

        def print_sketch():
            path = filedialog.asksaveasfilename(
                parent=window, title="Save Block Sketch (new file only)", defaultextension=".html",
                initialfile="QuiltBlock.html", filetypes=(("HTML report", "*.html"),))
            if not path:
                return
            current = self.db.get_block(block_id)
            parts = {part["ID"]: part for part in self.db.block_parts(block_id)}
            placements = self.db.block_placements(block_id)
            issues = validate_layout(current, list(parts.values()), placements)
            factor = min(700 / width, 500 / length)
            svg = []
            lines = []
            cutting_outlines = []
            for p in placements:
                part = parts[p["BlockPartID"]]
                geom = placed_shape(part, p, scale)
                points = " ".join(f"{x * factor:.4f},{y * factor:.4f}" for x, y in geom.exterior.coords)
                color = part["PartColor"].lower()
                svg.append(f'<polygon points="{points}" fill="{color}" stroke="black"/>')
                center = geom.representative_point()
                svg.append(f'<text x="{center.x * factor:.4f}" y="{center.y * factor:.4f}" '
                           f'text-anchor="middle">{part["ID"]}/{p["Instance"]}</text>')
                cut = cutting_shape(part, scale, current["SeamAllowance"])
                x1, y1, x2, y2 = cut.bounds
                offset_points = " ".join(
                    f"{(x - x1) * 120 / max(x2 - x1, y2 - y1):.4f},"
                    f"{(y - y1) * 120 / max(x2 - x1, y2 - y1):.4f}"
                    for x, y in cut.exterior.coords)
                cutting_outlines.append(
                    f'<h3>{escape(part["PartName"])} ({part["ID"]}/{p["Instance"]})</h3>'
                    f'<svg xmlns="http://www.w3.org/2000/svg" width="125" height="125">'
                    f'<polygon points="{offset_points}" fill="none" stroke="black"/></svg>')
                lines.append(f'{part["PartName"]} ({part["ID"]}/{p["Instance"]}, {part["Shape"]}, '
                             f'{part["PartColor"]}): cut outline bounding size {x2 - x1:.6f} x '
                             f'{y2 - y1:.6f} in')
            report = ('<!doctype html><html><head><meta charset="utf-8"><title>Block sketch</title>'
                      '<style>body{font-family:sans-serif}pre{white-space:pre-wrap}'
                      '@media print{button{display:none}}</style></head><body>'
                      f'<h1>{escape(current["BlockName"])}</h1>'
                      f'<p>{escape("; ".join(issues) if issues else "Layout is valid.")}</p>'
                      '<button onclick="window.print()">Print</button>'
                      f'<svg xmlns="http://www.w3.org/2000/svg" width="{width * factor}" '
                      f'height="{length * factor}">{"".join(svg)}</svg>'
                      f'<pre>{escape(chr(10).join(lines))}</pre>'
                      '<h2>Cutting outlines (not to scale)</h2>' + "".join(cutting_outlines) +
                      '<script>window.addEventListener("load",()=>window.print());</script></body></html>')
            destination = Path(path).resolve()
            with destination.open("x", encoding="utf-8") as output:
                output.write(report)
            if not webbrowser.open(destination.as_uri()):
                raise FieldError("Database", "Print", detail=f"Open {destination} manually and print.")

        form.widgets["Placement"].bind("<<ComboboxSelected>>", self.command(load))
        canvas.bind("<Configure>", lambda _: draw())
        self.button(actions, "Save Placement", save)
        self.button(actions, "Print Sketch", print_sketch)
        self.button(actions, "Close", close)
        window.protocol("WM_DELETE_WINDOW", self.command(close))
        window.bind("<Escape>", lambda _: self.command(close)())
        draw()

    def open_block_comparison(self, block_ids):
        window = self.dialog("Compare Block Sketches", "Compare Block Sketches")
        window.geometry("1000x700")
        actions = ttk.Frame(window, padding=4)
        actions.pack(side="bottom", fill="x")
        self.button(actions, "Close", window.destroy)

        container = ttk.Frame(window)
        container.pack(fill="both", expand=True)
        scroll = tk.Canvas(container, highlightthickness=0)
        vertical = ttk.Scrollbar(container, orient="vertical", command=scroll.yview)
        horizontal = ttk.Scrollbar(container, orient="horizontal", command=scroll.xview)
        scroll.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        vertical.pack(side="right", fill="y")
        horizontal.pack(side="bottom", fill="x")
        scroll.pack(side="left", fill="both", expand=True)
        cards = ttk.Frame(scroll, padding=4)
        scroll.create_window(0, 0, window=cards, anchor="nw")
        cards.bind("<Configure>", lambda _: scroll.configure(scrollregion=scroll.bbox("all")))

        for index, block_id in enumerate(block_ids):
            block = self.db.get_block(block_id)
            parts = {part["ID"]: part for part in self.db.block_parts(block_id)}
            placements = self.db.block_placements(block_id)
            card = ttk.LabelFrame(
                cards, text=f"{block['BlockName']} (ID {block_id}, revision {block['Revision']}, {block['Status']})",
                padding=4)
            card.grid(row=index // 3, column=index % 3, sticky="nw", padx=4, pady=4)
            sketch = tk.Canvas(card, width=280, height=220, background="white")
            sketch.pack()
            self.attach_help(sketch, "BlockSketch")
            sketch.bind("<Configure>", lambda _, c=sketch, b=block, p=parts, ps=placements:
                        draw_block_sketch(c, b, p, ps))
            issues = validate_layout(block, list(parts.values()), placements)
            ttk.Label(card, text="; ".join(issues) if issues else "Layout is valid.",
                      wraplength=280).pack(anchor="w")

    def approve_block(self):
        block_id = self.require_block()
        if self.block_form.values() != self.block_initial:
            raise FieldError("Conflict", "QuiltBlock")
        self.db.approve_block(block_id, self.block_revision)
        self.refresh_blocks(block_id)
