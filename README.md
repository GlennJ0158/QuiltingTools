# Quilting Tools

Python + SQLite desktop tools for quilting, using Tkinter and the Python standard
library plus Shapely for block geometry. The screen conventions follow the `GlennJ0158/PrintFilaments` inventory
application: blue entry area, list/detail maintenance, named selection sets,
multi-column sorting, and F1 field help.

## Current milestone: Fabric Inventory

Run with Python 3.10 or later:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python QuiltingTools.py
python QuiltingTools.py --database "/path/to/QuiltingInventory.db"
```

The default database is `QuiltingTools/QuiltingInventory.db` in your home directory.
Fabric and Setup show the actual database path. A new database is initialized
automatically. Schema version 17 is the current development baseline. Upgrade
code for older versions remains in place for now; the application is not yet
deployed. Upgrades add optional fabric color values and block-part ranges and
later database features; declining leaves the database unchanged. Close all
other copies of the application before accepting.
A verified `PreUpgrade_*` database is kept
beside the original. Existing inventory, history, IDs, selections and sort order
are preserved, and existing fabric descriptions seed the new lists. Failed
upgrades roll back. Unknown or incompatible databases are rejected.
Tkinter must be available in the Python installation.

### Navigation and help

Application screens have top-right navigation:
**Fabric / Quilt Backs / QuiltBlock / Quilt / DropDown / HelpText / ErrorMessage / Setup / Screen Help**.
Workflow dialogs stay on the current screen and provide **Screen Help** without
the screen-navigation buttons. They open at the top-left of the first list on
the current screen (or the screen's top-left when it has no list). Close or
cancel a dialog, or use its save-and-return action, before choosing another
application screen. Switching screens resets unsaved entry forms.
Saved inventory,
dropdown choices, help edits and selection sets are never undone by navigation.
Fabric list filters, saved selections and sort order are retained.

**Screen Help** opens help for the current screen or workflow without leaving it
or discarding edits. Closing help restores the underlying dialog's input grab.
Hover over an entry, button or list column for a tooltip; press **F1** for full
help. For list columns, F1 uses the last column under the pointer (initially ID).
Operating-system file pickers and confirmation/error prompts remain standard
modal dialogs; dismiss them before using application navigation.

Setup's **About Quilting Tools** block displays the application release version
and database schema version separately. For example, application version `0.5.0`
and schema version `16` are different numbering systems and are not expected to
match.

**HelpText** maintains a generated tooltip/full-help pair for every application
screen/field, list column and button. Select a row, edit the multiline **Hover
Text** and **Full Text**, then choose **Update**. Table Name identifies the screen;
Field Name is a field name, `Column:<name>`, `Button:<caption>` or `ScreenHelp`.
These keys are read-only. Saved edits take effect on the next tooltip/F1/help
lookup. Startup inserts missing help objects without overwriting user text.
If help is missing, its tooltip or F1 window shows a warning; the action remains
available. Text is plain text, not rich text.

HelpText includes the same Filter, Set Selection and multi-column Sort controls as
the other working lists. Its sort is saved separately from Fabric in the existing
`ScreenState` table; no separate sort table is added. Existing runtime `ErrorText`
functionality is unchanged.

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

The entry fields each show three lines and have vertical scrollbars. The read-only
ID appears above Error Text; it is blank when no record is selected. The toolbar is
**Select Highlighted / Filter / Set Selection / Reset Selection / Sort**, followed by
Refresh and Print. Filter searches Error Text, Likely Cause and
Description using literal text-contains matching, ignoring ASCII case. Multiple
nonblank criteria are ANDed, including any existing highlighted-row restriction.
Set Selection saves all listed IDs as a named snapshot, not just highlights. Applying a set
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
interchangeable pieces. Enter its Fabric Name, Color, Fabric Pattern, Usable Width,
Usable Length, Grain Direction, Print Direction, Storage Location, Status and
Notes. Fabric Pattern describes the fabric's print, not a quilt pattern.
Exclude selvage and damaged edges from usable dimensions. Grain and print
directions are relative to the width and length as entered; dimensions are not
silently rotated. Unknown directions remain explicitly unknown.

This milestone uses **inches**. Measurements accept whole numbers, decimals
through six places, and proper fractions in halves through sixty-fourths,
including mixed values such as `42 1/2`. Dimensions must be positive and no
larger than 10,800 inches (a full bolt). SQLite stores integer millionths of an inch, avoiding
binary floating-point rounding; fractions and decimals round-trip exactly.
Metric entry/conversion is not yet implemented.

Read-only dimensions are displayed as reduced fractions to the nearest 1/16
inch (halfway values round up); `~` marks a rounded value. Calculated cut sizes
round up to the next 1/16 inch instead. Editable fields retain exact values.
Plans and diagrams still use exact sizes and positions, so rounded-up cuts can
exceed the available space or overlap: verify fit and allocations before cutting.

### Maintaining inventory

- **Add** saves a new rectangle. **Clear** clears the details and highlights to
  prepare a new record; it does not delete anything.
- Highlight one row to fill the form. **Add** creates another physical piece
  from those values, with a new ID and independent history; **Update** modifies
  the highlighted piece. This supports several rectangles cut from the same
  bolt without re-entering their shared descriptions. Multiple highlights allow
  bulk updates of checked fields. Unsaved changes require confirmation
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
- **Print List** and **Print Labels** use highlighted rows when present, or
  otherwise the current Fabric working list, in its current sort order. Print
  List creates a landscape, double-spaced worksheet with exact measurements.
  Print Labels creates Avery 8660 sheets with a prominent rectangle ID and
  12-point name and dimensions; width and length round up to 1/16 inch without
  a rounding marker. Print labels at actual size (100%) on Avery 8660 stock.

### Quilt backs

Open **Quilt Backs** to enter a name, quilt width/length, separate top/bottom and
side overhang margins, and one seam allowance used at every seam. Margins over
10 inches produce a warning but are accepted. Existing plans retain their former
equal margins when the database is upgraded. The available
fabric list initially follows the Fabric Inventory working selection and filters.
**Use Named Selection** applies an existing Fabric selection locally, or restores
the current Fabric working list; **Select Highlighted** restricts the source list
to its highlighted rows. Neither changes the Fabric screen. Only available pieces
are shown. Highlight
rectangles to restrict a plan, or leave none highlighted to use all listed available
rectangles. Optionally choose a controlled **Sketch Color** for each source,
and choose **Generate Plans**. Color suggestions are derived from inventory text,
but can be overridden for the plan. No swatch data is added to inventory. The
assembly sketch shades every finished panel with its palette color, marks known
grain with arrows, identifies unknown grain, and includes a legend with the
inventory fabric name, rectangle ID (`Fabric Name (ID)`), and recorded color description.

The first planner release generates one-piece or equal-width vertical-strip or
equal-length horizontal-strip layouts, up to 20 panels. It uses the highlighted
rectangles if any, otherwise all listed available rectangles, never silently rotates them, and checks a nonoverlapping
shelf-cut placement within each source piece. A single rectangle can supply multiple
panels. The planner ranks feasible plans by panel-size tier (20% of quilt size
preferred, then 10%; every panel is at least 5 inches), known consistent grain,
fewer panels, and smaller total source area. It only shows alternatives from the
best feasible panel-size tier. The alternatives are compromises, not an automatic
promise of minimum waste. This release does not search arbitrary unequal panels,
T-joints, general two-dimensional nesting or layouts above 20 panels.
The layout heading reports the number of candidates without a sort order.
Quilt Backs measurement controls are eight characters wide but do not limit the
length of valid input. The fractional display rules above also apply to printed plans.

Preview the assembly sketch, then **Save Draft** and **Print Plan** as needed.
Drafts retain source IDs/revisions and do not reserve or modify inventory. At
**Confirm Cuts**, the operator reports the measured reusable remainder for each
source, or leaves both dimensions blank if it was consumed. These entries are
authoritative: the app does not infer actual cuts or limit a measured remainder
to the plan's estimated waste. It retires each source, adds entered remnants as
new inventory rectangles, and records the back, source snapshots and inventory
history in one transaction. A changed/retired source blocks confirmation so the
operator can generate a new draft using the reconciled inventory. **Mark Assembled** records sewing completion;
it does not alter inventory. Multiple drafts do not reserve fabric, so only the
first plan using a source can be confirmed without regeneration.

### Quilt blocks

Open **QuiltBlock** to add a named draft with finished width and length, scale
percentage (100 by default), and seam allowance (1/4 inch per edge by default).
Scale applies to the finished design and placement coordinates, not seam allowance.
Fabric inventory has an optional **Color Value** from 1 (very light) to 10
(very dark). Leave it blank if unknown. In **Parts**, enter both minimum and
maximum Color Value to restrict a part, or leave both blank for no restriction.
Unknown fabric values do not qualify for a restricted part.
Scale is displayed as a percentage without scientific notation. Existing scale
limits are unchanged. Approved blocks cannot be edited; select one and choose
**New Version** to make an editable draft. If a draft changed since it was loaded,
copy unsaved edits elsewhere, choose **Refresh**, confirm discarding them, select
the block again, and re-enter the edits before choosing **Update**. Selecting the
already-highlighted row does not reload it.
Add part definitions through **Parts**: rectangle, square, right triangle,
isosceles triangle, circle or semicircle. Enter finished measurements and a
count per block. Squares require equal sides. For triangles, side `a` is the
horizontal base and `b` and `c` connect its left and right ends to the third
vertex. Right triangles must satisfy the Pythagorean relationship within a
relative tolerance of 0.000001; isosceles triangles require equal entered sides.
Circles and semicircles use a diameter; the semicircle occupies the upper half
of its diameter's circle. Choose a controlled sketch color.

**Sketch** shows every part instance using finished dimensions; choose an instance
and save its unscaled position from the top left of the block, rotation in whole
degrees, and optional mirror. Its reported cut bounding dimensions come from an
outward seam offset, not independently enlarged triangle sides. Curves and
offsets are approximated as polygons (64 segments per quarter-circle); printed
outlines are visual guides, not cutting templates. Print Sketch saves an HTML
report at a new filename and opens the browser print dialog.
To compare saved layouts side by side, highlight multiple block rows (Ctrl-click
or Shift-click) and choose **Sketch**. Scroll to see additional blocks; close the
comparison and select one block to edit its placements.

**Fabric Rules** controls how each block copy uses fabric. **Legacy** preserves
the original unrestricted packing behavior. **Distinct** tries to use a different
fabric name for every position; **Grouped** permits reuse between positions.
Legacy ignores saved groups without deleting them.
In either new mode, select positions and assign the same group name to require
them to use the same fabric name, including across different part definitions
or mirrored instances. Leave the group blank for an independent position. Group
names and fabric names are compared without regard to case. Apply each group
before selecting another position, then save the rules. Rules are editable on
drafts, copied by New Version, and immutable after approval.

**Approve** checks all instances, overlaps, gaps and overflow against the block
rectangle before making the version immutable. The geometry check allows an area
tolerance for triangle-side rounding equivalent to one-half microinch of unscaled
geometry per block perimeter (at least 0.0000000001 square inches); curves are
approximations.
**New Version** copies a block and all placements into a separate draft, preserving
the original. Block selections and sort order are independent of Fabric. Deleting
a draft removes its parts and set memberships; approved versions are not deleted.

Block design never reserves or changes fabric inventory.

**Create from Template** adds an editable draft using the finished width and
length currently entered on the QuiltBlock form, along with its scale and seam
allowance. Starter layouts include Four Patch, Nine Patch, Flying Geese,
Log Cabin (Square), Log Cabin (Spiral), and Half-Square Triangle. Square retains
the original concentric layout. Spiral uses light top/left logs (values 1–4)
and dark bottom/right logs (values 7–10), with a stepped rather than straight
diagonal boundary. Its center follows the block proportions, is unrestricted
and defaults to yellow; edit
its color and optional value range in Parts. These are editable defaults and
existing saved blocks are unchanged. The generated parts and placements can be
edited before approval; colors are visual defaults. Wedding Ring is not included
because its curved arc pieces are not represented by the current geometry model.
New log cabin templates default to Distinct; the other templates default to
Grouped, with positions sharing a sketch color grouped together. These defaults
can be edited on the draft; existing saved blocks remain Legacy.

### Quilt composition and cutting plans

Open **Quilt** to create or select a project. Choose an approved block version and
use **Set Block Quantity** for the required count. A version may belong to several
quilts concurrently; later draft copies never alter their selected versions.
Block scale applies uniformly to the finished design; seam allowance remains the
entered physical allowance. Changes of scale require a new version once approved.

Choose a used **Part Color**, then an **Inventory Color**, and choose **Map Color**;
repeat for every part color. Mappings apply to every part of that color in the
quilt, and one part color can map to multiple inventory colors.
Choose a block already added to the quilt and open **Eligible Fabrics**. For each
part, highlight the desired pieces and choose **Assign Fabric to Part**; use
**Remove Assignment** to remove choices and **Save Selection and Return** to
save all changes. Assignments are per quilt and part, even when parts share a
color, and restrict rather than replace the color mappings. If a part has no
assignments, any otherwise matching piece may be used, preserving existing
quilts' behavior. Eligible Fabrics uses the current Fabric working selection and
also shows previously assigned pieces outside that selection. Planning checks
the working selection, availability, color mapping, value range, and fit;
assignments do not reserve fabric. **Plan Quilt**
aggregates all selected blocks' parts and packs their cut-outline bounding
rectangles into Available fabric in the Fabric Inventory working list. Legacy blocks
prefer an already used source with space, then a fitting leftover region and smaller
source area. For Distinct and Grouped blocks, the planner works from larger cut
bounding areas to smaller ones and chooses the smallest qualifying source area.
Pieces with the same fabric name count as the same fabric, even if they are
separate inventory rectangles. A sharing group must be satisfiable by that name
for every position, including each part's assignments, mapped color and value range.
Each group is allocated together when its largest position is encountered.
If Distinct runs out of unused qualifying names but reuse can complete the current
position or group, choose whether to clear that block copy's used-name markers and
continue with the existing choices, or cancel. If no qualifying fabric can fit,
planning cancels with a shortage message. In either case cancellation saves no
partial plan for the new rules. Retry choices stay in memory, do not reserve
inventory, and are discarded on cancellation or exit. The app does not hold a
database write transaction while prompting; it checks the inputs again before
saving and asks for replanning if they changed. Legacy blocks continue to report
shortages in saved partial plans. Parts can rotate 90 degrees;
the plan records source orientation, assembly rotation, mirrored instances, grain
and print descriptions for operator review. Many parts can share one source.

Packing is a deterministic heuristic, not a proof of minimum fabric consumption.
It does not interlock triangles or curves; each outline gets its own rectangular
bounding space. Plans support at most 10,000 required part instances and explicitly
report quantities left unfilled because no mapped color or fitting source was found.
It is possible another layout could fit where this search reports shortages.

Plans retain their quilt composition, color mapping and fabric revision snapshots.
They can be reopened and printed as an HTML cutting report with source diagrams.
Choose **Entire Quilt** to combine equivalent parts across blocks, or **By Block**
to group parts by block type and quantity. Both show required counts, source
fabric allocations and shortages, finished dimensions and cut bounding sizes;
the detailed source allocations and diagrams remain in the report.
Diagrams and cutting outlines are visual guides, not actual-size templates.
Plans are **informational only**: they neither reserve nor consume fabric. Save
quantity/mapping changes before planning, and regenerate after inventory changes.

### Standardized dropdowns

Fabric Name, Color, Fabric Pattern and Storage Location use database-backed,
read-only selection lists. Their order is **default first, Add Item second,
then the remaining values alphabetically**, ignoring case. With no active default,
Add Item comes first, followed by the active values alphabetically. Initially the default
is blank. Choose **Add Item** to enter a value without leaving the fabric form;
the window opens below and to the right of the field when space permits.
Cancel leaves the previous value intact. Names differing only in ASCII letter
case or surrounding whitespace reuse the existing spelling rather than creating
duplicates. With no default, the control displays **Choose \<FieldName\>** as a
placeholder; it is never saved as a value. Fabric Name is required, while Color,
Fabric Pattern and Storage Location save as NULL when left blank.

When adding an item, choose whether to set it as a default. If another default
exists for the same key, choose whether to clear the others, keep them (with a
warning), or cancel. Clearing the other defaults and saving the item are atomic.
The same choice is available when setting a default in DropDown maintenance.

Open **DropDown** from the navigation bar and choose a supported table or screen,
then its **Field Name**. Choose **Show Everything** in Table Name to view all
dropdown rows, including inactive items; Field Name is disabled in this view.
You can update or delete a highlighted row there, but adding requires a specific
table and field. Enter a **List Item**
and choose **Set Default** or **Clear Default**, and **Set Use** or **Clear Use**,
then choose **Add**. Highlight a row to **Update** or **Delete** it; on update,
each flag may be left unchanged with **Ignore for Update**. Blank List Item on update
leaves its value unchanged. Delete requires confirmation and removes the item from
saved dropdown selection sets, not existing fabric records. Saving fabric registers
its values and can recreate a deleted choice. Data-derived menus, such as saved
quilts, approved blocks and inventory colors, are not maintained here.

Values are stored per key, and inactive items remain visible for maintenance but
are excluded from fabric selection lists. A list can have no default. If multiple
items are marked default, a warning appears on Add or Update; the first active
default encountered is used and the others are ignored until corrected. The next
cleared/new form uses that default (or **Choose \<FieldName\>** if none); existing
records are not changed. Protected system lists cannot be added to, deleted or have
their values or Use flags changed. Changing their default requires confirmation
because it may affect internal program operations or assumptions; the UserModified
indicator is read-only. Def and Use are five-character columns. Navigating away from
Fabric discards unsaved form values after confirmation.
Grain Direction, Print Direction and Status get their defaults from the same
`Dropdown` table, but keep their defined choices: arbitrary directions or stock
statuses cannot be added.

### Working lists

The shared toolbar order is **Select Highlighted, Filter, Set Selection,
Reset Selection, Sort**, followed by screen-specific actions such as Refresh.

**Select Highlighted** restricts the current working list to its highlighted
rows. It requires at least one highlight and does not change inventory.
**Filter** adds case-insensitive text-contains criteria, inclusive minimum and maximum
width/length, inclusive After/Before Date Modified bounds and an optional status. Date
bounds use `mm/dd/yyyy` at 00:01 in the computer's local time; equality is included.
Date Modified reflects any saved inventory change, not only fabric use.
Color uses the inventory color dropdown.
Text such as `%` is matched literally. Size filtering respects the recorded orientation.

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

The **DropDown** choices, **HelpText** catalog, **Quilt Backs** saved plans and read-only **History** list use
the same selection, filtering, named-set and multi-column sort workflow. Dropdown
sets are scoped to the currently selected Table Name and Field Name; History sets
are scoped to the currently selected piece. Show Everything has its own selection
sets and saved sort; its default order is Table Name ascending, Def descending,
Field Name ascending, List Item ascending, then ID ascending. Dropdown filters search List Item or select
default/non-default rows. HelpText filters search each text/key column. History
filters match action, timestamp or saved Before/After values. Quilt Backs filters
match back name and status; its controls do not affect source or candidate lists.
Each list's sort is
saved independently; HelpText no longer relies on heading-click sorting. Applying
a saved set clears that list's other restrictions, and Reset Selection restores
all rows in the current scope.

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
2. **Quilt Backs**: the first-release rectangular strip planner and operator-confirmed
   inventory adjustment are implemented. Automatic general-purpose waste optimization
   and reservation workflows remain future work.
3. **Blocks & Quilts**: versioned block/part definitions, validated sketches,
   quilt quantities, explicit color mapping and informational cutting plans are
   implemented. Construction methods and automatic assembly remain future work.

Reservations, unrestricted geometry editing, metric measurements and exact waste
optimization are **not** implemented yet. Future block/layout calculation should stay separate
from the UI and inventory persistence. Do not copy filament-specific stock
calculations into quilting.

## Development

For implementation tasks, commit and merge completed changes unless the request
specifically says not to commit or merge.

Install dependencies from `requirements.txt` into the active environment before testing.

### Schema migrations

Keep fresh-database creation separate from upgrade migrations. For future schema
versions, isolate each version-to-version migration from legacy upgrade logic
rather than extending a shared chain of version-specific conditions. When schemas
below version 16 are no longer in scope, raise the minimum upgrade version and
remove those legacy migrations and their fixtures/tests without changing newer
migrations.

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
Block/quilt tests cover immutable approval, independent draft copies, seam offsets,
layout gaps/overlaps, rollback, multi-part source packing, saved shortages and
non-consuming GUI/printing workflows.
