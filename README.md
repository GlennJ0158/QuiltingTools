# Quilting Tools

Python + SQLite desktop tools for quilting, using Tkinter and the Python standard
library. The screen conventions follow the `GlennJ0158/PrintFilaments` inventory
application: blue entry area, list/detail maintenance, named selection sets,
multi-column sorting, and F1 field help.

## Current milestone: Fabric Inventory

Run with Python 3.10 or later:

```sh
python QuiltingTools.py
python QuiltingTools.py --database "/path/to/QuiltingInventory.db"
```

The default database is `QuiltingTools/QuiltingInventory.db` in your home directory.
The screen always shows the actual database path. A new database is initialized
automatically. Version 0.1 databases prompt for a backed-up upgrade to add the
Dropdown table; declining leaves the database unchanged. Close all other copies
of the application before accepting. A verified `PreUpgrade_*` database is kept
beside the original. Existing inventory, history, IDs, selections and sort order
are preserved, and existing fabric descriptions seed the new lists. Failed
upgrades roll back. Unknown or incompatible databases are rejected.
Tkinter must be available in the Python installation.

Each record represents **one physical usable rectangle**, not a quantity of
interchangeable pieces. Enter its Fabric Name, Color, Pattern Name, Usable Width,
Usable Length, Grain Direction, Print Direction, Storage Location, Status and
Notes. Pattern Name describes the fabric's print, not a quilt pattern.
Exclude selvage and damaged edges from usable dimensions. Grain and print
directions are relative to the width and length as entered; dimensions are not
silently rotated. Unknown directions remain explicitly unknown.

This milestone uses **inches**. Measurements accept whole numbers, decimals
through six places, and proper fractions in halves through sixty-fourths,
including mixed values such as `42 1/2`. Dimensions must be positive and no
larger than 10,800 inches (a full bolt). SQLite stores integer millionths of an inch, avoiding
binary floating-point rounding; fractions and decimals round-trip exactly.
Metric entry/conversion is not yet implemented.

### Maintaining inventory

- **Add** saves a new rectangle. **Clear** clears the details and highlights to
  prepare a new record; it does not delete anything.
- Highlight one row to fill the form. **Add** creates another physical piece
  from those values, with a new ID and independent history; **Update** modifies
  the highlighted piece. This supports several rectangles cut from the same
  bolt without re-entering their shared descriptions. Multiple highlights
  are for list selection, not bulk editing. Unsaved changes require confirmation
  before a navigation or close operation discards them.
- All entry fields are **left-aligned**, including measurements. Controls have
  fixed character widths reflecting expected input, rather than stretching with
  the window. Measurements use six characters; longer fractions still fit as
  scrollable input without restricting their accepted precision. Metadata keeps
  full timestamps in SQLite but displays local dates and `HH:MM` only.
- **History** shows before/after snapshots of every saved addition or change.
  No-op updates do not add history. Each save and its history commit together.
  Revision checks reject stale updates from another application instance.
- **Retired** removes a piece from the initial Available view without deleting
  its record or history. Status changes can be reversed with Update. Retirement
  is not a cutting transaction. Dimensions can be corrected manually, with the
  reason recorded in Notes.

### Standardized dropdowns

Fabric Name, Color, Pattern Name and Storage Location use database-backed,
read-only selection lists. Their order is **default first, Add Item second,
then the remaining values alphabetically**, ignoring case. Initially the default
is blank. Choose **Add Item** to enter a value without leaving the fabric form;
Cancel leaves the previous value intact. Names differing only in ASCII letter
case or surrounding whitespace reuse the existing spelling rather than creating
duplicates. Saving fabric also registers/canonicalizes these values at the
database boundary.

Open **Setup/Utilities > Dropdown**, choose a field, highlight an item, and use
**Set Default**. The next cleared/new form uses that default; existing records
and unsaved form values are not changed. The setup page can also add items.
Grain Direction, Print Direction and Status get their defaults from the same
`Dropdown` table, but keep their defined choices: arbitrary directions or stock
statuses cannot be added.

### Working lists

The shared toolbar order is **Select Highlighted, Filter, Set Selection, Sort**,
followed by Reset Selection and Refresh.

**Select Highlighted** restricts the current working list to its highlighted
rows. It requires at least one highlight and does not change inventory.
**Filter** adds case-insensitive text-contains criteria, inclusive minimum
width/length and an optional status. Text such as `%` is matched literally.
Minimum-size filtering respects the recorded orientation.

**Set Selection** saves all records in the current working list, not just
highlighted rows. Saved sets are database-backed snapshots of record IDs.
Applying a saved set clears other filters and highlight restrictions. Subsequent
edits or retirement do not change its membership; new inventory is not added
automatically. Deleting a set never deletes fabric.

**Sort** supports multiple distinct columns with ascending/descending order.
ID is appended if absent to make ties deterministic. Numbers sort numerically,
not by their formatted text. The sort is saved in SQLite. Current filters and
transient highlights reset on application startup to the Available view;
use a named set to retain a working group.

Immediately above each record list, a heading starts with the current working
record count, followed by its active sort and any restrictions. That count is
not the number of highlighted rows. Numeric values **and their column headings**
are right-aligned; all other values and headings are left-aligned. Internal
descriptive names such as `UsableWidth` appear as `Usable Width` in labels.
Press F1 in an editable field for help.

### Backup and restore

The controls are on the **Setup/Utilities** page, not the fabric form.
**Backup Database** uses SQLite's consistent backup API, checks the resulting
database, and publishes it only when complete. Unsaved form edits are not
included. Choose a **new filename**: existing files are never overwritten.
Keep backups on a separate device as appropriate.

**Restore Database** validates a selected backup and creates a separate
database at a new filename. It neither replaces nor switches the open database.
Close the application, then use the displayed `--database` command to open the
restored copy. The original, backup and restored copy retain their IDs,
relationships, history and automatic-ID counters.
Version 0.1 backups can also be restored to a new file, then upgraded when opened.

Keep the live SQLite database on a local disk, not a network share or actively
synchronized folder. The application is intended for local desktop use, not
high-concurrency or authenticated multi-user operation. History is an inventory
change record, not a security audit. Backup publication requires filesystem
support for hard links and reports a failure if that is unavailable; an existing
destination is never replaced.

### Validation and errors

Every editable field uses a declared Tk variable. The shared form checks the
field, widget and variable registries at creation and again before loading or
reading values. Missing, extra or disconnected fields stop the operation.
Validation also runs at the database boundary; key inventory invariants have
SQLite constraints.

`ErrorText` stores database-generated `ErrorTextID` numbers, stable internal
message keys, descriptions explaining when/why each message occurs, message
templates and resolution suggestions. Displayed validation messages include the
spaced field name, reason, suggestion when applicable, and Error ID.
Database/file failures are reported, not converted into successful operations.
Startup cannot rely on an error catalog in an unreadable database, so its
failure dialog reports the path and underlying reason directly. Unexpected
Tkinter callback failures display an error and write a traceback to stderr.

## Structure and next milestones

`QuiltingTools.py` is the entry point. `quilting/model.py` owns shared field
definitions and exact measurements; `quilting/database.py` owns persistence,
history, selections and backup/restore; `quilting/ui.py` owns screen behavior
and shared form/list controls. All persistent application information is in
SQLite; the source code defines supported validation rules and schema.

The integrated roadmap remains:

1. **Fabric Inventory and shared utilities**: implemented in this milestone.
2. **Quilt Backs**: selected rectangles, target backing dimensions and margins,
   seam allowances, rectangular panel layouts and printable cut/assembly plans.
   Drafts will not consume fabric. Confirmed cuts will recheck availability and
   transactionally record consumption and measured reusable remnants.
3. **Blocks & Quilts**: versioned reusable block definitions, construction methods,
   named quilt patterns and actual quilt projects. Begin with Nine Patch and
   one Flying Geese method. Produce block, batch and whole-quilt cutting lists,
   per-block assembly lists and block-type counts.

Cutting plans, remnant transactions, reservations, print reports, general
geometry editing, metric measurements and automatic waste optimization are
**not** implemented yet. Future block/layout calculation should stay separate
from the UI and inventory persistence. Do not copy filament-specific stock
calculations into quilting.

## Development

No third-party Python packages are needed.

```sh
python -m unittest discover -v
# Linux, including actual Tkinter screen tests:
xvfb-run -a python -m unittest discover -v
```

GUI tests require a display and are explicitly skipped without one. They exercise
field bindings and round-trips, list alignment and button order, selection,
filtering, saved sets, numeric sorting, unsaved edits, duplication from a highlighted
record, compact left-aligned entries, dropdown defaults, minute-level timestamps
and retirement.
Database tests cover validation, exact dimensions, stale updates, transaction
rollback, history, persistence, error messages, dropdown normalization,
backed-up upgrades/rollback and backup/restore.
