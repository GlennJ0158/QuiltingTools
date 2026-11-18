import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from quilting.database import Database
from quilting.model import (
    FABRIC_FIELDS, FILTER_FIELDS, FieldError, caption, display_measurement,
    measurement, normalize_sort, validate_fields,
)


def fabric(**overrides):
    values = {field.name: field.default for field in FABRIC_FIELDS}
    values.update(FabricName="Blue cotton", UsableWidth="42 1/2", UsableLength="72")
    values.update(overrides)
    return values


class MeasurementTests(unittest.TestCase):
    def test_exact_fraction_and_decimal_round_trips(self):
        for value in ("42", "42 1/2", "1/64", "42.125", "0.000001", "0.123456", "100000"):
            with self.subTest(value=value):
                stored = measurement(value, "UsableWidth")
                self.assertEqual(measurement(display_measurement(stored), "UsableWidth"), stored)
        self.assertEqual(measurement("42 1/2", "Width"), 42_500_000)
        self.assertEqual(measurement("1/64", "Width"), 15_625)

    def test_invalid_measurements(self):
        for value in ("", "0", "-1", "nan", "inf", "1e2", "1/0", "1/3", "2/2",
                      "1 -1/2", "42 in", "1.1234567", "100000.000001", "9" * 1000):
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
            FabricName="Red's cotton", Color="Red", PatternName="Tiny flowers",
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
            self.assertEqual(copy.get_piece(piece_id)["Color"], "")
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


if __name__ == "__main__":
    unittest.main()
