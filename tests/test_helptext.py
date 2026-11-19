import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quilting.database import Database, SCHEMA_VERSION, UpgradeRequired
from quilting.helptext import HELP_FIELDS, default_help
from quilting.model import FieldError
from tests.test_inventory import fabric


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

    def make_version_two(self):
        self.db.save_piece(fabric(Color="Sage"))
        with self.db.connection:
            self.db.connection.execute("DROP TABLE HelpText")
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
            self.assertEqual([tuple(row) for row in self.db.connection.execute(f"SELECT * FROM {name}")],
                             rows, name)
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
