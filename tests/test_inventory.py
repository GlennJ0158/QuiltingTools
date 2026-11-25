import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quilting.database import ALL_DROPDOWN_SCOPE, Database, UpgradeRequired
from quilting.model import (
    ADD_ITEM, FABRIC_FIELDS, FILTER_FIELDS, FieldError, caption, display_measurement,
    measurement, normalize_sort, validate_fields,
)


def fabric(**overrides):
    values = {field.name: field.default for field in FABRIC_FIELDS}
    values.update(FabricName="Blue cotton", UsableWidth="42 1/2", UsableLength="72")
    values.update(overrides)
    return values


def downgrade_dropdown_schema(connection, generalized=False):
    connection.execute("DROP INDEX IF EXISTS DropdownDefaultIndex")
    connection.execute("ALTER TABLE Dropdown RENAME TO DropdownCurrent")
    table_check = "" if generalized else " CHECK(TableName = 'FabricPiece')"
    connection.execute(f"""
        CREATE TABLE Dropdown (
            ID INTEGER PRIMARY KEY AUTOINCREMENT,
            TableName TEXT NOT NULL{table_check},
            FieldName TEXT NOT NULL,
            ListItem TEXT NOT NULL COLLATE NOCASE,
            Def INTEGER NOT NULL DEFAULT 0 CHECK(Def IN (0, 1)),
            Use INTEGER NOT NULL DEFAULT 1 CHECK(Use IN (0, 1)),
            UNIQUE(TableName, FieldName, ListItem)
        )
    """)
    connection.execute(
        "INSERT INTO Dropdown (ID, TableName, FieldName, ListItem, Def, Use) "
        "SELECT ID, TableName, FieldName, ListItem, Def, Use FROM DropdownCurrent "
        + ("" if generalized else "WHERE TableName = 'FabricPiece'")
    )
    connection.execute("DROP TABLE DropdownCurrent")


def assert_legacy_rows_preserved(test_case, database, table, rows):
    actual = [tuple(row) for row in database.connection.execute(f"SELECT * FROM {table}")]
    if table == "Dropdown":
        by_id = {row[0]: row for row in actual}
        for row in rows:
            test_case.assertEqual(by_id[row[0]][:len(row)], row)
        test_case.assertTrue(any(row["UserModified"] == 0
                                 for row in database.dropdown_rows("Status", table_name="FabricPiece")))
    else:
        test_case.assertEqual(actual, rows, table)


class MeasurementTests(unittest.TestCase):
    def test_exact_fraction_and_decimal_round_trips(self):
        for value in ("42", "42 1/2", "1/64", "42.125", "0.000001", "0.123456", "10800"):
            with self.subTest(value=value):
                stored = measurement(value, "UsableWidth")
                self.assertEqual(measurement(display_measurement(stored), "UsableWidth"), stored)
        self.assertEqual(measurement("42 1/2", "Width"), 42_500_000)
        self.assertEqual(measurement("1/64", "Width"), 15_625)

    def test_invalid_measurements(self):
        for value in ("", "0", "-1", "nan", "inf", "1e2", "1/0", "1/3", "2/2",
                      "1 -1/2", "42 in", "1.1234567", "10800.000001", "10801", "9" * 1000):
            with self.subTest(value=value), self.assertRaises(FieldError):
                measurement(value, "UsableLength")

    def test_every_field_is_validated(self):
        for field in FABRIC_FIELDS:
            if field.kind == "length":
                invalid = "-1"
            elif field.kind == "choice":
                invalid = "not a choice"
            else:
                invalid = "x" * (field.limit + 1)
            with self.subTest(field=field.name), self.assertRaises(FieldError) as raised:
                validate_fields(FABRIC_FIELDS, fabric(**{field.name: invalid}))
            self.assertEqual(raised.exception.field, field.name)
        for field in (field for field in FABRIC_FIELDS if field.required):
            with self.subTest(required=field.name), self.assertRaises(FieldError):
                validate_fields(FABRIC_FIELDS, fabric(**{field.name: " "}))

    def test_missing_and_unknown_assignments_are_rejected(self):
        for field in FABRIC_FIELDS:
            values = fabric()
            del values[field.name]
            with self.subTest(field=field.name), self.assertRaises(FieldError) as raised:
                validate_fields(FABRIC_FIELDS, values)
            self.assertEqual(raised.exception.key, "Binding")
        with self.assertRaises(FieldError):
            validate_fields(FABRIC_FIELDS, fabric(UnusedField="accidental"))

    def test_captions_and_sort_validation(self):
        self.assertEqual(caption("FabricPieceID"), "Fabric Piece ID")
        self.assertEqual(normalize_sort([("UsableWidth", "desc")]),
                         (("UsableWidth", "desc"), ("ID", "asc")))
        for order in ([], [("ID", "asc"), ("ID", "desc")],
                      [("Notes; DROP TABLE FabricPiece", "asc")], [("ID", "sideways")], ["ID"]):
            with self.subTest(order=order), self.assertRaises(FieldError):
                normalize_sort(order)


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "inventory.db"
        self.db = Database(self.path)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_all_fields_survive_update_and_reopen(self):
        values = fabric(
            FabricName="Red's cotton", Color="Red", FabricPattern="Tiny flowers",
            UsableWidth="41 1/64", UsableLength="0.123456", GrainDirection="Along Width",
            PrintDirection="Along Length", StorageLocation="Bin 3", Status="Retired",
            Notes="Washed; exclude selvage.",
        )
        piece_id = self.db.save_piece(values)
        self.db.close()
        self.db = Database(self.path)
        row = self.db.get_piece(piece_id)
        for key, value in validate_fields(FABRIC_FIELDS, values).items():
            self.assertEqual(row[key], value, key)
        values["UsableLength"] = "12 1/2"
        self.db.save_piece(values, piece_id, row["Revision"])
        changed = self.db.get_piece(piece_id)
        self.assertEqual(changed["Revision"], 2)
        self.assertEqual(changed["DateCreated"], row["DateCreated"])
        history = self.db.history(piece_id)
        self.assertEqual([entry["Action"] for entry in history], ["Updated", "Added"])
        self.assertEqual(json.loads(history[0]["BeforeValues"])["UsableLength"], 123456)
        self.assertEqual(json.loads(history[0]["AfterValues"])["UsableLength"], 12_500_000)

    def test_conflict_and_no_op_preserve_history(self):
        piece_id = self.db.save_piece(fabric())
        self.db.save_piece(fabric(), piece_id, 1)
        self.assertEqual(len(self.db.history(piece_id)), 1)
        other = Database(self.path)
        try:
            other.save_piece(fabric(Color="Green"), piece_id, 1)
            with self.assertRaises(FieldError) as raised:
                self.db.save_piece(fabric(Color="Red"), piece_id, 1)
            self.assertEqual(raised.exception.key, "Conflict")
        finally:
            other.close()
        self.assertEqual(self.db.get_piece(piece_id)["Color"], "Green")

    def test_inventory_and_history_commit_together(self):
        self.db.connection.execute(
            "CREATE TRIGGER FailHistory BEFORE INSERT ON FabricHistory "
            "BEGIN SELECT RAISE(ABORT, 'history write failed'); END"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.save_piece(fabric())
        self.assertEqual(self.db.pieces(), [])
        self.assertEqual(self.db.connection.execute("SELECT count(*) FROM FabricHistory").fetchone()[0], 0)

    def test_filter_numeric_sort_and_empty_highlight_restriction(self):
        ids = [self.db.save_piece(fabric(FabricName=name, UsableWidth=width))
               for name, width in (("100% cotton", "9"), ("Plain", "100"), ("100% cotton", "12"))]
        filters = {field.name: "" for field in FILTER_FIELDS}
        filters.update(FabricName="100%", MinimumWidth="10")
        self.assertEqual([row["ID"] for row in self.db.pieces(filters)], [ids[2]])
        self.assertEqual([row["ID"] for row in self.db.pieces(sort=[("UsableWidth", "asc")])],
                         [ids[0], ids[2], ids[1]])
        self.assertEqual(self.db.pieces(selected_ids=[]), [])
        self.assertEqual([row["ID"] for row in self.db.pieces(selected_ids=[ids[1]])], [ids[1]])

    def test_size_filter_includes_both_endpoints(self):
        sizes = (("9", "20"), ("10", "20"), ("15", "25"),
                 ("20", "30"), ("20", "31"), ("21", "30"))
        ids = [self.db.save_piece(fabric(UsableWidth=width, UsableLength=length))
               for width, length in sizes]
        filters = {field.name: "" for field in FILTER_FIELDS}
        filters.update(MinimumWidth="10", MaximumWidth="20", MinimumLength="20", MaximumLength="30")
        self.assertEqual({row["ID"] for row in self.db.pieces(filters)}, set(ids[1:4]))
        filters.update(MinimumWidth="20", MaximumWidth="10")
        self.assertEqual(self.db.pieces(filters), [])

    def test_selection_snapshot_and_sort_persistence(self):
        first = self.db.save_piece(fabric())
        set_id = self.db.save_set("Project blues", [first, first])
        self.db.save_piece(fabric())
        self.db.save_piece(fabric(Status="Retired"), first, 1)
        self.assertEqual(self.db.set_members(set_id), [first])
        self.assertEqual(self.db.sets()[0]["RecordCount"], 1)
        with self.assertRaises(FieldError) as raised:
            self.db.save_set("PROJECT BLUES", [first])
        self.assertEqual(raised.exception.key, "DuplicateSet")
        with self.assertRaises(FieldError):
            self.db.save_set("Empty", [])
        with self.assertRaises(FieldError):
            self.db.save_set("Missing", [9999])
        self.assertEqual(len(self.db.sets()), 1)
        self.db.save_sort([("UsableLength", "desc")])
        self.db.close()
        self.db = Database(self.path)
        self.assertEqual(self.db.load_sort(), (("UsableLength", "desc"), ("ID", "asc")))
        self.db.delete_set(set_id)
        self.assertEqual(self.db.sets(), [])
        self.assertEqual(len(self.db.pieces()), 2)
        self.assertEqual(self.db.connection.execute("SELECT count(*) FROM SelectionMember").fetchone()[0], 0)

    def test_catalog_errors_include_label_reason_resolution_and_generated_id(self):
        try:
            self.db.save_piece(fabric(UsableWidth="bad"))
        except FieldError as error:
            message = self.db.error_message(error)
        self.assertIn("Usable Width:", message)
        self.assertIn("positive measurement", message)
        self.assertIn("Examples:", message)
        self.assertRegex(message, r"Error ID: \d+")
        before = self.db.connection.execute("SELECT ErrorTextID FROM ErrorText").fetchall()
        self.db.close()
        self.db = Database(self.path)
        self.assertEqual(before, self.db.connection.execute("SELECT ErrorTextID FROM ErrorText").fetchall())

    def test_backup_restore_preserves_history_sets_ids_and_sequences(self):
        piece_id = self.db.save_piece(fabric())
        set_id = self.db.save_set("Keep", [piece_id])
        backup = Path(self.temp.name) / "backup.db"
        restored = Path(self.temp.name) / "restored.db"
        self.db.backup(backup)
        self.db.save_piece(fabric(Color="Changed"), piece_id, 1)
        Database.restore_to_new(backup, restored)
        copy = Database(restored)
        try:
            self.assertIsNone(copy.get_piece(piece_id)["Color"])
            self.assertEqual(copy.set_members(set_id), [piece_id])
            self.assertEqual(len(copy.history(piece_id)), 1)
            self.assertGreater(copy.save_piece(fabric()), piece_id)
        finally:
            copy.close()
        original = backup.read_bytes()
        with self.assertRaises(FileExistsError):
            self.db.backup(backup)
        with self.assertRaises(FileExistsError):
            Database.restore_to_new(backup, self.path)
        self.assertEqual(backup.read_bytes(), original)
        self.assertEqual(self.db.get_piece(piece_id)["Color"], "Changed")
        self.assertEqual(list(Path(self.temp.name).glob(".quilting-backup-*")), [])

    def test_foreign_database_is_rejected_without_modification(self):
        foreign = Path(self.temp.name) / "foreign.db"
        connection = sqlite3.connect(foreign)
        connection.execute("CREATE TABLE Other (ID INTEGER)")
        connection.close()
        original = foreign.read_bytes()
        with self.assertRaises(FieldError):
            Database(foreign)
        with self.assertRaises(FieldError):
            Database.restore_to_new(foreign, Path(self.temp.name) / "invalid.db")
        self.assertEqual(foreign.read_bytes(), original)
        self.assertFalse((Path(self.temp.name) / "invalid.db").exists())

    def test_invalid_saved_state_is_not_silently_reset(self):
        self.db.connection.execute(
            "INSERT INTO ScreenState VALUES ('FabricInventorySort', 'not json')"
        )
        self.db.connection.commit()
        with self.assertRaises(FieldError) as raised:
            self.db.load_sort()
        self.assertEqual(raised.exception.key, "DatabaseFormat")

    def test_dropdown_default_order_canonicalization_and_persistence(self):
        for value in ("Yellow", "blue", "Amber"):
            self.db.add_dropdown_item("Color", value)
        default = next(row for row in self.db.dropdown_rows("Color") if row["ListItem"] == "blue")
        self.db.set_dropdown_default(default["ID"])
        self.assertEqual(self.db.dropdown_choices("Color"), ("blue", ADD_ITEM, "Amber", "Yellow"))
        self.assertEqual(self.db.add_dropdown_item("Color", " BLUE "), "blue")
        piece_id = self.db.save_piece(fabric(Color="BLUE"))
        self.assertEqual(self.db.get_piece(piece_id)["Color"], "blue")
        self.assertEqual(len([row for row in self.db.dropdown_rows("Color")
                              if row["ListItem"].lower() == "blue"]), 1)
        self.db.close()
        self.db = Database(self.path)
        self.assertEqual(self.db.dropdown_default("Color"), "blue")
        self.assertEqual(self.db.dropdown_choices("Color")[1], ADD_ITEM)
        with self.assertRaises(FieldError):
            self.db.add_dropdown_item("Color", ADD_ITEM)
        with self.assertRaises(FieldError):
            self.db.add_dropdown_item("GrainDirection", "Diagonal")
        with self.assertRaises(FieldError):
            self.db.add_dropdown_item("Color", " " * 4)
        with self.assertRaises(FieldError):
            self.db.add_dropdown_item("Notes", "Not a dropdown")

    def test_v13_fabric_pattern_upgrade_preserves_data_and_custom_help(self):
        piece_id = self.db.save_piece(fabric(FabricPattern="Choose Fabric Pattern",
                                             Notes="Literal PatternName must stay unchanged."))
        item = self.db.dropdown_rows("FabricPattern")[0]
        set_id = self.db.save_set("Patterns", [item["ID"]], "DropDown", ("FabricPiece", "FabricPattern"))
        self.db.save_sort((("FabricPattern", "desc"),))
        with self.db.connection:
            self.db.connection.execute(
                "UPDATE Dropdown SET FieldName='PatternName' WHERE FieldName='FabricPattern'")
            self.db.connection.execute(
                "UPDATE WorkingListSet SET ScopeName=? WHERE ID=?",
                (json.dumps(("FabricPiece", "PatternName"), separators=(",", ":")), set_id))
            self.db.connection.execute(
                "UPDATE ScreenState SET StateValues=? WHERE ScreenName='FabricInventorySort'",
                (json.dumps([["PatternName", "desc"], ["ID", "asc"]]),))
            self.db.connection.execute(
                "UPDATE HelpText SET FieldName=replace(FieldName, 'FabricPattern', 'PatternName') "
                "WHERE FieldName IN ('FabricPattern', 'Column:FabricPattern')")
            self.db.connection.execute(
                "UPDATE HelpText SET HoverText='My custom help', FullText='My PatternName notes' "
                "WHERE TableName='Fabric' AND FieldName='PatternName'")
            self.db.connection.execute(
                "UPDATE HelpText SET HoverText='Filter fabric by pattern name.' "
                "WHERE TableName='Filter' AND FieldName='PatternName'")
            self.db.connection.execute(
                "UPDATE HelpText SET FullText=replace(FullText, 'Choose Fabric Pattern', 'Choose PatternName') "
                "WHERE TableName='Fabric' AND FieldName='Column:PatternName'")
            row = self.db.connection.execute(
                "SELECT ID, AfterValues FROM FabricHistory WHERE FabricPieceID=?", (piece_id,)).fetchone()
            snapshot = json.loads(row["AfterValues"])
            snapshot["PatternName"] = snapshot.pop("FabricPattern")
            self.db.connection.execute("UPDATE FabricHistory SET AfterValues=? WHERE ID=?",
                                       (json.dumps(snapshot), row["ID"]))
            self.db.connection.execute("ALTER TABLE FabricPiece RENAME COLUMN FabricPattern TO PatternName")
            self.db.connection.execute("PRAGMA user_version=13")
        self.db.close()
        with self.assertRaises(UpgradeRequired):
            Database(self.path)
        self.db = Database(self.path, upgrade=True)
        self.assertEqual(self.db.get_piece(piece_id)["FabricPattern"], "Choose Fabric Pattern")
        self.assertEqual(self.db.dropdown_placeholder("FabricPattern"), "Choose Fabric Pattern (2)")
        self.assertIn("Choose Fabric Pattern", self.db.dropdown_choices("FabricPattern"))
        self.assertEqual(self.db.set_members(set_id, "DropDown", ("FabricPiece", "FabricPattern")), [item["ID"]])
        self.assertEqual(self.db.load_sort(), (("FabricPattern", "desc"), ("ID", "asc")))
        history = json.loads(self.db.history(piece_id)[0]["AfterValues"])
        self.assertEqual(history["FabricPattern"], "Choose Fabric Pattern")
        self.assertEqual(history["Notes"], "Literal PatternName must stay unchanged.")
        self.assertNotIn("PatternName", history)
        self.assertEqual(self.db.help_pair("Fabric", "FabricPattern"), ("My custom help", "My PatternName notes"))
        self.assertIn("fabric pattern", self.db.help_pair("Filter", "FabricPattern")[0])
        self.assertIn("Choose Fabric Pattern", self.db.help_pair("Fabric", "Column:FabricPattern")[1])
        with sqlite3.connect(self.db.upgrade_backup) as backup:
            self.assertEqual(backup.execute("PRAGMA user_version").fetchone()[0], 13)
            self.assertEqual(backup.execute("SELECT PatternName FROM FabricPiece").fetchone()[0],
                             "Choose Fabric Pattern")

    def test_v13_fabric_pattern_upgrade_rolls_back_invalid_snapshot(self):
        piece_id = self.db.save_piece(fabric(FabricPattern="Floral"))
        with self.db.connection:
            self.db.connection.execute("UPDATE FabricHistory SET AfterValues='not json' WHERE FabricPieceID=?",
                                       (piece_id,))
            self.db.connection.execute("ALTER TABLE FabricPiece RENAME COLUMN FabricPattern TO PatternName")
            self.db.connection.execute("PRAGMA user_version=13")
        self.db.close()
        with self.assertRaises(FieldError):
            Database(self.path, upgrade=True)
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 13)
            self.assertEqual(connection.execute("SELECT PatternName FROM FabricPiece").fetchone()[0], "Floral")
    def test_all_dropdown_rows_sort_filter_and_selection_cleanup(self):
        blue, _ = self.db.save_dropdown("FabricPiece", "Color", "Blue", 1, 1)
        amber, _ = self.db.save_dropdown("FabricPiece", "FabricPattern", "Amber", 0, 0)
        self.db.save_sort((("ListItem", "desc"),), "DropDownSort")
        rows = self.db.dropdown_rows("", table_name=ALL_DROPDOWN_SCOPE[0], include_inactive=True)
        raw = [dict(row) for row in self.db.connection.execute("SELECT * FROM Dropdown")]
        expected = sorted(raw, key=lambda row: (
            row["TableName"].lower(), -row["Def"], row["FieldName"].lower(),
            row["ListItem"].lower(), row["ID"],
        ))
        self.assertEqual(rows, expected)
        self.assertIn(amber, [row["ID"] for row in rows])
        self.assertEqual(
            [row["ID"] for row in self.db.dropdown_rows(
                "", {"ListItem": "am", "Default": ""}, [amber],
                table_name=ALL_DROPDOWN_SCOPE[0], include_inactive=True)],
            [amber],
        )
        all_set = self.db.save_set("All", [blue, amber], "DropDown", ALL_DROPDOWN_SCOPE)
        field_set = self.db.save_set("Pattern", [amber], "DropDown", ("FabricPiece", "FabricPattern"))
        self.db.delete_dropdown(amber, self.db.get_dropdown(amber))
        self.assertEqual(self.db.set_members(all_set, "DropDown", ALL_DROPDOWN_SCOPE), [blue])
        self.assertEqual(self.db.set_members(field_set, "DropDown", ("FabricPiece", "FabricPattern")), [])
        self.db.save_sort((("ID", "desc"),), "DropDownAllSort")
        self.db.close()
        self.db = Database(self.path)
        self.assertEqual(self.db.load_sort("DropDownAllSort"), (("ID", "desc"),))
        self.assertEqual(self.db.load_sort("DropDownSort"), (("ListItem", "desc"), ("ID", "asc")))
        with self.assertRaises(FieldError):
            self.db.dropdown_rows("Color", table_name=ALL_DROPDOWN_SCOPE[0])

    def test_optional_dropdown_fields_store_null_and_required_name_rejects_placeholder(self):
        piece_id = self.db.save_piece(fabric(Color="", FabricPattern=None, StorageLocation=""))
        row = self.db.get_piece(piece_id)
        self.assertIsNone(row["Color"])
        self.assertIsNone(row["FabricPattern"])
        self.assertIsNone(row["StorageLocation"])
        with self.assertRaises(FieldError):
            self.db.save_piece(fabric(FabricName=""))
        self.assertEqual(self.db.dropdown_choices("Color"), (ADD_ITEM,))
        self.assertIsNone(self.db.dropdown_default("Color"))

    def test_protected_list_allows_only_default_changes_and_runtime_help_keeps_policy(self):
        available = next(row for row in self.db.dropdown_rows(
            "Status", table_name="FabricPiece") if row["ListItem"] == "Available")
        retired = next(row for row in self.db.dropdown_rows(
            "Status", table_name="FabricPiece") if row["ListItem"] == "Retired")
        self.assertEqual((available["UserModified"], retired["UserModified"]), (0, 0))
        with self.assertRaises(FieldError):
            self.db.add_dropdown_choice("FabricPiece", "Status", "Paused")
        with self.assertRaises(FieldError):
            self.db.save_dropdown("FabricPiece", "Status", "Renamed", None, None,
                                  available["ID"], available)
        with self.assertRaises(FieldError):
            self.db.save_dropdown("FabricPiece", "Status", "Available", None, 0,
                                  available["ID"], available)
        with self.assertRaises(FieldError):
            self.db.delete_dropdown(available["ID"], available)
        _, warning = self.db.save_dropdown(
            "FabricPiece", "Status", "Retired", 1, None, retired["ID"], retired,
        )
        self.assertTrue(warning)
        self.assertEqual(self.db.dropdown_default("Status"), "Available")
        protected_help = self.db.help_pair("Fabric", "Status")[1]
        self.assertIn(
            "This is a system-generated protected list. The values are used in internal program logic "
            "and changing values can interfere with program operation. The user may change the default "
            "value using the DropDown system.",
            protected_help,
        )
        dynamic_help = self.db.help_pair("Quilt", "InventoryColor")[1]
        self.assertIn(
            "This is a dynamic list whose values come directly from the data. "
            "This list does not use the DropDown system for setting or updating values.",
            dynamic_help,
        )
        with self.assertRaises(FieldError):
            self.db.dropdown_rows("InventoryColor", table_name="Quilt")

    def test_add_item_replaces_defaults_atomically_and_only_in_its_list(self):
        blue, _ = self.db.save_dropdown("FabricPiece", "Color", "Blue", 1, 1)
        name_default = self.db.dropdown_default("FabricName")
        self.assertEqual(self.db.add_dropdown_item("Color", "Sage", True, True), "Sage")
        rows = self.db.dropdown_rows("Color", include_inactive=True)
        self.assertEqual([row["ListItem"] for row in rows if row["Def"]], ["Sage"])
        self.assertEqual(self.db.get_dropdown(blue)["Use"], 1)
        self.assertEqual(self.db.dropdown_default("FabricName"), name_default)
        with self.db.connection:
            self.db.connection.execute(
                "CREATE TRIGGER reject_default BEFORE UPDATE OF Def ON Dropdown "
                "WHEN NEW.ListItem = 'Red' AND NEW.Def = 1 "
                "BEGIN SELECT RAISE(ABORT, 'rejected'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.add_dropdown_item("Color", "Red", True, True)
        self.assertEqual(self.db.dropdown_default("Color"), "Sage")
        self.assertNotIn("Red", [row["ListItem"] for row in self.db.dropdown_rows("Color")])
        with self.db.connection:
            self.db.connection.execute(
                "CREATE TRIGGER reject_insert BEFORE INSERT ON Dropdown "
                "WHEN NEW.ListItem = 'Red' AND NEW.Def = 1 "
                "BEGIN SELECT RAISE(ABORT, 'rejected'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.save_dropdown("FabricPiece", "Color", "Red", 1, 1, clear_other_defaults=True)
        self.assertEqual(self.db.dropdown_default("Color"), "Sage")

    def test_dropdown_flags_defaults_and_selection_cleanup(self):
        self.assertEqual(self.db.add_dropdown_choice("FabricPiece", "Color", "Sage"), "Sage")
        sage = next(row for row in self.db.dropdown_rows("Color") if row["ListItem"] == "Sage")
        self.db.delete_dropdown(sage["ID"], sage)
        amber, warning = self.db.save_dropdown("FabricPiece", "Color", "Amber", 0, 1)
        self.assertFalse(warning)
        blue, warning = self.db.save_dropdown("FabricPiece", "Color", "Blue", 1, 1)
        self.assertFalse(warning)
        amber_row = self.db.get_dropdown(amber)
        _, warning = self.db.save_dropdown("FabricPiece", "Color", "Amber", 1, None, amber, amber_row)
        self.assertTrue(warning)
        self.db.save_sort((("ListItem", "desc"),), "DropDownSort")
        self.assertEqual(self.db.dropdown_default("Color"), "Amber")
        self.assertEqual(self.db.dropdown_choices("Color"), ("Amber", ADD_ITEM, "Blue"))
        row = self.db.get_dropdown(amber)
        self.db.save_dropdown("FabricPiece", "Color", "", None, 0, amber, row)
        self.assertEqual(self.db.dropdown_default("Color"), "Blue")
        self.assertNotIn("Amber", self.db.dropdown_choices("Color"))
        self.assertIn(amber, [r["ID"] for r in self.db.dropdown_rows("Color", include_inactive=True)])
        self.db.save_piece(fabric(Color="Amber"))
        self.assertEqual(self.db.get_dropdown(amber)["Use"], 0)
        row = self.db.get_dropdown(blue)
        self.db.save_dropdown("FabricPiece", "Color", "Blue", 0, None, blue, row)
        self.assertIsNone(self.db.dropdown_default("Color"))
        self.assertEqual(self.db.dropdown_choices("Color"), (ADD_ITEM, "Blue"))
        set_id = self.db.save_set("Inactive", [amber], "DropDown", "Color")
        with self.assertRaises(FieldError):
            self.db.delete_dropdown(amber, amber_row)
        self.db.delete_dropdown(amber, self.db.get_dropdown(amber))
        self.assertEqual(self.db.set_members(set_id, "DropDown", "Color"), [])
        with self.assertRaises(FieldError):
            self.db.save_dropdown("FabricPiece", "Color", "New", None, 1)
        with self.assertRaises(FieldError):
            self.db.save_dropdown("FabricPiece", "Color", "Blue", 0, 1)
        self.db.delete_dropdown(blue, self.db.get_dropdown(blue))
        self.assertEqual(self.db.dropdown_choices("Color"), (ADD_ITEM,))

    def test_version_nine_upgrade_removes_default_index_and_preserves_rows(self):
        self.db.add_dropdown_item("Color", "Blue")
        before = self.db.dropdown_rows("Color", include_inactive=True)
        with self.db.connection:
            self.db.connection.execute(
                "CREATE UNIQUE INDEX DropdownDefaultIndex ON Dropdown(TableName, FieldName) "
                "WHERE Def = 1 AND Use = 1")
            self.db.connection.execute("ALTER TABLE Dropdown RENAME TO DropdownCurrent")
            self.db.connection.execute("""
                CREATE TABLE Dropdown (
                    ID INTEGER PRIMARY KEY AUTOINCREMENT,
                    TableName TEXT NOT NULL,
                    FieldName TEXT NOT NULL,
                    ListItem TEXT NOT NULL COLLATE NOCASE,
                    Def INTEGER NOT NULL DEFAULT 0,
                    Use INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(TableName, FieldName, ListItem)
                )
            """)
            self.db.connection.execute(
                "INSERT INTO Dropdown (ID, TableName, FieldName, ListItem, Def, Use) "
                "SELECT ID, TableName, FieldName, ListItem, Def, Use FROM DropdownCurrent")
            self.db.connection.execute("DROP TABLE DropdownCurrent")
            self.db.connection.execute("CREATE UNIQUE INDEX DropdownDefaultIndex "
                                       "ON Dropdown(TableName, FieldName) WHERE Def = 1 AND Use = 1")
            self.db.connection.execute("ALTER TABLE QuiltBack DROP COLUMN SideMargin")
            self.db.connection.execute("ALTER TABLE FabricPiece RENAME COLUMN FabricPattern TO PatternName")
            self.db.connection.execute("PRAGMA user_version = 9")
        self.db.close()
        with self.assertRaises(UpgradeRequired):
            Database(self.path)
        self.db = Database(self.path, upgrade=True)
        self.assertEqual(self.db.dropdown_rows("Color", include_inactive=True), before)
        self.assertTrue(self.db.upgrade_backup.exists())
        blue = next(row for row in before if row["ListItem"] == "Blue")
        _, warning = self.db.save_dropdown("FabricPiece", "Color", "Blue", 1, None, blue["ID"], blue)
        self.assertFalse(warning)
        _, warning = self.db.save_dropdown("FabricPiece", "Color", "Red", 1, 1)
        self.assertTrue(warning)

    def make_legacy_database(self):
        piece_id = self.db.save_piece(fabric(Color="Sage", StorageLocation="Bin C"))
        self.db.save_set("Keep these", [piece_id])
        self.db.save_sort([("UsableWidth", "desc")])
        with self.db.connection:
            for table in ("QuiltPlan", "QuiltColorMap", "QuiltBlockUse", "Quilt",
                          "BlockSetMember", "BlockSet", "BlockPartPlacement", "BlockPart", "QuiltBlock"):
                self.db.connection.execute(f"DROP TABLE {table}")
            for table in ("QuiltBackCutSource", "QuiltBackPanel", "QuiltBack"):
                self.db.connection.execute(f"DROP TABLE {table}")
            for table in ("WorkingListMember", "WorkingListSet",
                          "ErrorMessageMember", "ErrorMessageSet", "ErrorMessage"):
                self.db.connection.execute(f"DROP TABLE {table}")
            self.db.connection.execute("DROP TABLE Dropdown")
            self.db.connection.execute("DROP TABLE HelpText")
            self.db.connection.execute("ALTER TABLE FabricPiece RENAME COLUMN FabricPattern TO PatternName")
            self.db.connection.execute("PRAGMA user_version = 1")
        before = {
            table: [tuple(row) for row in self.db.connection.execute(f"SELECT * FROM {table}")]
            for table in ("FabricPiece", "FabricHistory", "SelectionSet", "SelectionMember", "ScreenState")
        }
        error_ids = [tuple(row) for row in self.db.connection.execute(
            "SELECT ErrorTextID, MessageKey FROM ErrorText ORDER BY ErrorTextID",
        )]
        self.db.close()
        return piece_id, before, error_ids

    def test_version_one_requires_consent_and_upgrade_preserves_existing_data(self):
        piece_id, before, error_ids = self.make_legacy_database()
        original = self.path.read_bytes()
        with self.assertRaises(UpgradeRequired):
            Database(self.path)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.glob("PreUpgrade_*")), [])
        self.db = Database(self.path, upgrade=True)
        for table, rows in before.items():
            self.assertEqual(rows, [tuple(row) for row in self.db.connection.execute(f"SELECT * FROM {table}")])
        self.assertEqual(error_ids, [tuple(row) for row in self.db.connection.execute(
            "SELECT ErrorTextID, MessageKey FROM ErrorText ORDER BY ErrorTextID",
        )])
        self.assertEqual(self.db.dropdown_choices("Color"), (ADD_ITEM, "Sage"))
        self.assertEqual(self.db.dropdown_choices("StorageLocation"), (ADD_ITEM, "Bin C"))
        self.assertTrue(self.db.upgrade_backup.exists())
        backup = sqlite3.connect(self.db.upgrade_backup)
        try:
            self.assertEqual(backup.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(tuple(backup.execute("SELECT * FROM FabricPiece").fetchone()), before["FabricPiece"][0])
        finally:
            backup.close()
        self.assertGreater(self.db.save_piece(fabric()), piece_id)
        self.assertEqual(len(self.db.sets()), 1)

    def test_failed_upgrade_rolls_back_schema_and_keeps_backup(self):
        _, before, _ = self.make_legacy_database()
        with patch.object(Database, "_seed_dropdowns", side_effect=sqlite3.IntegrityError("seed failed")):
            with self.assertRaises(sqlite3.IntegrityError):
                Database(self.path, upgrade=True)
        connection = sqlite3.connect(self.path)
        try:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertIsNone(connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'Dropdown'",
            ).fetchone())
            self.assertEqual(connection.execute("SELECT * FROM FabricPiece").fetchall(), before["FabricPiece"])
        finally:
            connection.close()
        self.assertEqual(len(list(self.path.parent.glob("PreUpgrade_*"))), 1)
        self.db = Database(self.path, upgrade=True)


if __name__ == "__main__":
    unittest.main()
