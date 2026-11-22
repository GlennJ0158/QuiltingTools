"""Quilt composition, color mapping and informational cutting plans."""

import webbrowser
from html import escape
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .blocks import COLORS
from .model import Field, FieldError, display_measurement
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
            Field("PartColor", "choice", choices=COLORS),
            Field("InventoryColor", "choice")), columns=2, style="Entry.TFrame",
            database=self.db, dropdown_scope="Quilt")
        self.quilt_form.pack(fill="x")
        actions = ttk.Frame(entry, padding=4, style="Entry.TFrame")
        actions.pack(fill="x")
        for label, action in (("Set Block Quantity", self.set_quilt_block),
                              ("Remove Block", self.remove_quilt_block),
                              ("Map Color", self.map_quilt_color), ("Remove Mapping", self.remove_quilt_mapping),
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
        self.quilt_summary.configure(text="Blocks: " + (", ".join(
            f"{r['BlockName']} (ID {r['ID']}): {r['Quantity']}" for r in uses) or "none")
            + "\nColor mappings: " + (", ".join(
                f"{r['PartColor']} -> {r['InventoryColor']}" for r in mappings) or "none"))
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
        self.db.add_quilt_mapping(quilt_id, self.quilt_revision, values["PartColor"], values["InventoryColor"])
        self.after_quilt_change(("PartColor", "InventoryColor"))

    def remove_quilt_mapping(self):
        quilt_id = self.require_quilt()
        values = self.quilt_form.values()
        self.db.remove_quilt_mapping(quilt_id, self.quilt_revision, values["PartColor"], values["InventoryColor"])
        self.after_quilt_change(("PartColor", "InventoryColor"))

    def generate_quilt_plan(self):
        quilt_id = self.require_quilt()
        if (self.quilt_form.values() != self.quilt_initial
                or self.quilt_name_form.values() != self.quilt_name_initial):
            raise FieldError("Database", "Quilt", detail="Save block quantities and color mappings, "
                             "or clear unsaved inputs before planning.")
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
        fmt = lambda value: display_measurement(value) if value else "0"
        lines = [f"Quilt: {data['quilt']['QuiltName']} (revision {plan['QuiltRevision']}); plan {plan['ID']}",
                 "Informational only: inventory is not reserved or changed. Replan after inventory changes.",
                 "Packing uses conservative cut-outline bounding rectangles; it is not a proven optimum.",
                 f"Required parts: {data['part_count']}"]
        for source in data["sources"]:
            fabric = source["source"]
            lines.append(f"\nSource ID {fabric['ID']}: {fabric['FabricName']} / {fabric['Color']}; "
                         f"{fmt(fabric['UsableWidth'])} x {fmt(fabric['UsableLength'])} in; "
                         f"revision {fabric['Revision']}; grain {fabric['GrainDirection']}; "
                         f"print {fabric['PrintDirection']}")
            for cut in source["cuts"]:
                lines.append(f"  Block {cut['block_name']} (ID {cut['block_id']}), "
                             f"{cut['part_name']} (ID {cut['part_id']}), {cut['shape']} / {cut['color']}: "
                             f"bounding cut {fmt(cut['cut_width'])} x {fmt(cut['cut_length'])} in; "
                             f"source position {fmt(cut['x'])}, {fmt(cut['y'])}; "
                             f"{'rotated 90 degrees' if cut['rotated'] else 'not rotated'}; "
                             f"block copy {cut['block_number']}, part instance {cut['instance']}, "
                             f"{'mirrored' if cut['mirrored'] else 'not mirrored'}, "
                             f"assembly rotation {cut['block_rotation']} degrees")
        if data["missing"]:
            lines.append("\nMissing parts (no mapped color or fitting fabric found):")
            for item in data["missing"]:
                lines.append(f"  {item['block_name']} / {item['part_name']} / {item['color']}: "
                             f"{item['count']} of {fmt(item['cut_width'])} x {fmt(item['cut_length'])} in "
                             f"({'mirrored' if item['mirrored'] else 'not mirrored'})")
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
            diagrams.append(f'<h2>Source {source["ID"]}: {escape(source["FabricName"])}</h2>'
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
