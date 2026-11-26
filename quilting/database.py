"""SQLite persistence. Draft planning must never change physical inventory."""

import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .backs import MAX_PANELS, MINIMUM_PART, PALETTE
from .blocks import BLOCK_COLUMNS, BLOCK_FILTER_FIELDS, parse_block, parse_part, validate_layout
from .block_templates import BLOCK_TEMPLATES, build_block_template
from .quilt_planner import plan_quilt
from .helptext import (
    BACK_COLUMNS, BACK_FILTER_FIELDS, DROPDOWN_COLUMNS, DROPDOWN_FILTER_FIELDS,
    HELP_COLUMNS, HELP_FIELDS, HELP_FILTER_FIELDS,
    HISTORY_COLUMNS, HISTORY_FILTER_FIELDS, SYSTEM_DROPDOWNS, DROPDOWN_LIST_FIELDS,
    PROTECTED_LIST_HELP, DYNAMIC_LIST_HELP, default_help,
)
from .errors import (
    BLOCK_CONFLICT_MESSAGES, ERROR_COLUMNS, ERROR_FIELDS, ERROR_FILTER_FIELDS, OLD_CONFLICT_REFERENCE,
    STARTUP_MESSAGES, TROUBLESHOOTING,
)
from .model import (
    ADD_ITEM, DEFAULT_SORT, DROPDOWN_FIELDS, FABRIC_FIELDS, FABRIC_NAMES, FILTER_FIELDS, MESSAGES,
    SORT_FIELDS, Field, FieldError, caption, measurement, normalize_sort, validate_fields,
)

APPLICATION_ID = 0x5155494C
SCHEMA_VERSION = 16


class MissingHelp(FieldError):
    def __init__(self, screen, name):
        super().__init__("DatabaseFormat", "HelpText", detail=f"Missing help for {screen}/{name}.")


BLOCK_SCHEMA = """
CREATE TABLE QuiltBlock (
    ID INTEGER PRIMARY KEY AUTOINCREMENT,
    ParentID INTEGER REFERENCES QuiltBlock(ID),
    BlockName TEXT NOT NULL CHECK(length(trim(BlockName)) BETWEEN 1 AND 120),
    Description TEXT NOT NULL CHECK(length(Description) <= 4000),
    FinishedWidth INTEGER NOT NULL CHECK(FinishedWidth > 0),
    FinishedLength INTEGER NOT NULL CHECK(FinishedLength > 0),
    Scale TEXT NOT NULL,
    SeamAllowance INTEGER NOT NULL CHECK(SeamAllowance >= 0),
    Status TEXT NOT NULL CHECK(Status IN ('Draft', 'Approved')),
    Revision INTEGER NOT NULL DEFAULT 1 CHECK(Revision > 0),
    DateCreated TEXT NOT NULL,
    DateModified TEXT NOT NULL
);
CREATE TABLE BlockPart (
    ID INTEGER PRIMARY KEY AUTOINCREMENT,
    QuiltBlockID INTEGER NOT NULL REFERENCES QuiltBlock(ID) ON DELETE CASCADE,
    PartName TEXT NOT NULL,
    Shape TEXT NOT NULL,
    PartColor TEXT NOT NULL,
    NumberInBlock INTEGER NOT NULL CHECK(NumberInBlock BETWEEN 1 AND 1000),
    PartWidth INTEGER,
    PartLength INTEGER,
    SideA INTEGER,
    SideB INTEGER,
    SideC INTEGER,
    Diameter INTEGER,
    MinimumColorValue INTEGER CHECK(MinimumColorValue IS NULL OR
        (typeof(MinimumColorValue) = 'integer' AND MinimumColorValue BETWEEN 1 AND 10)),
    MaximumColorValue INTEGER CHECK((MaximumColorValue IS NULL AND MinimumColorValue IS NULL) OR
        (typeof(MaximumColorValue) = 'integer' AND MaximumColorValue BETWEEN 1 AND 10
         AND MinimumColorValue IS NOT NULL AND MinimumColorValue <= MaximumColorValue))
);
CREATE TABLE BlockPartPlacement (
    ID INTEGER PRIMARY KEY AUTOINCREMENT,
    BlockPartID INTEGER NOT NULL REFERENCES BlockPart(ID) ON DELETE CASCADE,
    Instance INTEGER NOT NULL CHECK(Instance > 0),
    X INTEGER NOT NULL CHECK(X >= 0),
    Y INTEGER NOT NULL CHECK(Y >= 0),
    Rotation INTEGER NOT NULL CHECK(Rotation BETWEEN 0 AND 359),
    Mirrored INTEGER NOT NULL CHECK(Mirrored IN (0, 1)),
    UNIQUE(BlockPartID, Instance)
);
CREATE TABLE BlockSet (
    ID INTEGER PRIMARY KEY AUTOINCREMENT,
    SetName TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK(length(trim(SetName)) BETWEEN 1 AND 120),
    DateCreated TEXT NOT NULL
);
CREATE TABLE BlockSetMember (
    SelectionSetID INTEGER NOT NULL REFERENCES BlockSet(ID) ON DELETE CASCADE,
    QuiltBlockID INTEGER NOT NULL REFERENCES QuiltBlock(ID) ON DELETE CASCADE,
    PRIMARY KEY (SelectionSetID, QuiltBlockID)
);
CREATE TABLE Quilt (
    ID INTEGER PRIMARY KEY AUTOINCREMENT,
    QuiltName TEXT NOT NULL CHECK(length(trim(QuiltName)) BETWEEN 1 AND 120),
    Revision INTEGER NOT NULL DEFAULT 1 CHECK(Revision > 0),
    DateCreated TEXT NOT NULL,
    DateModified TEXT NOT NULL
);
CREATE TABLE QuiltBlockUse (
    QuiltID INTEGER NOT NULL REFERENCES Quilt(ID) ON DELETE CASCADE,
    QuiltBlockID INTEGER NOT NULL REFERENCES QuiltBlock(ID),
    Quantity INTEGER NOT NULL CHECK(Quantity BETWEEN 1 AND 10000),
    PRIMARY KEY (QuiltID, QuiltBlockID)
);
CREATE TABLE QuiltColorMap (
    QuiltID INTEGER NOT NULL REFERENCES Quilt(ID) ON DELETE CASCADE,
    PartColor TEXT NOT NULL,
    InventoryColor TEXT NOT NULL COLLATE NOCASE,
    PRIMARY KEY (QuiltID, PartColor, InventoryColor)
);
CREATE TABLE QuiltPartFabric (
    QuiltID INTEGER NOT NULL,
    QuiltBlockID INTEGER NOT NULL,
    BlockPartID INTEGER NOT NULL REFERENCES BlockPart(ID) ON DELETE CASCADE,
    FabricPieceID INTEGER NOT NULL REFERENCES FabricPiece(ID),
    PRIMARY KEY (QuiltID, BlockPartID, FabricPieceID),
    FOREIGN KEY (QuiltID, QuiltBlockID) REFERENCES QuiltBlockUse(QuiltID, QuiltBlockID) ON DELETE CASCADE
);
CREATE TABLE QuiltPlan (
    ID INTEGER PRIMARY KEY AUTOINCREMENT,
    QuiltID INTEGER NOT NULL REFERENCES Quilt(ID),
    QuiltRevision INTEGER NOT NULL,
    PlanData TEXT NOT NULL,
    DateCreated TEXT NOT NULL
);
"""
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
    ScreenName TEXT NOT NULL CHECK(ScreenName IN ('DropDown', 'HelpText', 'History', 'Quilt Backs')),
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
    TableName TEXT NOT NULL CHECK(length(trim(TableName)) BETWEEN 1 AND 120),
    FieldName TEXT NOT NULL CHECK(length(trim(FieldName)) BETWEEN 1 AND 120),
    ListItem TEXT NOT NULL COLLATE NOCASE CHECK(length(ListItem) <= 120),
    Def INTEGER NOT NULL DEFAULT 0 CHECK(Def IN (0, 1)),
    Use INTEGER NOT NULL DEFAULT 1 CHECK(Use IN (0, 1)),
    UserModified INTEGER NOT NULL DEFAULT 1 CHECK(UserModified IN (0, 1)),
    UNIQUE(TableName, FieldName, ListItem)
);
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
    DateModified TEXT NOT NULL,
    SideMargin INTEGER NOT NULL CHECK(SideMargin >= 0)
);
CREATE TABLE QuiltBackPanel (
    QuiltBackID INTEGER NOT NULL REFERENCES QuiltBack(ID) ON DELETE CASCADE,
    PanelNumber INTEGER NOT NULL CHECK(PanelNumber > 0),
    FabricPieceID INTEGER NOT NULL REFERENCES FabricPiece(ID),
    SourceRevision INTEGER NOT NULL CHECK(SourceRevision > 0),
    FabricName TEXT NOT NULL CHECK(length(trim(FabricName)) BETWEEN 1 AND 120),
    InventoryColor TEXT CHECK(InventoryColor IS NULL OR length(InventoryColor) <= 120),
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
    QuiltBackID INTEGER NOT NULL REFERENCES QuiltBack(ID) ON DELETE CASCADE,
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
    Color TEXT CHECK(Color IS NULL OR length(Color) <= 120),
    FabricPattern TEXT CHECK(FabricPattern IS NULL OR length(FabricPattern) <= 120),
    UsableWidth INTEGER NOT NULL CHECK(typeof(UsableWidth) = 'integer'
        AND UsableWidth BETWEEN 1 AND 100000000000),
    UsableLength INTEGER NOT NULL CHECK(typeof(UsableLength) = 'integer'
        AND UsableLength BETWEEN 1 AND 100000000000),
    GrainDirection TEXT NOT NULL CHECK(GrainDirection IN ('Unknown', 'Along Length', 'Along Width')),
    PrintDirection TEXT NOT NULL CHECK(PrintDirection IN
        ('Unknown', 'Non-directional', 'Along Length', 'Along Width')),
    StorageLocation TEXT CHECK(StorageLocation IS NULL OR length(StorageLocation) <= 120),
    Status TEXT NOT NULL CHECK(Status IN ('Available', 'Retired')),
    Notes TEXT NOT NULL CHECK(length(Notes) <= 4000),
    Revision INTEGER NOT NULL DEFAULT 1 CHECK(Revision >= 1),
    DateCreated TEXT NOT NULL,
    DateModified TEXT NOT NULL,
    ColorValue INTEGER CHECK(ColorValue IS NULL OR
        (typeof(ColorValue) = 'integer' AND ColorValue BETWEEN 1 AND 10))
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
""" + DROPDOWN_SCHEMA + HELP_SCHEMA + ERROR_SCHEMA + WORKING_LIST_SCHEMA + BACK_SCHEMA + BLOCK_SCHEMA
TABLE_COLUMNS = {
    "FabricPiece": ("ID", *(name for name in FABRIC_NAMES if name != "ColorValue"),
                    "Revision", "DateCreated", "DateModified", "ColorValue"),
    "FabricHistory": ("ID", "FabricPieceID", "Action", "BeforeValues", "AfterValues", "DateCreated"),
    "SelectionSet": ("ID", "SetName", "DateCreated"),
    "SelectionMember": ("SelectionSetID", "FabricPieceID"),
    "ErrorText": ("ErrorTextID", "MessageKey", "Description", "MessageTemplate", "ResolutionText"),
    "ScreenState": ("ScreenName", "StateValues"),
    "Dropdown": ("ID", "TableName", "FieldName", "ListItem", "Def", "Use", "UserModified"),
    "HelpText": HELP_COLUMNS,
    "ErrorMessage": ERROR_COLUMNS,
    "ErrorMessageSet": ("ID", "SetName", "DateCreated"),
    "ErrorMessageMember": ("SelectionSetID", "ErrorMessageID"),
    "WorkingListSet": ("ID", "ScreenName", "ScopeName", "SetName", "DateCreated"),
    "WorkingListMember": ("SelectionSetID", "RecordID"),
    "QuiltBack": (
        "ID", "BackName", "QuiltWidth", "QuiltLength", "Margin", "SeamAllowance",
        "BackWidth", "BackLength", "LayoutDirection", "RatioTier", "GrainConsistent",
        "Status", "DateCreated", "DateModified", "SideMargin",
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
    "QuiltBlock": ("ID", "ParentID", "BlockName", "Description", "FinishedWidth", "FinishedLength",
                   "Scale", "SeamAllowance", "Status", "Revision", "DateCreated", "DateModified"),
    "BlockPart": ("ID", "QuiltBlockID", "PartName", "Shape", "PartColor", "NumberInBlock",
                  "PartWidth", "PartLength", "SideA", "SideB", "SideC", "Diameter",
                  "MinimumColorValue", "MaximumColorValue"),
    "BlockPartPlacement": ("ID", "BlockPartID", "Instance", "X", "Y", "Rotation", "Mirrored"),
    "BlockSet": ("ID", "SetName", "DateCreated"),
    "BlockSetMember": ("SelectionSetID", "QuiltBlockID"),
    "Quilt": ("ID", "QuiltName", "Revision", "DateCreated", "DateModified"),
    "QuiltBlockUse": ("QuiltID", "QuiltBlockID", "Quantity"),
    "QuiltColorMap": ("QuiltID", "PartColor", "InventoryColor"),
    "QuiltPartFabric": ("QuiltID", "QuiltBlockID", "BlockPartID", "FabricPieceID"),
    "QuiltPlan": ("ID", "QuiltID", "QuiltRevision", "PlanData", "DateCreated"),
}
SAVED_SORTS = {
    "FabricInventorySort": (SORT_FIELDS, DEFAULT_SORT),
    "DropDownSort": (DROPDOWN_COLUMNS,
                     (("Def", "desc"), ("ListItem", "asc"), ("ID", "asc"))),
    "DropDownAllSort": (DROPDOWN_COLUMNS,
                        (("TableName", "asc"), ("Def", "desc"), ("FieldName", "asc"),
                         ("ListItem", "asc"), ("ID", "asc"))),
    "HelpTextSort": (HELP_COLUMNS, (("TableName", "asc"), ("FieldName", "asc"), ("ID", "asc"))),
    "ErrorMessageSort": (ERROR_COLUMNS, (("ID", "asc"),)),
    "HistorySort": (("ID", "Action", "DateCreated"),
                    (("ID", "desc"),)),
    "QuiltBlockSort": (BLOCK_COLUMNS, (("BlockName", "asc"), ("ID", "asc"))),
    "QuiltBackSort": (BACK_COLUMNS, (("DateModified", "desc"), ("ID", "desc"))),
}
SELECTION_TABLES = {
    "Fabric": ("SelectionSet", "SelectionMember", "FabricPieceID"),
    "ErrorMessage": ("ErrorMessageSet", "ErrorMessageMember", "ErrorMessageID"),
    "QuiltBlock": ("BlockSet", "BlockSetMember", "QuiltBlockID"),
}
WORKING_LIST_SCREENS = frozenset(("DropDown", "HelpText", "History", "Quilt Backs"))
DROPDOWN_SCOPE_FIELDS = {
    **DROPDOWN_LIST_FIELDS,
}
ALL_DROPDOWN_ROWS = "Show Everything"
ALL_DROPDOWN_SCOPE = (ALL_DROPDOWN_ROWS, "")


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
                  tuple(range(1, SCHEMA_VERSION))):
                self.validate(self.connection, allow_legacy=True)
                if not upgrade:
                    raise UpgradeRequired()
                self._upgrade()
            self.validate(self.connection)
            with self.connection:
                self._seed_help()
                self._update_conflict_reference()
        except (sqlite3.Error, OSError, FieldError):
            self.connection.close()
            raise

    def close(self):
        self.connection.close()

    @staticmethod
    def validate(connection, allow_legacy=False):
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if (connection.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID
                or version not in ((*range(1, SCHEMA_VERSION), SCHEMA_VERSION)
                                   if allow_legacy else (SCHEMA_VERSION,))):
            raise FieldError("DatabaseFormat", "Database", detail="Unsupported database or schema version.")
        for table, expected in TABLE_COLUMNS.items():
            if version < 16 and table == "QuiltPartFabric":
                continue
            if version < 9 and table in ("QuiltBlock", "BlockPart", "BlockPartPlacement", "BlockSet",
                                         "BlockSetMember", "Quilt", "QuiltBlockUse", "QuiltColorMap", "QuiltPlan"):
                continue
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
            if version < 15 and table == "FabricPiece":
                expected = expected[:-1]
            if version < 15 and table == "BlockPart":
                expected = expected[:-2]
            if table == "FabricPiece" and version < 14:
                expected = tuple("PatternName" if name == "FabricPattern" else name for name in expected)
            if table == "Dropdown" and version < 11:
                expected = expected[:-1]
            if table == "QuiltBack" and version < 13:
                expected = expected[:-1]
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
        self.connection.execute("PRAGMA foreign_keys = OFF")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.validate(self.connection, allow_legacy=True)
            version = self.connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in tuple(range(1, SCHEMA_VERSION)):
                raise FieldError("DatabaseFormat", "Database", detail="Database version changed during upgrade.")
            schema = ((DROPDOWN_SCHEMA if version == 1 else "")
                      + (HELP_SCHEMA if version < 3 else "")
                      + (ERROR_SCHEMA if version < 4 else "")
                      + (WORKING_LIST_SCHEMA if version < 5 else "")
                      + (BACK_SCHEMA if version < 6 else "") + (BLOCK_SCHEMA if version < 9 else ""))
            if 5 <= version < 7:
                self.connection.execute("ALTER TABLE WorkingListMember RENAME TO OldWorkingListMember")
                self.connection.execute("ALTER TABLE WorkingListSet RENAME TO OldWorkingListSet")
                schema += WORKING_LIST_SCHEMA
            for statement in schema.split(";"):
                if statement.strip():
                    self.connection.execute(statement)
            if 5 <= version < 7:
                self.connection.execute("INSERT INTO WorkingListSet SELECT * FROM OldWorkingListSet")
                self.connection.execute("INSERT INTO WorkingListMember SELECT * FROM OldWorkingListMember")
                self.connection.execute("DROP TABLE OldWorkingListMember")
                self.connection.execute("DROP TABLE OldWorkingListSet")
            if version < 14:
                self._upgrade_fabric_pattern()
            if version >= 5:
                self._upgrade_dropdown_scopes(version)
            if 2 <= version < 8:
                self._upgrade_dropdown_schema(version)
            elif 8 <= version < 11:
                self.connection.execute("DROP INDEX IF EXISTS DropdownDefaultIndex")
                self.connection.execute(
                    "ALTER TABLE Dropdown ADD COLUMN UserModified INTEGER NOT NULL DEFAULT 1 "
                    "CHECK(UserModified IN (0, 1))")
            if version == 1:
                self._seed_dropdowns()
                message = next(message for message in MESSAGES if message[0] == "Measurement")
                self.connection.execute(
                    "UPDATE ErrorText SET Description = ?, MessageTemplate = ?, ResolutionText = ? "
                    "WHERE MessageKey = ?", (*message[1:], message[0]),
                )
            if version < 11:
                self._upgrade_fabric_nullability()
            if version < 12:
                self._upgrade_back_panel_nullability()
            if 6 <= version < 13:
                self.connection.execute(
                    "ALTER TABLE QuiltBack ADD COLUMN SideMargin INTEGER NOT NULL DEFAULT 0 "
                    "CHECK(SideMargin >= 0)")
                self.connection.execute("UPDATE QuiltBack SET SideMargin = Margin")
            if version < 15:
                self.connection.execute(
                    "ALTER TABLE FabricPiece ADD COLUMN ColorValue INTEGER CHECK(ColorValue IS NULL OR "
                    "(typeof(ColorValue) = 'integer' AND ColorValue BETWEEN 1 AND 10))")
                if version >= 9:
                    self.connection.execute(
                        "ALTER TABLE BlockPart ADD COLUMN MinimumColorValue INTEGER "
                        "CHECK(MinimumColorValue IS NULL OR "
                        "(typeof(MinimumColorValue) = 'integer' AND MinimumColorValue BETWEEN 1 AND 10))")
                    self.connection.execute(
                        "ALTER TABLE BlockPart ADD COLUMN MaximumColorValue INTEGER "
                        "CHECK((MaximumColorValue IS NULL AND MinimumColorValue IS NULL) OR "
                        "(typeof(MaximumColorValue) = 'integer' AND MaximumColorValue BETWEEN 1 AND 10 "
                        "AND MinimumColorValue IS NOT NULL AND MinimumColorValue <= MaximumColorValue))")
            if version >= 9:
                self.connection.execute("""
                    CREATE TABLE QuiltPartFabric (
                        QuiltID INTEGER NOT NULL,
                        QuiltBlockID INTEGER NOT NULL,
                        BlockPartID INTEGER NOT NULL REFERENCES BlockPart(ID) ON DELETE CASCADE,
                        FabricPieceID INTEGER NOT NULL REFERENCES FabricPiece(ID),
                        PRIMARY KEY (QuiltID, BlockPartID, FabricPieceID),
                        FOREIGN KEY (QuiltID, QuiltBlockID)
                            REFERENCES QuiltBlockUse(QuiltID, QuiltBlockID) ON DELETE CASCADE
                    )
                """)
            self.connection.execute(
                "DELETE FROM WorkingListMember WHERE SelectionSetID IN "
                "(SELECT ID FROM WorkingListSet WHERE ScreenName = 'DropDown') "
                "AND RecordID IN (SELECT ID FROM Dropdown WHERE ListItem = '')")
            self.connection.execute("DELETE FROM Dropdown WHERE ListItem = ''")
            self.connection.execute("UPDATE Dropdown SET Def = 0 WHERE Use = 0")
            self._seed_system_dropdowns()
            self._seed_help()
            self._upgrade_quilt_help()
            if version < 13:
                self._upgrade_margin_help()
            if version < 4:
                self._seed_errors()
            self.connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self.validate(self.connection)
            self.connection.commit()
        except (sqlite3.Error, FieldError):
            self.connection.rollback()
            raise
        finally:
            self.connection.execute("PRAGMA foreign_keys = ON")

    def _upgrade_fabric_pattern(self):
        self.connection.execute("ALTER TABLE FabricPiece RENAME COLUMN PatternName TO FabricPattern")
        self.connection.execute(
            "UPDATE Dropdown SET FieldName = 'FabricPattern' "
            "WHERE TableName = 'FabricPiece' AND FieldName = 'PatternName'")
        defaults = default_help()
        for row in self.connection.execute(
                "SELECT ID, TableName, FieldName, HoverText, FullText FROM HelpText "
                "WHERE FieldName IN ('PatternName', 'Column:PatternName')").fetchall():
            new_name = row["FieldName"].replace("PatternName", "FabricPattern")
            pair = defaults.get((row["TableName"], new_name))
            hover, full = row["HoverText"], row["FullText"]
            if pair:
                old_pair = tuple(text.replace("Choose Fabric Pattern", "Choose PatternName")
                                 .replace("FabricPattern", "PatternName")
                                 .replace("fabric pattern", "pattern name")
                                 .replace("Fabric Pattern", "Pattern Name") for text in pair)
                hover = pair[0] if hover == old_pair[0] else hover
                full = pair[1] if full == old_pair[1] else full
            self.connection.execute(
                "UPDATE HelpText SET FieldName = ?, HoverText = ?, FullText = ? WHERE ID = ?",
                (new_name, hover, full, row["ID"]))
        saved = self.connection.execute(
            "SELECT StateValues FROM ScreenState WHERE ScreenName = 'FabricInventorySort'").fetchone()
        if saved:
            try:
                order = json.loads(saved["StateValues"])
                order = [("FabricPattern" if field == "PatternName" else field, direction)
                         for field, direction in order]
                order = normalize_sort(order)
            except (ValueError, TypeError) as error:
                raise FieldError("DatabaseFormat", "Sort", detail=f"Saved sort is invalid: {error}") from error
            self.connection.execute(
                "UPDATE ScreenState SET StateValues = ? WHERE ScreenName = 'FabricInventorySort'",
                (json.dumps(order),))
        for table in ("FabricHistory", "QuiltBackCutSource"):
            for row in self.connection.execute(
                    f"SELECT rowid AS snapshot_rowid, BeforeValues, AfterValues FROM {table}").fetchall():
                values = []
                changed = False
                for text in (row["BeforeValues"], row["AfterValues"]):
                    if text is None:
                        values.append(None)
                        continue
                    try:
                        snapshot = json.loads(text)
                    except (TypeError, ValueError) as error:
                        raise FieldError("DatabaseFormat", table, detail=f"Invalid saved snapshot: {error}") from error
                    if not isinstance(snapshot, dict):
                        raise FieldError("DatabaseFormat", table, detail="Invalid saved snapshot.")
                    if "PatternName" in snapshot:
                        snapshot = self._rename_pattern_snapshot(snapshot, table)
                        text = json.dumps(snapshot)
                        changed = True
                    values.append(text)
                if changed:
                    self.connection.execute(
                        f"UPDATE {table} SET BeforeValues = ?, AfterValues = ? WHERE rowid = ?",
                        (*values, row["snapshot_rowid"]))
        for row in self.connection.execute("SELECT ID, PlanData FROM QuiltPlan").fetchall():
            try:
                plan = json.loads(row["PlanData"])
                sources = plan["sources"]
                if not isinstance(sources, list):
                    raise ValueError("Plan sources must be a list.")
                changed = False
                for entry in sources:
                    source = entry["source"]
                    if not isinstance(source, dict):
                        raise ValueError("Plan source must be an object.")
                    if "PatternName" in source:
                        entry["source"] = self._rename_pattern_snapshot(source, "QuiltPlan")
                        changed = True
            except (TypeError, ValueError, KeyError) as error:
                raise FieldError("DatabaseFormat", "QuiltPlan", detail=f"Invalid saved plan: {error}") from error
            if changed:
                self.connection.execute("UPDATE QuiltPlan SET PlanData = ? WHERE ID = ?",
                                        (json.dumps(plan), row["ID"]))

    @staticmethod
    def _rename_pattern_snapshot(snapshot, table):
        if "FabricPattern" in snapshot:
            raise FieldError("DatabaseFormat", table, detail="Conflicting fabric pattern keys.")
        return {("FabricPattern" if key == "PatternName" else key): value for key, value in snapshot.items()}

    def _upgrade_dropdown_schema(self, version):
        self.connection.execute("DROP INDEX IF EXISTS DropdownDefaultIndex")
        self.connection.execute("ALTER TABLE Dropdown RENAME TO DropdownPrevious")
        for statement in DROPDOWN_SCHEMA.split(";"):
            if statement.strip():
                self.connection.execute(statement)
        self.connection.execute(
            "INSERT INTO Dropdown (ID, TableName, FieldName, ListItem, Def, Use) "
            "SELECT ID, TableName, FieldName, ListItem, Def, Use FROM DropdownPrevious",
        )
        self.connection.execute("DROP TABLE DropdownPrevious")

    def _upgrade_dropdown_scopes(self, version):
        for row in self.connection.execute(
                "SELECT ID, ScopeName FROM WorkingListSet WHERE ScreenName = 'DropDown'").fetchall():
            try:
                scope = json.loads(row["ScopeName"]) if version >= 8 else row["ScopeName"]
            except json.JSONDecodeError:
                scope = row["ScopeName"]
            if isinstance(scope, str):
                scope = ("FabricPiece", scope)
            elif isinstance(scope, list):
                scope = tuple(scope)
            if scope == ("FabricPiece", "PatternName"):
                scope = ("FabricPiece", "FabricPattern")
            if (not isinstance(scope, tuple) or len(scope) != 2
                    or not all(isinstance(part, str) for part in scope)
                    or scope[1] not in DROPDOWN_SCOPE_FIELDS.get(scope[0], ())):
                continue
            self.connection.execute(
                "UPDATE WorkingListSet SET ScopeName = ? WHERE ID = ?",
                (json.dumps(scope, separators=(",", ":")), row["ID"]),
            )

    def _upgrade_fabric_nullability(self):
        columns = ", ".join(name for name in FABRIC_NAMES if name != "ColorValue")
        values = ", ".join(
            f"NULLIF({name}, '')" if name in ("Color", "FabricPattern", "StorageLocation") else name
            for name in FABRIC_NAMES if name != "ColorValue"
        )
        self.connection.execute("""
            CREATE TABLE FabricPieceNullable (
        ID INTEGER PRIMARY KEY AUTOINCREMENT,
        FabricName TEXT NOT NULL CHECK(length(trim(FabricName)) BETWEEN 1 AND 120),
        Color TEXT CHECK(Color IS NULL OR length(Color) <= 120),
        FabricPattern TEXT CHECK(FabricPattern IS NULL OR length(FabricPattern) <= 120),
        UsableWidth INTEGER NOT NULL CHECK(typeof(UsableWidth) = 'integer'
            AND UsableWidth BETWEEN 1 AND 100000000000),
        UsableLength INTEGER NOT NULL CHECK(typeof(UsableLength) = 'integer'
            AND UsableLength BETWEEN 1 AND 100000000000),
        GrainDirection TEXT NOT NULL CHECK(GrainDirection IN ('Unknown', 'Along Length', 'Along Width')),
        PrintDirection TEXT NOT NULL CHECK(PrintDirection IN
            ('Unknown', 'Non-directional', 'Along Length', 'Along Width')),
        StorageLocation TEXT CHECK(StorageLocation IS NULL OR length(StorageLocation) <= 120),
        Status TEXT NOT NULL CHECK(Status IN ('Available', 'Retired')),
        Notes TEXT NOT NULL CHECK(length(Notes) <= 4000),
        Revision INTEGER NOT NULL DEFAULT 1 CHECK(Revision >= 1),
        DateCreated TEXT NOT NULL,
        DateModified TEXT NOT NULL
            )
        """)
        self.connection.execute(
            f"INSERT INTO FabricPieceNullable (ID, {columns}, Revision, DateCreated, DateModified) "
            f"SELECT ID, {values}, Revision, DateCreated, DateModified FROM FabricPiece")
        self.connection.execute("DROP TABLE FabricPiece")
        self.connection.execute("ALTER TABLE FabricPieceNullable RENAME TO FabricPiece")
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS FabricNameIndex ON FabricPiece(FabricName COLLATE NOCASE, ID)")
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS FabricHistoryPieceIndex ON FabricHistory(FabricPieceID, ID)")

    def _upgrade_back_panel_nullability(self):
        table_exists = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'QuiltBackPanel'",
        ).fetchone()
        if table_exists is None:
            return
        columns = tuple(row[1] for row in self.connection.execute("PRAGMA table_info(QuiltBackPanel)"))
        if columns != TABLE_COLUMNS["QuiltBackPanel"]:
            return
        inventory_color = next(
            row for row in self.connection.execute("PRAGMA table_info(QuiltBackPanel)")
            if row[1] == "InventoryColor"
        )
        if not inventory_color[3]:
            return
        self.connection.execute("""
            CREATE TABLE QuiltBackPanelNullable (
                QuiltBackID INTEGER NOT NULL REFERENCES QuiltBack(ID),
                PanelNumber INTEGER NOT NULL CHECK(PanelNumber > 0),
                FabricPieceID INTEGER NOT NULL REFERENCES FabricPiece(ID),
                SourceRevision INTEGER NOT NULL CHECK(SourceRevision > 0),
                FabricName TEXT NOT NULL CHECK(length(trim(FabricName)) BETWEEN 1 AND 120),
                InventoryColor TEXT CHECK(InventoryColor IS NULL OR length(InventoryColor) <= 120),
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
            )
        """)
        columns = ", ".join(TABLE_COLUMNS["QuiltBackPanel"])
        values = ", ".join(
            "NULLIF(InventoryColor, '')" if name == "InventoryColor" else name
            for name in TABLE_COLUMNS["QuiltBackPanel"]
        )
        self.connection.execute(
            f"INSERT INTO QuiltBackPanelNullable ({columns}) SELECT {values} FROM QuiltBackPanel")
        self.connection.execute("DROP TABLE QuiltBackPanel")
        self.connection.execute("ALTER TABLE QuiltBackPanelNullable RENAME TO QuiltBackPanel")

    def _seed_help(self):
        self.connection.executemany(
            "INSERT INTO HelpText (TableName, FieldName, HoverText, FullText) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(TableName, FieldName) DO NOTHING",
            ((screen, name, *pair) for (screen, name), pair in default_help().items()),
        )

    def _upgrade_margin_help(self):
        defaults = default_help()
        screen_hover, screen_full = defaults["Quilt Backs", "ScreenHelp"]
        previous_screen_full = screen_full.replace(
            "Enter the quilt size, separate top/bottom and side overhang margins, and one seam allowance. ",
            "Enter the quilt size, equal overhang margin and one seam allowance for the entire back. ",
        )
        for field, old_pair in (
            ("ScreenHelp", (screen_hover, previous_screen_full)),
            ("Margin", ("Set the same overhang on all four sides.",
                        "Backing target width and length each add twice this value to the quilt dimensions.")),
        ):
            hover, full = defaults["Quilt Backs", field]
            self.connection.execute(
                "UPDATE HelpText SET HoverText=?, FullText=? WHERE TableName='Quilt Backs' "
                "AND FieldName=? AND HoverText=? AND FullText=?",
                (hover, full, field, *old_pair),
            )

    def _upgrade_quilt_help(self):
        previous = {
            ("Eligible Fabrics", "ScreenHelp"): (
                "Review fabrics matching a block part's color value range.",
                "Choose a part to list value-eligible available fabric in the Fabric working "
                "selection. Map inventory colors on the Quilt screen; planning also checks "
                "those mappings and the size of each piece."),
            ("Eligible Fabrics", "BlockPartChoice"): (
                "Choose a block part.", "Select a part to see available fabric pieces "
                "that match its optional color value range."),
            ("Quilt", "Button:Eligible Fabrics"): (
                "Review fabric values for a block part.", "Choose an approved block, then "
                "review available pieces matching each part's color value range."),
            ("Quilt", "PartColor"): (
                "Enter part color.", "Enter the part color for this block or part. "
                "This is a system-generated protected list. The values are used in internal "
                "program logic and changing values can interfere with program operation. "
                "The user may change the default value using the DropDown system."),
            ("Quilt", "ScreenHelp"): (
                "Compose a quilt and plan its cuts.",
                "Create or select a quilt; choose approved block versions and their quantities. "
                "Map each part color to one or more inventory color values, then choose Plan Quilt. "
                "Plans pack conservative cut bounding rectangles, can report shortages and do not "
                "reserve or change inventory. Existing plans are snapshots; regenerate after changes. "
                "Available sources follow the Fabric working list. Eligible Fabrics lists pieces "
                "matching a selected part's optional color value range. Choose Entire Quilt or By Block, "
                "then Print Quilt Plan to print the saved plan."),
        }
        defaults = default_help()
        for (screen, field), old_pair in previous.items():
            self.connection.execute(
                "UPDATE HelpText SET HoverText=?, FullText=? WHERE TableName=? AND FieldName=? "
                "AND HoverText=? AND FullText=?",
                (*defaults[screen, field], screen, field, *old_pair))

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

    def _update_conflict_reference(self):
        self.connection.execute(
            "UPDATE ErrorMessage SET LikelyCause = ?, Description = ? "
            "WHERE ID = (SELECT ErrorTextID FROM ErrorText WHERE MessageKey = 'Conflict') "
            "AND ErrorText = (SELECT MessageTemplate FROM ErrorText WHERE MessageKey = 'Conflict') "
            "AND LikelyCause = ? AND Description = ?",
            (*TROUBLESHOOTING["Conflict"], *OLD_CONFLICT_REFERENCE),
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
            raise MissingHelp(screen, name)
        hover, full = tuple(row)
        if (screen, name) in DYNAMIC_LIST_HELP:
            notice = ("This is a dynamic list whose values come directly from the data. "
                      "This list does not use the DropDown system for setting or updating values.")
            if notice not in full:
                full = f"{full} {notice}"
        elif (screen, name) in PROTECTED_LIST_HELP:
            notice = ("This is a system-generated protected list. The values are used in internal "
                      "program logic and changing values can interfere with program operation. "
                      "The user may change the default value using the DropDown system.")
            if notice not in full:
                full = f"{full} {notice}"
        elif screen == "DropDown" and name == "ScreenHelp":
            notice = ("Only supported lists appear here. Dynamic menus whose values are determined "
                      "by data are outside the DropDown system. UserModified is read-only. Protected "
                      "items can only have their default changed, after confirmation.")
            if notice not in full:
                full = f"{full} {notice}"
            notice = ("Choose Show Everything in Table Name to view all dropdown rows. "
                      "Select a specific table and field to add an item.")
            if notice not in full:
                full = f"{full} {notice}"
        return hover, full

    def help_rows(self, filters=None, selected_ids=None, sort=None):
        values = {field.name: "" for field in HELP_FILTER_FIELDS} if filters is None else filters
        clean = validate_fields(HELP_FILTER_FIELDS, values)
        order = self.load_sort("HelpTextSort") if sort is None else normalize_sort(sort, HELP_COLUMNS)
        clauses, args = [], []
        for name, value in clean.items():
            if value:
                if name == "FieldName":
                    clauses.append("(instr(lower(FieldName), lower(?)) > 0 OR "
                                   "instr(lower(replace(FieldName, 'FabricPattern', 'Fabric Pattern')), lower(?)) > 0)")
                    args.extend((value, value))
                else:
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
            if field.kind == "dropdown":
                for row in self.connection.execute(f'SELECT DISTINCT "{name}" FROM FabricPiece ORDER BY ID'):
                    if row[0]:
                        self._dropdown_item(name, row[0])
        self._seed_system_dropdowns()

    def _seed_system_dropdowns(self):
        for (table_name, field_name), (items, default) in SYSTEM_DROPDOWNS.items():
            self.connection.execute(
                "UPDATE Dropdown SET UserModified = 0 WHERE TableName = ? AND FieldName = ?",
                (table_name, field_name),
            )
            placeholders = ", ".join("?" for _ in items)
            self.connection.execute(
                f"UPDATE Dropdown SET Def = 0 WHERE TableName = ? AND FieldName = ? "
                f"AND ListItem NOT IN ({placeholders})",
                (table_name, field_name, *items),
            )
            self.connection.execute(
                f"UPDATE Dropdown SET Use = 1 WHERE TableName = ? AND FieldName = ? "
                f"AND ListItem IN ({placeholders})",
                (table_name, field_name, *items),
            )
            current_defaults = self.connection.execute(
                "SELECT ListItem FROM Dropdown WHERE TableName = ? AND FieldName = ? "
                "AND Def = 1 AND Use = 1", (table_name, field_name),
            ).fetchall()
            keep_default = any(row["ListItem"] in items for row in current_defaults)
            for item in items:
                if not item:
                    continue
                self.connection.execute(
                    "INSERT OR IGNORE INTO Dropdown "
                    "(TableName, FieldName, ListItem, Def, Use, UserModified) VALUES (?, ?, ?, ?, 1, 0)",
                    (table_name, field_name, item,
                     int(not keep_default and bool(default) and item == default)),
                )


    def _dropdown_item(self, name, value, reactivate=False):
        field = DROPDOWN_FIELDS.get(name)
        if field is None:
            raise FieldError("Choice", "FieldName")
        if field.kind != "dropdown":
            raise FieldError("Database", "ListItem", detail="This system list is protected.")
        clean = validate_fields((field,), {name: value})[name]
        if clean.casefold() == ADD_ITEM.casefold():
            raise FieldError("Choice", name)
        row = self.connection.execute(
            "SELECT ID, ListItem FROM Dropdown WHERE TableName = 'FabricPiece' AND FieldName = ? "
            "AND ListItem = ? COLLATE NOCASE", (name, clean),
        ).fetchone()
        if row is not None:
            if reactivate:
                self.connection.execute(
                    "UPDATE Dropdown SET Use = 1, Def = 0 WHERE ID = ? AND Use = 0",
                    (row["ID"],),
                )
            return row["ListItem"]
        self.connection.execute(
            "INSERT INTO Dropdown (TableName, FieldName, ListItem, UserModified) "
            "VALUES ('FabricPiece', ?, ?, 1)",
            (name, clean),
        )
        return clean

    def add_dropdown_item(self, name, value, default=False, clear_other_defaults=False):
        if not isinstance(value, str) or not value.strip():
            raise FieldError("Required", name)
        if value.strip().casefold() == self.dropdown_placeholder(name).casefold():
            raise FieldError("Choice", name)
        with self._write_transaction():
            stored = self._dropdown_item(name, value, reactivate=True)
            if default:
                if clear_other_defaults:
                    self.connection.execute(
                        "UPDATE Dropdown SET Def = 0 WHERE TableName = 'FabricPiece' AND FieldName = ?",
                        (name,),
                    )
                self.connection.execute(
                    "UPDATE Dropdown SET Def = 1 WHERE TableName = 'FabricPiece' AND FieldName = ? "
                    "AND ListItem = ? COLLATE NOCASE", (name, stored),
                )
            return stored

    def add_dropdown_choice(self, table_name, field_name, value):
        if (table_name, field_name) in SYSTEM_DROPDOWNS:
            raise FieldError("Database", "ListItem", detail="This system list is protected.")
        if table_name == "FabricPiece" and field_name in DROPDOWN_FIELDS:
            return self.add_dropdown_item(field_name, value)
        if field_name not in DROPDOWN_SCOPE_FIELDS.get(table_name, ()):
            raise FieldError("Choice", "FieldName")
        clean = validate_fields((Field("ListItem", required=True),), {"ListItem": value})["ListItem"]
        if clean.casefold() == ADD_ITEM.casefold():
            raise FieldError("Choice", "ListItem")
        if clean.casefold() == f"choose {field_name}".casefold():
            raise FieldError("Choice", "ListItem")
        with self.connection:
            row = self.connection.execute(
                "SELECT ID, ListItem FROM Dropdown WHERE TableName = ? AND FieldName = ? "
                "AND ListItem = ? COLLATE NOCASE", (table_name, field_name, clean),
            ).fetchone()
            if row is not None:
                self.connection.execute("UPDATE Dropdown SET Use = 1 WHERE ID = ?", (row["ID"],))
                return row["ListItem"]
            self.connection.execute(
                "INSERT INTO Dropdown (TableName, FieldName, ListItem, UserModified) "
                "VALUES (?, ?, ?, 1)",
                (table_name, field_name, clean),
            )
        return clean

    def has_dropdown_list(self, table_name, field_name):
        return field_name in DROPDOWN_SCOPE_FIELDS.get(table_name, ())

    def dropdown_placeholder(self, name):
        if name != "FabricPattern":
            return f"Choose {name}"
        used = {row[0].casefold() for row in self.connection.execute(
            "SELECT ListItem FROM Dropdown WHERE TableName = 'FabricPiece' AND FieldName = ?", (name,))}
        base = "Choose Fabric Pattern"
        candidate = base
        index = 2
        while candidate.casefold() in used:
            candidate = f"{base} ({index})"
            index += 1
        return candidate

    def dropdown_items(self, table_name, field_name):
        if not self.has_dropdown_list(table_name, field_name):
            raise FieldError("Choice", "FieldName")
        rows = self.connection.execute(
            "SELECT ListItem FROM Dropdown WHERE TableName = ? AND FieldName = ? AND Use = 1 "
            "AND ListItem != '' ORDER BY ListItem COLLATE NOCASE",
            (table_name, field_name),
        )
        values = [row["ListItem"] for row in rows]
        if (table_name, field_name) in SYSTEM_DROPDOWNS:
            allowed = SYSTEM_DROPDOWNS[table_name, field_name][0]
            values = [value for value in values if value in allowed]
        return tuple(values)

    def _validate_fields(self, fields, values, table_name):
        choices = {
            field.name: self.dropdown_items(table_name, field.name)
            for field in fields if self.has_dropdown_list(table_name, field.name)
        }
        return validate_fields(fields, values, choices)

    def other_dropdown_defaults(self, table_name, field_name, item_id=None, item_value=None):
        return self.connection.execute(
            "SELECT 1 FROM Dropdown WHERE TableName = ? AND FieldName = ? AND Def = 1 "
            "AND (? IS NULL OR ID != ?) AND (? IS NULL OR ListItem != ? COLLATE NOCASE) LIMIT 1",
            (table_name, field_name, item_id, item_id, item_value, item_value),
        ).fetchone() is not None

    def fabric_colors(self):
        return tuple(row["Color"] for row in self.connection.execute(
            "SELECT DISTINCT Color FROM FabricPiece WHERE Color IS NOT NULL AND trim(Color) != '' "
            "ORDER BY Color COLLATE NOCASE",
        ))

    def dropdown_rows(self, name, filters=None, selected_ids=None, sort=None, table_name="FabricPiece",
                      include_inactive=False):
        all_rows = (table_name, name) == ALL_DROPDOWN_SCOPE
        if not all_rows and (table_name not in DROPDOWN_SCOPE_FIELDS
                             or name not in DROPDOWN_SCOPE_FIELDS[table_name]):
            raise FieldError("Choice", "FieldName")
        values = {field.name: "" for field in DROPDOWN_FILTER_FIELDS} if filters is None else filters
        clean = self._validate_fields(DROPDOWN_FILTER_FIELDS, values, "DropDown Filter")
        sort_key = "DropDownAllSort" if all_rows else "DropDownSort"
        order = self.load_sort(sort_key) if sort is None else normalize_sort(sort, DROPDOWN_COLUMNS)
        clauses, args = ([], []) if all_rows else (["TableName = ?", "FieldName = ?"], [table_name, name])
        if not include_inactive:
            clauses.append("Use = 1")
        if clean["ListItem"]:
            clauses.append("instr(lower(ListItem), lower(?)) > 0")
            args.append(clean["ListItem"])
        if clean["Default"]:
            clauses.append("Def = ?")
            args.append(int(clean["Default"] == "Yes"))
        sql_order = ", ".join(
            f'"{field}"{" COLLATE NOCASE" if field in ("TableName", "FieldName", "ListItem") else ""} {direction}'
            for field, direction in order
        )
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = [dict(row) for row in self.connection.execute(
            "SELECT * FROM Dropdown" + where + f" ORDER BY {sql_order}", args,
        )]
        if selected_ids is not None:
            allowed = set(selected_ids)
            rows = [row for row in rows if row["ID"] in allowed]
        return rows

    def dropdown_default(self, name, table_name="FabricPiece"):
        allowed = SYSTEM_DROPDOWNS.get((table_name, name), (None,))[0]
        for row in self.connection.execute(
                "SELECT ListItem FROM Dropdown WHERE TableName = ? AND FieldName = ? "
                "AND Def = 1 AND Use = 1 AND ListItem != '' ORDER BY ID",
                (table_name, name)):
            if allowed is None or row["ListItem"] in allowed:
                return row["ListItem"]
        return None

    def dropdown_choices(self, name, table_name="FabricPiece"):
        rows = self.dropdown_rows(name, sort=(("ID", "asc"),), table_name=table_name)
        if (table_name, name) in SYSTEM_DROPDOWNS:
            allowed = SYSTEM_DROPDOWNS[table_name, name][0]
            rows = [row for row in rows if row["ListItem"] in allowed]
        rows = [row for row in rows if row["ListItem"]]
        default_row = next((row for row in rows if row["Def"]), None)
        remaining = sorted(
            (row["ListItem"] for row in rows if row is not default_row),
            key=str.casefold,
        )
        leading = (default_row["ListItem"],) if default_row is not None else ()
        choices = (*leading, *remaining)
        if table_name == "FabricPiece" and name in DROPDOWN_FIELDS and DROPDOWN_FIELDS[name].kind == "dropdown":
            choices = ((*leading, ADD_ITEM, *remaining) if leading
                       else (ADD_ITEM, *remaining))
        return choices

    def get_dropdown(self, item_id):
        row = self.connection.execute("SELECT * FROM Dropdown WHERE ID = ?", (item_id,)).fetchone()
        if row is None:
            raise FieldError("MissingRecord", "DropdownID")
        return dict(row)

    def save_dropdown(self, table_name, field_name, value, default, use, item_id=None, original=None,
                      clear_other_defaults=False):
        if field_name not in DROPDOWN_SCOPE_FIELDS.get(table_name, ()):
            raise FieldError("Choice", "FieldName")
        adding = item_id is None
        flag_choices = ((0, 1) if adding else (None, 0, 1))
        if default not in flag_choices or use not in flag_choices:
            raise FieldError("Required" if adding and (default is None or use is None) else "Choice",
                             "Def" if default not in flag_choices else "Use")
        with self._write_transaction():
            row = None if adding else self.get_dropdown(item_id)
            protected = (table_name, field_name) in SYSTEM_DROPDOWNS or (
                row is not None and not row["UserModified"])
            if adding and (table_name, field_name) in SYSTEM_DROPDOWNS:
                raise FieldError("Database", "ListItem", detail="This system list is protected.")
            if row is not None:
                if original != row:
                    raise FieldError("Conflict", "DropdownID")
                if (row["TableName"], row["FieldName"]) != (table_name, field_name):
                    raise FieldError("Choice", "FieldName")
            clean = validate_fields((Field("ListItem", required=adding),), {"ListItem": value})["ListItem"]
            if not clean and row is not None:
                clean = row["ListItem"]
            if protected and row is not None and (
                    clean != row["ListItem"] or (use is not None and use != row["Use"])):
                raise FieldError("Database", "ListItem", detail="Only the default may be changed for a protected item.")
            if (protected and (table_name, field_name) in SYSTEM_DROPDOWNS
                    and clean not in SYSTEM_DROPDOWNS[table_name, field_name][0]):
                raise FieldError("Database", "ListItem", detail="This value is not a supported system choice.")
            if clean.casefold() == ADD_ITEM.casefold():
                raise FieldError("Choice", "ListItem")
            placeholder = (self.dropdown_placeholder(field_name) if table_name == "FabricPiece"
                           else f"Choose {field_name}")
            if clean.casefold() == placeholder.casefold():
                raise FieldError("Choice", "ListItem")
            if table_name == "FabricPiece" and field_name in DROPDOWN_FIELDS and (
                    clean or row is None or row["ListItem"] != ""):
                field = DROPDOWN_FIELDS[field_name]
                clean = validate_fields((field,), {field_name: clean})[field_name]
            target_default = default if default is not None else row["Def"] if row else 0
            target_use = use if use is not None else row["Use"] if row else 1
            if target_use == 0 and default is None:
                target_default = 0
            if target_default == 1 and target_use != 1:
                raise FieldError("Choice", "Def")
            duplicate = self.connection.execute(
                "SELECT ID FROM Dropdown WHERE TableName = ? AND FieldName = ? "
                "AND ListItem = ? COLLATE NOCASE AND ID != ?",
                (table_name, field_name, clean, item_id if item_id is not None else -1),
            ).fetchone()
            if duplicate:
                raise FieldError("Database", "ListItem", detail="A dropdown item with this name already exists.")
            if target_default == 1 and clear_other_defaults:
                self.connection.execute(
                    "UPDATE Dropdown SET Def = 0 WHERE TableName = ? AND FieldName = ? AND ID != ?",
                    (table_name, field_name, item_id if item_id is not None else -1),
                )
            if adding:
                cursor = self.connection.execute(
                    "INSERT INTO Dropdown (TableName, FieldName, ListItem, Def, Use, UserModified) "
                    "VALUES (?, ?, ?, ?, ?, 1)",
                    (table_name, field_name, clean, target_default, target_use),
                )
                item_id = cursor.lastrowid
            else:
                self.connection.execute(
                    "UPDATE Dropdown SET ListItem = ?, Def = ?, Use = ? WHERE ID = ?",
                    (clean, target_default, target_use, item_id),
                )
            multiple_defaults = target_default == 1 and self.connection.execute(
                "SELECT count(*) FROM Dropdown WHERE TableName = ? AND FieldName = ? AND Def = 1",
                (table_name, field_name),
            ).fetchone()[0] > 1
            return item_id, multiple_defaults

    def delete_dropdown(self, item_id, original):
        with self._write_transaction():
            row = self.get_dropdown(item_id)
            if row != original:
                raise FieldError("Conflict", "DropdownID")
            if not row["UserModified"] or (row["TableName"], row["FieldName"]) in SYSTEM_DROPDOWNS:
                raise FieldError("Database", "ListItem", detail="This system item is protected.")
            self.connection.execute(
                "DELETE FROM WorkingListMember WHERE RecordID = ? AND SelectionSetID IN "
                "(SELECT ID FROM WorkingListSet WHERE ScreenName = 'DropDown')",
                (item_id,),
            )
            self.connection.execute("DELETE FROM Dropdown WHERE ID = ?", (item_id,))

    def set_dropdown_default(self, item_id):
        with self.connection:
            row = self.connection.execute(
                "SELECT TableName, FieldName FROM Dropdown WHERE ID = ? AND Use = 1", (item_id,),
            ).fetchone()
            if row is None:
                raise FieldError("MissingRecord", "DropdownID")
            self.connection.execute(
                "UPDATE Dropdown SET Def = 0 WHERE TableName = ? AND FieldName = ?",
                (row["TableName"], row["FieldName"]),
            )
            self.connection.execute("UPDATE Dropdown SET Def = 1 WHERE ID = ?", (item_id,))

    def error_message(self, error):
        row = self.connection.execute(
            "SELECT * FROM ErrorText WHERE MessageKey = ?", (error.key,),
        ).fetchone()
        if row is None:
            raise FieldError("DatabaseFormat", "ErrorText", detail=f"Missing error message {error.key}.")
        if error.key == "Conflict" and error.field == "QuiltBlock" and "reason" in error.details:
            message, resolution = BLOCK_CONFLICT_MESSAGES[error.details["reason"]]
            return f"{caption(error.field)}: {message}\n\n{resolution}\n\nError ID: {row['ErrorTextID']}"
        if (error.key == "Choice" and error.field == "MinimumColorValue"
                and error.details.get("reason") == "range_order"):
            return ("Minimum Color Value: The minimum cannot exceed the maximum.\n\n"
                    "Choose an ordered range from 1 to 10, or leave both values blank.\n\n"
                    f"Error ID: {row['ErrorTextID']}")
        text = f"{caption(error.field)}: {row['MessageTemplate'].format(**error.details)}"
        if row["ResolutionText"]:
            text += f"\n\n{row['ResolutionText']}"
        return f"{text}\n\nError ID: {row['ErrorTextID']}"

    def blocks(self, filters=None, selected_ids=None, sort=None):
        clean = self._validate_fields(
            BLOCK_FILTER_FIELDS, filters or {"BlockName": "", "Status": ""}, "QuiltBlock Filter",
        )
        order = self.load_sort("QuiltBlockSort") if sort is None else normalize_sort(sort, BLOCK_COLUMNS)
        clauses, args = [], []
        if clean["BlockName"]:
            clauses.append("instr(lower(BlockName), lower(?)) > 0")
            args.append(clean["BlockName"])
        if clean["Status"]:
            clauses.append("Status = ?")
            args.append(clean["Status"])
        sql_order = ", ".join(
            f'"{name}" {"" if name in ("ID", "FinishedWidth", "FinishedLength", "Revision") else "COLLATE NOCASE "}{direction}'
            if name != "Scale" else f'CAST(Scale AS REAL) {direction}' for name, direction in order)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = [dict(row) for row in self.connection.execute(f"SELECT * FROM QuiltBlock{where} ORDER BY {sql_order}", args)]
        if selected_ids is not None:
            ids = set(selected_ids)
            rows = [row for row in rows if row["ID"] in ids]
        return rows

    def get_block(self, block_id):
        row = self.connection.execute("SELECT * FROM QuiltBlock WHERE ID = ?", (block_id,)).fetchone()
        if row is None:
            raise FieldError("MissingRecord", "QuiltBlock")
        return dict(row)

    def block_parts(self, block_id):
        self.get_block(block_id)
        return [dict(row) for row in self.connection.execute(
            "SELECT * FROM BlockPart WHERE QuiltBlockID = ? ORDER BY ID", (block_id,))]

    def block_placements(self, block_id):
        self.get_block(block_id)
        return [dict(row) for row in self.connection.execute(
            "SELECT p.* FROM BlockPartPlacement p JOIN BlockPart b ON b.ID = p.BlockPartID "
            "WHERE b.QuiltBlockID = ? ORDER BY b.ID, p.Instance", (block_id,))]

    def _block_draft(self, block_id, revision):
        row = self.get_block(block_id)
        if row["Status"] != "Draft":
            raise FieldError("Conflict", "QuiltBlock", reason="approved")
        if row["Revision"] != revision:
            raise FieldError("Conflict", "QuiltBlock", reason="stale")
        return row

    @contextmanager
    def _write_transaction(self):
        self.connection.execute("BEGIN IMMEDIATE")
        with self.connection:
            yield

    def _touch_block(self, block_id):
        self.connection.execute(
            "UPDATE QuiltBlock SET Revision = Revision + 1, DateModified = ? WHERE ID = ?",
            (now(), block_id))

    def add_block(self, values):
        clean = parse_block(values)
        timestamp = now()
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO QuiltBlock (BlockName, Description, FinishedWidth, FinishedLength, "
                "Scale, SeamAllowance, Status, DateCreated, DateModified) "
                "VALUES (?, ?, ?, ?, ?, ?, 'Draft', ?, ?)", (*clean.values(), timestamp, timestamp))
        return cursor.lastrowid

    def create_block_template(self, name, values):
        if name not in BLOCK_TEMPLATES:
            raise FieldError("Choice", "QuiltBlock")
        block_values = dict(values)
        block_values["BlockName"] = name
        block_values["Description"] = BLOCK_TEMPLATES[name]
        clean_block = parse_block(block_values)
        specs = build_block_template(name, clean_block["FinishedWidth"], clean_block["FinishedLength"])
        choices = {
            field: self.dropdown_items("Block Parts", field)
            for field in ("Shape", "PartColor")
        }
        timestamp = now()
        with self._write_transaction():
            cursor = self.connection.execute(
                "INSERT INTO QuiltBlock (BlockName, Description, FinishedWidth, FinishedLength, "
                "Scale, SeamAllowance, Status, DateCreated, DateModified) "
                "VALUES (?, ?, ?, ?, ?, ?, 'Draft', ?, ?)",
                (*clean_block.values(), timestamp, timestamp))
            block_id = cursor.lastrowid
            for spec in specs:
                part = parse_part(spec["values"], choices)
                part_cursor = self.connection.execute(
                    "INSERT INTO BlockPart (QuiltBlockID, PartName, Shape, PartColor, NumberInBlock, "
                    "PartWidth, PartLength, SideA, SideB, SideC, Diameter, MinimumColorValue, MaximumColorValue) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (block_id, *(part[field] for field in (
                        "PartName", "Shape", "PartColor", "NumberInBlock", "PartWidth", "PartLength",
                        "SideA", "SideB", "SideC", "Diameter", "MinimumColorValue", "MaximumColorValue"))))
                part_id = part_cursor.lastrowid
                self.connection.executemany(
                    "INSERT INTO BlockPartPlacement "
                    "(BlockPartID, Instance, X, Y, Rotation, Mirrored) VALUES (?, ?, ?, ?, ?, ?)",
                    ((part_id, instance, x, y, rotation, int(mirrored))
                     for instance, (x, y, rotation, mirrored) in enumerate(spec["placements"], 1)))
            issues = validate_layout(
                self.get_block(block_id), self.block_parts(block_id), self.block_placements(block_id),
            )
            if issues:
                raise FieldError("Database", "QuiltBlock", detail=" ".join(issues))
        return block_id

    def update_block(self, block_id, revision, values):
        clean = parse_block(values)
        with self._write_transaction():
            self._block_draft(block_id, revision)
            self.connection.execute(
                "UPDATE QuiltBlock SET BlockName = ?, Description = ?, FinishedWidth = ?, "
                "FinishedLength = ?, Scale = ?, SeamAllowance = ? WHERE ID = ?",
                (*clean.values(), block_id))
            self._touch_block(block_id)

    def delete_block(self, block_id, revision):
        with self._write_transaction():
            self._block_draft(block_id, revision)
            self.connection.execute("DELETE FROM QuiltBlock WHERE ID = ?", (block_id,))

    def copy_block(self, block_id):
        timestamp = now()
        with self._write_transaction():
            source = self.get_block(block_id)
            cursor = self.connection.execute(
                "INSERT INTO QuiltBlock (ParentID, BlockName, Description, FinishedWidth, FinishedLength, "
                "Scale, SeamAllowance, Status, DateCreated, DateModified) VALUES (?, ?, ?, ?, ?, ?, ?, "
                "'Draft', ?, ?)",
                (block_id, *(source[name] for name in (
                    "BlockName", "Description", "FinishedWidth", "FinishedLength", "Scale", "SeamAllowance")),
                 timestamp, timestamp))
            new_id = cursor.lastrowid
            for part in self.block_parts(block_id):
                result = self.connection.execute(
                    "INSERT INTO BlockPart (QuiltBlockID, PartName, Shape, PartColor, NumberInBlock, "
                    "PartWidth, PartLength, SideA, SideB, SideC, Diameter, MinimumColorValue, MaximumColorValue) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (new_id, *(part[name] for name in (
                        "PartName", "Shape", "PartColor", "NumberInBlock", "PartWidth", "PartLength",
                        "SideA", "SideB", "SideC", "Diameter", "MinimumColorValue", "MaximumColorValue"))))
                self.connection.execute(
                    "INSERT INTO BlockPartPlacement (BlockPartID, Instance, X, Y, Rotation, Mirrored) "
                    "SELECT ?, Instance, X, Y, Rotation, Mirrored FROM BlockPartPlacement WHERE BlockPartID = ?",
                    (result.lastrowid, part["ID"]))
        return new_id

    def save_block_part(self, block_id, revision, values, part_id=None):
        clean = parse_part(values, {
            name: self.dropdown_items("Block Parts", name) for name in ("Shape", "PartColor")
        })
        with self._write_transaction():
            self._block_draft(block_id, revision)
            if part_id is None:
                cursor = self.connection.execute(
                    "INSERT INTO BlockPart (QuiltBlockID, PartName, Shape, PartColor, NumberInBlock, "
                    "PartWidth, PartLength, SideA, SideB, SideC, Diameter, MinimumColorValue, MaximumColorValue) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (block_id, *clean.values()))
                part_id = cursor.lastrowid
            else:
                cursor = self.connection.execute(
                    "UPDATE BlockPart SET PartName=?, Shape=?, PartColor=?, NumberInBlock=?, "
                    "PartWidth=?, PartLength=?, SideA=?, SideB=?, SideC=?, Diameter=?, "
                    "MinimumColorValue=?, MaximumColorValue=? "
                    "WHERE ID=? AND QuiltBlockID=?", (*clean.values(), part_id, block_id))
                if cursor.rowcount != 1:
                    raise FieldError("MissingRecord", "BlockPart")
            self.connection.execute(
                "DELETE FROM BlockPartPlacement WHERE BlockPartID=? AND Instance>?",
                (part_id, clean["NumberInBlock"]))
            self.connection.executemany(
                "INSERT OR IGNORE INTO BlockPartPlacement "
                "(BlockPartID, Instance, X, Y, Rotation, Mirrored) VALUES (?, ?, 0, 0, 0, 0)",
                ((part_id, number) for number in range(1, clean["NumberInBlock"] + 1)))
            self._touch_block(block_id)
        return part_id

    def delete_block_part(self, block_id, revision, part_id):
        with self._write_transaction():
            self._block_draft(block_id, revision)
            cursor = self.connection.execute(
                "DELETE FROM BlockPart WHERE ID=? AND QuiltBlockID=?", (part_id, block_id))
            if cursor.rowcount != 1:
                raise FieldError("MissingRecord", "BlockPart")
            self._touch_block(block_id)

    def save_block_placement(self, block_id, revision, placement_id, x, y, rotation, mirrored):
        if (type(x) is not int or type(y) is not int or x < 0 or y < 0
                or type(rotation) is not int or not 0 <= rotation < 360 or type(mirrored) is not bool):
            raise FieldError("Choice", "BlockPartPlacement")
        with self._write_transaction():
            self._block_draft(block_id, revision)
            cursor = self.connection.execute(
                "UPDATE BlockPartPlacement SET X=?, Y=?, Rotation=?, Mirrored=? WHERE ID=? AND "
                "BlockPartID IN (SELECT ID FROM BlockPart WHERE QuiltBlockID=?)",
                (x, y, rotation, int(mirrored), placement_id, block_id))
            if cursor.rowcount != 1:
                raise FieldError("MissingRecord", "BlockPartPlacement")
            self._touch_block(block_id)

    def approve_block(self, block_id, revision):
        with self._write_transaction():
            block = self._block_draft(block_id, revision)
            issues = validate_layout(block, self.block_parts(block_id), self.block_placements(block_id))
            if issues:
                raise FieldError("Database", "QuiltBlock", detail=" ".join(issues))
            self.connection.execute("UPDATE QuiltBlock SET Status='Approved' WHERE ID=?", (block_id,))
            self._touch_block(block_id)

    def quilts(self):
        return [dict(row) for row in self.connection.execute(
            "SELECT * FROM Quilt ORDER BY QuiltName COLLATE NOCASE, ID")]

    def get_quilt(self, quilt_id):
        row = self.connection.execute("SELECT * FROM Quilt WHERE ID=?", (quilt_id,)).fetchone()
        if row is None:
            raise FieldError("MissingRecord", "Quilt")
        return dict(row)

    def add_quilt(self, name):
        clean = validate_fields((Field("QuiltName", required=True),), {"QuiltName": name})["QuiltName"]
        timestamp = now()
        with self.connection:
            return self.connection.execute(
                "INSERT INTO Quilt (QuiltName, DateCreated, DateModified) VALUES (?, ?, ?)",
                (clean, timestamp, timestamp)).lastrowid

    def _quilt_revision(self, quilt_id, revision):
        row = self.get_quilt(quilt_id)
        if row["Revision"] != revision:
            raise FieldError("Conflict", "Quilt")

    def _touch_quilt(self, quilt_id):
        self.connection.execute("UPDATE Quilt SET Revision=Revision+1, DateModified=? WHERE ID=?",
                                (now(), quilt_id))

    def quilt_uses(self, quilt_id):
        self.get_quilt(quilt_id)
        return [dict(row) for row in self.connection.execute(
            "SELECT b.ID, b.BlockName, b.Scale, u.Quantity FROM QuiltBlockUse u "
            "JOIN QuiltBlock b ON b.ID=u.QuiltBlockID WHERE u.QuiltID=? ORDER BY b.BlockName, b.ID", (quilt_id,))]

    def set_quilt_use(self, quilt_id, revision, block_id, quantity):
        if type(quantity) is not int or not 1 <= quantity <= 10000:
            raise FieldError("Choice", "Quantity")
        with self._write_transaction():
            self._quilt_revision(quilt_id, revision)
            if self.get_block(block_id)["Status"] != "Approved":
                raise FieldError("Choice", "QuiltBlock")
            self.connection.execute(
                "INSERT INTO QuiltBlockUse (QuiltID, QuiltBlockID, Quantity) VALUES (?, ?, ?) "
                "ON CONFLICT(QuiltID, QuiltBlockID) DO UPDATE SET Quantity=excluded.Quantity",
                (quilt_id, block_id, quantity))
            self._touch_quilt(quilt_id)

    def remove_quilt_use(self, quilt_id, revision, block_id):
        with self._write_transaction():
            self._quilt_revision(quilt_id, revision)
            cursor = self.connection.execute(
                "DELETE FROM QuiltBlockUse WHERE QuiltID=? AND QuiltBlockID=?", (quilt_id, block_id))
            if cursor.rowcount != 1:
                raise FieldError("MissingRecord", "QuiltBlock")
            self._touch_quilt(quilt_id)

    def quilt_mappings(self, quilt_id):
        self.get_quilt(quilt_id)
        return [dict(row) for row in self.connection.execute(
            "SELECT PartColor, InventoryColor FROM QuiltColorMap WHERE QuiltID=? "
            "ORDER BY PartColor, InventoryColor COLLATE NOCASE", (quilt_id,))]

    def add_quilt_mapping(self, quilt_id, revision, part_color, inventory_color):
        from .blocks import COLORS
        if part_color not in COLORS:
            raise FieldError("Choice", "PartColor")
        valid = set(self.fabric_colors())
        if inventory_color not in valid or not inventory_color:
            raise FieldError("Choice", "InventoryColor")
        with self._write_transaction():
            self._quilt_revision(quilt_id, revision)
            self.connection.execute(
                "INSERT OR IGNORE INTO QuiltColorMap (QuiltID, PartColor, InventoryColor) VALUES (?, ?, ?)",
                (quilt_id, part_color, inventory_color))
            self._touch_quilt(quilt_id)

    def remove_quilt_mapping(self, quilt_id, revision, part_color, inventory_color):
        with self._write_transaction():
            self._quilt_revision(quilt_id, revision)
            cursor = self.connection.execute(
                "DELETE FROM QuiltColorMap WHERE QuiltID=? AND PartColor=? AND InventoryColor=?",
                (quilt_id, part_color, inventory_color))
            if cursor.rowcount != 1:
                raise FieldError("MissingRecord", "QuiltColorMap")
            self._touch_quilt(quilt_id)

    def quilt_part_fabrics(self, quilt_id, block_id=None):
        self.get_quilt(quilt_id)
        sql = ("SELECT BlockPartID, FabricPieceID FROM QuiltPartFabric WHERE QuiltID=?")
        args = [quilt_id]
        if block_id is not None:
            sql += " AND QuiltBlockID=?"
            args.append(block_id)
        assignments = {}
        for row in self.connection.execute(sql + " ORDER BY BlockPartID, FabricPieceID", args):
            assignments.setdefault(row["BlockPartID"], []).append(row["FabricPieceID"])
        return assignments

    def save_quilt_part_fabrics(self, quilt_id, revision, block_id, assignments):
        with self._write_transaction():
            self._quilt_revision(quilt_id, revision)
            if not self.connection.execute(
                    "SELECT 1 FROM QuiltBlockUse WHERE QuiltID=? AND QuiltBlockID=?",
                    (quilt_id, block_id)).fetchone():
                raise FieldError("Choice", "ApprovedBlock")
            valid_parts = {part["ID"] for part in self.block_parts(block_id)}
            if not set(assignments) <= valid_parts:
                raise FieldError("Choice", "BlockPartChoice")
            for ids in assignments.values():
                for piece_id in ids:
                    self.get_piece(piece_id)
            self.connection.execute(
                "DELETE FROM QuiltPartFabric WHERE QuiltID=? AND QuiltBlockID=?", (quilt_id, block_id))
            self.connection.executemany(
                "INSERT INTO QuiltPartFabric (QuiltID, QuiltBlockID, BlockPartID, FabricPieceID) "
                "VALUES (?, ?, ?, ?)",
                ((quilt_id, block_id, part_id, piece_id)
                 for part_id, ids in assignments.items() for piece_id in sorted(set(ids))))
            self._touch_quilt(quilt_id)

    def quilt_plans(self, quilt_id):
        self.get_quilt(quilt_id)
        return [dict(row) for row in self.connection.execute(
            "SELECT ID, QuiltID, QuiltRevision, DateCreated FROM QuiltPlan WHERE QuiltID=? ORDER BY ID DESC",
            (quilt_id,))]

    def get_quilt_plan(self, plan_id):
        row = self.connection.execute("SELECT * FROM QuiltPlan WHERE ID=?", (plan_id,)).fetchone()
        if row is None:
            raise FieldError("MissingRecord", "QuiltPlan")
        result = dict(row)
        try:
            result["PlanData"] = json.loads(result["PlanData"])
        except (ValueError, TypeError) as error:
            raise FieldError("DatabaseFormat", "QuiltPlan", detail=str(error)) from error
        return result

    def create_quilt_plan(self, quilt_id, revision, selected_ids=None):
        with self._write_transaction():
            self._quilt_revision(quilt_id, revision)
            records = self.quilt_uses(quilt_id)
            if not records:
                raise FieldError("Required", "QuiltBlock")
            uses = []
            for record in records:
                block = self.get_block(record["ID"])
                if block["Status"] != "Approved":
                    raise FieldError("Choice", "QuiltBlock")
                uses.append({"block": block, "parts": self.block_parts(block["ID"]),
                             "placements": self.block_placements(block["ID"]),
                             "quantity": record["Quantity"]})
            mappings = {}
            for row in self.quilt_mappings(quilt_id):
                mappings.setdefault(row["PartColor"], []).append(row["InventoryColor"])
            assignments = self.quilt_part_fabrics(quilt_id)
            draft = plan_quilt(uses, mappings, self.pieces(selected_ids=selected_ids), assignments)
            draft.update(quilt=self.get_quilt(quilt_id), uses=uses, mappings=mappings,
                         assignments=assignments)
            return self.connection.execute(
                "INSERT INTO QuiltPlan (QuiltID, QuiltRevision, PlanData, DateCreated) VALUES (?, ?, ?, ?)",
                (quilt_id, revision, json.dumps(draft), now())).lastrowid

    def get_piece(self, piece_id):
        row = self.connection.execute("SELECT * FROM FabricPiece WHERE ID = ?", (piece_id,)).fetchone()
        if row is None:
            raise FieldError("MissingRecord", "FabricPieceID")
        return dict(row)

    def save_piece(self, values, piece_id=None, revision=None):
        if set(values) != set(FABRIC_NAMES):
            validate_fields(FABRIC_FIELDS, values)
        values = {
            name: "" if values[name] is None and name in ("Color", "FabricPattern", "StorageLocation")
            else values[name] for name in FABRIC_NAMES
        }
        clean = self._validate_fields(FABRIC_FIELDS, values, "FabricPiece")
        clean["ColorValue"] = int(clean["ColorValue"]) if clean["ColorValue"] else None
        timestamp = now()
        with self.connection:
            for name in DROPDOWN_FIELDS:
                if DROPDOWN_FIELDS[name].kind == "dropdown":
                    if not clean[name]:
                        clean[name] = None
                    else:
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

    def save_back_draft(self, back_name, quilt_width, quilt_length, margin, seam_allowance, layout,
                        *, side_margin=None):
        if side_margin is None:
            side_margin = margin
        name = validate_fields(
            (Field("BackName", required=True),), {"BackName": back_name},
        )["BackName"]
        if (not layout.panels or len(layout.panels) > MAX_PANELS or layout.ratio_tier < 0
                or layout.direction not in ("single", "vertical", "horizontal")):
            raise FieldError("Required", "FabricPieceID")
        if (layout.target_width != quilt_width + 2 * side_margin
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
                "DateCreated, DateModified, SideMargin) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Draft', ?, ?, ?)",
                (name, quilt_width, quilt_length, margin, seam_allowance,
                 layout.target_width, layout.target_length,
                 "single" if len(layout.panels) == 1 else layout.direction,
                 layout.ratio_tier, int(layout.grain_consistent), timestamp, timestamp, side_margin),
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

    def quilt_backs(self, filters=None, selected_ids=None, sort=None):
        values = {field.name: "" for field in BACK_FILTER_FIELDS} if filters is None else filters
        clean = self._validate_fields(BACK_FILTER_FIELDS, values, "Quilt Backs Filter")
        order = self.load_sort("QuiltBackSort") if sort is None else normalize_sort(sort, BACK_COLUMNS)
        clauses, args = [], []
        if clean["BackName"]:
            clauses.append("instr(lower(BackName), lower(?)) > 0")
            args.append(clean["BackName"])
        if clean["Status"]:
            clauses.append("Status = ?")
            args.append(clean["Status"])
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql_order = ", ".join(f'"{name}" COLLATE NOCASE {direction}' for name, direction in order)
        rows = [dict(row) for row in self.connection.execute(
            "SELECT ID, BackName, BackWidth, BackLength, Status, DateModified "
            f"FROM QuiltBack{where} ORDER BY {sql_order}", args,
        )]
        if selected_ids is not None:
            allowed = set(selected_ids)
            rows = [row for row in rows if row["ID"] in allowed]
        return rows

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
        if set(values) != set(FABRIC_NAMES):
            raise FieldError("Binding", "FabricPiece")
        clean = {
            name: "" if values[name] is None and name in ("Color", "FabricPattern", "StorageLocation")
            else values[name] for name in FABRIC_NAMES
        }
        for name in DROPDOWN_FIELDS:
            if DROPDOWN_FIELDS[name].kind == "dropdown":
                clean[name] = self._dropdown_item(name, clean[name]) if clean[name] else None
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
        for name in ("FabricName", "Color", "FabricPattern", "StorageLocation"):
            if clean[name]:
                clauses.append(f"instr(lower({name}), lower(?)) > 0")
                args.append(clean[name])
        for name, column, operator in (
                ("MinimumWidth", "UsableWidth", ">="), ("MaximumWidth", "UsableWidth", "<="),
                ("MinimumLength", "UsableLength", ">="), ("MaximumLength", "UsableLength", "<=")):
            if clean[name] is not None:
                clauses.append(f"{column} {operator} ?")
                args.append(clean[name])
        if clean["Status"]:
            clauses.append("Status = ?")
            args.append(clean["Status"])
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        order_sql = ", ".join(
            f"{field}{'' if field in ('ID', 'UsableWidth', 'UsableLength', 'ColorValue') else ' COLLATE NOCASE'} {direction}"
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
            if isinstance(scope, str):
                table_name, field_name = "FabricPiece", scope
            elif isinstance(scope, (tuple, list)) and len(scope) == 2:
                table_name, field_name = scope
            else:
                raise FieldError("Choice", "FieldName")
            if ((table_name, field_name) != ALL_DROPDOWN_SCOPE
                    and (table_name not in DROPDOWN_SCOPE_FIELDS
                         or field_name not in DROPDOWN_SCOPE_FIELDS[table_name])):
                raise FieldError("Choice", "FieldName")
            return json.dumps((table_name, field_name), separators=(",", ":"))
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
            table_name, field_name = json.loads(scope)
            return self.dropdown_rows(field_name, table_name=table_name, include_inactive=True)
        if screen == "History":
            return self.history(int(scope))
        if screen == "Quilt Backs":
            return self.quilt_backs()
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
                {"Fabric": self.get_piece, "ErrorMessage": self.get_error, "QuiltBlock": self.get_block}[screen](record_id)
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
