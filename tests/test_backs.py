import sqlite3
import tempfile
import unittest
from pathlib import Path

from quilting.backs import (
    INCH, PALETTE, generate_layouts, layout_svg, palette_suggestion, ratio_label,
)
from quilting.database import Database, SCHEMA_VERSION, UpgradeRequired
from quilting.model import FieldError
from tests.test_inventory import downgrade_dropdown_schema, fabric


class QuiltBackPlanningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "inventory.db"
        self.db = Database(self.path)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def add_piece(self, **overrides):
        return self.db.save_piece(fabric(**overrides))

    def test_one_piece_plan_and_palette_sketch(self):
        source_id = self.add_piece(
            FabricName="Blue cotton", Color="Navy", UsableWidth="110",
            UsableLength="110", GrainDirection="Along Width",
        )
        piece = self.db.get_piece(source_id)
        layouts = generate_layouts([piece], 100 * INCH, 100 * INCH, 4 * INCH, INCH)
        self.assertTrue(layouts)
        layout = layouts[0]
        self.assertEqual(layout.direction, "single")
        self.assertEqual(layout.panels[0].cut_width, 108 * INCH)
        self.assertEqual(layout.panels[0].finished_width, 108 * INCH)
        self.assertEqual(layout.panels[0].grain_axis, "x")
        self.assertEqual(layout.ratio_tier, 2)
        self.assertEqual(palette_suggestion("navy"), "Blue")
        self.assertIn(PALETTE["Blue"], layout_svg(layout))
        self.assertIn("marker-end", layout_svg(layout))
        self.assertEqual(ratio_label(layout.ratio_tier), "20% target met")

    def test_equal_strip_candidates_include_seam_allowance_and_grain_mix(self):
        pieces = [
            self.db.get_piece(self.add_piece(
                FabricName=f"Piece {index}", Color=color, UsableWidth="42",
                UsableLength="60", GrainDirection=grain,
            ))
            for index, (color, grain) in enumerate(
                (("Red", "Along Width"), ("Blue", "Along Length")), 1,
            )
        ]
        layouts = generate_layouts(pieces, 50 * INCH, 50 * INCH, 0, INCH)
        two_panel = next(layout for layout in layouts if len(layout.panels) == 2)
        self.assertEqual(two_panel.direction, "vertical")
        self.assertEqual([panel.finished_width for panel in two_panel.panels],
                         [25 * INCH, 25 * INCH])
        self.assertEqual([panel.cut_width for panel in two_panel.panels],
                         [26 * INCH, 26 * INCH])
        self.assertFalse(two_panel.grain_consistent)

    def test_one_source_can_supply_multiple_nonoverlapping_panels(self):
        source_id = self.add_piece(
            FabricName="Long backing", UsableWidth="42", UsableLength="220",
            GrainDirection="Along Width",
        )
        piece = self.db.get_piece(source_id)
        layout = next(layout for layout in generate_layouts(
            [piece], 50 * INCH, 100 * INCH, 0, INCH,
        ) if len(layout.panels) == 2)
        self.assertEqual([panel.source_id for panel in layout.panels], [source_id, source_id])
        self.assertEqual(layout.panels[0].source_y, 0)
        self.assertEqual(layout.panels[1].source_y, 100 * INCH)
        back_id = self.db.save_back_draft(
            "Long backing plan", 50 * INCH, 100 * INCH, 0, INCH, layout,
        )
        self.assertEqual(
            [panel["SourceY"] for panel in self.db.get_quilt_back(back_id)["Panels"]],
            [0, 100 * INCH],
        )
        self.db.confirm_back_cut(back_id, {source_id: ("20", "40")})
        self.assertEqual(self.db.get_piece(source_id)["Status"], "Retired")
        self.assertEqual(self.db.connection.execute(
            "SELECT count(*) FROM QuiltBackCutSource WHERE QuiltBackID = ?", (back_id,),
        ).fetchone()[0], 1)

    def test_rotation_is_not_silently_assumed_and_fallback_tiers(self):
        source_id = self.add_piece(
            FabricName="Narrow fabric", UsableWidth="30", UsableLength="80",
        )
        self.assertEqual(
            generate_layouts([self.db.get_piece(source_id)], 80 * INCH, 30 * INCH, 0, 0),
            [],
        )
        sources = [
            self.db.get_piece(self.add_piece(
                FabricName=f"Wide {index}", UsableWidth="170", UsableLength="1000",
            ))
            for index in range(6)
        ]
        layouts = generate_layouts(sources, 1000 * INCH, 1000 * INCH, 0, 0)
        self.assertTrue(layouts)
        self.assertTrue(all(layout.ratio_tier == 1 for layout in layouts))
        self.assertTrue(all(panel.finished_width >= 100 * INCH
                            for layout in layouts for panel in layout.panels))

    def test_draft_does_not_change_stock_then_cut_and_remnant_are_atomic(self):
        sources = [
            self.add_piece(FabricName=f"Backing {index}", Color="Green",
                           UsableWidth="42", UsableLength="60",
                           GrainDirection="Along Width")
            for index in range(2)
        ]
        pieces = [self.db.get_piece(source_id) for source_id in sources]
        layout = next(layout for layout in generate_layouts(
            pieces, 50 * INCH, 50 * INCH, 0, INCH,
        ) if len(layout.panels) == 2)
        back_id = self.db.save_back_draft(
            "Guest room", 50 * INCH, 50 * INCH, 0, INCH, layout,
        )
        self.assertEqual(self.db.get_quilt_back(back_id)["Status"], "Draft")
        self.assertTrue(all(self.db.get_piece(source_id)["Status"] == "Available"
                            for source_id in sources))
        with self.assertRaises(FieldError):
            self.db.confirm_back_cut(back_id, {
                sources[0]: ("5", "10"), sources[1]: ("5", ""),
            })
        self.assertEqual(self.db.get_quilt_back(back_id)["Status"], "Draft")
        self.assertTrue(all(self.db.get_piece(source_id)["Status"] == "Available"
                            for source_id in sources))
        back = self.db.confirm_back_cut(back_id, {
            sources[0]: ("30", "45"), sources[1]: None,
        })
        self.assertEqual(back["Status"], "Cut")
        self.assertEqual(self.db.get_piece(sources[0])["Status"], "Retired")
        self.assertEqual(self.db.get_piece(sources[1])["Status"], "Retired")
        remnant_id = self.db.connection.execute(
            "SELECT RemnantPieceID FROM QuiltBackCutSource WHERE QuiltBackID = ? AND FabricPieceID = ?",
            (back_id, sources[0]),
        ).fetchone()[0]
        self.assertEqual(self.db.get_piece(remnant_id)["UsableWidth"], 30 * INCH)
        self.assertEqual(self.db.history(remnant_id)[0]["Action"], "Added")
        self.assertEqual(self.db.history(sources[0])[0]["Action"], "Updated")
        assembled = self.db.mark_quilt_back_assembled(back_id)
        self.assertEqual(assembled["Status"], "Assembled")

    def test_stale_source_revision_blocks_cut_without_partial_inventory_updates(self):
        source_ids = [
            self.add_piece(FabricName=f"Piece {index}", UsableWidth="42", UsableLength="60")
            for index in range(2)
        ]
        pieces = [self.db.get_piece(source_id) for source_id in source_ids]
        layout = next(layout for layout in generate_layouts(
            pieces, 50 * INCH, 50 * INCH, 0, 0,
        ) if len(layout.panels) == 2)
        back_id = self.db.save_back_draft("Conflict", 50 * INCH, 50 * INCH, 0, 0, layout)
        other = Database(self.path)
        try:
            row = other.get_piece(source_ids[0])
            other.save_piece(fabric(
                FabricName=row["FabricName"], UsableWidth="42", UsableLength="60", Notes="Changed",
            ), source_ids[0], row["Revision"])
        finally:
            other.close()
        with self.assertRaises(FieldError) as raised:
            self.db.confirm_back_cut(back_id, {source_id: None for source_id in source_ids})
        self.assertEqual(raised.exception.key, "Conflict")
        self.assertEqual(self.db.get_quilt_back(back_id)["Status"], "Draft")
        self.assertEqual(self.db.get_piece(source_ids[1])["Status"], "Available")

    def test_version_five_upgrade_adds_back_tables_and_keeps_a_verified_backup(self):
        self.add_piece(FabricName="Legacy")
        with self.db.connection:
            for table in ("QuiltPlan", "QuiltColorMap", "QuiltBlockUse", "Quilt",
                          "BlockSetMember", "BlockSet", "BlockPartPlacement", "BlockPart", "QuiltBlock"):
                self.db.connection.execute(f"DROP TABLE {table}")
            for table in ("QuiltBackCutSource", "QuiltBackPanel", "QuiltBack"):
                self.db.connection.execute(f"DROP TABLE {table}")
            downgrade_dropdown_schema(self.db.connection)
            self.db.connection.execute("PRAGMA user_version = 5")
        self.db.close()
        with self.assertRaises(UpgradeRequired):
            Database(self.path)
        self.db = Database(self.path, upgrade=True)
        self.assertEqual(self.db.connection.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
        self.assertEqual(self.db.pieces()[0]["FabricName"], "Legacy")
        with sqlite3.connect(self.db.upgrade_backup) as backup:
            self.assertEqual(backup.execute("PRAGMA user_version").fetchone()[0], 5)
        self.assertEqual(
            [row[0] for row in self.db.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'QuiltBack%' ORDER BY name",
            )],
            ["QuiltBack", "QuiltBackCutSource", "QuiltBackPanel"],
        )

    def test_version_six_upgrade_preserves_existing_working_sets(self):
        help_id = self.db.help_rows()[0]["ID"]
        set_id = self.db.save_set("Existing help", [help_id], "HelpText")
        connection = self.db.connection
        with connection:
            for table in ("QuiltPlan", "QuiltColorMap", "QuiltBlockUse", "Quilt",
                          "BlockSetMember", "BlockSet", "BlockPartPlacement", "BlockPart", "QuiltBlock"):
                connection.execute(f"DROP TABLE {table}")
            connection.execute("ALTER TABLE WorkingListMember RENAME TO NewMember")
            connection.execute("ALTER TABLE WorkingListSet RENAME TO NewSet")
            connection.execute(
                "CREATE TABLE WorkingListSet ("
                "ID INTEGER PRIMARY KEY AUTOINCREMENT, "
                "ScreenName TEXT NOT NULL CHECK(ScreenName IN "
                "('DropDown', 'HelpText', 'History')), "
                "ScopeName TEXT NOT NULL DEFAULT '', "
                "SetName TEXT NOT NULL CHECK(length(trim(SetName)) BETWEEN 1 AND 120), "
                "DateCreated TEXT NOT NULL, "
                "UNIQUE(ScreenName, ScopeName, SetName COLLATE NOCASE))"
            )
            connection.execute(
                "CREATE TABLE WorkingListMember ("
                "SelectionSetID INTEGER NOT NULL REFERENCES WorkingListSet(ID) ON DELETE CASCADE, "
                "RecordID INTEGER NOT NULL, PRIMARY KEY (SelectionSetID, RecordID))"
            )
            connection.execute("INSERT INTO WorkingListSet SELECT * FROM NewSet")
            connection.execute("INSERT INTO WorkingListMember SELECT * FROM NewMember")
            connection.execute("DROP TABLE NewMember")
            connection.execute("DROP TABLE NewSet")
            downgrade_dropdown_schema(connection)
            connection.execute("PRAGMA user_version = 6")
        self.db.close()
        with self.assertRaises(UpgradeRequired):
            Database(self.path)
        self.db = Database(self.path, upgrade=True)
        self.assertEqual(self.db.set_members(set_id, "HelpText"), [help_id])
        self.assertEqual(self.db.connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        with sqlite3.connect(self.db.upgrade_backup) as backup:
            self.assertEqual(backup.execute("PRAGMA user_version").fetchone()[0], 6)
            self.assertEqual(
                backup.execute("SELECT RecordID FROM WorkingListMember").fetchone()[0], help_id,
            )

    def test_version_eleven_upgrade_makes_panel_inventory_color_nullable(self):
        source_id = self.add_piece(Color="Navy", UsableWidth="100", UsableLength="100")
        layout = generate_layouts([self.db.get_piece(source_id)], 30 * INCH, 30 * INCH, 0, INCH)[0]
        back_id = self.db.save_back_draft("Legacy color snapshot", 30 * INCH, 30 * INCH, 0, INCH, layout)
        before = self.db.get_quilt_back(back_id)["Panels"][0]["InventoryColor"]
        empty_source_id = self.add_piece(Color=None, UsableWidth="100", UsableLength="100")
        empty_layout = generate_layouts(
            [self.db.get_piece(empty_source_id)], 30 * INCH, 30 * INCH, 0, INCH,
        )[0]
        empty_back_id = self.db.save_back_draft(
            "Legacy empty snapshot", 30 * INCH, 30 * INCH, 0, INCH, empty_layout,
        )
        with self.db.connection:
            self.db.connection.execute(
                "UPDATE QuiltBackPanel SET InventoryColor = '' WHERE QuiltBackID = ?",
                (empty_back_id,),
            )
            sql = self.db.connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='QuiltBackPanel'",
            ).fetchone()[0]
            old_sql = sql.replace("CREATE TABLE QuiltBackPanel", "CREATE TABLE QuiltBackPanelOld", 1)
            old_sql = old_sql.replace(
                "InventoryColor TEXT CHECK(InventoryColor IS NULL OR length(InventoryColor) <= 120)",
                "InventoryColor TEXT NOT NULL CHECK(length(InventoryColor) <= 120)",
            )
            self.db.connection.execute(old_sql)
            columns = ", ".join(row[1] for row in self.db.connection.execute(
                "PRAGMA table_info(QuiltBackPanel)"))
            self.db.connection.execute(
                f"INSERT INTO QuiltBackPanelOld ({columns}) SELECT {columns} FROM QuiltBackPanel")
            self.db.connection.execute("DROP TABLE QuiltBackPanel")
            self.db.connection.execute("ALTER TABLE QuiltBackPanelOld RENAME TO QuiltBackPanel")
            self.db.connection.execute("PRAGMA user_version = 11")
        self.db.close()
        with self.assertRaises(UpgradeRequired):
            Database(self.path)
        self.db = Database(self.path, upgrade=True)
        self.assertEqual(
            self.db.get_quilt_back(back_id)["Panels"][0]["InventoryColor"], before,
        )
        self.assertIsNone(self.db.get_quilt_back(empty_back_id)["Panels"][0]["InventoryColor"])
        inventory_color = next(row for row in self.db.connection.execute(
            "PRAGMA table_info(QuiltBackPanel)") if row[1] == "InventoryColor")
        self.assertEqual(inventory_color[3], 0)
        uncolored_id = self.add_piece(Color=None, UsableWidth="100", UsableLength="100")
        uncolored_layout = generate_layouts(
            [self.db.get_piece(uncolored_id)], 30 * INCH, 30 * INCH, 0, INCH,
        )[0]
        uncolored_back_id = self.db.save_back_draft(
            "Uncolored snapshot", 30 * INCH, 30 * INCH, 0, INCH, uncolored_layout,
        )
        self.assertIsNone(self.db.get_quilt_back(uncolored_back_id)["Panels"][0]["InventoryColor"])
        self.assertEqual(self.db.connection.execute("PRAGMA foreign_key_check").fetchall(), [])


if __name__ == "__main__":
    unittest.main()
