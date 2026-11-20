"""SQLite persistence. Draft planning must never change physical inventory."""

import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .backs import MAX_PANELS, MINIMUM_PART, PALETTE
from .helptext import (
    DROPDOWN_COLUMNS, DROPDOWN_FILTER_FIELDS, HELP_COLUMNS, HELP_FIELDS, HELP_FILTER_FIELDS,
    HISTORY_COLUMNS, HISTORY_FILTER_FIELDS, default_help,
)
from .errors import ERROR_COLUMNS, ERROR_FIELDS, ERROR_FILTER_FIELDS, STARTUP_MESSAGES, TROUBLESHOOTING
from .model import (
    ADD_ITEM, DEFAULT_SORT, DROPDOWN_FIELDS, FABRIC_FIELDS, FABRIC_NAMES, FILTER_FIELDS, MESSAGES,
    SORT_FIELDS, Field, FieldError, caption, measurement, normalize_sort, validate_fields,
)

APPLICATION_ID = 0x5155494C
SCHEMA_VERSION = 6
ERROR_SCHEMA = """
CREATE TABLE ErrorMessage (
    ID INTEGER PRIMARY KEY AUTOINCREMENT,
    ErrorText TEXT NOT NULL CHECK(length(trim(ErrorText)) BETWEEN 1 AND 4000),
    LikelyCause TEXT NOT NULL CHECK(length(trim(LikelyCause)) BETWEEN 1 AND 4000),
    Description TEXT NOT NULL CHECK(length(trim(Description)) BETWEEN 1 AND 16000)
);
CREATE TABLE ErrorMessageSet (
    ID INTEGER PRIMARY KEY AUTOINCREMENT,
    SetName TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK(length(trim(SetName)) BETWEEN 1 AND 120),
    DateCreated TEXT NOT NULL
);
CREATE TABLE ErrorMessageMember (
    SelectionSetID INTEGER NOT NULL REFERENCES ErrorMessageSet(ID) ON DELETE CASCADE,
    ErrorMessageID INTEGER NOT NULL REFERENCES ErrorMessage(ID) ON DELETE CASCADE,
    PRIMARY KEY (SelectionSetID, ErrorMessageID)
);
"""
WORKING_LIST_SCHEMA = """
CREATE TABLE WorkingListSet (
    ID INTEGER PRIMARY KEY AUTOINCREMENT,
    ScreenName TEXT NOT NULL CHECK(ScreenName IN ('DropDown', 'HelpText', 'History')),
    ScopeName TEXT NOT NULL DEFAULT '',
    SetName TEXT NOT NULL CHECK(length(trim(SetName)) BETWEEN 1 AND 120),
    DateCreated TEXT NOT NULL,
    UNIQUE(ScreenName, ScopeName, SetName COLLATE NOCASE)
);
CREATE TABLE WorkingListMember (
    SelectionSetID INTEGER NOT NULL REFERENCES WorkingListSet(ID) ON DELETE CASCADE,
    RecordID INTEGER NOT NULL,
    PRIMARY KEY (SelectionSetID, RecordID)
);
"""
HELP_SCHEMA = """
CREATE TABLE HelpText (
    ID INTEGER PRIMARY KEY AUTOINCREMENT,
    TableName TEXT NOT NULL CHECK(length(trim(TableName)) BETWEEN 1 AND 120),
    FieldName TEXT NOT NULL CHECK(length(trim(FieldName)) BETWEEN 1 AND 120),
    HoverText TEXT NOT NULL CHECK(length(trim(HoverText)) BETWEEN 1 AND 4000),
    FullText TEXT NOT NULL CHECK(length(trim(FullText)) BETWEEN 1 AND 16000),
    UNIQUE(TableName, FieldName)
);
"""
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
BACK_SCHEMA = """
CREATE TABLE QuiltBack (
    ID INTEGER PRIMARY KEY AUTOINCREMENT,
    BackName TEXT NOT NULL CHECK(length(trim(BackName)) BETWEEN 1 AND 120),
    QuiltWidth INTEGER NOT NULL CHECK(QuiltWidth > 0),
    QuiltLength INTEGER NOT NULL CHECK(QuiltLength > 0),
    Margin INTEGER NOT NULL CHECK(Margin >= 0),
    SeamAllowance INTEGER NOT NULL CHECK(SeamAllowance >= 0),
    BackWidth INTEGER NOT NULL CHECK(BackWidth > 0),
    BackLength INTEGER NOT NULL CHECK(BackLength > 0),
    LayoutDirection TEXT NOT NULL CHECK(LayoutDirection IN ('single', 'vertical', 'horizontal')),
    RatioTier INTEGER NOT NULL CHECK(RatioTier IN (0, 1, 2)),
    GrainConsistent INTEGER NOT NULL CHECK(GrainConsistent IN (0, 1)),
    Status TEXT NOT NULL CHECK(Status IN ('Draft', 'Cut', 'Assembled')),
    DateCreated TEXT NOT NULL,
    DateModified TEXT NOT NULL
);
CREATE TABLE QuiltBackPanel (
    QuiltBackID INTEGER NOT NULL REFERENCES QuiltBack(ID) ON DELETE CASCADE,
    PanelNumber INTEGER NOT NULL CHECK(PanelNumber > 0),
    FabricPieceID INTEGER NOT NULL REFERENCES FabricPiece(ID),
    SourceRevision INTEGER NOT NULL CHECK(SourceRevision > 0),
    FabricName TEXT NOT NULL CHECK(length(trim(FabricName)) BETWEEN 1 AND 120),
    InventoryColor TEXT NOT NULL CHECK(length(InventoryColor) <= 120),
    SourceGrain TEXT NOT NULL CHECK(SourceGrain IN ('Unknown', 'Along Length', 'Along Width')),
    SourceWidth INTEGER NOT NULL CHECK(SourceWidth > 0),
    SourceLength INTEGER NOT NULL CHECK(SourceLength > 0),
    PaletteColor TEXT NOT NULL CHECK(length(trim(PaletteColor)) BETWEEN 1 AND 32),
    CutWidth INTEGER NOT NULL CHECK(CutWidth > 0),
    CutLength INTEGER NOT NULL CHECK(CutLength > 0),
    FinishedWidth INTEGER NOT NULL CHECK(FinishedWidth > 0),
    FinishedLength INTEGER NOT NULL CHECK(FinishedLength > 0),
    GrainAxis TEXT CHECK(GrainAxis IN ('x', 'y')),
    SourceX INTEGER NOT NULL CHECK(SourceX >= 0),
    SourceY INTEGER NOT NULL CHECK(SourceY >= 0),
    X INTEGER NOT NULL CHECK(X >= 0),
    Y INTEGER NOT NULL CHECK(Y >= 0),
    PRIMARY KEY (QuiltBackID, PanelNumber)
);
CREATE TABLE QuiltBackCutSource (
    QuiltBackID INTEGER NOT NULL REFERENCES QuiltBack(ID),
    FabricPieceID INTEGER NOT NULL REFERENCES FabricPiece(ID),
    SourceRevision INTEGER NOT NULL CHECK(SourceRevision > 0),
    BeforeValues TEXT NOT NULL,
    AfterValues TEXT NOT NULL,
    PlannedCutArea INTEGER NOT NULL CHECK(PlannedCutArea > 0),
    RemnantPieceID INTEGER REFERENCES FabricPiece(ID),
    PRIMARY KEY (QuiltBackID, FabricPieceID)
);
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
""" + DROPDOWN_SCHEMA + HELP_SCHEMA + ERROR_SCHEMA + WORKING_LIST_SCHEMA + BACK_SCHEMA
TABLE_COLUMNS = {
    "FabricPiece": ("ID", *FABRIC_NAMES, "Revision", "DateCreated", "DateModified"),
    "FabricHistory": ("ID", "FabricPieceID", "Action", "BeforeValues", "AfterValues", "DateCreated"),
    "SelectionSet": ("ID", "SetName", "DateCreated"),
    "SelectionMember": ("SelectionSetID", "FabricPieceID"),
    "ErrorText": ("ErrorTextID", "MessageKey", "Description", "MessageTemplate", "ResolutionText"),
    "ScreenState": ("ScreenName", "StateValues"),
    "Dropdown": ("ID", "TableName", "FieldName", "ListItem", "Def", "Use"),
    "HelpText": HELP_COLUMNS,
    "ErrorMessage": ERROR_COLUMNS,
    "ErrorMessageSet": ("ID", "SetName", "DateCreated"),
    "ErrorMessageMember": ("SelectionSetID", "ErrorMessageID"),
    "WorkingListSet": ("ID", "ScreenName", "ScopeName", "SetName", "DateCreated"),
    "WorkingListMember": ("SelectionSetID", "RecordID"),
    "QuiltBack": (
        "ID", "BackName", "QuiltWidth", "QuiltLength", "Margin", "SeamAllowance",
        "BackWidth", "BackLength", "LayoutDirection", "RatioTier", "GrainConsistent",
        "Status", "DateCreated", "DateModified",
    ),
    "QuiltBackPanel": (
        "QuiltBackID", "PanelNumber", "FabricPieceID", "SourceRevision", "FabricName",
        "InventoryColor", "SourceGrain", "SourceWidth", "SourceLength", "PaletteColor",
        "CutWidth", "CutLength", "FinishedWidth", "FinishedLength", "GrainAxis",
        "SourceX", "SourceY", "X", "Y",
    ),
    "QuiltBackCutSource": (
        "QuiltBackID", "FabricPieceID", "SourceRevision", "BeforeValues", "AfterValues",
        "PlannedCutArea", "RemnantPieceID",
    ),
}
SAVED_SORTS = {
    "FabricInventorySort": (SORT_FIELDS, DEFAULT_SORT),
    "DropDownSort": (("ID", "FieldName", "ListItem", "Def", "Use"),
                     (("Def", "desc"), ("ListItem", "asc"), ("ID", "asc"))),
    "HelpTextSort": (HELP_COLUMNS, (("TableName", "asc"), ("FieldName", "asc"), ("ID", "asc"))),
    "ErrorMessageSort": (ERROR_COLUMNS, (("ID", "asc"),)),
    "HistorySort": (("ID", "Action", "DateCreated"),
                    (("ID", "desc"),)),
}
SELECTION_TABLES = {
    "Fabric": ("SelectionSet", "SelectionMember", "FabricPieceID"),
    "ErrorMessage": ("ErrorMessageSet", "ErrorMessageMember", "ErrorMessageID"),
}
WORKING_LIST_SCREENS = frozenset(("DropDown", "HelpText", "History"))


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
                    self._seed_errors()
            elif (self.connection.execute("PRAGMA application_id").fetchone()[0] == APPLICATION_ID
                  and self.connection.execute("PRAGMA user_version").fetchone()[0] in
                  (1, 2, 3, 4, 5)):
                self.validate(self.connection, allow_legacy=True)
                if not upgrade:
                    raise UpgradeRequired()
                self._upgrade()
            self.validate(self.connection)
            with self.connection:
                self._seed_help()
        except (sqlite3.Error, OSError, FieldError):
            self.connection.close()
            raise

    def close(self):
        self.connection.close()

    @staticmethod
    def validate(connection, allow_legacy=False):
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if (connection.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID
                or version not in ((1, 2, 3, 4, 5, SCHEMA_VERSION)
                                   if allow_legacy else (SCHEMA_VERSION,))):
            raise FieldError("DatabaseFormat", "Database", detail="Unsupported database or schema version.")
        for table, expected in TABLE_COLUMNS.items():
            if version < 5 and table in ("WorkingListSet", "WorkingListMember"):
                continue
            if version < 6 and table in ("QuiltBack", "QuiltBackPanel", "QuiltBackCutSource"):
                continue
            if version < 4 and table in ("ErrorMessage", "ErrorMessageSet", "ErrorMessageMember"):
                continue
            if version == 1 and table == "Dropdown":
                continue
            if version < 3 and table == "HelpText":
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
            version = self.connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (1, 2, 3, 4, 5):
                raise FieldError("DatabaseFormat", "Database", detail="Database version changed during upgrade.")
            schema = ((DROPDOWN_SCHEMA if version == 1 else "")
                      + (HELP_SCHEMA if version < 3 else "")
                      + (ERROR_SCHEMA if version < 4 else "")
                      + (WORKING_LIST_SCHEMA if version < 5 else "")
                      + BACK_SCHEMA)
            for statement in schema.split(";"):
                if statement.strip():
                    self.connection.execute(statement)
            if version == 1:
                self._seed_dropdowns()
                message = next(message for message in MESSAGES if message[0] == "Measurement")
                self.connection.execute(
                    "UPDATE ErrorText SET Description = ?, MessageTemplate = ?, ResolutionText = ? "
                    "WHERE MessageKey = ?", (*message[1:], message[0]),
                )
            self._seed_help()
            if version < 4:
                self._seed_errors()
            self.connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self.validate(self.connection)
            self.connection.commit()
        except (sqlite3.Error, FieldError):
            self.connection.rollback()
            raise

    def _seed_help(self):
        self.connection.executemany(
            "INSERT INTO HelpText (TableName, FieldName, HoverText, FullText) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(TableName, FieldName) DO NOTHING",
            ((screen, name, *pair) for (screen, name), pair in default_help().items()),
        )

    def _seed_errors(self):
        for row in self.connection.execute("SELECT * FROM ErrorText ORDER BY ErrorTextID").fetchall():
            causes, fixes = TROUBLESHOOTING.get(
                row["MessageKey"], (row["Description"], row["ResolutionText"]),
            )
            self.connection.execute(
                "INSERT INTO ErrorMessage (ID, ErrorText, LikelyCause, Description) VALUES (?, ?, ?, ?)",
                (row["ErrorTextID"], row["MessageTemplate"], causes, fixes),
            )
        self.connection.executemany(
            "INSERT INTO ErrorMessage (ErrorText, LikelyCause, Description) VALUES (?, ?, ?)",
            STARTUP_MESSAGES,
        )

    def error_rows(self, filters=None, selected_ids=None, sort=None):
        values = {field.name: "" for field in ERROR_FILTER_FIELDS} if filters is None else filters
        clean = validate_fields(ERROR_FILTER_FIELDS, values)
        order = self.load_sort("ErrorMessageSort") if sort is None else normalize_sort(sort, ERROR_COLUMNS)
        clauses, args = [], []
        for name, value in clean.items():
            if value:
                clauses.append(f'instr(lower("{name}"), lower(?)) > 0')
                args.append(value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql_order = ", ".join(f'"{name}" COLLATE NOCASE {direction}' for name, direction in order)
        rows = [dict(row) for row in self.connection.execute(
            f"SELECT * FROM ErrorMessage{where} ORDER BY {sql_order}", args,
        )]
        if selected_ids is not None:
            allowed = set(selected_ids)
            rows = [row for row in rows if row["ID"] in allowed]
        return rows

    def get_error(self, message_id):
        row = self.connection.execute("SELECT * FROM ErrorMessage WHERE ID = ?", (message_id,)).fetchone()
        if row is None:
            raise FieldError("MissingRecord", "ErrorMessage")
        return dict(row)

    def save_error(self, values, message_id=None, previous=None):
        clean = validate_fields(ERROR_FIELDS, values)
        if message_id is not None:
            previous = validate_fields(ERROR_FIELDS, previous if previous is not None else {})
        with self.connection:
            if message_id is None:
                return self.connection.execute(
                    "INSERT INTO ErrorMessage (ErrorText, LikelyCause, Description) VALUES (?, ?, ?)",
                    tuple(clean.values()),
                ).lastrowid
            self.get_error(message_id)
            cursor = self.connection.execute(
                "UPDATE ErrorMessage SET ErrorText = ?, LikelyCause = ?, Description = ? "
                "WHERE ID = ? AND ErrorText = ? AND LikelyCause = ? AND Description = ?",
                (*clean.values(), message_id, *(previous[field.name] for field in ERROR_FIELDS)),
            )
            if cursor.rowcount != 1:
                raise FieldError("Conflict", "ErrorMessage")
        return message_id

    def delete_error(self, message_id, previous):
        previous = validate_fields(ERROR_FIELDS, previous)
        with self.connection:
            self.get_error(message_id)
            cursor = self.connection.execute(
                "DELETE FROM ErrorMessage WHERE ID = ? AND ErrorText = ? AND LikelyCause = ? "
                "AND Description = ?",
                (message_id, *(previous[field.name] for field in ERROR_FIELDS)),
            )
            if cursor.rowcount != 1:
                raise FieldError("Conflict", "ErrorMessage")

    def help_pair(self, screen, name):
        row = self.connection.execute(
            "SELECT HoverText, FullText FROM HelpText WHERE TableName = ? AND FieldName = ?",
            (screen, name),
        ).fetchone()
        if row is None:
            raise FieldError("DatabaseFormat", "HelpText", detail=f"Missing help for {screen}/{name}.")
        return tuple(row)

    def help_rows(self, filters=None, selected_ids=None, sort=None):
        values = {field.name: "" for field in HELP_FILTER_FIELDS} if filters is None else filters
        clean = validate_fields(HELP_FILTER_FIELDS, values)
        order = self.load_sort("HelpTextSort") if sort is None else normalize_sort(sort, HELP_COLUMNS)
        clauses, args = [], []
        for name, value in clean.items():
            if value:
                clauses.append(f'instr(lower("{name}"), lower(?)) > 0')
                args.append(value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql_order = ", ".join(f'"{name}" COLLATE NOCASE {direction}' for name, direction in order)
        rows = [dict(row) for row in self.connection.execute(
            f"SELECT * FROM HelpText{where} ORDER BY {sql_order}", args,
        )]
        if selected_ids is not None:
            allowed = set(selected_ids)
            rows = [row for row in rows if row["ID"] in allowed]
        return rows

    def save_help(self, help_id, values, previous):
        clean = validate_fields(HELP_FIELDS, values)
        with self.connection:
            row = self.connection.execute("SELECT * FROM HelpText WHERE ID = ?", (help_id,)).fetchone()
            if row is None:
                raise FieldError("MissingRecord", "HelpText")
            if any(clean[name] != row[name] for name in ("TableName", "FieldName")):
                raise FieldError("Choice", "FieldName")
            cursor = self.connection.execute(
                "UPDATE HelpText SET HoverText = ?, FullText = ? WHERE ID = ? "
                "AND HoverText = ? AND FullText = ?",
                (clean["HoverText"], clean["FullText"], help_id, previous["HoverText"], previous["FullText"]),
            )
            if cursor.rowcount != 1:
                raise FieldError("Conflict", "HelpText")

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

    def dropdown_rows(self, name, filters=None, selected_ids=None, sort=None):
        if name not in DROPDOWN_FIELDS:
            raise FieldError("Choice", "FieldName")
        values = {field.name: "" for field in DROPDOWN_FILTER_FIELDS} if filters is None else filters
        clean = validate_fields(DROPDOWN_FILTER_FIELDS, values)
        order = self.load_sort("DropDownSort") if sort is None else normalize_sort(sort, DROPDOWN_COLUMNS)
        clauses, args = ["FieldName = ?", "Use = 1"], [name]
        if clean["ListItem"]:
            clauses.append("instr(lower(ListItem), lower(?)) > 0")
            args.append(clean["ListItem"])
        if clean["Default"]:
            clauses.append("Def = ?")
            args.append(int(clean["Default"] == "Yes"))
        sql_order = ", ".join(
            f'"{field}"{" COLLATE NOCASE" if field in ("FieldName", "ListItem") else ""} {direction}'
            for field, direction in order
        )
        rows = [dict(row) for row in self.connection.execute(
            "SELECT * FROM Dropdown WHERE TableName = 'FabricPiece' AND "
            + " AND ".join(clauses) + f" ORDER BY {sql_order}", args,
        )]
        if selected_ids is not None:
            allowed = set(selected_ids)
            rows = [row for row in rows if row["ID"] in allowed]
        return rows

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

    def save_back_draft(self, back_name, quilt_width, quilt_length, margin, seam_allowance, layout):
        name = validate_fields(
            (Field("BackName", required=True),), {"BackName": back_name},
        )["BackName"]
        if (not layout.panels or len(layout.panels) > MAX_PANELS or layout.ratio_tier < 0
                or layout.direction not in ("single", "vertical", "horizontal")):
            raise FieldError("Required", "FabricPieceID")
        if (layout.target_width != quilt_width + 2 * margin
                or layout.target_length != quilt_length + 2 * margin
                or layout.seam_allowance != seam_allowance):
            raise FieldError("Conflict", "QuiltBack")
        timestamp = now()
        with self.connection:
            sources = {}
            source_cuts = {}
            for panel in layout.panels:
                if min(panel.finished_width, panel.finished_length) < MINIMUM_PART:
                    raise FieldError("Measurement", "Panel")
                source = self.get_piece(panel.source_id)
                if source["Revision"] != panel.source_revision or source["Status"] != "Available":
                    raise FieldError("Conflict", "FabricPieceID")
                if panel.palette_color not in PALETTE:
                    raise FieldError("Choice", "PaletteColor")
                if (panel.source_x < 0 or panel.source_y < 0
                        or panel.source_x + panel.cut_width > source["UsableWidth"]
                        or panel.source_y + panel.cut_length > source["UsableLength"]):
                    raise FieldError("Measurement", "Panel")
                expected_grain = (
                    "x" if source["GrainDirection"] == "Along Width" else
                    "y" if source["GrainDirection"] == "Along Length" else None
                )
                if panel.grain_axis != expected_grain:
                    raise FieldError("Conflict", "GrainDirection")
                rect = (panel.source_x, panel.source_y, panel.cut_width, panel.cut_length)
                for previous in source_cuts.setdefault(panel.source_id, []):
                    if (rect[0] < previous[0] + previous[2]
                            and previous[0] < rect[0] + rect[2]
                            and rect[1] < previous[1] + previous[3]
                            and previous[1] < rect[1] + rect[3]):
                        raise FieldError("Measurement", "Panel")
                source_cuts[panel.source_id].append(rect)
                sources[panel.source_id] = source
            known_grains = {panel.grain_axis for panel in layout.panels if panel.grain_axis}
            if layout.grain_consistent != (len(known_grains) <= 1):
                raise FieldError("Conflict", "GrainDirection")
            ordered = sorted(layout.panels, key=lambda panel: panel.number)
            if [panel.number for panel in ordered] != list(range(1, len(ordered) + 1)):
                raise FieldError("Measurement", "Panel")
            position = 0
            for index, panel in enumerate(ordered):
                joins = int(index > 0) + int(index < len(ordered) - 1)
                if layout.direction == "vertical":
                    valid = (
                        panel.x == position and panel.y == 0
                        and panel.finished_length == layout.target_length
                        and panel.cut_width == panel.finished_width + joins * seam_allowance
                        and panel.cut_length == layout.target_length
                    )
                    position += panel.finished_width
                elif layout.direction == "horizontal":
                    valid = (
                        panel.y == position and panel.x == 0
                        and panel.finished_width == layout.target_width
                        and panel.cut_length == panel.finished_length + joins * seam_allowance
                        and panel.cut_width == layout.target_width
                    )
                    position += panel.finished_length
                else:
                    valid = (
                        len(ordered) == 1 and panel.x == panel.y == 0
                        and panel.finished_width == layout.target_width
                        and panel.finished_length == layout.target_length
                        and panel.cut_width == layout.target_width
                        and panel.cut_length == layout.target_length
                    )
                if not valid:
                    raise FieldError("Measurement", "Panel")
            if ((layout.direction == "vertical" and position != layout.target_width)
                    or (layout.direction == "horizontal" and position != layout.target_length)):
                raise FieldError("Measurement", "Panel")
            cursor = self.connection.execute(
                "INSERT INTO QuiltBack (BackName, QuiltWidth, QuiltLength, Margin, SeamAllowance, "
                "BackWidth, BackLength, LayoutDirection, RatioTier, GrainConsistent, Status, "
                "DateCreated, DateModified) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Draft', ?, ?)",
                (name, quilt_width, quilt_length, margin, seam_allowance,
                 layout.target_width, layout.target_length,
                 "single" if len(layout.panels) == 1 else layout.direction,
                 layout.ratio_tier, int(layout.grain_consistent), timestamp, timestamp),
            )
            back_id = cursor.lastrowid
            self.connection.executemany(
                "INSERT INTO QuiltBackPanel (QuiltBackID, PanelNumber, FabricPieceID, "
                "SourceRevision, FabricName, InventoryColor, SourceGrain, SourceWidth, "
                "SourceLength, PaletteColor, "
                "CutWidth, CutLength, FinishedWidth, "
                "FinishedLength, GrainAxis, SourceX, SourceY, X, Y) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ((back_id, panel.number, panel.source_id, panel.source_revision,
                  panel.source_name, panel.source_color, sources[panel.source_id]["GrainDirection"],
                  sources[panel.source_id]["UsableWidth"], sources[panel.source_id]["UsableLength"],
                  panel.palette_color, panel.cut_width, panel.cut_length, panel.finished_width,
                  panel.finished_length, panel.grain_axis, panel.source_x, panel.source_y,
                  panel.x, panel.y)
                 for panel in layout.panels),
            )
        return back_id

    def quilt_backs(self):
        return [dict(row) for row in self.connection.execute(
            "SELECT ID, BackName, BackWidth, BackLength, Status, DateModified "
            "FROM QuiltBack ORDER BY DateModified DESC, ID DESC",
        )]

    def get_quilt_back(self, back_id):
        row = self.connection.execute("SELECT * FROM QuiltBack WHERE ID = ?", (back_id,)).fetchone()
        if row is None:
            raise FieldError("MissingRecord", "QuiltBackID")
        back = dict(row)
        back["Panels"] = [dict(panel) for panel in self.connection.execute(
            "SELECT * FROM QuiltBackPanel WHERE QuiltBackID = ? ORDER BY PanelNumber", (back_id,),
        )]
        return back

    def confirm_back_cut(self, back_id, remnants):
        """Record operator-reported cuts and remnants with inventory history atomically."""
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            back = self.get_quilt_back(back_id)
            if back["Status"] != "Draft":
                raise FieldError("Conflict", "QuiltBackID")
            panels_by_source = {}
            for panel in back["Panels"]:
                panels_by_source.setdefault(panel["FabricPieceID"], []).append(panel)
            if set(remnants) != set(panels_by_source):
                raise FieldError("Binding", "Remnants", detail="one remainder entry is required per source piece")
            timestamp = now()
            for source_id, panels in panels_by_source.items():
                source = self.get_piece(source_id)
                expected_revision = panels[0]["SourceRevision"]
                if (any(panel["SourceRevision"] != expected_revision for panel in panels)
                        or source["Revision"] != expected_revision or source["Status"] != "Available"):
                    raise FieldError("Conflict", "FabricPieceID")
                planned_cut_area = sum(panel["CutWidth"] * panel["CutLength"] for panel in panels)
                remaining = remnants[source_id]
                remnant_values = None
                if remaining is not None:
                    if not isinstance(remaining, (tuple, list)) or len(remaining) != 2:
                        raise FieldError("Binding", "Remnants", detail="a remnant needs width and length")
                    width = measurement(str(remaining[0]), "UsableWidth")
                    length = measurement(str(remaining[1]), "UsableLength")
                    remnant_values = {
                        **{name: source[name] for name in FABRIC_NAMES},
                        "UsableWidth": width,
                        "UsableLength": length,
                        "Status": "Available",
                        "Notes": f"Reusable remnant from Quilt Back {back_id}, source {source_id}.",
                    }
                before = source
                cursor = self.connection.execute(
                    "UPDATE FabricPiece SET Status = 'Retired', Revision = Revision + 1, "
                    "DateModified = ? WHERE ID = ? AND Revision = ? AND Status = 'Available'",
                    (timestamp, source_id, expected_revision),
                )
                if cursor.rowcount != 1:
                    raise FieldError("Conflict", "FabricPieceID")
                after = self.get_piece(source_id)
                self.connection.execute(
                    "INSERT INTO FabricHistory (FabricPieceID, Action, BeforeValues, AfterValues, DateCreated) "
                    "VALUES (?, 'Updated', ?, ?, ?)",
                    (source_id, json.dumps(before), json.dumps(after), timestamp),
                )
                remnant_id = self._add_piece_in_transaction(remnant_values, timestamp) if remnant_values else None
                self.connection.execute(
                    "INSERT INTO QuiltBackCutSource (QuiltBackID, FabricPieceID, SourceRevision, "
                    "BeforeValues, AfterValues, PlannedCutArea, RemnantPieceID) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (back_id, source_id, expected_revision, json.dumps(before), json.dumps(after),
                     planned_cut_area, remnant_id),
                )
            self.connection.execute(
                "UPDATE QuiltBack SET Status = 'Cut', DateModified = ? WHERE ID = ? AND Status = 'Draft'",
                (timestamp, back_id),
            )
            self.connection.commit()
        except (sqlite3.Error, FieldError, TypeError, ValueError):
            self.connection.rollback()
            raise
        return self.get_quilt_back(back_id)

    def _add_piece_in_transaction(self, values, timestamp):
        clean = dict(values)
        for name in DROPDOWN_FIELDS:
            clean[name] = self._dropdown_item(name, clean[name])
        columns = ", ".join(FABRIC_NAMES)
        placeholders = ", ".join("?" for _ in FABRIC_NAMES)
        cursor = self.connection.execute(
            f"INSERT INTO FabricPiece ({columns}, DateCreated, DateModified) "
            f"VALUES ({placeholders}, ?, ?)",
            (*(clean[name] for name in FABRIC_NAMES), timestamp, timestamp),
        )
        piece_id = cursor.lastrowid
        after = self.get_piece(piece_id)
        self.connection.execute(
            "INSERT INTO FabricHistory (FabricPieceID, Action, BeforeValues, AfterValues, DateCreated) "
            "VALUES (?, 'Added', NULL, ?, ?)",
            (piece_id, json.dumps(after), timestamp),
        )
        return piece_id

    def mark_quilt_back_assembled(self, back_id):
        with self.connection:
            cursor = self.connection.execute(
                "UPDATE QuiltBack SET Status = 'Assembled', DateModified = ? "
                "WHERE ID = ? AND Status = 'Cut'", (now(), back_id),
            )
            if cursor.rowcount != 1:
                if self.connection.execute(
                    "SELECT 1 FROM QuiltBack WHERE ID = ?", (back_id,),
                ).fetchone() is None:
                    raise FieldError("MissingRecord", "QuiltBackID")
                raise FieldError("Conflict", "QuiltBackID")
        return self.get_quilt_back(back_id)

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

    def history(self, piece_id, filters=None, selected_ids=None, sort=None):
        self.get_piece(piece_id)
        values = {field.name: "" for field in HISTORY_FILTER_FIELDS} if filters is None else filters
        clean = validate_fields(HISTORY_FILTER_FIELDS, values)
        order = self.load_sort("HistorySort") if sort is None else normalize_sort(sort, HISTORY_COLUMNS)
        clauses, args = ["FabricPieceID = ?"], [piece_id]
        if clean["Action"]:
            clauses.append("Action = ?")
            args.append(clean["Action"])
        if clean["DateCreated"]:
            clauses.append("instr(lower(DateCreated), lower(?)) > 0")
            args.append(clean["DateCreated"])
        if clean["Values"]:
            clauses.append(
                "instr(lower(coalesce(BeforeValues, '') || ' ' || coalesce(AfterValues, '')), lower(?)) > 0"
            )
            args.append(clean["Values"])
        sql_order = ", ".join(
            f'"{field}" COLLATE NOCASE {direction}' for field, direction in order
        )
        rows = [dict(row) for row in self.connection.execute(
            "SELECT * FROM FabricHistory WHERE " + " AND ".join(clauses) + f" ORDER BY {sql_order}", args,
        )]
        if selected_ids is not None:
            allowed = set(selected_ids)
            rows = [row for row in rows if row["ID"] in allowed]
        return rows

    def _working_list_scope(self, screen, scope):
        if screen not in WORKING_LIST_SCREENS:
            raise FieldError("Choice", "Screen")
        if screen == "DropDown":
            if scope not in DROPDOWN_FIELDS:
                raise FieldError("Choice", "FieldName")
            return scope
        if screen == "History":
            try:
                piece_id = int(scope)
            except (TypeError, ValueError) as error:
                raise FieldError("Choice", "FabricPieceID") from error
            self.get_piece(piece_id)
            return str(piece_id)
        if scope not in (None, ""):
            raise FieldError("Choice", "Screen")
        return ""

    def _working_list_rows(self, screen, scope):
        if screen == "DropDown":
            return self.dropdown_rows(scope)
        if screen == "History":
            return self.history(int(scope))
        return self.help_rows()

    def save_set(self, name, ids, screen="Fabric", scope=None):
        if screen in WORKING_LIST_SCREENS:
            scope_name = self._working_list_scope(screen, scope)
            name = validate_fields((Field("SetName", required=True),), {"SetName": name})["SetName"]
            ids = sorted(set(ids))
            if not ids:
                raise FieldError("EmptySet", "SetName")
            valid_ids = {row["ID"] for row in self._working_list_rows(screen, scope_name)}
            if any(record_id not in valid_ids for record_id in ids):
                raise FieldError("MissingRecord", screen)
            with self.connection:
                if self.connection.execute(
                    "SELECT 1 FROM WorkingListSet WHERE ScreenName = ? AND ScopeName = ? "
                    "AND SetName = ? COLLATE NOCASE", (screen, scope_name, name),
                ).fetchone():
                    raise FieldError("DuplicateSet", "SetName")
                cursor = self.connection.execute(
                    "INSERT INTO WorkingListSet (ScreenName, ScopeName, SetName, DateCreated) "
                    "VALUES (?, ?, ?, ?)", (screen, scope_name, name, now()),
                )
                self.connection.executemany(
                    "INSERT INTO WorkingListMember (SelectionSetID, RecordID) VALUES (?, ?)",
                    ((cursor.lastrowid, record_id) for record_id in ids),
                )
                return cursor.lastrowid
        table, members, column = SELECTION_TABLES[screen]
        name = validate_fields((Field("SetName", required=True),), {"SetName": name})["SetName"]
        ids = sorted(set(ids))
        if not ids:
            raise FieldError("EmptySet", "SetName")
        with self.connection:
            if self.connection.execute(
                    f"SELECT 1 FROM {table} WHERE SetName = ? COLLATE NOCASE", (name,)).fetchone():
                raise FieldError("DuplicateSet", "SetName")
            for record_id in ids:
                (self.get_piece if screen == "Fabric" else self.get_error)(record_id)
            cursor = self.connection.execute(
                f"INSERT INTO {table} (SetName, DateCreated) VALUES (?, ?)", (name, now()),
            )
            self.connection.executemany(
                f"INSERT INTO {members} (SelectionSetID, {column}) VALUES (?, ?)",
                ((cursor.lastrowid, piece_id) for piece_id in ids),
            )
            return cursor.lastrowid

    def sets(self, screen="Fabric", scope=None):
        if screen in WORKING_LIST_SCREENS:
            scope_name = self._working_list_scope(screen, scope)
            return [dict(row) for row in self.connection.execute(
                "SELECT s.ID, s.SetName, count(m.RecordID) AS RecordCount "
                "FROM WorkingListSet s LEFT JOIN WorkingListMember m ON s.ID = m.SelectionSetID "
                "WHERE s.ScreenName = ? AND s.ScopeName = ? "
                "GROUP BY s.ID ORDER BY s.SetName COLLATE NOCASE, s.ID",
                (screen, scope_name),
            )]
        table, members, column = SELECTION_TABLES[screen]
        return [dict(row) for row in self.connection.execute(
            f"SELECT s.ID, s.SetName, count(m.{column}) AS RecordCount "
            f"FROM {table} s LEFT JOIN {members} m ON s.ID = m.SelectionSetID "
            "GROUP BY s.ID ORDER BY s.SetName COLLATE NOCASE, s.ID",
        )]

    def set_members(self, set_id, screen="Fabric", scope=None):
        if screen in WORKING_LIST_SCREENS:
            scope_name = self._working_list_scope(screen, scope)
            if self.connection.execute(
                "SELECT 1 FROM WorkingListSet WHERE ID = ? AND ScreenName = ? AND ScopeName = ?",
                (set_id, screen, scope_name),
            ).fetchone() is None:
                raise FieldError("MissingRecord", "SelectionSetID")
            return [row[0] for row in self.connection.execute(
                "SELECT RecordID FROM WorkingListMember WHERE SelectionSetID = ? ORDER BY RecordID",
                (set_id,),
            )]
        table, members, column = SELECTION_TABLES[screen]
        if self.connection.execute(f"SELECT 1 FROM {table} WHERE ID = ?", (set_id,)).fetchone() is None:
            raise FieldError("MissingRecord", "SelectionSetID")
        return [row[0] for row in self.connection.execute(
            f"SELECT {column} FROM {members} WHERE SelectionSetID = ? ORDER BY {column}",
            (set_id,),
        )]

    def delete_set(self, set_id, screen="Fabric", scope=None):
        if screen in WORKING_LIST_SCREENS:
            scope_name = self._working_list_scope(screen, scope)
            with self.connection:
                cursor = self.connection.execute(
                    "DELETE FROM WorkingListSet WHERE ID = ? AND ScreenName = ? AND ScopeName = ?",
                    (set_id, screen, scope_name),
                )
                if cursor.rowcount != 1:
                    raise FieldError("MissingRecord", "SelectionSetID")
            return
        table, _, _ = SELECTION_TABLES[screen]
        with self.connection:
            cursor = self.connection.execute(f"DELETE FROM {table} WHERE ID = ?", (set_id,))
            if cursor.rowcount != 1:
                raise FieldError("MissingRecord", "SelectionSetID")

    def save_sort(self, sort, screen="FabricInventorySort"):
        fields, _ = SAVED_SORTS[screen]
        clean = normalize_sort(sort, fields)
        with self.connection:
            self.connection.execute(
                "INSERT INTO ScreenState VALUES (?, ?) "
                "ON CONFLICT(ScreenName) DO UPDATE SET StateValues = excluded.StateValues",
                (screen, json.dumps(clean)),
            )

    def load_sort(self, screen="FabricInventorySort"):
        fields, default = SAVED_SORTS[screen]
        row = self.connection.execute(
            "SELECT StateValues FROM ScreenState WHERE ScreenName = ?", (screen,),
        ).fetchone()
        if row is None:
            return default
        try:
            return normalize_sort(json.loads(row[0]), fields)
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
