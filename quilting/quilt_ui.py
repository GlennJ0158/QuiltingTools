"""Quilt composition, color mapping and informational cutting plans."""

import webbrowser
from html import escape
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .model import Field, FieldError, display_fabric_name, display_fractional_measurement
from .quilt_planner import matches_color_value
from .quilt_report import cutting_list_description


class QuiltScreenMixin:
    def build_quilts(self):
        from .ui import Form
        ttk.Label(self.quilt_page, text="Quilts and Cutting Plans",
                  font=("TkDefaultFont", 14, "bold")).pack(anchor="w")
        entry = ttk.Frame(self.quilt_page, style="Entry.TFrame")
        entry.pack(fill="x")
        self.quilt_name_form = Form(entry, (Field("QuiltName", required=True),),
                                    columns=1, style="Entry.TFrame")
        self.quilt_name_form.pack(fill="x")
        bar = ttk.Frame(entry, padding=4, style="Entry.TFrame")
        bar.pack(fill="x")
        self.button(bar, "Add Quilt", self.add_quilt)
        self.quilt_choice = ttk.Combobox(bar, state="readonly", width=45)
        self.quilt_choice.pack(side="left", padx=8)
        self.attach_help(self.quilt_choice, "SavedQuilt")
        self.quilt_choice.bind("<<ComboboxSelected>>", self.command(self.open_quilt))
        self.quilt_status = ttk.Label(bar, text="No quilt selected", style="Entry.TLabel")
        self.quilt_status.pack(side="left")
        self.quilt_form = Form(entry, (
            Field("ApprovedBlock", "choice"), Field("Quantity", default="1"),
            Field("PartColor", "choice"),
            Field("InventoryColor", "choice")), columns=2, style="Entry.TFrame",
            database=self.db, dropdown_scope="Quilt")
        self.quilt_form.pack(fill="x")
        ttk.Label(entry, text="1. Add each approved block and quantity.  2. Choose a used part color and "
                  "inventory color, then Map Color; repeat for each color.  3. Choose a block and "
                  "Eligible Fabrics to assign pieces to its parts.  4. Plan Quilt.",
                  wraplength=1100, style="Entry.TLabel").pack(anchor="w", padx=4)
        actions = ttk.Frame(entry, padding=4, style="Entry.TFrame")
        actions.pack(fill="x")
        for label, action in (("Set Block Quantity", self.set_quilt_block),
                              ("Remove Block", self.remove_quilt_block),
                              ("Map Color", self.map_quilt_color), ("Remove Mapping", self.remove_quilt_mapping),
                              ("Eligible Fabrics", self.show_eligible_fabrics),
                              ("Plan Quilt", self.generate_quilt_plan), ("Print Quilt Plan", self.print_quilt_plan)):
            self.button(actions, label, action)
        self.quilt_summary = ttk.Label(self.quilt_page, text="", wraplength=1100, justify="left")
        self.quilt_summary.pack(fill="x")
        report_bar = ttk.Frame(self.quilt_page, padding=4)
        report_bar.pack(fill="x")
        ttk.Label(report_bar, text="Saved cutting plan").pack(side="left")
        self.quilt_plan_choice = ttk.Combobox(report_bar, state="readonly", width=45)
        self.quilt_plan_choice.pack(side="left", padx=8)
        self.attach_help(self.quilt_plan_choice, "SavedQuiltPlan")
        self.quilt_plan_choice.bind("<<ComboboxSelected>>", self.command(self.open_quilt_plan))
        ttk.Label(report_bar, text="Print format").pack(side="left")
        self.quilt_report_format = ttk.Combobox(
            report_bar, state="readonly", width=14,
            values=self.db.dropdown_choices("QuiltReportFormat", "Quilt"),
        )
        self.quilt_report_format.set(self.db.dropdown_default("QuiltReportFormat", "Quilt") or "")
        self.quilt_report_format.pack(side="left", padx=8)
        self.attach_help(self.quilt_report_format, "QuiltReportFormat")
        from tkinter import Text
        self.quilt_text = Text(self.quilt_page, wrap="word", state="disabled", height=12)
        self.quilt_text.pack(fill="both", expand=True)
        self.attach_help(self.quilt_text, "QuiltPlanDetails")
        self.quilt_id = self.quilt_revision = self.quilt_plan_id = None
        self.quilt_initial = self.quilt_form.values()
        self.quilt_name_initial = self.quilt_name_form.values()
        self.last_quilt_choice = ""
        self.refresh_quilts()

    def allow_quilt_discard(self):
        return (self.quilt_form.values() == self.quilt_initial
                and self.quilt_name_form.values() == self.quilt_name_initial) or messagebox.askyesno(
                    "Unsaved Changes", "Discard unsaved quilt inputs?",
                    parent=self.root.grab_current() or self.root)

    def refresh_quilts(self):
        self.quilt_choices = {f"{row['QuiltName']} (ID {row['ID']})": row["ID"] for row in self.db.quilts()}
        self.quilt_choice.configure(values=tuple(self.quilt_choices))
        self.approved_blocks = {
            f"{row['BlockName']} (ID {row['ID']}, scale {row['Scale']}%)": row["ID"]
            for row in self.db.blocks() if row["Status"] == "Approved"
        }
        self.quilt_form.widgets["ApprovedBlock"].configure(values=tuple(self.approved_blocks))
        self.quilt_form.widgets["InventoryColor"].configure(values=self.db.fabric_colors())

    def add_quilt(self):
        name = self.quilt_name_form.values()["QuiltName"]
        if self.quilt_form.values() != self.quilt_initial and not self.allow_quilt_discard():
            return
        quilt_id = self.db.add_quilt(name)
        self.quilt_name_form.defaults()
        self.quilt_name_initial = self.quilt_name_form.values()
        self.quilt_form.defaults()
        self.quilt_initial = self.quilt_form.values()
        self.refresh_quilts()
        self.load_quilt(quilt_id)

    def open_quilt(self):
        selected = self.quilt_choice.get()
        if selected not in self.quilt_choices:
            raise FieldError("Choice", "SavedQuilt")
        if not self.allow_quilt_discard():
            self.quilt_choice.set(self.last_quilt_choice)
            return
        self.quilt_name_form.defaults()
        self.quilt_name_initial = self.quilt_name_form.values()
        self.quilt_form.defaults()
        self.quilt_initial = self.quilt_form.values()
        self.load_quilt(self.quilt_choices[selected])

    def load_quilt(self, quilt_id):
        row = self.db.get_quilt(quilt_id)
        self.quilt_id, self.quilt_revision = quilt_id, row["Revision"]
        self.last_quilt_choice = next(label for label, value in self.quilt_choices.items() if value == quilt_id)
        self.quilt_choice.set(self.last_quilt_choice)
        self.quilt_status.configure(text=f"Revision {row['Revision']}")
        uses = self.db.quilt_uses(quilt_id)
        mappings = self.db.quilt_mappings(quilt_id)
        parts = [part for use in uses for part in self.db.block_parts(use["ID"])]
        colors = tuple(sorted({part["PartColor"] for part in parts}))
        self.quilt_form.widgets["PartColor"].configure(values=colors)
        if self.quilt_form.variables["PartColor"].get() not in colors:
            self.quilt_form.variables["PartColor"].set("")
            self.quilt_initial["PartColor"] = ""
        assigned = self.db.quilt_part_fabrics(quilt_id)
        unmapped = sorted(set(colors) - {mapping["PartColor"] for mapping in mappings})
        unassigned = [f"{part['PartName']} (ID {part['ID']})" for part in parts if part["ID"] not in assigned]
        self.quilt_summary.configure(text="Blocks: " + (", ".join(
            f"{r['BlockName']} (ID {r['ID']}): {r['Quantity']}" for r in uses) or "none")
            + "\nColor mappings: " + (", ".join(
                f"{r['PartColor']} -> {r['InventoryColor']}" for r in mappings) or "none")
            + "\nUnmapped colors: " + (", ".join(unmapped) or "none")
            + "\nParts without fabric assignments (any matching fabric may be used): "
            + (", ".join(unassigned) or "none"))
        self.quilt_plan_choices = {
            f"Plan {plan['ID']} / quilt revision {plan['QuiltRevision']} / {plan['DateCreated']}": plan["ID"]
            for plan in self.db.quilt_plans(quilt_id)}
        self.quilt_plan_choice.configure(values=tuple(self.quilt_plan_choices))
        self.quilt_plan_choice.set("")
        self.quilt_plan_id = None
        self.set_quilt_text("")

    def require_quilt(self):
        if self.quilt_id is None:
            raise FieldError("OneRecord", "Quilt")
        return self.quilt_id

    def chosen_quilt_block(self):
        name = self.quilt_form.values()["ApprovedBlock"]
        if name not in self.approved_blocks:
            raise FieldError("Required", "ApprovedBlock")
        return self.approved_blocks[name]

    def after_quilt_change(self, fields):
        values = self.quilt_form.values()
        for name in fields:
            self.quilt_initial[name] = values[name]
        self.load_quilt(self.quilt_id)

    def set_quilt_block(self):
        quilt_id = self.require_quilt()
        try:
            quantity = int(self.quilt_form.values()["Quantity"])
        except ValueError as error:
            raise FieldError("Choice", "Quantity") from error
        self.db.set_quilt_use(quilt_id, self.quilt_revision, self.chosen_quilt_block(), quantity)
        self.after_quilt_change(("ApprovedBlock", "Quantity"))

    def remove_quilt_block(self):
        quilt_id = self.require_quilt()
        self.db.remove_quilt_use(quilt_id, self.quilt_revision, self.chosen_quilt_block())
        self.after_quilt_change(("ApprovedBlock",))

    def map_quilt_color(self):
        quilt_id = self.require_quilt()
        values = self.quilt_form.values()
        if values["PartColor"] not in self.quilt_form.widgets["PartColor"].cget("values"):
            raise FieldError("Choice", "PartColor")
        self.db.add_quilt_mapping(quilt_id, self.quilt_revision, values["PartColor"], values["InventoryColor"])
        self.after_quilt_change(("PartColor", "InventoryColor"))

    def remove_quilt_mapping(self):
        quilt_id = self.require_quilt()
        values = self.quilt_form.values()
        self.db.remove_quilt_mapping(quilt_id, self.quilt_revision, values["PartColor"], values["InventoryColor"])
        self.after_quilt_change(("PartColor", "InventoryColor"))

    def show_eligible_fabrics(self):
        from .ui import Form, RecordList

        quilt_id = self.require_quilt()
        block_id = self.chosen_quilt_block()
        if block_id not in {use["ID"] for use in self.db.quilt_uses(quilt_id)}:
            raise FieldError("Database", "ApprovedBlock",
                             detail="Add this block to the quilt with Set Block Quantity first.")
        self.quilt_initial["ApprovedBlock"] = self.quilt_form.values()["ApprovedBlock"]
        revision = self.quilt_revision
        parts = self.db.block_parts(block_id)
        block = self.db.get_block(block_id)
        choices = {f"{block['BlockName']} / {part['PartName']} (part ID {part['ID']}; "
                   f"{part['PartColor']}; value "
                   f"{str(part['MinimumColorValue']) + '-' + str(part['MaximumColorValue']) if part['MinimumColorValue'] is not None else 'any'})": part
                   for part in parts}
        original = {key: set(ids) for key, ids in self.db.quilt_part_fabrics(quilt_id, block_id).items()}
        assigned = {key: set(ids) for key, ids in original.items()}
        window = self.dialog("Eligible Fabrics", "Eligible Fabrics")
        self.dialog_dirty[window] = lambda: assigned != original
        window.geometry("1100x650")
        ttk.Label(window, text="Choose a part. Highlight one or more eligible pieces and choose Assign "
                  "Fabric to Part; repeat for each part. Highlight assigned pieces and choose Remove "
                  "Assignment to remove them. Save Selection and Return saves all changes; Cancel discards them. "
                  "No assignment means any matching fabric may be used. Assignments restrict, but do not "
                  "replace, quilt-wide color mappings. Planning also checks fit and availability; it does not reserve fabric.",
                  wraplength=950, padding=8).pack(anchor="w")
        form = Form(window, (Field("BlockPartChoice", "choice", choices=tuple(choices), width=85),), columns=1)
        form.pack(fill="x")
        detail = ttk.Label(window, text="", wraplength=1000, padding=4)
        detail.pack(anchor="w")
        listing = RecordList(window, ("ID", "FabricName", "Color", "ColorValue", "UsableWidth", "UsableLength",
                                      "Assigned", "Eligibility"))
        listing.pack(fill="both", expand=True)

        def refresh():
            selected = form.variables["BlockPartChoice"].get()
            part = choices[selected]
            current = {row["ID"]: row for row in self.available_inventory()}
            ids = assigned.get(part["ID"], set())
            rows = {row["ID"]: row for row in current.values() if matches_color_value(part, row)}
            for piece_id in ids:
                if piece_id not in rows:
                    rows[piece_id] = self.db.get_piece(piece_id)
            mappings = {row["InventoryColor"].casefold() for row in self.db.quilt_mappings(quilt_id)
                        if row["PartColor"] == part["PartColor"]}
            decorated = []
            for row in rows.values():
                reason = ("Outside available Fabric working selection" if row["ID"] not in current
                          else "Color value no longer matches" if not matches_color_value(part, row)
                          else "Inventory color not mapped" if not row["Color"] or row["Color"].casefold() not in mappings
                          else "Color and value match; fit checked during planning")
                decorated.append({**row, "Assigned": "Yes" if row["ID"] in ids else "", "Eligibility": reason})
            eligible = [row for row in current.values() if matches_color_value(part, row)]
            mapped_count = sum(bool(row["Color"]) and row["Color"].casefold() in mappings for row in eligible)
            warning = ("No color-mapped, value-eligible pieces in the Fabric working selection. "
                       if not mapped_count else "")
            detail.configure(text=f"Part ID {part['ID']}: {len(ids)} assigned piece(s); "
                             f"{len(eligible)} available value-eligible piece(s), "
                             f"{mapped_count} with mapped colors. {warning}"
                             "Rows include saved assignments even if no longer eligible. "
                             "The list otherwise uses the available Fabric working selection.")
            listing.fill(decorated, "fabric pieces", self.sort)

        def change_assignment(add):
            if form.variables["BlockPartChoice"].get() not in choices:
                raise FieldError("Required", "BlockPartChoice")
            part = choices[form.variables["BlockPartChoice"].get()]
            ids = {int(value) for value in listing.tree.selection()}
            if not ids:
                raise FieldError("NoHighlight", "Fabric")
            current = {row["ID"]: row for row in self.available_inventory()}
            if add and any(piece_id not in current or not matches_color_value(part, current[piece_id])
                           for piece_id in ids):
                raise FieldError("Database", "Fabric", detail="Assign only available pieces in the Fabric "
                                 "working selection that match the part's color value range.")
            if add:
                assigned.setdefault(part["ID"], set()).update(ids)
            else:
                assigned.setdefault(part["ID"], set()).difference_update(ids)
                if not assigned[part["ID"]]:
                    assigned.pop(part["ID"])
            refresh()

        def cancel():
            if assigned != original and not messagebox.askyesno(
                    "Unsaved Changes", "Discard unsaved fabric assignments?", parent=window):
                return
            window.destroy()

        def save():
            if assigned != original:
                self.db.save_quilt_part_fabrics(quilt_id, revision, block_id, assigned)
                self.load_quilt(quilt_id)
            window.destroy()

        form.widgets["BlockPartChoice"].bind("<<ComboboxSelected>>", self.command(refresh))
        if choices:
            form.variables["BlockPartChoice"].set(next(iter(choices)))
            refresh()
        else:
            listing.fill([], "value-eligible fabric pieces", self.sort)
        bar = ttk.Frame(window, padding=8)
        bar.pack(fill="x")
        self.button(bar, "Assign Fabric to Part", lambda: change_assignment(True))
        self.button(bar, "Remove Assignment", lambda: change_assignment(False))
        self.button(bar, "Save Selection and Return", save)
        self.button(bar, "Cancel", cancel)
        window.protocol("WM_DELETE_WINDOW", cancel)
        window.bind("<Escape>", lambda _: cancel())

    def generate_quilt_plan(self):
        quilt_id = self.require_quilt()
        if (self.quilt_form.values() != self.quilt_initial
                or self.quilt_name_form.values() != self.quilt_name_initial):
            raise FieldError("Database", "Quilt", detail="Save block quantities and color mappings, "
                             "or clear unsaved inputs before planning.")
        parts = [part for use in self.db.quilt_uses(quilt_id) for part in self.db.block_parts(use["ID"])]
        mapped = {row["PartColor"] for row in self.db.quilt_mappings(quilt_id)}
        missing_colors = sorted({part["PartColor"] for part in parts} - mapped)
        assigned = self.db.quilt_part_fabrics(quilt_id)
        unrestricted = [part for part in parts if part["ID"] not in assigned]
        if (missing_colors or unrestricted) and not messagebox.askyesno(
                "Incomplete Fabric Choices",
                "Unmapped colors: " + (", ".join(missing_colors) or "none")
                + f"\nParts without assignments: {len(unrestricted)}. "
                "Unassigned parts can use any otherwise matching fabric. "
                "Unmapped colors will produce shortages. Continue planning?",
                parent=self.root):
            return
        plan_id = self.db.create_quilt_plan(
            quilt_id, self.quilt_revision, [row["ID"] for row in self.available_inventory()])
        self.quilt_initial = self.quilt_form.values()
        self.load_quilt(quilt_id)
        self.load_quilt_plan(plan_id)

    def open_quilt_plan(self):
        selected = self.quilt_plan_choice.get()
        if selected not in self.quilt_plan_choices:
            raise FieldError("Choice", "SavedQuiltPlan")
        self.load_quilt_plan(self.quilt_plan_choices[selected])

    def load_quilt_plan(self, plan_id):
        plan = self.db.get_quilt_plan(plan_id)
        if plan["QuiltID"] != self.require_quilt():
            raise FieldError("Choice", "QuiltPlan")
        self.quilt_plan_id = plan_id
        self.quilt_plan_choice.set(next(label for label, value in self.quilt_plan_choices.items() if value == plan_id))
        self.set_quilt_text(self.quilt_plan_description(plan))

    @staticmethod
    def quilt_plan_description(plan):
        data = plan["PlanData"]
        fmt = display_fractional_measurement
        cut_fmt = lambda value: display_fractional_measurement(value, round_up=True)
        lines = [f"Quilt: {data['quilt']['QuiltName']} (revision {plan['QuiltRevision']}); plan {plan['ID']}",
                 "Informational only: inventory is not reserved or changed. Replan after inventory changes.",
                 "Packing uses conservative cut-outline bounding rectangles; it is not a proven optimum.",
                 "~ marks dimensions and positions rounded to 1/16 in; cut sizes round up. "
                 "The plan uses exact sizes and positions: verify rounded cuts fit without overlap "
                 "and check allocations before cutting.",
                 f"Required parts: {data['part_count']}"]
        assignments = data.get("assignments", {})
        if assignments:
            lines.append("Fabric restrictions saved with this plan:")
            for use in data["uses"]:
                for part in use["parts"]:
                    ids = assignments.get(str(part["ID"]), assignments.get(part["ID"], []))
                    if ids:
                        lines.append(f"  {use['block']['BlockName']} / {part['PartName']} "
                                     f"(part ID {part['ID']}): fabric IDs {', '.join(map(str, ids))}")
        for source in data["sources"]:
            fabric = source["source"]
            value = fabric.get("ColorValue")
            lines.append(f"\nSource {display_fabric_name(fabric['FabricName'], fabric['ID'])} / {fabric['Color']}; "
                         f"{fmt(fabric['UsableWidth'])} x {fmt(fabric['UsableLength'])} in; "
                         f"revision {fabric['Revision']}; grain {fabric['GrainDirection']}; "
                         f"print {fabric['PrintDirection']}; color value {value if value is not None else 'unknown'}")
            for cut in source["cuts"]:
                lines.append(f"  Block {cut['block_name']} (ID {cut['block_id']}), "
                             f"{cut['part_name']} (ID {cut['part_id']}), {cut['shape']} / {cut['color']}: "
                             f"bounding cut {cut_fmt(cut['cut_width'])} x {cut_fmt(cut['cut_length'])} in; "
                             f"source position {fmt(cut['x'])}, {fmt(cut['y'])}; "
                             f"{'rotated 90 degrees' if cut['rotated'] else 'not rotated'}; "
                             f"block copy {cut['block_number']}, part instance {cut['instance']}, "
                             f"{'mirrored' if cut['mirrored'] else 'not mirrored'}, "
                             f"assembly rotation {cut['block_rotation']} degrees")
        if data["missing"]:
            lines.append("\nMissing parts (no assigned when restricted, mapped, value-eligible "
                         "and fitting fabric found):")
            for item in data["missing"]:
                minimum, maximum = item.get("MinimumColorValue"), item.get("MaximumColorValue")
                value_range = f"; color value {minimum}-{maximum}" if minimum is not None else ""
                lines.append(f"  {item['block_name']} / {item['part_name']} / {item['color']}: "
                             f"{item['count']} of {cut_fmt(item['cut_width'])} x {cut_fmt(item['cut_length'])} in "
                             f"({'mirrored' if item['mirrored'] else 'not mirrored'}{value_range})")
        else:
            lines.append("\nAll required parts allocated in this snapshot.")
        return "\n".join(lines)

    def set_quilt_text(self, text):
        self.quilt_text.configure(state="normal")
        self.quilt_text.delete("1.0", "end")
        self.quilt_text.insert("1.0", text)
        self.quilt_text.configure(state="disabled")

    def print_quilt_plan(self):
        if self.quilt_plan_id is None:
            raise FieldError("OneRecord", "QuiltPlan")
        plan = self.db.get_quilt_plan(self.quilt_plan_id)
        destination = filedialog.asksaveasfilename(
            parent=self.root, title="Save Quilt Cutting Plan (new file only)", defaultextension=".html",
            initialfile="QuiltPlan.html", filetypes=(("HTML report", "*.html"),))
        if not destination:
            return
        diagrams = []
        for entry in plan["PlanData"]["sources"]:
            source = entry["source"]
            factor = min(700e6 / source["UsableWidth"], 500e6 / source["UsableLength"])
            shapes = []
            for number, cut in enumerate(entry["cuts"], 1):
                points = []
                for x, y in cut["outline"]:
                    if cut["rotated"]:
                        x, y = cut["cut_length"] / 1e6 - y, x
                    points.append(f"{(cut['x'] / 1e6 + x) * factor:.4f},"
                                  f"{(cut['y'] / 1e6 + y) * factor:.4f}")
                shapes.append(f'<polygon points="{" ".join(points)}" fill="{cut["color"].lower()}" stroke="black"/>')
                shapes.append(f'<text x="{(cut["x"] + cut["source_width"] / 2) / 1e6 * factor:.4f}" '
                              f'y="{(cut["y"] + cut["source_length"] / 2) / 1e6 * factor:.4f}" '
                              f'text-anchor="middle">{number}</text>')
            w, h = source["UsableWidth"] / 1e6 * factor, source["UsableLength"] / 1e6 * factor
            diagrams.append(f'<h2>Source {escape(display_fabric_name(source["FabricName"], source["ID"]))}</h2>'
                            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}">'
                            f'<rect width="{w}" height="{h}" fill="none" stroke="black"/>'
                            f'{"".join(shapes)}</svg>')
        report = ('<!doctype html><html><head><meta charset="utf-8"><title>Quilt plan</title>'
                  '<style>pre{white-space:pre-wrap}@media print{button{display:none}}</style></head>'
                  '<body><button onclick="window.print()">Print</button>'
                  f'<pre>{escape(cutting_list_description(plan, self.quilt_report_format.get()))}</pre>'
                  f'<h2>Detailed source allocations</h2><pre>{escape(self.quilt_plan_description(plan))}</pre>'
                  + "".join(diagrams) +
                  '<script>window.addEventListener("load",()=>window.print());</script></body></html>')
        path = Path(destination).resolve()
        with path.open("x", encoding="utf-8") as output:
            output.write(report)
        if not webbrowser.open(path.as_uri()):
            raise FieldError("Database", "Print", detail=f"Open {path} manually and print.")
