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
Fabric and Setup show the actual database path. A new database is initialized
automatically. Databases from versions 0.1 through 0.3 prompt for a backed-up upgrade
to add ErrorMessage (plus HelpText before 0.3 and Dropdown for 0.1); declining leaves the database
unchanged. Close all other copies
of the application before accepting. A verified `PreUpgrade_*` database is kept
beside the original. Existing inventory, history, IDs, selections and sort order
are preserved, and existing fabric descriptions seed the new lists. Failed
upgrades roll back. Unknown or incompatible databases are rejected.
Tkinter must be available in the Python installation.

### Navigation and help

Every application screen and workflow window has the same top-right navigation:
**Fabric / DropDown / HelpText / ErrorMessage / Setup / Screen Help**.
Switching screens closes unfinished dialogs, releases their modal grabs, and
resets unsaved entry forms before showing the destination. Unsaved input requires
confirmation; declining keeps the current screen, input and dialog intact.
This also applies when choosing the current screen again. Saved inventory,
dropdown choices, help edits and selection sets are never undone by navigation.
Fabric list filters, saved selections and sort order are retained.

**Screen Help** opens help for the current screen or workflow without leaving it
or discarding edits. Closing help restores the underlying dialog's input grab.
Hover over an entry, button or list column for a tooltip; press **F1** for full
help. For list columns, F1 uses the last column under the pointer (initially ID).
Operating-system file pickers and confirmation/error prompts remain standard
modal dialogs; dismiss them before using application navigation.

**HelpText** maintains a generated tooltip/full-help pair for every application
screen/field, list column and button. Select a row, edit the multiline **Hover
Text** and **Full Text**, then choose **Update**. Table Name identifies the screen;
Field Name is a field name, `Column:<name>`, `Button:<caption>` or `ScreenHelp`.
These keys are read-only. Saved edits take effect on the next tooltip/F1/help
lookup. Startup inserts missing help objects without overwriting user text.
Text is plain text, not rich text.

Click a HelpText column heading to toggle ascending/descending order. Its sort
is saved separately from Fabric in the existing `ScreenState` table; no separate
sort table is added. Existing runtime `ErrorText` functionality is unchanged.

### Error-message reference

**ErrorMessage** provides a blue entry area and a list for adding, updating and
deleting troubleshooting messages. Its table contains generated **ID**, **ErrorText**,
**LikelyCause** and **Description** columns. All three text fields are required;
Error Text and Likely Cause allow 4,000 characters, Description 16,000. Highlight
one row to edit it; Add creates a separate entry, Update changes that entry, and
Delete requires confirmation. Stale updates/deletions are rejected. Navigation,
highlight changes and list changes protect unsaved input with confirmation.

New databases and upgrades populate the reference from every existing runtime
message template, plus startup and error-catalog failure templates. Initial runtime
reference IDs match the runtime Error IDs. Later reference additions have independent
IDs. Numbered likely causes have corresponding numbered fixes in Description.
Braced placeholders such as `{detail}` and `{limit}` represent variable values,
not literal complete error messages. System/SQLite exception details are represented
by their enclosing template; arbitrary OS-specific strings are not enumerated.
Startup messages may not have runtime Error IDs.

The toolbar is **Select Highlighted / Filter / Set / Sort**, followed by Reset
Selection, Refresh and Print. Filter searches Error Text, Likely Cause and
Description using literal text-contains matching, ignoring ASCII case. Multiple
nonblank criteria are ANDed, including any existing highlighted-row restriction.
Set saves all listed IDs as a named snapshot, not just highlights. Applying a set
clears other restrictions. Message sets and saved multi-column sorts are separate
from Fabric's. ID sorts numerically and is added to break sort ties. Deleting a
message also removes its saved-set memberships; deleting a set keeps its messages.
List restrictions persist during navigation, but reset on restart; sets and sorts
persist in SQLite.

**Print** saves an HTML report at a **new filename** and opens the default browser's
print dialog. The report contains exactly the listed messages, including all
three text fields, in their current sort order, regardless of highlights. It
excludes unsaved entry edits and changes not yet refreshed into the list. An empty
list prints headings only. Use browser printing to select a printer or save to PDF.
If the browser cannot open, the report remains available to open and print manually.
Existing files are never overwritten.

**Scope:** this is an editable troubleshooting reference, not a rewrite of runtime
error handling. The existing `ErrorText` table still supplies actual error dialogs;
editing or deleting reference entries cannot disable them. Reference defaults are
populated once, so edits and deletions survive restart. Backup/restore includes
messages, message sets and sort settings. No inventory behavior, logging system,
error history, printer drivers, or other report types are added.

### Fabric rectangles

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

Open **DropDown** from the navigation bar, choose a field, highlight an item, and use
**Set Default**. The next cleared/new form uses that default; existing records
are not changed. Navigating away from Fabric discards unsaved form values after
confirmation. The DropDown screen can also add items.
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

The controls are on the **Setup** page, not the fabric form.
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
history, selections and backup/restore; `quilting/helptext.py` defines the default
help catalog; `quilting/ui.py` owns screen behavior and shared form/list controls.
`quilting/errors.py` defines error-reference fields and default causes/fixes.
All persistent application information is in
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

Cutting plans, remnant transactions, reservations, inventory/cutting print reports, general
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
record, compact left-aligned entries, dropdown defaults, minute-level timestamps,
retirement, navigation alignment and cleanup, nested modal help, complete
control-help bindings, live help edits, independent HelpText sorting, error-message
maintenance/list operations and escaped, ordered print-report snapshots.
Database tests cover validation, exact dimensions, stale updates, transaction
rollback, history, persistence, error messages, dropdown normalization,
backed-up upgrades/rollback, HelpText validation and preservation, error-reference
CRUD/conflicts, literal searches, isolated selection sets, and backup/restore.
