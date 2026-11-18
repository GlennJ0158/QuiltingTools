"""SQLite persistence. Draft planning must never change physical inventory."""

import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .model import (
    ADD_ITEM, DEFAULT_SORT, DROPDOWN_FIELDS, FABRIC_FIELDS, FABRIC_NAMES, FILTER_FIELDS, MESSAGES,
    Field, FieldError, caption, normalize_sort, validate_fields,
)

APPLICATION_ID = 0x5155494C
SCHEMA_VERSION = 2
DROPDOWN_SCHEMA = """
CREATE TABLE Dropdown (
    ID INTEGER PRIMARY KEY AUTOINCREMENT,
    TableName TEXT NOT NULL CHECK(TableName = 'FabricPiece'),
    FieldName TEXT NOT NULL,
    ListItem TEXT NOT NULL COLLATE NOCASE CHECK(length(ListItem) <= 120),
    Def INTEGER NOT NULL DEFAULT 0 CHECK(Def IN (0, 1)),
    Use INTEGER NOT NULL DEFAULT 1 CHECK(Use IN (0, 1)),
    UNIQUE(TableName, FieldName, ListItem)
);
CREATE UNIQUE INDEX DropdownDefaultIndex ON Dropdown(TableName, FieldName)
    WHERE Def = 1 AND Use = 1;
"""
SCHEMA = """
CREATE TABLE FabricPiece (
    ID INTEGER PRIMARY KEY AUTOINCREMENT,
    FabricName TEXT NOT NULL CHECK(length(trim(FabricName)) BETWEEN 1 AND 120),
    Color TEXT NOT NULL CHECK(length(Color) <= 120),
    PatternName TEXT NOT NULL CHECK(length(PatternName) <= 120),
    UsableWidth INTEGER NOT NULL CHECK(typeof(UsableWidth) = 'integer'
        AND UsableWidth BETWEEN 1 AND 100000000000),
    UsableLength INTEGER NOT NULL CHECK(typeof(UsableLength) = 'integer'
        AND UsableLength BETWEEN 1 AND 100000000000),
    GrainDirection TEXT NOT NULL CHECK(GrainDirection IN ('Unknown', 'Along Length', 'Along Width')),
    PrintDirection TEXT NOT NULL CHECK(PrintDirection IN
        ('Unknown', 'Non-directional', 'Along Length', 'Along Width')),
    StorageLocation TEXT NOT NULL CHECK(length(StorageLocation) <= 120),
    Status TEXT NOT NULL CHECK(Status IN ('Available', 'Retired')),
    Notes TEXT NOT NULL CHECK(length(Notes) <= 4000),
    Revision INTEGER NOT NULL DEFAULT 1 CHECK(Revision >= 1),
    DateCreated TEXT NOT NULL,
    DateModified TEXT NOT NULL
);
CREATE TABLE FabricHistory (
    ID INTEGER PRIMARY KEY AUTOINCREMENT,
    FabricPieceID INTEGER NOT NULL REFERENCES FabricPiece(ID),
    Action TEXT NOT NULL CHECK(Action IN ('Added', 'Updated')),
    BeforeValues TEXT,
    AfterValues TEXT NOT NULL,
    DateCreated TEXT NOT NULL
);
CREATE TABLE SelectionSet (
    ID INTEGER PRIMARY KEY AUTOINCREMENT,
    SetName TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK(length(trim(SetName)) BETWEEN 1 AND 120),
    DateCreated TEXT NOT NULL
);
CREATE TABLE SelectionMember (
    SelectionSetID INTEGER NOT NULL REFERENCES SelectionSet(ID) ON DELETE CASCADE,
    FabricPieceID INTEGER NOT NULL REFERENCES FabricPiece(ID),
    PRIMARY KEY (SelectionSetID, FabricPieceID)
);
CREATE TABLE ErrorText (
    ErrorTextID INTEGER PRIMARY KEY AUTOINCREMENT,
    MessageKey TEXT NOT NULL UNIQUE,
    Description TEXT NOT NULL,
    MessageTemplate TEXT NOT NULL,
    ResolutionText TEXT NOT NULL
);
CREATE TABLE ScreenState (
    ScreenName TEXT PRIMARY KEY,
    StateValues TEXT NOT NULL
);
CREATE INDEX FabricNameIndex ON FabricPiece(FabricName COLLATE NOCASE, ID);
CREATE INDEX FabricHistoryPieceIndex ON FabricHistory(FabricPieceID, ID);
""" + DROPDOWN_SCHEMA
TABLE_COLUMNS = {
    "FabricPiece": ("ID", *FABRIC_NAMES, "Revision", "DateCreated", "DateModified"),
    "FabricHistory": ("ID", "FabricPieceID", "Action", "BeforeValues", "AfterValues", "DateCreated"),
    "SelectionSet": ("ID", "SetName", "DateCreated"),
    "SelectionMember": ("SelectionSetID", "FabricPieceID"),
    "ErrorText": ("ErrorTextID", "MessageKey", "Description", "MessageTemplate", "ResolutionText"),
    "ScreenState": ("ScreenName", "StateValues"),
    "Dropdown": ("ID", "TableName", "FieldName", "ListItem", "Def", "Use"),
}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class Database:
    def __init__(self, path, upgrade=False):
        self.path = Path(path).expanduser().resolve()
        self.upgrade_backup = None
        new = not self.path.exists()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if new:
            # Claim a new path exclusively before SQLite opens it.
            with self.path.open("xb"):
                pass
        self.connection = sqlite3.connect(self.path, timeout=5)
        self.connection.row_factory = sqlite3.Row
        try:
            self.connection.execute("PRAGMA foreign_keys = ON")
            if new:
                self.connection.executescript(
                    f"BEGIN IMMEDIATE;\n{SCHEMA}\nPRAGMA application_id = {APPLICATION_ID};"
                    f"\nPRAGMA user_version = {SCHEMA_VERSION};"
                )
                with self.connection:
                    self.connection.executemany(
                        "INSERT INTO ErrorText (MessageKey, Description, MessageTemplate, ResolutionText) "
                        "VALUES (?, ?, ?, ?)", MESSAGES,
                    )
                    self._seed_dropdowns()
            elif (self.connection.execute("PRAGMA application_id").fetchone()[0] == APPLICATION_ID
                  and self.connection.execute("PRAGMA user_version").fetchone()[0] == 1):
                self.validate(self.connection, allow_legacy=True)
                if not upgrade:
                    raise UpgradeRequired()
                self._upgrade()
            self.validate(self.connection)
        except (sqlite3.Error, OSError, FieldError):
            self.connection.close()
            raise

    def close(self):
        self.connection.close()

    @staticmethod
    def validate(connection, allow_legacy=False):
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if (connection.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID
                or version not in ((1, SCHEMA_VERSION) if allow_legacy else (SCHEMA_VERSION,))):
            raise FieldError("DatabaseFormat", "Database", detail="Unsupported database or schema version.")
        for table, expected in TABLE_COLUMNS.items():
            if version == 1 and table == "Dropdown":
                continue
            columns = tuple(row[1] for row in connection.execute(f'PRAGMA table_info("{table}")'))
            if columns != expected:
                raise FieldError("DatabaseFormat", "Database", detail=f"{table} has an unexpected schema.")
        if [row[0] for row in connection.execute("PRAGMA quick_check")] != ["ok"]:
            raise FieldError("DatabaseFormat", "Database", detail="Database integrity check failed.")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise FieldError("DatabaseFormat", "Database", detail="Database relationships are incomplete.")
        keys = {row[0] for row in connection.execute("SELECT MessageKey FROM ErrorText")}
        if not {message[0] for message in MESSAGES} <= keys:
            raise FieldError("DatabaseFormat", "ErrorText", detail="Required error messages are missing.")

    def _upgrade(self):
        backup = self.path.with_name(
            f"PreUpgrade_{datetime.now(timezone.utc):%Y%m%d_%H%M%S_%f}_{self.path.name}",
        )
        self._copy_to_new(self.connection, backup)
        self.upgrade_backup = backup
        # All other clients must be closed before confirmation. Recheck under the write lock.
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.validate(self.connection, allow_legacy=True)
            if self.connection.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise FieldError("DatabaseFormat", "Database", detail="Database version changed during upgrade.")
            for statement in DROPDOWN_SCHEMA.split(";"):
                if statement.strip():
                    self.connection.execute(statement)
            self._seed_dropdowns()
            message = next(message for message in MESSAGES if message[0] == "Measurement")
            self.connection.execute(
                "UPDATE ErrorText SET Description = ?, MessageTemplate = ?, ResolutionText = ? "
                "WHERE MessageKey = ?", (*message[1:], message[0]),
            )
            self.connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self.validate(self.connection)
            self.connection.commit()
        except (sqlite3.Error, FieldError):
            self.connection.rollback()
            raise

    def _seed_dropdowns(self):
        for name, field in DROPDOWN_FIELDS.items():
            items = field.choices if field.kind == "choice" else ("",)
            for item in items:
                self.connection.execute(
                    "INSERT INTO Dropdown (TableName, FieldName, ListItem, Def) VALUES ('FabricPiece', ?, ?, ?)",
                    (name, item, int(item == field.default)),
                )
            if field.kind == "dropdown":
                for row in self.connection.execute(f'SELECT DISTINCT "{name}" FROM FabricPiece ORDER BY ID'):
                    self._dropdown_item(name, row[0])

    def _dropdown_item(self, name, value):
        field = DROPDOWN_FIELDS.get(name)
        if field is None:
            raise FieldError("Choice", "FieldName")
        clean = validate_fields((field,), {name: value})[name]
        if clean.casefold() == ADD_ITEM.casefold():
            raise FieldError("Choice", name)
        row = self.connection.execute(
            "SELECT ID, ListItem FROM Dropdown WHERE TableName = 'FabricPiece' AND FieldName = ? "
            "AND ListItem = ? COLLATE NOCASE", (name, clean),
        ).fetchone()
        if row is not None:
            self.connection.execute("UPDATE Dropdown SET Use = 1 WHERE ID = ?", (row["ID"],))
            return row["ListItem"]
        self.connection.execute(
            "INSERT INTO Dropdown (TableName, FieldName, ListItem) VALUES ('FabricPiece', ?, ?)",
            (name, clean),
        )
        return clean

    def add_dropdown_item(self, name, value):
        if not isinstance(value, str) or not value.strip():
            raise FieldError("Required", name)
        with self.connection:
            return self._dropdown_item(name, value)

    def dropdown_rows(self, name):
        if name not in DROPDOWN_FIELDS:
            raise FieldError("Choice", "FieldName")
        return [dict(row) for row in self.connection.execute(
            "SELECT * FROM Dropdown WHERE TableName = 'FabricPiece' AND FieldName = ? AND Use = 1 "
            "ORDER BY Def DESC, ListItem COLLATE NOCASE, ID", (name,),
        )]

    def dropdown_default(self, name):
        rows = self.dropdown_rows(name)
        defaults = [row["ListItem"] for row in rows if row["Def"]]
        if len(defaults) != 1:
            raise FieldError("DatabaseFormat", name, detail="Exactly one active dropdown default is required.")
        return defaults[0]

    def dropdown_choices(self, name):
        rows = self.dropdown_rows(name)
        default = self.dropdown_default(name)
        remaining = [row["ListItem"] for row in rows if row["ListItem"] != default]
        if DROPDOWN_FIELDS[name].kind == "dropdown":
            return (default, ADD_ITEM, *remaining)
        return (default, *remaining)

    def set_dropdown_default(self, item_id):
        with self.connection:
            row = self.connection.execute(
                "SELECT FieldName FROM Dropdown WHERE ID = ? AND Use = 1", (item_id,),
            ).fetchone()
            if row is None:
                raise FieldError("MissingRecord", "DropdownID")
            self.connection.execute(
                "UPDATE Dropdown SET Def = 0 WHERE TableName = 'FabricPiece' AND FieldName = ?",
                (row["FieldName"],),
            )
            self.connection.execute("UPDATE Dropdown SET Def = 1 WHERE ID = ?", (item_id,))

    def error_message(self, error):
        row = self.connection.execute(
            "SELECT * FROM ErrorText WHERE MessageKey = ?", (error.key,),
        ).fetchone()
        if row is None:
            raise FieldError("DatabaseFormat", "ErrorText", detail=f"Missing error message {error.key}.")
        text = f"{caption(error.field)}: {row['MessageTemplate'].format(**error.details)}"
        if row["ResolutionText"]:
            text += f"\n\n{row['ResolutionText']}"
        return f"{text}\n\nError ID: {row['ErrorTextID']}"

    def get_piece(self, piece_id):
        row = self.connection.execute("SELECT * FROM FabricPiece WHERE ID = ?", (piece_id,)).fetchone()
        if row is None:
            raise FieldError("MissingRecord", "FabricPieceID")
        return dict(row)

    def save_piece(self, values, piece_id=None, revision=None):
        clean = validate_fields(FABRIC_FIELDS, values)
        timestamp = now()
        with self.connection:
            for name in DROPDOWN_FIELDS:
                clean[name] = self._dropdown_item(name, clean[name])
            if piece_id is None:
                columns = ", ".join(FABRIC_NAMES)
                placeholders = ", ".join("?" for _ in FABRIC_NAMES)
                cursor = self.connection.execute(
                    f"INSERT INTO FabricPiece ({columns}, DateCreated, DateModified) "
                    f"VALUES ({placeholders}, ?, ?)", (*clean.values(), timestamp, timestamp),
                )
                piece_id, before, action = cursor.lastrowid, None, "Added"
            else:
                before = self.get_piece(piece_id)
                if before["Revision"] != revision:
                    raise FieldError("Conflict", "FabricPieceID")
                if all(before[name] == value for name, value in clean.items()):
                    return piece_id
                assignments = ", ".join(f"{name} = ?" for name in FABRIC_NAMES)
                cursor = self.connection.execute(
                    f"UPDATE FabricPiece SET {assignments}, Revision = Revision + 1, DateModified = ? "
                    "WHERE ID = ? AND Revision = ?",
                    (*clean.values(), timestamp, piece_id, revision),
                )
                if cursor.rowcount != 1:
                    raise FieldError("Conflict", "FabricPieceID")
                action = "Updated"
            after = self.get_piece(piece_id)
            self.connection.execute(
                "INSERT INTO FabricHistory (FabricPieceID, Action, BeforeValues, AfterValues, DateCreated) "
                "VALUES (?, ?, ?, ?, ?)",
                (piece_id, action, json.dumps(before) if before else None, json.dumps(after), timestamp),
            )
        return piece_id

    def pieces(self, filters=None, selected_ids=None, sort=DEFAULT_SORT):
        values = {field.name: "" for field in FILTER_FIELDS} if filters is None else filters
        clean = validate_fields(FILTER_FIELDS, values)
        order = normalize_sort(sort)
        clauses, args = [], []
        for name in ("FabricName", "Color", "PatternName", "StorageLocation"):
            if clean[name]:
                clauses.append(f"instr(lower({name}), lower(?)) > 0")
                args.append(clean[name])
        for name, column in (("MinimumWidth", "UsableWidth"), ("MinimumLength", "UsableLength")):
            if clean[name] is not None:
                clauses.append(f"{column} >= ?")
                args.append(clean[name])
        if clean["Status"]:
            clauses.append("Status = ?")
            args.append(clean["Status"])
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        order_sql = ", ".join(
            f"{field}{'' if field in ('ID', 'UsableWidth', 'UsableLength') else ' COLLATE NOCASE'} {direction}"
            for field, direction in order
        )
        rows = [dict(row) for row in self.connection.execute(
            f"SELECT * FROM FabricPiece{where} ORDER BY {order_sql}", args,
        )]
        if selected_ids is not None:
            allowed = set(selected_ids)
            rows = [row for row in rows if row["ID"] in allowed]
        return rows

    def history(self, piece_id):
        self.get_piece(piece_id)
        return [dict(row) for row in self.connection.execute(
            "SELECT * FROM FabricHistory WHERE FabricPieceID = ? ORDER BY ID DESC", (piece_id,),
        )]

    def save_set(self, name, ids):
        name = validate_fields((Field("SetName", required=True),), {"SetName": name})["SetName"]
        ids = sorted(set(ids))
        if not ids:
            raise FieldError("EmptySet", "SetName")
        with self.connection:
            if self.connection.execute(
                    "SELECT 1 FROM SelectionSet WHERE SetName = ? COLLATE NOCASE", (name,)).fetchone():
                raise FieldError("DuplicateSet", "SetName")
            for piece_id in ids:
                self.get_piece(piece_id)
            cursor = self.connection.execute(
                "INSERT INTO SelectionSet (SetName, DateCreated) VALUES (?, ?)", (name, now()),
            )
            self.connection.executemany(
                "INSERT INTO SelectionMember (SelectionSetID, FabricPieceID) VALUES (?, ?)",
                ((cursor.lastrowid, piece_id) for piece_id in ids),
            )
            return cursor.lastrowid

    def sets(self):
        return [dict(row) for row in self.connection.execute(
            "SELECT s.ID, s.SetName, count(m.FabricPieceID) AS RecordCount "
            "FROM SelectionSet s LEFT JOIN SelectionMember m ON s.ID = m.SelectionSetID "
            "GROUP BY s.ID ORDER BY s.SetName COLLATE NOCASE, s.ID",
        )]

    def set_members(self, set_id):
        if self.connection.execute("SELECT 1 FROM SelectionSet WHERE ID = ?", (set_id,)).fetchone() is None:
            raise FieldError("MissingRecord", "SelectionSetID")
        return [row[0] for row in self.connection.execute(
            "SELECT FabricPieceID FROM SelectionMember WHERE SelectionSetID = ? ORDER BY FabricPieceID",
            (set_id,),
        )]

    def delete_set(self, set_id):
        with self.connection:
            cursor = self.connection.execute("DELETE FROM SelectionSet WHERE ID = ?", (set_id,))
            if cursor.rowcount != 1:
                raise FieldError("MissingRecord", "SelectionSetID")

    def save_sort(self, sort):
        clean = normalize_sort(sort)
        with self.connection:
            self.connection.execute(
                "INSERT INTO ScreenState VALUES ('FabricInventorySort', ?) "
                "ON CONFLICT(ScreenName) DO UPDATE SET StateValues = excluded.StateValues",
                (json.dumps(clean),),
            )

    def load_sort(self):
        row = self.connection.execute(
            "SELECT StateValues FROM ScreenState WHERE ScreenName = 'FabricInventorySort'",
        ).fetchone()
        if row is None:
            return DEFAULT_SORT
        try:
            return normalize_sort(json.loads(row[0]))
        except (ValueError, TypeError) as error:
            raise FieldError("DatabaseFormat", "Sort", detail=f"Saved sort is invalid: {error}") from error

    @staticmethod
    def _copy_to_new(source, destination):
        destination = Path(destination).expanduser().resolve()
        if destination.exists():
            raise FileExistsError(f"Destination already exists: {destination}. Choose a new filename.")
        handle, temporary = tempfile.mkstemp(prefix=".quilting-backup-", dir=destination.parent)
        os.close(handle)
        temporary = Path(temporary)
        try:
            target = sqlite3.connect(temporary)
            try:
                source.backup(target)
                Database.validate(target, allow_legacy=True)
            finally:
                target.close()
            # Publish only a complete copy; a racing destination must not be overwritten.
            os.link(temporary, destination)
        finally:
            temporary.unlink()
        return destination

    def backup(self, destination):
        return self._copy_to_new(self.connection, destination)

    @staticmethod
    def restore_to_new(source, destination):
        path = Path(source).expanduser().resolve()
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        try:
            Database.validate(connection, allow_legacy=True)
            return Database._copy_to_new(connection, destination)
        finally:
            connection.close()


class UpgradeRequired(FieldError):
    def __init__(self):
        super().__init__("DatabaseFormat", "Database", detail="A backed-up database upgrade is required.")
