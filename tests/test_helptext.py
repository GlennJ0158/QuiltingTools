import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quilting.backs import INCH, generate_layouts
from quilting.database import Database, SCHEMA_VERSION, UpgradeRequired
from quilting.helptext import HELP_FIELDS, default_help
from quilting.model import FieldError
from tests.test_inventory import assert_legacy_rows_preserved, downgrade_color_value_schema, downgrade_dropdown_schema, fabric


class HelpTextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "help.db"
        self.db = Database(self.path)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_generated_help_and_user_edits_survive_reopen_and_backup(self):
        defaults = default_help()
        rows = self.db.help_rows()
        self.assertEqual({(row["TableName"], row["FieldName"]) for row in rows}, set(defaults))
        for key, pair in defaults.items():
            self.assertTrue(all(text.strip() for text in pair), key)
            self.assertEqual(self.db.help_pair(*key), pair)
        row = rows[0]
        values = {field.name: row[field.name] for field in HELP_FIELDS}
        values.update(HoverText="My tooltip", FullText="My detailed help\nSecond paragraph.")
        self.db.save_help(row["ID"], values, row)
        # A missing future object is reseeded, while existing user text remains untouched.
        with self.db.connection:
            self.db.connection.execute("DELETE FROM HelpText WHERE ID = ?", (rows[1]["ID"],))
        self.db.close()
        self.db = Database(self.path)
        self.assertEqual(len(self.db.help_rows()), len(defaults))
        self.assertEqual(self.db.help_pair(row["TableName"], row["FieldName"]),
                         (values["HoverText"], values["FullText"]))
        backup = Path(self.temp.name) / "backup.db"
        self.db.backup(backup)
        copied = Database(backup)
        try:
            self.assertEqual(copied.help_rows(), self.db.help_rows())
        finally:
            copied.close()

    def test_help_validation_immutable_keys_and_conflicts(self):
        row = self.db.help_rows()[0]
        values = {field.name: row[field.name] for field in HELP_FIELDS}
        for name, value in (("HoverText", " "), ("FullText", "x" * 16001),
                            ("TableName", "Other"), ("FieldName", "Other")):
            with self.subTest(field=name), self.assertRaises(FieldError):
                self.db.save_help(row["ID"], {**values, name: value}, row)
        self.db.save_help(row["ID"], {**values, "FullText": "Changed elsewhere"}, row)
        with self.assertRaises(FieldError) as conflict:
            self.db.save_help(row["ID"], {**values, "HoverText": "Stale edit"}, row)
        self.assertEqual(conflict.exception.key, "Conflict")
        self.assertEqual(self.db.help_pair(row["TableName"], row["FieldName"])[1], "Changed elsewhere")
        self.assertFalse(self.db.connection.in_transaction)
        with self.assertRaises(FieldError):
            self.db.help_pair("Missing", "Missing")

    def test_new_dialog_help_is_seeded_without_replacing_custom_help(self):
        key = ("Quilt Backs", "Button:Print Plan")
        row = next(row for row in self.db.help_rows()
                   if (row["TableName"], row["FieldName"]) == key)
        values = {field.name: row[field.name] for field in HELP_FIELDS}
        self.db.save_help(row["ID"], {**values, "HoverText": "Custom print help"}, row)
        with self.db.connection:
            self.db.connection.execute(
                "DELETE FROM HelpText WHERE TableName = ? AND FieldName = ?",
                ("QuiltBlock", "Button:Create"))
        self.db.close()
        self.db = Database(self.path)
        self.assertEqual(self.db.help_pair(*key)[0], "Custom print help")
        self.assertEqual(self.db.help_pair("QuiltBlock", "Button:Create"),
                         default_help()["QuiltBlock", "Button:Create"])

    def test_filter_help_updates_old_default_but_preserves_custom_text(self):
        hover, full = default_help()["Filter", "ScreenHelp"]
        previous = ("Text filters match text anywhere in the field, ignoring case. Minimum dimensions are "
                    "inclusive inches and respect the rectangle's recorded orientation. Blank means no "
                    "restriction. Apply validates and applies the criteria; Cancel leaves the list unchanged.")
        with self.db.connection:
            self.db.connection.execute(
                "UPDATE HelpText SET FullText=? WHERE TableName='Filter' AND FieldName='ScreenHelp'",
                (previous,))
        self.db.close()
        self.db = Database(self.path)
        self.assertEqual(self.db.help_pair("Filter", "ScreenHelp"), (hover, full))
        with self.db.connection:
            self.db.connection.execute(
                "UPDATE HelpText SET FullText='Custom filter help' WHERE TableName='Filter' AND FieldName='ScreenHelp'")
        self.db.close()
        self.db = Database(self.path)
        self.assertEqual(self.db.help_pair("Filter", "ScreenHelp"), (hover, "Custom filter help"))
        for field in ("AfterDateModified", "BeforeDateModified"):
            self.assertIn("00:01 local time", self.db.help_pair("Filter", field)[1])

    def test_help_sort_is_validated_and_persists_independently(self):
        self.db.save_sort((("UsableWidth", "desc"),))
        self.db.save_sort((("HoverText", "desc"),), "HelpTextSort")
        with self.assertRaises(FieldError):
            self.db.save_sort((("UsableWidth", "asc"),), "HelpTextSort")
        self.db.close()
        self.db = Database(self.path)
        self.assertEqual(self.db.load_sort(), (("UsableWidth", "desc"), ("ID", "asc")))
        self.assertEqual(self.db.load_sort("HelpTextSort"), (("HoverText", "desc"), ("ID", "asc")))
        texts = [row["HoverText"].lower() for row in self.db.help_rows()]
        self.assertEqual(texts, sorted(texts, reverse=True))
        with self.db.connection:
            self.db.connection.execute(
                "UPDATE ScreenState SET StateValues = 'not json' WHERE ScreenName = 'HelpTextSort'")
        with self.assertRaises(FieldError):
            self.db.load_sort("HelpTextSort")

    def test_additional_working_lists_filter_sort_and_scope_saved_sets(self):
        self.db.add_dropdown_item("Color", "Blue")
        self.db.add_dropdown_item("Color", "Sage")
        self.db.add_dropdown_item("FabricPattern", "Blue")
        dropdown_ids = {row["ListItem"]: row["ID"] for row in self.db.dropdown_rows("Color")}
        sage = dropdown_ids["Sage"]
        dropdown_filter = {"ListItem": "a", "Default": ""}
        self.assertEqual([row["ListItem"] for row in self.db.dropdown_rows(
            "Color", dropdown_filter)], ["Sage"])
        self.db.save_sort((("ListItem", "desc"),), "DropDownSort")
        self.assertEqual(self.db.load_sort("DropDownSort"), (("ListItem", "desc"), ("ID", "asc")))
        color_set = self.db.save_set("Only Sage", [sage], "DropDown", "Color")
        self.assertEqual(self.db.set_members(color_set, "DropDown", "Color"), [sage])
        self.assertEqual(self.db.sets("DropDown", "FabricPattern"), [])
        with self.assertRaises(FieldError):
            self.db.set_members(color_set, "DropDown", "FabricPattern")

        help_rows = self.db.help_rows({"TableName": "History", "FieldName": "", "HoverText": "", "FullText": ""})
        self.assertTrue(help_rows)
        help_set = self.db.save_set("History help", [help_rows[0]["ID"]], "HelpText")
        self.assertEqual(self.db.set_members(help_set, "HelpText"), [help_rows[0]["ID"]])
        self.db.save_sort((("TableName", "desc"), ("ID", "asc")), "HelpTextSort")
        table_names = [row["TableName"] for row in self.db.help_rows()]
        self.assertEqual(table_names[0], sorted(table_names, key=str.casefold, reverse=True)[0])

        piece_id = self.db.save_piece(fabric())
        self.db.save_piece(fabric(Notes="Changed"), piece_id, 1)
        history_filter = {"Action": "Updated", "DateCreated": "", "Values": "Changed"}
        history = self.db.history(piece_id, history_filter)
        self.assertEqual(len(history), 1)
        history_set = self.db.save_set("Update", [history[0]["ID"]], "History", piece_id)
        other_piece = self.db.save_piece(fabric(FabricName="Second"))
        self.assertEqual(self.db.sets("History", other_piece), [])
        self.assertEqual(self.db.set_members(history_set, "History", piece_id), [history[0]["ID"]])
        self.assertEqual(dropdown_ids["Blue"], self.db.dropdown_rows("Color")[1]["ID"])

    def test_version_four_upgrade_adds_working_list_tables_without_losing_data(self):
        piece_id = self.db.save_piece(fabric())
        history_id = self.db.history(piece_id)[0]["ID"]
        message_id = self.db.save_error({
            "ErrorText": "Existing error",
            "LikelyCause": "Existing cause",
            "Description": "Existing fix",
        })
        self.db.save_set("Existing errors", [message_id], "ErrorMessage")
        with self.db.connection:
            for table in ("QuiltPartFabric", "QuiltPlan", "QuiltColorMap", "QuiltBlockUse", "Quilt",
                          "BlockSetMember", "BlockSet", "BlockPartPlacement", "BlockPart", "QuiltBlock"):
                self.db.connection.execute(f"DROP TABLE {table}")
            for table in ("QuiltBackCutSource", "QuiltBackPanel", "QuiltBack"):
                self.db.connection.execute(f"DROP TABLE {table}")
            self.db.connection.execute("DROP TABLE WorkingListMember")
            self.db.connection.execute("DROP TABLE WorkingListSet")
            downgrade_dropdown_schema(self.db.connection)
            self.db.connection.execute("ALTER TABLE FabricPiece RENAME COLUMN FabricPattern TO PatternName")
            downgrade_color_value_schema(self.db.connection)
            self.db.connection.execute("PRAGMA user_version = 4")
        self.db.close()
        with self.assertRaises(UpgradeRequired):
            Database(self.path)
        self.db = Database(self.path, upgrade=True)
        self.assertEqual(self.db.connection.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
        self.assertEqual(self.db.history(piece_id)[0]["ID"], history_id)
        self.assertEqual(self.db.get_error(message_id)["ErrorText"], "Existing error")
        self.assertEqual(self.db.sets("ErrorMessage")[0]["SetName"], "Existing errors")
        self.assertEqual(self.db.sets("History", piece_id), [])
        with sqlite3.connect(self.db.upgrade_backup) as backup:
            self.assertEqual(backup.execute("PRAGMA user_version").fetchone()[0], 4)

    def test_version_five_upgrade_scopes_dropdown_keys_and_preserves_sets(self):
        color = self.db.add_dropdown_item("Color", "Blue")
        color_id = next(row["ID"] for row in self.db.dropdown_rows("Color")
                        if row["ListItem"] == color)
        set_id = self.db.save_set("Blue colors", [color_id], "DropDown", "Color")
        with self.db.connection:
            dynamic_set_id = self.db.connection.execute(
                "INSERT INTO WorkingListSet (ScreenName, ScopeName, SetName, DateCreated) "
                "VALUES ('DropDown', 'InventoryColor', 'Legacy dynamic colors', '2000-01-01')",
            ).lastrowid
            for table in ("QuiltPartFabric", "QuiltPlan", "QuiltColorMap", "QuiltBlockUse", "Quilt",
                          "BlockSetMember", "BlockSet", "BlockPartPlacement", "BlockPart", "QuiltBlock"):
                self.db.connection.execute(f"DROP TABLE {table}")
            self.db.connection.execute("DROP INDEX IF EXISTS DropdownDefaultIndex")
            self.db.connection.execute("ALTER TABLE Dropdown RENAME TO DropdownCurrent")
            self.db.connection.execute("""
                CREATE TABLE Dropdown (
                    ID INTEGER PRIMARY KEY AUTOINCREMENT,
                    TableName TEXT NOT NULL CHECK(TableName = 'FabricPiece'),
                    FieldName TEXT NOT NULL,
                    ListItem TEXT NOT NULL COLLATE NOCASE CHECK(length(ListItem) <= 120),
                    Def INTEGER NOT NULL DEFAULT 0 CHECK(Def IN (0, 1)),
                    Use INTEGER NOT NULL DEFAULT 1 CHECK(Use IN (0, 1)),
                    UNIQUE(TableName, FieldName, ListItem)
                )
            """)
            self.db.connection.execute(
                "INSERT INTO Dropdown (ID, TableName, FieldName, ListItem, Def, Use) "
                "SELECT ID, TableName, FieldName, ListItem, Def, Use FROM DropdownCurrent "
                "WHERE TableName = 'FabricPiece'")
            self.db.connection.execute("DROP TABLE DropdownCurrent")
            self.db.connection.execute(
                "CREATE UNIQUE INDEX DropdownDefaultIndex ON Dropdown(TableName, FieldName) "
                "WHERE Def = 1 AND Use = 1")
            self.db.connection.execute(
                "UPDATE WorkingListSet SET ScopeName = 'Color' WHERE ID = ?", (set_id,))
            for table in ("QuiltBackCutSource", "QuiltBackPanel", "QuiltBack"):
                self.db.connection.execute(f"DROP TABLE {table}")
            self.db.connection.execute("ALTER TABLE FabricPiece RENAME COLUMN FabricPattern TO PatternName")
            downgrade_color_value_schema(self.db.connection)
            self.db.connection.execute("PRAGMA user_version = 5")
        self.db.close()
        self.db = Database(self.path, upgrade=True)
        self.assertEqual(self.db.dropdown_rows("Color")[0]["ID"], color_id)
        self.assertEqual(self.db.set_members(
            set_id, "DropDown", ("FabricPiece", "Color")), [color_id])
        self.assertEqual(self.db.connection.execute(
            "SELECT ScopeName FROM WorkingListSet WHERE ID = ?", (dynamic_set_id,),
        ).fetchone()[0], "InventoryColor")
        with self.assertRaises(FieldError):
            self.db.add_dropdown_choice("HelpText", "Update", "Apply help changes")

    def test_version_seven_upgrade_preserves_back_and_dropdown_sets(self):
        source_id = self.db.save_piece(fabric(UsableWidth="100", UsableLength="100"))
        layout = generate_layouts([self.db.get_piece(source_id)], 30 * INCH, 30 * INCH, 0, INCH)[0]
        back_id = self.db.save_back_draft("Legacy back", 30 * INCH, 30 * INCH, 0, INCH, layout)
        back_set = self.db.save_set("Backs", [back_id], "Quilt Backs")
        self.db.add_dropdown_item("Color", "Blue")
        color_id = next(row["ID"] for row in self.db.dropdown_rows("Color") if row["ListItem"] == "Blue")
        color_set = self.db.save_set("Colors", [color_id], "DropDown", "Color")
        with self.db.connection:
            for table in ("QuiltPartFabric", "QuiltPlan", "QuiltColorMap", "QuiltBlockUse", "Quilt",
                          "BlockSetMember", "BlockSet", "BlockPartPlacement", "BlockPart", "QuiltBlock"):
                self.db.connection.execute(f"DROP TABLE {table}")
            self.db.connection.execute(
                "UPDATE WorkingListSet SET ScopeName = 'Color' WHERE ID = ?", (color_set,))
            self.db.connection.execute("DROP INDEX IF EXISTS DropdownDefaultIndex")
            self.db.connection.execute("ALTER TABLE Dropdown RENAME TO DropdownCurrent")
            self.db.connection.execute("""
                CREATE TABLE Dropdown (
                    ID INTEGER PRIMARY KEY AUTOINCREMENT,
                    TableName TEXT NOT NULL CHECK(TableName = 'FabricPiece'),
                    FieldName TEXT NOT NULL,
                    ListItem TEXT NOT NULL COLLATE NOCASE CHECK(length(ListItem) <= 120),
                    Def INTEGER NOT NULL DEFAULT 0 CHECK(Def IN (0, 1)),
                    Use INTEGER NOT NULL DEFAULT 1 CHECK(Use IN (0, 1)),
                    UNIQUE(TableName, FieldName, ListItem)
                )
            """)
            self.db.connection.execute(
                "INSERT INTO Dropdown (ID, TableName, FieldName, ListItem, Def, Use) "
                "SELECT ID, TableName, FieldName, ListItem, Def, Use FROM DropdownCurrent "
                "WHERE TableName = 'FabricPiece'")
            self.db.connection.execute("DROP TABLE DropdownCurrent")
            self.db.connection.execute(
                "CREATE UNIQUE INDEX DropdownDefaultIndex ON Dropdown(TableName, FieldName) "
                "WHERE Def = 1 AND Use = 1")
            self.db.connection.execute("ALTER TABLE QuiltBack DROP COLUMN SideMargin")
            self.db.connection.execute("ALTER TABLE FabricPiece RENAME COLUMN FabricPattern TO PatternName")
            downgrade_color_value_schema(self.db.connection)
            self.db.connection.execute("PRAGMA user_version = 7")
        self.db.close()
        with self.assertRaises(UpgradeRequired):
            Database(self.path)
        self.db = Database(self.path, upgrade=True)
        self.assertEqual(self.db.set_members(color_set, "DropDown", ("FabricPiece", "Color")), [color_id])
        self.assertEqual(self.db.set_members(back_set, "Quilt Backs"), [back_id])
        self.assertEqual(self.db.get_quilt_back(back_id)["BackName"], "Legacy back")
        self.assertEqual(self.db.connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        with sqlite3.connect(self.db.upgrade_backup) as backup:
            self.assertEqual(backup.execute("PRAGMA user_version").fetchone()[0], 7)
            self.assertEqual(
                backup.execute("SELECT ScopeName FROM WorkingListSet WHERE ID = ?", (color_set,)).fetchone()[0],
                "Color",
            )

    def make_version_two(self):
        self.db.save_piece(fabric(Color="Sage"))
        with self.db.connection:
            for table in ("QuiltPartFabric", "QuiltPlan", "QuiltColorMap", "QuiltBlockUse", "Quilt",
                          "BlockSetMember", "BlockSet", "BlockPartPlacement", "BlockPart", "QuiltBlock"):
                self.db.connection.execute(f"DROP TABLE {table}")
            for table in ("QuiltBackCutSource", "QuiltBackPanel", "QuiltBack"):
                self.db.connection.execute(f"DROP TABLE {table}")
            for table in ("WorkingListMember", "WorkingListSet",
                          "ErrorMessageMember", "ErrorMessageSet", "ErrorMessage"):
                self.db.connection.execute(f"DROP TABLE {table}")
            self.db.connection.execute("DROP TABLE HelpText")
            downgrade_dropdown_schema(self.db.connection)
            self.db.connection.execute("ALTER TABLE FabricPiece RENAME COLUMN FabricPattern TO PatternName")
            downgrade_color_value_schema(self.db.connection)
            self.db.connection.execute("PRAGMA user_version = 2")
        tables = ("FabricPiece", "FabricHistory", "Dropdown", "ErrorText")
        before = {name: [tuple(row) for row in self.db.connection.execute(f"SELECT * FROM {name}")]
                  for name in tables}
        self.db.close()
        return before

    def test_version_two_upgrade_requires_consent_and_preserves_existing_tables(self):
        before = self.make_version_two()
        original = self.path.read_bytes()
        with self.assertRaises(UpgradeRequired):
            Database(self.path)
        self.assertEqual(self.path.read_bytes(), original)
        self.db = Database(self.path, upgrade=True)
        for name, rows in before.items():
            assert_legacy_rows_preserved(self, self.db, name, rows)
        self.assertEqual(self.db.connection.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
        self.assertEqual(len(self.db.help_rows()), len(default_help()))
        with sqlite3.connect(self.db.upgrade_backup) as backup:
            self.assertEqual(backup.execute("PRAGMA user_version").fetchone()[0], 2)
            Database.validate(backup, allow_legacy=True)

    def test_failed_help_upgrade_rolls_back_and_keeps_verified_backup(self):
        before = self.make_version_two()
        with patch.object(Database, "_seed_help", side_effect=sqlite3.IntegrityError("seed failed")):
            with self.assertRaises(sqlite3.IntegrityError):
                Database(self.path, upgrade=True)
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 2)
            self.assertIsNone(connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'HelpText'").fetchone())
            self.assertEqual(connection.execute("SELECT * FROM ErrorText").fetchall(), before["ErrorText"])
        self.assertEqual(len(list(self.path.parent.glob("PreUpgrade_*"))), 1)
        self.db = Database(self.path, upgrade=True)
