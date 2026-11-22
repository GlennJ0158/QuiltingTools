import sqlite3
import tempfile
import unittest
from pathlib import Path

from quilting.blocks import cutting_shape, finished_shape, parse_part, validate_layout
from quilting.database import Database, UpgradeRequired
from quilting.model import FieldError
from tests.test_inventory import downgrade_dropdown_schema


def block(**overrides):
    return {"BlockName": "Test", "Description": "", "FinishedWidth": "10",
            "FinishedLength": "10", "Scale": "100", "SeamAllowance": "1/4", **overrides}


def part(**overrides):
    return {"PartName": "Panel", "Shape": "Rectangle", "PartColor": "Red", "NumberInBlock": "2",
            "PartWidth": "5", "PartLength": "10", "SideA": "", "SideB": "", "SideC": "",
            "Diameter": "", **overrides}


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
            for name in ("QuiltPlan", "QuiltColorMap", "QuiltBlockUse", "Quilt",
                         "BlockSetMember", "BlockSet", "BlockPartPlacement", "BlockPart", "QuiltBlock"):
                self.db.connection.execute(f"DROP TABLE {name}")
            downgrade_dropdown_schema(self.db.connection)
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
            for name in ("QuiltPlan", "QuiltColorMap", "QuiltBlockUse", "Quilt",
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
            self.db.connection.execute("PRAGMA user_version=8")
        self.db.close()
        self.db = Database(self.path, upgrade=True)
        self.assertEqual(self.db.set_members(set_id, "DropDown", ("FabricPiece", "Color")), [row["ID"]])
        with self.assertRaises(FieldError):
            self.db.dropdown_rows("Update", table_name="HelpText")
        self.assertEqual(self.db.blocks(), [])
