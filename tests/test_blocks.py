import sqlite3
import tempfile
import unittest
from pathlib import Path

from quilting.blocks import cutting_shape, finished_shape, parse_part, validate_layout
from quilting.block_templates import BLOCK_TEMPLATES
from quilting.database import Database, UpgradeRequired
from quilting.model import FieldError
from tests.test_inventory import downgrade_color_value_schema, downgrade_dropdown_schema


def block(**overrides):
    return {"BlockName": "Test", "Description": "", "FinishedWidth": "10",
            "FinishedLength": "10", "Scale": "100", "SeamAllowance": "1/4", **overrides}


def part(**overrides):
    return {"PartName": "Panel", "Shape": "Rectangle", "PartColor": "Red", "NumberInBlock": "2",
            "PartWidth": "5", "PartLength": "10", "SideA": "", "SideB": "", "SideC": "",
            "Diameter": "", "MinimumColorValue": "", "MaximumColorValue": "", **overrides}


class BlockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "blocks.db"
        self.db = Database(self.path)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_validated_layout_approval_is_immutable_and_copy_is_independent(self):
        block_id = self.db.add_block(block())
        part_id = self.db.save_block_part(block_id, 1, part())
        placements = self.db.block_placements(block_id)
        with self.assertRaises(FieldError):
            self.db.approve_block(block_id, 2)
        self.db.save_block_placement(block_id, 2, placements[1]["ID"], 5_000_000, 0, 0, False)
        self.db.approve_block(block_id, 3)
        self.assertEqual(self.db.get_block(block_id)["Status"], "Approved")
        for action in (lambda: self.db.update_block(block_id, 4, block()),
                       lambda: self.db.delete_block_part(block_id, 4, part_id),
                       lambda: self.db.delete_block(block_id, 4)):
            with self.assertRaises(FieldError):
                action()
        new_id = self.db.copy_block(block_id)
        self.assertEqual(self.db.get_block(new_id)["ParentID"], block_id)
        self.assertEqual(len(self.db.block_placements(new_id)), 2)
        self.db.update_block(new_id, 1, block(BlockName="New"))
        self.assertEqual(self.db.get_block(block_id)["BlockName"], "Test")

    def test_stale_edits_and_invalid_geometry_are_rejected(self):
        block_id = self.db.add_block(block())
        self.db.save_block_part(block_id, 1, part())
        with self.assertRaises(FieldError):
            self.db.update_block(block_id, 1, block())
        issues = validate_layout(self.db.get_block(block_id), self.db.block_parts(block_id),
                                 self.db.block_placements(block_id))
        self.assertIn("Parts overlap.", issues)
        self.assertIn("Parts do not completely cover the block.", issues)
        for invalid in (
            part(Shape="Square"), part(Shape="Right Triangle", PartWidth="", PartLength="",
                                         SideA="3", SideB="4", SideC="6"),
            part(Shape="Isosceles Triangle", PartWidth="", PartLength="", SideA="1", SideB="2", SideC="4"),
            part(NumberInBlock="0"),
        ):
            with self.assertRaises(FieldError):
                parse_part(invalid)

    def test_shapes_have_actual_seam_offsets_and_scale_does_not_change_allowance(self):
        rectangle = parse_part(part())
        geom = cutting_shape(rectangle, 2, 250_000)
        self.assertAlmostEqual(geom.bounds[2] - geom.bounds[0], 10.5)
        self.assertAlmostEqual(geom.bounds[3] - geom.bounds[1], 20.5)
        triangle = parse_part(part(Shape="Right Triangle", PartWidth="", PartLength="",
                                   SideA="3", SideB="4", SideC="5"))
        self.assertGreater(cutting_shape(triangle, 1, 250_000).area, finished_shape(triangle).area)
        circle = parse_part(part(Shape="Circle", PartWidth="", PartLength="", Diameter="4"))
        self.assertAlmostEqual(cutting_shape(circle, 1, 250_000).bounds[2]
                               - cutting_shape(circle, 1, 250_000).bounds[0], 4.5, places=3)

    def test_templates_create_complete_editable_layouts(self):
        for name in BLOCK_TEMPLATES:
            for width, length, scale in (("12", "12", "100"), ("12", "10", "10000")):
                with self.subTest(template=name, size=(width, length), scale=scale):
                    block_id = self.db.create_block_template(
                        name, block(BlockName="Ignored", FinishedWidth=width,
                                    FinishedLength=length, Scale=scale))
                    current = self.db.get_block(block_id)
                    self.assertEqual(current["BlockName"], name)
                    self.assertEqual(current["Status"], "Draft")
                    self.assertGreater(len(self.db.block_parts(block_id)), 1)
                    self.assertEqual(validate_layout(
                        current, self.db.block_parts(block_id), self.db.block_placements(block_id)), [])
                    self.db.approve_block(block_id, current["Revision"])

    def test_template_fabric_rules_copy_and_individual_groups(self):
        for name in BLOCK_TEMPLATES:
            block_id = self.db.create_block_template(name, block())
            rule = self.db.block_fabric_rule(block_id)
            self.assertEqual(rule["mode"], "Distinct" if name.startswith("Log Cabin") else "Grouped")
            if not name.startswith("Log Cabin"):
                self.assertEqual(len(rule["groups"]), len(self.db.block_placements(block_id)))
                copy_id = self.db.copy_block(block_id)
                self.assertEqual(sorted(rule["groups"].values()),
                                 sorted(self.db.block_fabric_rule(copy_id)["groups"].values()))
        block_id = self.db.add_block(block())
        self.db.save_block_part(block_id, 1, part())
        placements = self.db.block_placements(block_id)
        self.db.save_block_fabric_rule(block_id, 2, "Distinct", {placements[0]["ID"]: "Same"})
        self.assertEqual(self.db.block_fabric_rule(block_id),
                         {"mode": "Distinct", "groups": {placements[0]["ID"]: "Same"}})
        with self.assertRaises(FieldError):
            self.db.save_block_fabric_rule(block_id, 2, "Grouped", {})
        with self.assertRaises(FieldError):
            self.db.save_block_fabric_rule(block_id, 3, "Grouped", {999999: "Same"})
        self.db.save_block_fabric_rule(block_id, 3, "Legacy", {placements[0]["ID"]: "Same"})
        self.assertEqual(self.db.block_fabric_rule(block_id),
                         {"mode": "Legacy", "groups": {placements[0]["ID"]: "Same"}})

    def test_v16_upgrade_preserves_blocks_and_plans_with_legacy_rule(self):
        block_id = self.db.add_block(block())
        self.db.save_block_part(block_id, 1, part())
        with self.db.connection:
            self.db.connection.execute("DROP TABLE PlacementFabricGroup")
            self.db.connection.execute("DROP TABLE BlockFabricRule")
            self.db.connection.execute("PRAGMA user_version=16")
        self.db.close()
        self.db = Database(self.path, upgrade=True)
        self.assertEqual(self.db.block_fabric_rule(block_id), {"mode": "Legacy", "groups": {}})
        self.assertEqual(len(self.db.block_parts(block_id)), 1)

    def test_log_cabin_spiral_light_dark_ranges_and_square_original(self):
        spiral_id = self.db.create_block_template(
            "Log Cabin (Spiral)", block(FinishedWidth="12.000001", FinishedLength="10"))
        parts = {p["PartName"]: p for p in self.db.block_parts(spiral_id)}
        self.assertEqual(len(parts), 9)
        self.assertEqual(parts["Center"]["Shape"], "Rectangle")
        self.assertEqual((parts["Center"]["PartWidth"], parts["Center"]["PartLength"]),
                         (2_400_000, 2_000_000))
        self.assertEqual((parts["Center"]["MinimumColorValue"], parts["Center"]["MaximumColorValue"]),
                         (None, None))
        for side in ("top", "left", "bottom", "right"):
            for ring in ("Inner", "Outer"):
                item = parts[f"{ring} {side} log"]
                expected = ("White", 1, 4) if side in ("top", "left") else ("Black", 7, 10)
                self.assertEqual((item["PartColor"], item["MinimumColorValue"], item["MaximumColorValue"]),
                                 expected)
        placements = {p["BlockPartID"]: p for p in self.db.block_placements(spiral_id)}
        # The inner bottom and left logs continue around the preceding logs, not concentric rings.
        center = parts["Center"]
        bottom, left = parts["Inner bottom log"], parts["Inner left log"]
        self.assertEqual(placements[bottom["ID"]]["X"], placements[center["ID"]]["X"])
        self.assertEqual(placements[left["ID"]]["Y"], placements[center["ID"]]["Y"])
        self.assertEqual(validate_layout(self.db.get_block(spiral_id), list(parts.values()),
                                         list(placements.values())), [])
        square_id = self.db.create_block_template("Log Cabin (Square)", block())
        square = {p["PartName"]: p for p in self.db.block_parts(square_id)}
        self.assertEqual(square["Inner top log"]["PartColor"], "Red")
        self.assertEqual(square["Inner bottom log"]["PartColor"], "Red")
        self.assertEqual(square["Outer top log"]["PartColor"], "Blue")
        self.assertIsNone(square["Outer top log"]["MinimumColorValue"])
        self.db.approve_block(spiral_id, 1)
        copy_id = self.db.copy_block(spiral_id)
        copied = {p["PartName"]: p for p in self.db.block_parts(copy_id)}
        self.assertEqual(copied["Inner right log"]["MinimumColorValue"], 7)
        self.assertEqual(copied["Inner right log"]["MaximumColorValue"], 10)

    def test_spiral_center_follows_block_proportions_and_preserves_saved_blocks(self):
        existing = self.db.add_block(block(BlockName="Existing"))
        self.db.save_block_part(existing, 1, part(PartName="Existing center", Shape="Square",
                                                 NumberInBlock="1", PartWidth="2", PartLength="2"))
        before = self.db.block_parts(existing)
        for width, length, center_width, center_length, shape in (
                ("12", "10", 2_400_000, 2_000_000, "Rectangle"),
                ("10", "12", 2_000_000, 2_400_000, "Rectangle"),
                ("12", "12", 2_400_000, 2_400_000, "Square")):
            with self.subTest(width=width, length=length):
                block_id = self.db.create_block_template(
                    "Log Cabin (Spiral)", block(FinishedWidth=width, FinishedLength=length))
                parts = self.db.block_parts(block_id)
                center = next(item for item in parts if item["PartName"] == "Center")
                self.assertEqual((center["Shape"], center["PartWidth"], center["PartLength"]),
                                 (shape, center_width, center_length))
                self.assertEqual(validate_layout(self.db.get_block(block_id), parts,
                                                 self.db.block_placements(block_id)), [])
        self.assertEqual(self.db.block_parts(existing), before)

    def test_color_value_range_requires_valid_ordered_pair(self):
        for minimum, maximum in (("1", ""), ("", "4"), ("5", "4"), ("0", "4"), ("1", "11")):
            with self.subTest(minimum=minimum, maximum=maximum), self.assertRaises(FieldError):
                parse_part(part(MinimumColorValue=minimum, MaximumColorValue=maximum))
        parsed = parse_part(part(MinimumColorValue="1", MaximumColorValue="10"))
        self.assertEqual((parsed["MinimumColorValue"], parsed["MaximumColorValue"]), (1, 10))
        with self.assertRaises(FieldError) as raised:
            parse_part(part(MinimumColorValue="8", MaximumColorValue="2"))
        self.assertIn("minimum cannot exceed the maximum", self.db.error_message(raised.exception))

    def test_unknown_template_does_not_create_a_block(self):
        with self.assertRaises(FieldError):
            self.db.create_block_template("Unknown", block())
        self.assertEqual(self.db.blocks(), [])

    def test_large_block_does_not_accept_small_physical_gap(self):
        block_id = self.db.add_block(block(FinishedWidth="1000", FinishedLength="1000"))
        self.db.save_block_part(block_id, 1, part(NumberInBlock="1", PartWidth="999.999",
                                                  PartLength="1000"))
        issues = validate_layout(self.db.get_block(block_id), self.db.block_parts(block_id),
                                 self.db.block_placements(block_id))
        self.assertIn("Parts do not completely cover the block.", issues)
        with self.assertRaises(FieldError):
            self.db.approve_block(block_id, 2)

    def test_block_sets_persist_and_remove_deleted_members_without_affecting_fabric(self):
        first = self.db.add_block(block(BlockName="Alpha"))
        second = self.db.add_block(block(BlockName="Beta"))
        set_id = self.db.save_set("Project", [first, second], "QuiltBlock")
        self.db.save_sort((("Scale", "desc"),), "QuiltBlockSort")
        self.db.delete_block(first, 1)
        self.db.close()
        self.db = Database(self.path)
        self.assertEqual(self.db.set_members(set_id, "QuiltBlock"), [second])
        self.assertEqual(self.db.load_sort("QuiltBlockSort"), (("Scale", "desc"), ("ID", "asc")))
        self.assertEqual(self.db.sets(), [])

    def test_failed_part_save_rolls_back_and_stale_instances_cannot_update(self):
        block_id = self.db.add_block(block())
        self.db.connection.execute(
            "CREATE TRIGGER FailPlacement BEFORE INSERT ON BlockPartPlacement "
            "BEGIN SELECT RAISE(ABORT, 'placement failed'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.save_block_part(block_id, 1, part())
        self.assertEqual(self.db.block_parts(block_id), [])
        self.assertEqual(self.db.get_block(block_id)["Revision"], 1)
        self.db.connection.execute("DROP TRIGGER FailPlacement")
        self.db.save_block_part(block_id, 1, part())
        other = Database(self.path)
        try:
            other.update_block(block_id, 2, block(BlockName="Changed"))
            with self.assertRaises(FieldError):
                self.db.save_block_placement(block_id, 2, self.db.block_placements(block_id)[0]["ID"],
                                             0, 0, 0, False)
        finally:
            other.close()

    def test_upgrade_v6_requires_consent_and_retains_backup(self):
        with self.db.connection:
            for name in ("QuiltPartFabric", "QuiltPlan", "QuiltColorMap", "QuiltBlockUse", "Quilt",
                         "BlockSetMember", "BlockSet", "BlockPartPlacement", "BlockPart", "QuiltBlock"):
                self.db.connection.execute(f"DROP TABLE {name}")
            downgrade_dropdown_schema(self.db.connection)
            self.db.connection.execute("ALTER TABLE QuiltBack DROP COLUMN SideMargin")
            self.db.connection.execute("ALTER TABLE FabricPiece RENAME COLUMN FabricPattern TO PatternName")
            downgrade_color_value_schema(self.db.connection)
            self.db.connection.execute("PRAGMA user_version=6")
        self.db.close()
        with self.assertRaises(UpgradeRequired):
            Database(self.path)
        self.db = Database(self.path, upgrade=True)
        self.assertTrue(self.db.upgrade_backup.exists())
        with sqlite3.connect(self.db.upgrade_backup) as backup:
            self.assertEqual(backup.execute("PRAGMA user_version").fetchone()[0], 6)
        self.assertEqual(self.db.blocks(), [])

    def test_upgrade_v8_preserves_supported_dropdown_sets(self):
        self.db.add_dropdown_choice("FabricPiece", "Color", "Blue")
        row = next(row for row in self.db.dropdown_rows("Color") if row["ListItem"] == "Blue")
        set_id = self.db.save_set("Fabric colors", [row["ID"]], "DropDown", ("FabricPiece", "Color"))
        with self.db.connection:
            for name in ("QuiltPartFabric", "QuiltPlan", "QuiltColorMap", "QuiltBlockUse", "Quilt",
                         "BlockSetMember", "BlockSet", "BlockPartPlacement", "BlockPart", "QuiltBlock"):
                self.db.connection.execute(f"DROP TABLE {name}")
            self.db.connection.execute("ALTER TABLE Dropdown RENAME TO DropdownCurrent")
            self.db.connection.execute("""
                CREATE TABLE Dropdown (
                    ID INTEGER PRIMARY KEY AUTOINCREMENT, TableName TEXT NOT NULL,
                    FieldName TEXT NOT NULL, ListItem TEXT NOT NULL COLLATE NOCASE,
                    Def INTEGER NOT NULL DEFAULT 0, Use INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(TableName, FieldName, ListItem))
            """)
            self.db.connection.execute(
                "INSERT INTO Dropdown (ID, TableName, FieldName, ListItem, Def, Use) "
                "SELECT ID, TableName, FieldName, ListItem, Def, Use FROM DropdownCurrent")
            self.db.connection.execute("DROP TABLE DropdownCurrent")
            self.db.connection.execute("ALTER TABLE QuiltBack DROP COLUMN SideMargin")
            self.db.connection.execute("ALTER TABLE FabricPiece RENAME COLUMN FabricPattern TO PatternName")
            downgrade_color_value_schema(self.db.connection)
            self.db.connection.execute("PRAGMA user_version=8")
        self.db.close()
        self.db = Database(self.path, upgrade=True)
        self.assertEqual(self.db.set_members(set_id, "DropDown", ("FabricPiece", "Color")), [row["ID"]])
        with self.assertRaises(FieldError):
            self.db.dropdown_rows("Update", table_name="HelpText")
        self.assertEqual(self.db.blocks(), [])
