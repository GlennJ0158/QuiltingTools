"""Editable troubleshooting reference; runtime ErrorText templates stay independent."""

from .model import Field

ERROR_FIELDS = (
    Field("ErrorText", kind="memo", required=True, limit=4000, width=80),
    Field("LikelyCause", kind="memo", required=True, limit=4000, width=80),
    Field("Description", kind="memo", required=True, limit=16000, width=80),
)
ERROR_COLUMNS = ("ID", *(field.name for field in ERROR_FIELDS))
ERROR_FILTER_FIELDS = tuple(Field(field.name, limit=field.limit) for field in ERROR_FIELDS)

BLOCK_CONFLICT_MESSAGES = {
    "approved": (
        "This block is Approved and cannot be changed.",
        "To edit it, close any open block dialog, select the block, and choose New Version. "
        "Confirm discarding any unsaved details, then edit the new draft; "
        "the approved version remains unchanged.",
    ),
    "stale": (
        "This block has changed since its details were loaded.",
        "Copy any unsaved changes elsewhere. Close any open block dialog, choose Refresh, "
        "and confirm discarding the unsaved details. Select the block again, re-enter your changes, "
        "and choose Update. Highlighting the already-selected row does not reload it.",
    ),
    "unsaved": (
        "The block has unsaved details and cannot be approved yet.",
        "Choose Update to save your changes before choosing Approve, or choose Refresh "
        "and confirm discarding them.",
    ),
}

OLD_CONFLICT_REFERENCE = (
    "1. Another window or application instance saved the record after it was loaded.",
    "1. Copy any unsaved text elsewhere, refresh and reload the record, then reapply the "
    "intended changes. Do not overwrite another edit blindly.",
)

# Numbered fixes correspond to the numbered causes, including dynamic {detail} messages.
TROUBLESHOOTING = {
    "Required": (
        "1. A required field is empty or contains only spaces.",
        "1. Enter a nonblank value in the field named by the error, then retry.",
    ),
    "TooLong": (
        "1. Typed or pasted text exceeds the field's character limit.",
        "1. Shorten the named field to the displayed {limit}; preserve longer notes outside that field.",
    ),
    "Choice": (
        "1. A value is outside the permitted choices, or Add Item was supplied as a value.\n"
        "2. A read-only help key was changed, or an unsupported screen/field was requested.",
        "1. Select an offered value; use Add Item only to create a supported fabric choice.\n"
        "2. Reload the screen without changing generated keys. Report a repeatable application defect.",
    ),
    "Measurement": (
        "1. The dimension is zero, negative, or greater than 10,800 inches.\n"
        "2. The format includes units, excess decimal precision, or an unsupported/improper fraction.",
        "1. Measure the usable rectangle and enter a positive value no greater than 10,800 inches.\n"
        "2. Remove units; use at most six decimal places or a proper fraction with denominator "
        "2, 4, 8, 16, 32 or 64, optionally preceded by whole inches (for example 42 1/2).",
    ),
    "Binding": (
        "1. A form's fields, widgets and Tk variables disagree.\n"
        "2. A caller supplied missing, extra or non-text form values.",
        "1. Do not save the form. Reopen it and report the named disconnected control if it recurs.\n"
        "2. Correct the caller to supply exactly the declared fields as text; report the detail.",
    ),
    "MissingRecord": (
        "1. Another operation deleted the selected message or saved set.\n"
        "2. A stale selection references a record that no longer exists.",
        "1. Refresh the list and choose a current record or set.\n"
        "2. Reset the selection and select again; restore a verified backup only if data was lost.",
    ),
    "Conflict": (
        "1. The record changed after its details were loaded.\n"
        "2. A Quilt Block is Approved and cannot be edited.\n"
        "3. A Quilt Block has unsaved details when Approve is selected.",
        "1. Copy unsaved edits elsewhere, close any dialog, choose Refresh, confirm discarding "
        "the edits, then select the record again and re-enter them.\n"
        "2. Select the approved block and choose New Version; confirm discarding unsaved details "
        "and edit the new draft.\n"
        "3. Choose Update to save the block details before choosing Approve, or Refresh "
        "to discard the edits.",
    ),
    "NoHighlight": (
        "1. Select Highlighted was requested without any highlighted rows.",
        "1. Highlight one or more rows in the working list, then choose Select Highlighted.",
    ),
    "OneRecord": (
        "1. Update or Delete was requested without exactly one highlighted record.\n"
        "2. An operation requiring a single record was requested with multiple highlights.",
        "1. Highlight the one record to maintain before retrying.\n"
        "2. Reduce the highlights to one; use Select Highlighted for a multi-record working list.",
    ),
    "EmptySet": (
        "1. Save Current was requested while the working list contains no records.",
        "1. Reset or relax filters/restrictions to include records, then save the set.",
    ),
    "DuplicateSet": (
        "1. A saved set already has this name, ignoring ASCII letter case.",
        "1. Choose a different name, or delete the old saved set before saving its replacement. "
        "Deleting a set does not delete its records.",
    ),
    "Sort": (
        "1. No sort field was selected, a field was repeated, or a direction is invalid.",
        "1. Choose at least one supported, distinct field with asc or desc for each. "
        "Clear unused rows; ID is appended automatically to break ties.",
    ),
    "Database": (
        "1. The database, backup or report path is missing, inaccessible, full, or read-only.\n"
        "2. Another process holds a SQLite write lock, or a constraint rejects the operation.\n"
        "3. A backup destination exists or its filesystem does not support hard links.\n"
        "4. No browser is available to open the print report.",
        "1. Check the displayed detail, directory, permissions and free space; use a writable local disk.\n"
        "2. Close competing writers and refresh before retrying. Report repeated constraint failures.\n"
        "3. Choose a new backup filename on a filesystem supporting hard links.\n"
        "4. Open the saved HTML report manually in a browser and use its Print command, "
        "or configure a default browser.",
    ),
    "DatabaseFormat": (
        "1. The file is not a supported Quilting Tools database, or an upgrade is required.\n"
        "2. A table has an unexpected schema, integrity checks fail, or relationships are incomplete.\n"
        "3. Required runtime messages/help, a dropdown default, or saved sort settings are invalid.\n"
        "4. The database version changed while an upgrade was being prepared.",
        "1. Choose the correct file and compatible application; accept a backed-up upgrade only "
        "after closing other copies.\n"
        "2. Keep the damaged original and restore a verified backup to a new file; do not edit "
        "SQLite structures manually.\n"
        "3. Preserve a backup and report the exact detail for repair; do not delete runtime ErrorText rows.\n"
        "4. Close other copies and reopen the database to check its current version before retrying.",
    ),
    "Unexpected": (
        "1. An unhandled application or Tkinter callback failure occurred.",
        "1. Keep the traceback from stderr and note the steps and displayed detail. Check whether "
        "the last save committed before retrying; reload the affected record and report the defect.",
    ),
}

STARTUP_MESSAGES = (
    (
        "Database: Unable to open {path}.\n\n{error}\n\nAny uncommitted upgrade was rolled back. "
        "If an upgrade was started, retain the PreUpgrade backup beside the database.",
        "1. The path is unavailable, permissions or disk space prevent opening it, or SQLite rejected it.\n"
        "2. The database is unsupported, damaged, or a backed-up upgrade failed.",
        "1. Check the path, permissions, free space and underlying {error}; keep the database on a local disk.\n"
        "2. Retain the original and PreUpgrade backup. Use a compatible application or restore "
        "a verified backup to a new filename; report the exact startup error.",
    ),
    (
        "Quilting Tools - Startup Failed: {error}",
        "1. Screen initialization failed after the database opened, for example due to invalid "
        "saved settings or missing help data.",
        "1. Preserve a backup and the underlying {error}. Reopen with a verified compatible "
        "database; report repeated initialization failures.",
    ),
    (
        "{Field}: {error}\n\nError catalog failure: {catalog_error}",
        "1. The runtime ErrorText catalog could not be read, is incomplete, or contains an "
        "invalid formatting template.",
        "1. Keep both errors and the stderr traceback. Preserve a backup and restore a verified "
        "catalog/database or report the defect. Editing this reference table does not repair ErrorText.",
    ),
)
