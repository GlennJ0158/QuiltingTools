import json
import tempfile
import unittest
from pathlib import Path

from quilting.database import Database, SCHEMA_VERSION, UpgradeRequired
from quilting.model import FieldError
from quilting.quilt_report import cutting_list_description
from quilting.quilt_ui import QuiltScreenMixin
from tests.test_blocks import block, part
from tests.test_inventory import downgrade_color_value_schema, fabric


class QuiltPlanningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "quilt.db")
        self.block_id = self.db.add_block(block())
        self.db.save_block_part(self.block_id, 1, part())
        placements = self.db.block_placements(self.block_id)
        self.db.save_block_placement(self.block_id, 2, placements[1]["ID"], 5_000_000, 0, 0, False)
        self.db.approve_block(self.block_id, 3)
        self.quilt_id = self.db.add_quilt("Test quilt")
        self.db.set_quilt_use(self.quilt_id, 1, self.block_id, 2)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_part_assignments_restrict_mapping_persist_and_leave_saved_plan_unchanged(self):
        red_a = self.db.save_piece(fabric(FabricName="A", Color="Red", UsableWidth="12", UsableLength="22"))
        red_b = self.db.save_piece(fabric(FabricName="B", Color="Red", UsableWidth="12", UsableLength="22"))
        blue = self.db.save_piece(fabric(FabricName="C", Color="Blue", UsableWidth="12", UsableLength="22"))
        self.db.add_quilt_mapping(self.quilt_id, 2, "Red", "Red")
        part_id = self.db.block_parts(self.block_id)[0]["ID"]
        before_id = self.db.create_quilt_plan(self.quilt_id, 3)
        old = json.dumps(self.db.get_quilt_plan(before_id)["PlanData"], sort_keys=True)
        self.db.save_quilt_part_fabrics(self.quilt_id, 3, self.block_id, {part_id: [red_b, blue]})
        with self.assertRaises(FieldError):
            self.db.save_quilt_part_fabrics(self.quilt_id, 3, self.block_id, {part_id: [red_a]})
        plan = self.db.get_quilt_plan(self.db.create_quilt_plan(self.quilt_id, 4))
        self.assertEqual([entry["source"]["ID"] for entry in plan["PlanData"]["sources"]], [red_b])
        self.assertEqual(plan["PlanData"]["assignments"][str(part_id)], [red_b, blue])
        self.assertIn(f"part ID {part_id}", QuiltScreenMixin.quilt_plan_description(plan))
        self.assertEqual(json.dumps(self.db.get_quilt_plan(before_id)["PlanData"], sort_keys=True), old)
        restricted = self.db.get_quilt_plan(self.db.create_quilt_plan(self.quilt_id, 4, [red_a]))
        self.assertFalse(restricted["PlanData"]["sources"])
        self.assertEqual(restricted["PlanData"]["missing"][0]["count"], 4)
        self.db.save_quilt_part_fabrics(self.quilt_id, 4, self.block_id, {})
        self.assertEqual(self.db.quilt_part_fabrics(self.quilt_id), {})
        unrestricted = self.db.get_quilt_plan(self.db.create_quilt_plan(self.quilt_id, 5, [red_a]))
        self.assertEqual(unrestricted["PlanData"]["sources"][0]["source"]["ID"], red_a)

    def test_assignments_are_scoped_to_quilt_and_removed_with_block(self):
        source = self.db.save_piece(fabric(Color="Red"))
        part_id = self.db.block_parts(self.block_id)[0]["ID"]
        other = self.db.add_quilt("Other")
        self.db.set_quilt_use(other, 1, self.block_id, 1)
        self.db.save_quilt_part_fabrics(self.quilt_id, 2, self.block_id, {part_id: [source]})
        self.assertEqual(self.db.quilt_part_fabrics(other), {})
        with self.assertRaises(FieldError):
            self.db.save_quilt_part_fabrics(other, 2, self.block_id, {999999: [source]})
        self.db.remove_quilt_use(self.quilt_id, 3, self.block_id)
        self.assertEqual(self.db.quilt_part_fabrics(self.quilt_id), {})

    def test_v15_upgrade_preserves_quilt_and_unrestricted_plans(self):
        source = self.db.save_piece(fabric(Color="Red", UsableWidth="12", UsableLength="22"))
        self.db.add_quilt_mapping(self.quilt_id, 2, "Red", "Red")
        plan_id = self.db.create_quilt_plan(self.quilt_id, 3)
        old_data = self.db.get_quilt_plan(plan_id)["PlanData"]
        old_data.pop("assignments")
        before = json.dumps(old_data, sort_keys=True)
        with self.db.connection:
            self.db.connection.execute("UPDATE QuiltPlan SET PlanData=? WHERE ID=?", (before, plan_id))
            self.db.connection.execute(
                "UPDATE HelpText SET HoverText='Custom hover', FullText='Custom help' "
                "WHERE TableName='Eligible Fabrics' AND FieldName='BlockPartChoice'")
            self.db.connection.execute(
                "UPDATE HelpText SET HoverText=?, FullText=? WHERE TableName='Eligible Fabrics' "
                "AND FieldName='ScreenHelp'",
                ("Review fabrics matching a block part's color value range.",
                 "Choose a part to list value-eligible available fabric in the Fabric working "
                 "selection. Map inventory colors on the Quilt screen; planning also checks "
                 "those mappings and the size of each piece."))
            self.db.connection.execute("DROP TABLE QuiltPartFabric")
            self.db.connection.execute("PRAGMA user_version=15")
        path = self.db.path
        self.db.close()
        with self.assertRaises(UpgradeRequired):
            Database(path)
        self.db = Database(path, upgrade=True)
        self.assertEqual(self.db.connection.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
        self.assertTrue(self.db.upgrade_backup.exists())
        self.assertEqual(self.db.quilt_part_fabrics(self.quilt_id), {})
        self.assertEqual(self.db.help_pair("Eligible Fabrics", "BlockPartChoice"), ("Custom hover", "Custom help"))
        self.assertIn("Save Selection and Return", self.db.help_pair("Eligible Fabrics", "ScreenHelp")[1])
        self.assertEqual(json.dumps(self.db.get_quilt_plan(plan_id)["PlanData"], sort_keys=True), before)
        self.assertIn("Required parts:", QuiltScreenMixin.quilt_plan_description(self.db.get_quilt_plan(plan_id)))
        plan = self.db.get_quilt_plan(self.db.create_quilt_plan(self.quilt_id, 3))
        self.assertEqual(plan["PlanData"]["sources"][0]["source"]["ID"], source)

    def test_multiple_parts_share_small_source_and_inventory_is_unchanged(self):
        small = self.db.save_piece(fabric(FabricName="Small", Color="Red", UsableWidth="12", UsableLength="22"))
        large = self.db.save_piece(fabric(FabricName="Large", Color="Red", UsableWidth="100", UsableLength="100"))
        self.db.add_quilt_mapping(self.quilt_id, 2, "Red", "Red")
        before = self.db.pieces()
        plan_id = self.db.create_quilt_plan(self.quilt_id, 3)
        plan = self.db.get_quilt_plan(plan_id)["PlanData"]
        self.assertEqual(plan["part_count"], 4)
        self.assertEqual(plan["missing"], [])
        self.assertEqual([entry["source"]["ID"] for entry in plan["sources"]], [small])
        self.assertEqual(len(plan["sources"][0]["cuts"]), 4)
        self.assertEqual(self.db.pieces(), before)
        self.assertEqual(self.db.get_piece(large)["Revision"], 1)
        cuts = plan["sources"][0]["cuts"]
        for i, cut in enumerate(cuts):
            for other in cuts[:i]:
                overlap = (cut["x"] < other["x"] + other["source_width"]
                           and other["x"] < cut["x"] + cut["source_width"]
                           and cut["y"] < other["y"] + other["source_length"]
                           and other["y"] < cut["y"] + cut["source_length"])
                self.assertFalse(overlap)

    def test_unmapped_and_insufficient_fabric_produce_saved_partial_plan(self):
        self.db.save_piece(fabric(Color="Red", UsableWidth="6", UsableLength="11"))
        plan = self.db.get_quilt_plan(self.db.create_quilt_plan(self.quilt_id, 2))["PlanData"]
        self.assertEqual(plan["missing"][0]["count"], 4)
        self.db.add_quilt_mapping(self.quilt_id, 2, "Red", "Red")
        plan = self.db.get_quilt_plan(self.db.create_quilt_plan(self.quilt_id, 3))["PlanData"]
        self.assertEqual(len(plan["sources"][0]["cuts"]), 1)
        self.assertEqual(plan["missing"][0]["count"], 3)

    def test_part_ranges_limit_matching_pieces_and_saved_plan_is_a_snapshot(self):
        block_id = self.db.add_block(block(BlockName="Contrasting"))
        light_id = self.db.save_block_part(block_id, 1, part(
            PartName="Light", NumberInBlock="1", MinimumColorValue="1", MaximumColorValue="4"))
        dark_id = self.db.save_block_part(block_id, 2, part(
            PartName="Dark", NumberInBlock="1", MinimumColorValue="7", MaximumColorValue="10"))
        dark_placement = next(p for p in self.db.block_placements(block_id) if p["BlockPartID"] == dark_id)
        self.db.save_block_placement(block_id, 3, dark_placement["ID"], 5_000_000, 0, 0, False)
        self.db.approve_block(block_id, 4)
        quilt = self.db.add_quilt("Contrast")
        self.db.set_quilt_use(quilt, 1, block_id, 1)
        for value in ("", "5", "1", "10"):
            self.db.save_piece(fabric(FabricName=f"Value {value}", Color="Red", ColorValue=value,
                                      UsableWidth="6", UsableLength="11"))
        self.db.add_quilt_mapping(quilt, 2, "Red", "Red")
        plan_id = self.db.create_quilt_plan(quilt, 3)
        plan = self.db.get_quilt_plan(plan_id)
        by_part = {cut["part_id"]: entry["source"]["ColorValue"]
                   for entry in plan["PlanData"]["sources"] for cut in entry["cuts"]}
        self.assertEqual(by_part, {light_id: 1, dark_id: 10})
        self.assertFalse(plan["PlanData"]["missing"])
        self.assertIn("color value 1-4", cutting_list_description(plan, "Entire Quilt"))
        before = json.dumps(plan["PlanData"], sort_keys=True)
        light_source = next(entry["source"]["ID"] for entry in plan["PlanData"]["sources"]
                            if entry["source"]["ColorValue"] == 1)
        self.db.save_quilt_part_fabrics(quilt, 3, block_id, {light_id: [light_source]})
        self.db.save_piece(fabric(FabricName="Value 1", Color="Red", ColorValue="5",
                                  UsableWidth="6", UsableLength="11"),
                           light_source, 1)
        self.assertEqual(json.dumps(self.db.get_quilt_plan(plan_id)["PlanData"], sort_keys=True), before)
        new_plan = self.db.get_quilt_plan(self.db.create_quilt_plan(quilt, 4))["PlanData"]
        self.assertEqual(new_plan["missing"][0]["part_id"], light_id)
        self.assertEqual(new_plan["missing"][0]["count"], 1)

    def test_v13_upgrade_renames_saved_plan_source_pattern(self):
        self.db.save_piece(fabric(Color="Red", FabricPattern="Floral", UsableWidth="12", UsableLength="22",
                                  Notes="PatternName is just text"))
        self.db.add_quilt_mapping(self.quilt_id, 2, "Red", "Red")
        plan_id = self.db.create_quilt_plan(self.quilt_id, 3)
        plan = self.db.get_quilt_plan(plan_id)["PlanData"]
        source = plan["sources"][0]["source"]
        source["PatternName"] = source.pop("FabricPattern")
        with self.db.connection:
            self.db.connection.execute("UPDATE QuiltPlan SET PlanData=? WHERE ID=?", (json.dumps(plan), plan_id))
            self.db.connection.execute("ALTER TABLE FabricPiece RENAME COLUMN FabricPattern TO PatternName")
            downgrade_color_value_schema(self.db.connection)
            self.db.connection.execute("PRAGMA user_version=13")
        path = self.db.path
        self.db.close()
        self.db = Database(path, upgrade=True)
        source = self.db.get_quilt_plan(plan_id)["PlanData"]["sources"][0]["source"]
        self.assertEqual(source["FabricPattern"], "Floral")
        self.assertNotIn("PatternName", source)
        self.assertEqual(source["Notes"], "PatternName is just text")

    def test_v14_upgrade_preserves_old_saved_plan_and_reporting(self):
        self.db.save_piece(fabric(Color="Red", UsableWidth="12", UsableLength="22"))
        self.db.add_quilt_mapping(self.quilt_id, 2, "Red", "Red")
        plan_id = self.db.create_quilt_plan(self.quilt_id, 3)
        old = self.db.get_quilt_plan(plan_id)["PlanData"]
        for use in old["uses"]:
            for record in use["parts"]:
                record.pop("MinimumColorValue")
                record.pop("MaximumColorValue")
        for entry in old["sources"]:
            entry["source"].pop("ColorValue")
            for cut in entry["cuts"]:
                cut.pop("MinimumColorValue")
                cut.pop("MaximumColorValue")
        with self.db.connection:
            self.db.connection.execute("UPDATE QuiltPlan SET PlanData=? WHERE ID=?", (json.dumps(old), plan_id))
            downgrade_color_value_schema(self.db.connection)
            self.db.connection.execute("PRAGMA user_version=14")
        path = self.db.path
        self.db.close()
        self.db = Database(path, upgrade=True)
        plan = self.db.get_quilt_plan(plan_id)
        self.assertEqual(plan["PlanData"], old)
        self.assertIn("Cutting list:", cutting_list_description(plan, "Entire Quilt"))
        regenerated = self.db.get_quilt_plan(self.db.create_quilt_plan(self.quilt_id, 3))["PlanData"]
        self.assertFalse(regenerated["missing"])

    def test_quilts_share_approved_version_and_conflicts_are_rejected(self):
        second = self.db.add_quilt("Another")
        self.db.set_quilt_use(second, 1, self.block_id, 1)
        self.assertEqual(self.db.quilt_uses(second)[0]["ID"], self.block_id)
        with self.assertRaises(FieldError):
            self.db.set_quilt_use(self.quilt_id, 1, self.block_id, 3)
        draft = self.db.copy_block(self.block_id)
        with self.assertRaises(FieldError):
            self.db.set_quilt_use(second, 2, draft, 1)
        with self.assertRaises(FieldError):
            self.db.add_quilt_mapping(second, 2, "Red", "not in inventory")


class QuiltCuttingListTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "reports.db")
        quilt = self.db.add_quilt("Report quilt")
        for index in range(6):
            size, scale = ("1", "200") if index == 1 else ("2", "100")
            block_id = self.db.add_block(block(BlockName=f"Block {index + 1}", FinishedWidth=size,
                                               FinishedLength=size, Scale=scale))
            self.db.save_block_part(block_id, 1, part(PartName=f"Panel {index + 1}", Shape="Square",
                                                     NumberInBlock="1", PartWidth=size, PartLength=size))
            self.db.approve_block(block_id, 2)
            self.db.set_quilt_use(quilt, index + 1, block_id, 6)
        self.fabric_a = self.db.save_piece(fabric(FabricName="First", Color="Red",
                                                  UsableWidth="2.5", UsableLength="45"))
        self.fabric_b = self.db.save_piece(fabric(FabricName="Second", Color="Red",
                                                  UsableWidth="2.5", UsableLength="40"))
        self.db.add_quilt_mapping(quilt, 7, "Red", "Red")
        self.plan = self.db.get_quilt_plan(self.db.create_quilt_plan(quilt, 8))

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_entire_quilt_combines_equivalent_scaled_parts_and_reports_sources_and_shortage(self):
        report = cutting_list_description(self.plan, "Entire Quilt")
        self.assertIn("Total blocks: 36; required parts: 36", report)
        self.assertEqual(report.count("36 Red Square"), 1)
        self.assertIn("finished width 2, length 2 in", report)
        self.assertIn("seam allowance 1/4 in; cut bounding size 2 1/2 x 2 1/2 in", report)
        self.assertIn(f"18 from Fabric First ({self.fabric_a}) / Red, 2 1/2 x 45 in", report)
        self.assertIn(f"16 from Fabric Second ({self.fabric_b}) / Red, 2 1/2 x 40 in", report)
        self.assertIn("Missing: 2", report)

    def test_duplicate_names_in_saved_plan_are_distinguished_in_both_cutting_formats(self):
        for piece_id, length in ((self.fabric_a, "45"), (self.fabric_b, "40")):
            self.db.save_piece(fabric(FabricName="Same fabric", Color="Red",
                                      UsableWidth="2.5", UsableLength=length), piece_id, 1)
        plan_id = self.db.create_quilt_plan(self.plan["QuiltID"], self.plan["QuiltRevision"])
        self.db.save_piece(fabric(FabricName="Renamed", Color="Red",
                                  UsableWidth="2.5", UsableLength="45"), self.fabric_a, 2)
        plan = self.db.get_quilt_plan(plan_id)
        data = plan["PlanData"]
        before = json.dumps(data, sort_keys=True)
        for report in (cutting_list_description(plan, "Entire Quilt"),
                       cutting_list_description(plan, "By Block"),
                       QuiltScreenMixin.quilt_plan_description(plan)):
            self.assertIn(f"Same fabric ({self.fabric_a})", report)
            self.assertIn(f"Same fabric ({self.fabric_b})", report)
        self.assertEqual(json.dumps(data, sort_keys=True), before)

    def test_rounding_plan_output_does_not_change_snapshot_or_claim_fit(self):
        data = self.plan["PlanData"]
        source = data["sources"][0]
        source["source"]["UsableWidth"] = 2_510_000
        cut = source["cuts"][0]
        cut["cut_width"] = 2_510_000
        cut["x"] = 10_000
        before = json.dumps(data, sort_keys=True)
        for text in (QuiltScreenMixin.quilt_plan_description(self.plan),
                     cutting_list_description(self.plan, "Entire Quilt"),
                     cutting_list_description(self.plan, "By Block")):
            self.assertIn("~2 9/16", text)
            self.assertIn("~2 1/2", text)
            self.assertIn("verify rounded cuts fit without overlap", text)
            self.assertIn("check allocations before cutting", text)
        self.assertIn("source position ~0", QuiltScreenMixin.quilt_plan_description(self.plan))
        self.assertEqual(json.dumps(data, sort_keys=True), before)

    def test_by_block_keeps_block_totals_and_partial_allocations_separate(self):
        report = cutting_list_description(self.plan, "By Block")
        for index in range(6):
            self.assertIn(f"Block Block {index + 1} (ID", report)
            self.assertIn(f"Panel {index + 1} (part ID", report)
        self.assertEqual(report.count("quantity 6"), 6)
        self.assertEqual(report.count("6 Red Square"), 6)
        self.assertIn("Missing: 2", report)

    def test_distinct_geometry_seams_and_mirroring_are_not_combined(self):
        data = self.plan["PlanData"]
        second_use = data["uses"][1]
        second_use["block"]["SeamAllowance"] = 500_000
        cuts = [cut for source in data["sources"] for cut in source["cuts"]
                if cut["block_id"] == second_use["block"]["ID"]]
        cuts[0]["mirrored"] = True
        report = cutting_list_description(self.plan, "Entire Quilt")
        self.assertIn("1 Red Square; finished width 2, length 2 in; seam allowance 1/2 in", report)
        self.assertIn("5 Red Square; finished width 2, length 2 in; seam allowance 1/2 in", report)
        self.assertIn("30 Red Square; finished width 2, length 2 in; seam allowance 1/4 in", report)

    def test_triangle_side_lengths_remain_distinct_even_with_same_cut_bounds(self):
        data = self.plan["PlanData"]
        for use, sides in zip(data["uses"][:2], ((3, 3, 5), (5, 5, 6))):
            use["block"]["Scale"] = "100"
            part_data = use["parts"][0]
            part_data["Shape"] = "Isosceles Triangle"
            for field, value in zip(("SideA", "SideB", "SideC"), sides):
                part_data[field] = value * 1_000_000
        report = cutting_list_description(self.plan, "Entire Quilt")
        self.assertIn("6 Red Isosceles Triangle; finished a 3, b 3, c 5 in", report)
        self.assertIn("6 Red Isosceles Triangle; finished a 5, b 5, c 6 in", report)
