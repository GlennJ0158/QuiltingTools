import ast
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quilting.database import Database, SCHEMA_VERSION, UpgradeRequired
from quilting.errors import ERROR_FIELDS, ERROR_FILTER_FIELDS, OLD_CONFLICT_REFERENCE, STARTUP_MESSAGES, TROUBLESHOOTING
from quilting.model import FieldError
from tests.test_inventory import assert_legacy_rows_preserved, downgrade_dropdown_schema, fabric


def error_values(**overrides):
    return {
        "ErrorText": "Example failure",
        "LikelyCause": "1. Example cause",
        "Description": "1. Example fix",
        **overrides,
    }


class ErrorMessageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "errors.db"
        self.db = Database(self.path)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_seed_covers_issued_error_keys_and_non_catalog_failure_templates(self):
        runtime = {row["MessageKey"]: dict(row) for row in self.db.connection.execute("SELECT * FROM ErrorText")}
        issued = set()
        for path in (Path(__file__).parents[1] / "quilting").glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id == "FieldError" and node.args
                        and isinstance(node.args[0], ast.Constant)):
                    issued.add(node.args[0].value)
        self.assertTrue(issued <= runtime.keys())
        rows = {row["ID"]: row for row in self.db.error_rows()}
        for key in issued:
            template = runtime[key]
            row = rows[template["ErrorTextID"]]
            self.assertEqual(row["ErrorText"], template["MessageTemplate"])
            self.assertIn("1.", row["LikelyCause"])
            self.assertIn("1.", row["Description"])
        self.assertTrue({row[0] for row in STARTUP_MESSAGES}
                        <= {row["ErrorText"] for row in rows.values()})

    def test_crud_persists_without_reseeding_or_changing_runtime_and_backup_restores_it(self):
        original_runtime = self.db.connection.execute("SELECT * FROM ErrorText").fetchall()
        original = self.db.error_rows()[0]
        self.db.delete_error(original["ID"], error_values(**{
            field.name: original[field.name] for field in ERROR_FIELDS
        }))
        message_id = self.db.save_error(error_values())
        self.db.save_error(error_values(Description="1. Updated fix"), message_id, error_values())
        self.db.close()
        self.db = Database(self.path)
        self.assertNotIn(original["ID"], [row["ID"] for row in self.db.error_rows()])
        self.assertEqual(self.db.get_error(message_id)["Description"], "1. Updated fix")
        self.assertEqual(original_runtime, self.db.connection.execute("SELECT * FROM ErrorText").fetchall())
        self.assertIn("Error ID:", self.db.error_message(FieldError("Required", "ErrorText")))
        backup = Path(self.temp.name) / "backup.db"
        restored = Path(self.temp.name) / "restored.db"
        self.db.save_set("Errors", [message_id], "ErrorMessage")
        self.db.save_sort((("Description", "desc"),), "ErrorMessageSort")
        self.db.backup(backup)
        Database.restore_to_new(backup, restored)
        copy = Database(restored)
        try:
            self.assertEqual(copy.error_rows(), self.db.error_rows())
            self.assertEqual(copy.sets("ErrorMessage"), self.db.sets("ErrorMessage"))
            self.assertEqual(copy.set_members(copy.sets("ErrorMessage")[0]["ID"], "ErrorMessage"), [message_id])
            self.assertEqual(copy.load_sort("ErrorMessageSort"), self.db.load_sort("ErrorMessageSort"))
        finally:
            copy.close()

    def test_existing_default_conflict_reference_is_updated_but_edits_are_preserved(self):
        conflict = self.db.connection.execute(
            "SELECT ErrorTextID FROM ErrorText WHERE MessageKey = 'Conflict'").fetchone()[0]
        with self.db.connection:
            self.db.connection.execute(
                "UPDATE ErrorMessage SET LikelyCause = ?, Description = ? WHERE ID = ?",
                (*OLD_CONFLICT_REFERENCE, conflict))
        self.db.close()
        self.db = Database(self.path)
        row = self.db.get_error(conflict)
        self.assertEqual((row["LikelyCause"], row["Description"]), TROUBLESHOOTING["Conflict"])
        with self.db.connection:
            self.db.connection.execute(
                "UPDATE ErrorMessage SET LikelyCause = ?, Description = ? WHERE ID = ?",
                (OLD_CONFLICT_REFERENCE[0], "My customized instructions", conflict))
        self.db.close()
        self.db = Database(self.path)
        row = self.db.get_error(conflict)
        self.assertEqual(row["LikelyCause"], OLD_CONFLICT_REFERENCE[0])
        self.assertEqual(row["Description"], "My customized instructions")

    def test_required_limits_binding_missing_and_stale_changes_are_rejected(self):
        for field in ERROR_FIELDS:
            for value in (" ", "x" * (field.limit + 1)):
                with self.subTest(field=field.name, value=len(value)), self.assertRaises(FieldError):
                    self.db.save_error(error_values(**{field.name: value}))
        with self.assertRaises(FieldError):
            self.db.save_error({**error_values(), "UnexpectedField": "extra"})
        message_id = self.db.save_error(error_values())
        with self.assertRaises(FieldError):
            self.db.save_error(error_values(), message_id)
        self.db.save_error(error_values(Description="Changed elsewhere"), message_id, error_values())
        for action in (
            lambda: self.db.save_error(error_values(), message_id, error_values()),
            lambda: self.db.delete_error(message_id, error_values()),
        ):
            with self.assertRaises(FieldError) as raised:
                action()
            self.assertEqual(raised.exception.key, "Conflict")
        self.db.delete_error(message_id, error_values(Description="Changed elsewhere"))
        for action in (
            lambda: self.db.get_error(message_id),
            lambda: self.db.save_error(error_values(), message_id, error_values()),
            lambda: self.db.delete_error(message_id, error_values()),
        ):
            with self.assertRaises(FieldError) as raised:
                action()
            self.assertEqual(raised.exception.key, "MissingRecord")

    def test_literal_filters_numeric_multifield_sort_and_separate_selection_snapshots(self):
        first = self.db.save_error(error_values(ErrorText="100% _ Cotton", Description="A"))
        second = self.db.save_error(error_values(ErrorText="100% _ cotton", Description="Z"))
        third = self.db.save_error(error_values(ErrorText="Other"))
        filters = {field.name: "" for field in ERROR_FILTER_FIELDS}
        filters.update(ErrorText="100% _ COTTON", LikelyCause="example CAUSE")
        rows = self.db.error_rows(filters, sort=(("Description", "desc"), ("ID", "asc")))
        self.assertEqual([row["ID"] for row in rows], [second, first])
        self.assertEqual(self.db.error_rows(filters, selected_ids=[]), [])
        self.assertEqual([row["ID"] for row in self.db.error_rows(filters, [first])], [first])
        self.db.save_sort((("ID", "desc"),), "ErrorMessageSort")
        ids = [row["ID"] for row in self.db.error_rows()]
        self.assertEqual(ids, sorted(ids, reverse=True))
        with self.assertRaises(FieldError):
            self.db.error_rows(sort=(("FabricName", "asc"),))
        with self.assertRaises(FieldError):
            self.db.save_sort((("ID; DROP TABLE ErrorMessage", "asc"),), "ErrorMessageSort")
        piece_id = self.db.save_piece(fabric())
        self.db.save_set("Same name", [piece_id])
        set_id = self.db.save_set("Same name", [first, second], "ErrorMessage")
        self.db.save_error(error_values())
        self.assertEqual(self.db.set_members(set_id, "ErrorMessage"), [first, second])
        with self.assertRaises(FieldError) as raised:
            self.db.save_set("SAME NAME", [third], "ErrorMessage")
        self.assertEqual(raised.exception.key, "DuplicateSet")
        for ids in ([], [999999]):
            with self.assertRaises(FieldError):
                self.db.save_set("Invalid", ids, "ErrorMessage")
        self.db.delete_error(first, error_values(ErrorText="100% _ Cotton", Description="A"))
        self.assertEqual(self.db.set_members(set_id, "ErrorMessage"), [second])
        self.db.delete_set(set_id, "ErrorMessage")
        self.assertEqual(self.db.sets("ErrorMessage"), [])
        self.assertEqual(len(self.db.sets()), 1)
        self.assertEqual(self.db.get_error(second)["ID"], second)

    def make_version_three(self):
        piece_id = self.db.save_piece(fabric())
        self.db.save_set("Keep", [piece_id])
        self.db.save_sort((("UsableWidth", "desc"),))
        with self.db.connection:
            for table in ("QuiltPlan", "QuiltColorMap", "QuiltBlockUse", "Quilt",
                          "BlockSetMember", "BlockSet", "BlockPartPlacement", "BlockPart", "QuiltBlock"):
                self.db.connection.execute(f"DROP TABLE {table}")
            for table in ("QuiltBackCutSource", "QuiltBackPanel", "QuiltBack"):
                self.db.connection.execute(f"DROP TABLE {table}")
            for table in ("WorkingListMember", "WorkingListSet",
                          "ErrorMessageMember", "ErrorMessageSet", "ErrorMessage"):
                self.db.connection.execute(f"DROP TABLE {table}")
            downgrade_dropdown_schema(self.db.connection)
            self.db.connection.execute("ALTER TABLE FabricPiece RENAME COLUMN FabricPattern TO PatternName")
            self.db.connection.execute("PRAGMA user_version = 3")
        tables = ("FabricPiece", "FabricHistory", "SelectionSet", "SelectionMember",
                  "ErrorText", "Dropdown", "HelpText", "ScreenState")
        before = {name: [tuple(row) for row in self.db.connection.execute(f"SELECT * FROM {name}")]
                  for name in tables}
        self.db.close()
        return before

    def test_version_three_upgrade_consent_backup_and_preservation(self):
        before = self.make_version_three()
        original = self.path.read_bytes()
        with self.assertRaises(UpgradeRequired):
            Database(self.path)
        self.assertEqual(original, self.path.read_bytes())
        self.db = Database(self.path, upgrade=True)
        for table, rows in before.items():
            assert_legacy_rows_preserved(self, self.db, table, rows)
        self.assertTrue(self.db.error_rows())
        self.assertEqual(self.db.connection.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
        with sqlite3.connect(self.db.upgrade_backup) as backup:
            Database.validate(backup, allow_legacy=True)
            self.assertEqual(backup.execute("PRAGMA user_version").fetchone()[0], 3)

    def test_failed_upgrade_rolls_back_all_new_tables_and_retains_backup(self):
        before = self.make_version_three()
        with patch.object(Database, "_seed_errors", side_effect=sqlite3.IntegrityError("seed failed")):
            with self.assertRaises(sqlite3.IntegrityError):
                Database(self.path, upgrade=True)
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 3)
            self.assertEqual(connection.execute("SELECT * FROM FabricPiece").fetchall(), before["FabricPiece"])
            for name in ("ErrorMessage", "ErrorMessageSet", "ErrorMessageMember"):
                self.assertIsNone(connection.execute(
                    "SELECT name FROM sqlite_master WHERE name = ?", (name,)).fetchone())
        self.assertEqual(len(list(self.path.parent.glob("PreUpgrade_*"))), 1)
        self.db = Database(self.path, upgrade=True)
