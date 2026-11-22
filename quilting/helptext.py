"""Default help catalog, keyed by screen and field, column or button."""

from .model import (
    FABRIC_FIELDS, FILTER_FIELDS, GRAIN_DIRECTIONS, LIST_COLUMNS, PRINT_DIRECTIONS, SORT_FIELDS,
    STATUSES, Field,
)
from .errors import ERROR_COLUMNS, ERROR_FIELDS, ERROR_FILTER_FIELDS
from .blocks import BLOCK_COLUMNS, BLOCK_FIELDS, BLOCK_FILTER_FIELDS, COLORS, PART_FIELDS, SHAPES
from .backs import PALETTE

NAVIGATION = ("Fabric", "Quilt Backs", "QuiltBlock", "Quilt", "DropDown", "HelpText", "ErrorMessage", "Setup", "Screen Help")
DROPDOWN_FORM_FIELDS = (
    Field("TableName", "choice"),
    Field("FieldName", "choice"),
    Field("ListItem"),
    Field("Def", "choice"),
    Field("Use", "choice"),
)
HELP_FIELDS = (
    Field("TableName", required=True),
    Field("FieldName", required=True),
    Field("HoverText", required=True, limit=4000, kind="memo", width=80),
    Field("FullText", required=True, limit=16000, kind="memo", width=80),
)
HELP_COLUMNS = ("ID", "TableName", "FieldName", "HoverText", "FullText")
DROPDOWN_COLUMNS = ("ID", "TableName", "FieldName", "ListItem", "Def", "Use", "UserModified")
HISTORY_COLUMNS = ("ID", "Action", "DateCreated")
BACK_LAYOUT_COLUMNS = ("ID", "Layout", "Parts", "Seams", "Grain", "Minimum", "FabricArea")
BACK_COLUMNS = ("ID", "BackName", "BackWidth", "BackLength", "Status", "DateModified")
BACK_FILTER_FIELDS = (
    Field("BackName"),
    Field("Status", "choice", choices=("", "Draft", "Cut", "Assembled")),
)
DROPDOWN_FILTER_FIELDS = (
    Field("ListItem"),
    Field("Default", "choice", choices=("", "Yes", "No")),
)
HELP_FILTER_FIELDS = tuple(
    Field(name, limit=16000 if name == "FullText" else 4000)
    for name in HELP_COLUMNS[1:]
)
HISTORY_FILTER_FIELDS = (
    Field("Action", "choice", choices=("", "Added", "Updated")),
    Field("DateCreated"),
    Field("Values", limit=16000),
)

SCREEN_HELP = {
    "Quilt": ("Compose a quilt and plan its cuts.", "Create or select a quilt; choose approved block "
              "versions and their quantities. Map each part color to one or more inventory color "
              "values, then choose Plan Quilt. Plans pack conservative cut bounding rectangles, "
              "can report shortages and do not reserve or change inventory. Existing plans are "
              "snapshots; regenerate after changes. Available sources follow the Fabric working list. "
              "Choose Entire Quilt or By Block, then "
              "Print Quilt Plan to print the saved plan."),
    "QuiltBlock": ("Maintain reusable block designs.", "Save a draft block, add parts, set each "
                   "instance's position and orientation in Sketch, then approve a fully covered, "
                   "non-overlapping layout. Approved blocks are immutable; New Version copies one "
                   "to an independent draft. Scale changes finished dimensions, not seam allowance."),
    "Block Parts": ("Maintain a block's part definitions.", "Choose one supported shape and enter its "
                    "finished dimensions, color and number per block. Triangle a is the horizontal base; "
                    "b and c meet its left and right ends. Circles and semicircles use diameter."),
    "Block Sketch": ("Arrange each part instance.", "Choose a part instance, enter its unscaled base "
                     "position, rotation and mirror setting, then Save Placement. The displayed sketch "
                     "uses the block scale. Approval requires no overlap, gaps or out-of-bounds areas."),
    "QuiltBlock Filter": ("Filter the block list.", "Match literal name text and optional status."),
    "QuiltBlock Sort": ("Sort the block list.", "Choose distinct columns and ascending or descending order."),
    "QuiltBlock Set": ("Save or apply a block selection.", "Named sets contain listed block IDs; "
                       "deleting a set never deletes blocks."),
    "Fabric": (
        "Maintain one record for each physical usable fabric rectangle.",
        "Enter usable dimensions in inches, excluding selvage and damaged edges. Highlight one row "
        "to edit it. Add makes a separate rectangle; Update changes the highlighted rectangle. "
        "History shows saved changes. Retire a piece instead of deleting its history. "
        "Select Highlighted, Filter and Set Selection restrict the working list; Reset Selection "
        "shows all records. Sort saves an ordered list of sort fields. Quilt Backs and Quilt planning "
        "use only available fabric in this working list. Quilt Backs drafts do not "
        "change fabric; confirmed cuts retire sources and add operator-measured remnants. "
        "Navigation cancels unfinished work after confirmation; "
        "committed records are never undone.",
    ),
    "Quilt Backs": (
        "Plan, sketch and record rectangular quilt-back panels.",
        "Enter the quilt size, equal overhang margin and one seam allowance for the entire back. "
        "Available rectangles follow the Fabric working list. Highlight specific rectangles, or leave "
        "none highlighted to use all listed available rectangles, and generate layouts up "
        "to twenty panels. A source may supply multiple panels when a nonoverlapping shelf cut fits. "
        "Ranked alternatives favor minimum panel sizes, consistent grain, fewer parts and smaller "
        "source pieces. Source pieces are not rotated. Set a controlled sketch color per selected fabric; the "
        "legend also shows its inventory color description. Saving a draft does not change inventory. "
        "Confirm Cuts asks the operator to report any reusable remainder; source retirement and "
        "remnant creation are committed together. The Saved Plans controls filter, select and sort "
        "saved backs independently of fabric and candidate plans.",
    ),
    "Quilt Backs Filter": (
        "Filter saved quilt backs.",
        "Match literal text in Back Name and optionally choose a status. Both criteria apply together.",
    ),
    "Quilt Backs Sort": (
        "Choose the saved quilt backs order.",
        "Choose distinct columns and directions. Dimensions and IDs sort numerically; ID breaks ties.",
    ),
    "Quilt Backs Set": (
        "Save or recall a snapshot of saved quilt backs.",
        "Save Current saves all listed back IDs. Apply Saved clears other restrictions; "
        "Delete Saved removes only the snapshot.",
    ),
    "DropDown": (
        "Maintain supported dropdown lists and defaults.",
        "Choose a supported Table Name and Field Name. Dynamic menus whose values come from data "
        "are outside the DropDown system. UserModified is read-only. Protected system items cannot "
        "be added, deleted, or have their item text or Use flag changed; only Def can be changed, "
        "after confirmation that the change may affect internal program operations or assumptions. "
        "The list shows values for that key. Select Highlighted, Filter, Set Selection and Sort "
        "manage the current list. Add, Update and Delete maintain user-editable values and their "
        "Def and Use flags. Multiple active defaults produce a warning; the first encountered is used. "
        "Only supported lists appear here. Dynamic menus whose values are determined by data are "
        "outside the DropDown system. UserModified is read-only. Protected items can only have their "
        "default changed, after confirmation.",
    ),
    "Add Item": (
        "Add a fabric choice without saving the fabric form.",
        "Enter one nonblank choice and choose Add Item. The choice is saved immediately and "
        "selected in the Fabric form, but no fabric record is saved. Optionally set it as the default "
        "and clear other defaults for this list. Cancel restores the previous "
        "choice. Navigation abandons unfinished input after confirmation; a successfully saved "
        "choice is not removed when later fabric edits are discarded.",
    ),
    "HelpText": (
        "Edit the tooltip and detailed help for application controls.",
        "Highlight one help record. Table Name identifies its screen; Field Name identifies its "
        "field, Column: name, Button: caption, or ScreenHelp entry. Edit Hover Text and Full Text, "
        "then choose Update. Select Highlighted, Filter, Set Selection and Sort manage the list; "
        "saved sets contain HelpText row IDs. Hover Text appears as a tooltip and Full Text appears with F1. "
        "ScreenHelp entries supply Screen Help. Generated keys are read-only; user edits are "
        "preserved when the application restarts or new help objects are added. Click a column "
        "title to sort ascending or descending; the order is saved independently of Fabric.",
    ),
    "ErrorMessage": (
        "Maintain a searchable troubleshooting reference.",
        "Add, Update or Delete reference messages using Error Text, Likely Cause and Description. "
        "Numbered fixes in Description correspond to numbered likely causes. ID is generated. "
        "Select Highlighted restricts the working list; Filter searches text in all three fields; "
        "Set Selection saves or recalls named snapshots; Sort saves multi-column ordering. Reset Selection "
        "shows all messages. Print saves an HTML report of exactly the displayed rows in their "
        "current order and opens the browser print dialog. Empty lists print headings only. "
        "Unsaved form text is not printed. Reference edits and deletions do not change runtime "
        "ErrorText dialogs. Defaults are populated once, not recreated after deletion. Braced "
        "placeholders stand for variable runtime values; operating-system errors are represented "
        "by their enclosing message template rather than every possible detail.",
    ),
    "Error Filter": (
        "Search the ErrorMessage working list.",
        "Match text anywhere in Error Text, Likely Cause and Description, ignoring ASCII case. "
        "Nonblank criteria are combined with AND and any highlighted-record restriction. "
        "Percent and underscore are literal characters. Blank fields impose no restriction. "
        "Apply updates the working list; Cancel leaves it unchanged.",
    ),
    "Error Sort": (
        "Choose the ErrorMessage list's saved multi-field order.",
        "Choose distinct columns in priority order, with asc or desc for each. ID sorts "
        "numerically and is added to break ties. Unused rows can be blank. Apply saves this "
        "order independently of Fabric and HelpText; Print uses the displayed order.",
    ),
    "Error Set": (
        "Save or recall a snapshot of the ErrorMessage working list.",
        "Save Current saves IDs of all listed messages, not just highlights. Choose a unique "
        "Set Name. Apply Saved clears other restrictions and recalls the snapshot. New messages "
        "are not added automatically; deleted messages are removed from membership. Delete Saved "
        "removes only the set, never messages. ErrorMessage sets are separate from Fabric sets.",
    ),
    "Setup": (
        "Back up saved data or restore a backup to a separate database.",
        "Backup Database makes a verified copy of committed records at a new filename. "
        "Restore Database makes a separate verified database and never replaces the open one. "
        "Close the application and open the restored path to use it. Keep the live database on "
        "a local disk and coordinate backups, restores and upgrades with other users.",
    ),
    "Filter": (
        "Restrict the Fabric working list without changing inventory.",
        "Text filters match text anywhere in the field, ignoring case. Minimum dimensions are "
        "inclusive inches and respect the rectangle's recorded orientation. Blank means no "
        "restriction. Apply validates and applies the criteria; Cancel leaves the list unchanged.",
    ),
    "Sort": (
        "Choose the Fabric list's saved multi-field sort order.",
        "Choose distinct sort fields in priority order, with asc or desc for each. Leave unused "
        "fields blank. ID is added as a final tie-breaker. Apply validates and saves the sort. "
        "Cancel closes this dialog without changing the saved order.",
    ),
    "Set Selection": (
        "Save or recall a snapshot of the Fabric working list.",
        "Save Current saves IDs of every record in the working list, not just highlighted rows. "
        "Apply Saved recalls the chosen snapshot and clears other list restrictions. Later edits "
        "do not remove members and new records are not added automatically. Delete Saved removes "
        "only the named set, never fabric. Saved changes take effect immediately.",
    ),
    "History": (
        "Review committed additions and updates to a fabric rectangle.",
        "Highlight a history row to see its Before and After values. Select Highlighted, Filter, "
        "Set Selection and Sort operate only on this piece's history; saved sets are scoped to "
        "this piece. Reset Selection restores its full history. Each inventory save and its history "
        "commit together. Measurements display in inches and timestamps display local time to the "
        "minute. This screen is read-only.",
    ),
    "DropDown Filter": (
        "Restrict the active values for the selected table or screen key.",
        "List Item matches literal text anywhere in the value, ignoring case. Default selects "
        "only the current default or all other values. Apply updates this key's working list; "
        "Reset Selection removes the filter and highlighted-row restriction.",
    ),
    "DropDown Sort": (
        "Choose the selected key's saved multi-field order.",
        "Choose distinct columns in priority order, with asc or desc for each. Leave unused rows "
        "blank. The default order puts the default choice first; ID is appended to break ties.",
    ),
    "DropDown Set": (
        "Save or recall a snapshot of the selected key's values.",
        "Save Current saves IDs of all listed values, not just highlights. Sets are scoped to the "
        "selected Table Name and Field Name. Applying a set clears other list restrictions; "
        "deleting it never changes the source values.",
    ),
    "HelpText Filter": (
        "Search the HelpText working list.",
        "Each nonblank Table Name, Field Name, Hover Text and Full Text criterion matches literal "
        "text anywhere in that field, ignoring case. Criteria are combined with AND. Apply updates "
        "the list; Reset Selection clears filters and highlighted-row restrictions.",
    ),
    "HelpText Sort": (
        "Choose the HelpText list's saved multi-field order.",
        "Choose distinct columns in priority order, with asc or desc for each. ID is appended to "
        "break ties. This sort is saved independently from other lists.",
    ),
    "HelpText Set": (
        "Save or recall a snapshot of HelpText rows.",
        "Save Current saves IDs of all listed help records, not just highlights. Applying a set "
        "clears other restrictions. Deleting a set never changes help text.",
    ),
    "History Filter": (
        "Search the selected fabric piece's history.",
        "Action matches Added or Updated exactly. Date Created and Values match literal text "
        "anywhere in their displayed timestamp or saved Before/After snapshots, ignoring case. "
        "Nonblank criteria are combined with AND.",
    ),
    "History Sort": (
        "Choose this piece's history order.",
        "Choose distinct columns in priority order, with asc or desc for each. ID is appended to "
        "break ties. The sort setting is shared by History windows.",
    ),
    "History Set": (
        "Save or recall a snapshot of this piece's history.",
        "Save Current saves IDs of all listed history rows, not just highlights. Sets are scoped "
        "to this piece. Applying a set clears other restrictions; deleting a set does not change history.",
    ),
    "Screen Help": (
        "Read detailed help without leaving the current operation.",
        "This window shows the selected control's Full Text or the current screen's ScreenHelp "
        "entry. Close it to resume the underlying operation without losing edits. Choosing a "
        "navigation destination instead closes unfinished dialogs and resets unsaved forms after "
        "confirmation. Already committed changes are retained.",
    ),
}

FIELD_HELP = {
    "QuiltName": ("Name a quilt project.", "Required name, up to 120 characters."),
    "SavedQuilt": ("Choose a saved quilt.", "Select a saved quilt to review its composition and plans."),
    "ApprovedBlock": ("Choose an approved block version.", "Choose one approved block and set its quantity."),
    "Quantity": ("Enter the number of blocks.", "Enter an integer from 1 through 10,000."),
    "InventoryColor": ("Select a fabric inventory color.", "Map each part color to one or more inventory colors."),
    "SavedQuiltPlan": ("Choose a saved cutting plan.", "Saved plans are snapshots and do not reserve fabric."),
    "QuiltReportFormat": ("Choose the cutting list format.", "Entire Quilt combines equivalent parts; "
                          "By Block groups them by block type. Both include source allocations and shortages."),
    "QuiltPlanDetails": ("Review the cutting plan.", "Shows source IDs, allocations, cutting bounds and shortages."),
    **{field.name: (f"Enter {field.label.lower()}.", f"Enter the {field.label.lower()} for this block or part.")
       for field in (*BLOCK_FIELDS, *PART_FIELDS)},
    "Placement": ("Choose an instance to position.", "Select a numbered part instance."),
    "PositionX": ("Enter its horizontal position.", "Unscaled distance from the left edge in inches."),
    "PositionY": ("Enter its vertical position.", "Unscaled distance from the top edge in inches."),
    "Rotation": ("Rotate the selected instance.", "Enter a whole number of degrees from 0 to 359."),
    "Mirror": ("Mirror the selected instance.", "Mirror horizontally before rotation."),
    "BlockSketch": ("Finished-size block sketch.", "Position each instance using the placement controls."),
    "ErrorText": ("Enter the error message or template.", "Required plain text up to 4,000 characters. "
                  "Braces identify variable runtime details. Editing this troubleshooting reference "
                  "does not change the message displayed by the program."),
    "LikelyCause": ("Describe why this error may occur.", "Required plain text up to 4,000 characters. "
                    "Number separate likely causes so Description can give a matching fix for each."),
    "Description": ("Describe a likely fix for each cause.", "Required plain text up to 16,000 "
                    "characters. Use the same numbering as Likely Cause and explain safe recovery."),
    "FabricName": ("Identify this physical rectangle.", "Required fabric name, up to 120 characters. "
                   "Choose FabricName is a display-only placeholder; enter or select a value before saving. "
                   "Several physical rectangles can share a name; each remains a separate record."),
    "Color": ("Describe the fabric color.", "Optional color description. Choose an existing value "
              "or Add Item. With no default, Choose Color is only a placeholder; leaving it blank saves NULL. "
              "Fabric filters match text contained anywhere in this value."),
    "PatternName": ("Name the fabric print or design.", "Optional print or design name, not a quilt "
                    "construction pattern. Choose an existing value or Add Item. With no default, "
                    "Choose PatternName is only a placeholder; leaving it blank saves NULL."),
    "UsableWidth": ("Enter usable width in inches.", "Required positive width, excluding selvage and "
                    "damage. Enter 42, 42.5 or 42 1/2. Fractions through 1/64 and up to six decimal "
                    "places are stored exactly. Maximum 10,800 inches; do not include unit symbols."),
    "UsableLength": ("Enter usable length in inches.", "Required positive length, excluding damage. "
                     "Use whole inches, up to six decimal places or a fraction through 1/64. "
                     "Maximum 10,800 inches. Width and length retain the orientation you assign."),
    "GrainDirection": ("Identify lengthwise grain relative to this rectangle.", "Along Length and "
                       "Along Width refer to the recorded dimensions. Unknown is explicit and "
                       "does not mean rotation is safe."),
    "PrintDirection": ("Identify the directional print's orientation.", "Along Length and Along "
                       "Width refer to the recorded dimensions. Non-directional means rotation "
                       "does not affect the print's orientation. Unknown is not non-directional."),
    "StorageLocation": ("Locate the fabric on a shelf or in a bin.", "Optional physical storage "
                        "location. Choose an existing value or Add Item; maximum 120 characters. "
                        "With no default, Choose StorageLocation is only a placeholder; leaving it blank saves NULL."),
    "Status": ("Choose Available or Retired.", "Available pieces appear in the initial Fabric list. "
               "Retired pieces retain their records and history. Retirement is not a cutting "
               "transaction. Use Reset Selection to include retired pieces."),
    "Notes": ("Record optional details or reasons for a correction.", "Optional notes up to 4,000 "
              "characters. Inventory corrections should explain changes to the usable dimensions."),
    "MinimumWidth": ("Set an inclusive minimum width in inches.", "Blank means no width restriction. "
                     "Use the same inch formats as Usable Width. Filtering does not rotate pieces."),
    "MinimumLength": ("Set an inclusive minimum length in inches.", "Blank means no length "
                      "restriction. Use the same inch formats as Usable Length. Filtering does "
                      "not rotate pieces."),
    "SavedSet": ("Choose a saved selection snapshot.", "Choose the named set to apply or delete. "
                 "Applying a set clears other Fabric list restrictions; deleting it keeps fabric."),
    "SetName": ("Name a snapshot of the entire working list.", "Enter a unique name, up to 120 "
                "characters. Save Current includes all working-list records, not just highlights."),
    "TableName": ("Screen owning this help entry.", "Read-only screen name for the selected generated "
                  "help object. Choose a different row to edit help for another screen."),
    "FieldName": ("Object owning this help entry.", "Read-only object key within the selected screen. "
                  "Column: keys identify list headings; Button: keys identify action buttons."),
    "HoverText": ("Edit the brief tooltip.", "Required plain text, up to 4,000 characters, displayed "
                  "when the pointer rests on this object. Update saves it; navigation can discard "
                  "unsaved edits after confirmation."),
    "FullText": ("Edit detailed F1 or screen help.", "Required plain text, up to 16,000 characters. "
                 "F1 displays this text for the object. Screen Help uses the ScreenHelp record "
                 "for the current screen. Update saves changes immediately."),
    "BackName": ("Name the quilt back.", "Required name, up to 120 characters, retained with its plan."),
    "QuiltWidth": ("Enter the quilt's finished width in inches.", "The planned back adds the same "
                   "margin on both sides. Use the supported exact inch formats."),
    "QuiltLength": ("Enter the quilt's finished length in inches.", "The planned back adds the same "
                    "margin at both ends. Use the supported exact inch formats."),
    "Margin": ("Set the same overhang on all four sides.", "Backing target width and length each add "
               "twice this value to the quilt dimensions."),
    "SeamAllowance": ("Set one allowance for every panel seam.", "Cut widths and lengths include this "
                      "same allowance on both joined edges."),
    "ListItem": ("Enter a new dropdown choice.", "Required nonblank text, up to 120 characters. "
                 "Choose Add Item to save it. Existing choices differing only in ASCII case or "
                 "surrounding spaces reuse the existing spelling."),
    "HistoryValues": ("Before and After values for the highlighted change.", "Read-only details of "
                       "the selected history row. Added records have no Before snapshot."),
    "HelpContent": ("Detailed help for the selected screen or control.", "Read-only Full Text "
                    "from the selected HelpText record. Close this window to resume your work."),
}

BUTTON_HELP = {
    "Quilt": ("Open quilt planning.", "Compose quilts and create non-consuming cutting plans."),
    "Add Quilt": ("Save a new quilt project.", "Enter a name and create an independent quilt."),
    "Set Block Quantity": ("Add or update a block quantity.", "Choose an approved version and its required count."),
    "Remove Block": ("Remove the selected block from the quilt.", "This never deletes the block version."),
    "Map Color": ("Map a part color to an inventory color.", "A part color can map to multiple inventory colors."),
    "Remove Mapping": ("Remove the chosen color mapping.", "Removing a mapping does not change inventory."),
    "Plan Quilt": ("Generate a cutting plan.", "Allocate part cut bounds to matching available fabric; "
                   "the saved plan reports unfilled demand and does not change inventory."),
    "Print Quilt Plan": ("Print the selected cutting plan.", "Choose a cutting list format, then save an HTML "
                         "report at a new path and print in a browser."),
    "QuiltBlock": ("Open block design.", "Maintain and approve reusable block definitions."),
    "New Version": ("Copy the block to a draft version.", "The source version remains unchanged."),
    "Parts": ("Open part maintenance.", "Add, update or delete part definitions on a draft."),
    "Sketch": ("Open the editable sketch.", "Position and orient each part instance."),
    "Approve": ("Approve a complete layout.", "Approval requires all instances and no gaps, overlap or overflow."),
    "Save Placement": ("Save the selected placement.", "Persist the part instance position and orientation."),
    "Print Sketch": ("Print this block sketch.", "Save an HTML report at a new filename; "
                     "the report includes finished shapes and bounding cut dimensions."),
    "ErrorMessage": ("Open error-message maintenance.", "Switch to the searchable troubleshooting reference."),
    "Delete": ("Delete the highlighted reference message.", "Highlight exactly one message. After "
               "confirmation, delete its reference entry and saved-set memberships, not runtime ErrorText."),
    "Print": ("Print exactly the listed messages in their current order.", "Save an HTML report, "
              "then use the browser print dialog. All listed messages are included, not just "
              "highlights; unsaved form edits are excluded. If the browser does not open, open "
              "the saved report manually. An empty list produces a headings-only report."),
    "Fabric": ("Open Fabric inventory.", "Switch to the Fabric working list and entry form."),
    "Quilt Backs": ("Plan and track quilt-back construction.", "Open the quilt-back planner."),
    "DropDown": ("Open dropdown maintenance.", "Switch to fabric choice and default maintenance."),
    "HelpText": ("Open help maintenance.", "Switch to editable tooltip and detailed-help records."),
    "Setup": ("Open backup and restore utilities.", "Switch to Setup for verified database copies."),
    "Screen Help": ("Show help for this screen.", "Open detailed help for the current screen. "
                    "This does not navigate away or discard unfinished work."),
    "Add": ("Save a new physical fabric rectangle.", "Validate and save a separate fabric record "
            "with a new ID and history, even when the form was filled from an existing piece."),
    "Update": ("Save changes to the highlighted record.", "Validate and save the selected record. "
               "For fabric, stale revisions are rejected and each change records history."),
    "Clear": ("Discard entry changes and clear the highlighted record.", "After confirmation for "
              "unsaved changes, clear the form without deleting saved records."),
    "History": ("Review the highlighted piece's saved changes.", "Select exactly one fabric "
                "rectangle, then open its committed Before and After history."),
    "Select Highlighted": ("Restrict the list to highlighted records.", "Requires at least one "
                           "highlight. Restricts the working list without changing inventory."),
    "Filter": ("Set Fabric list criteria.", "Open text, minimum-size and status filters. "
               "Unapplied criteria can be canceled without changing the working list."),
    "Set Selection": ("Save or recall a working-list snapshot.", "Open named selection sets to "
                      "save the entire working list, apply an existing set or delete a set."),
    "Sort": ("Choose Fabric list sort priorities.", "Open the saved multi-field sort editor. "
             "Sort numbers numerically, not as formatted text."),
    "Reset Selection": ("Show all rows in this list's scope.", "Clear filters and highlighted-record "
                        "or saved-set restrictions without changing saved records."),
    "Refresh": ("Reload committed records.", "After confirmation for unsaved edits, reload the "
                "working list using its current restrictions and sort."),
    "Backup Database": ("Create a verified backup at a new filename.", "Copy committed SQLite data "
                        "and verify the result before publishing it. Existing files are never "
                        "overwritten. Unsaved form edits are not part of the backup."),
    "Restore Database": ("Restore a backup to a separate new file.", "Choose a valid backup and a "
                         "new destination. Verify the copy without replacing the open database. "
                         "Reopen the application with the new path to use the restored data."),
    "Add Item": ("Save a choice for the selected fabric field.", "Enter a nonblank item up to 120 "
                 "characters. Existing names differing only in ASCII case or surrounding spaces "
                 "reuse the stored spelling. Fixed direction and status choices cannot be extended."),
    "Set Default": ("Mark the highlighted item as this key's default.", "Select exactly one active "
                    "dropdown record. Save its default immediately; FabricPiece form defaults "
                    "change for new or cleared forms, but saved fabric is not modified."),
    "Generate Plans": ("Rank feasible rectangular panel layouts.", "Generate candidates from highlighted "
                       "rectangles, or all listed available rectangles if none are highlighted."),
    "Set Sketch Color": ("Choose the controlled sketch color for one fabric.", "This plan-only palette "
                         "color does not change inventory. The printed legend also retains the recorded color."),
    "Preview Sketch": ("Preview the selected assembly sketch.", "Panels are shaded by the controlled "
                       "palette. Arrows show recorded grain direction; unknown grain is labeled."),
    "Save Draft": ("Save the selected plan without changing inventory.", "The saved draft records "
                   "source IDs and revisions. Inventory is adjusted only when cuts are confirmed."),
    "Confirm Cuts": ("Record operator-reported cuts and remnants.", "Sources are rechecked for availability "
                     "and revision. Retired sources and new reusable remnants are committed atomically."),
    "Mark Assembled": ("Mark a cut back as assembled.", "This records the operator's completion status; "
                       "it does not change inventory."),
    "Print Plan": ("Print the sketch and assembly legend.", "Save an HTML plan to a new filename; "
                   "the report includes target dimensions, seam allowance, panel cut sizes, colors and grain."),
    "Refresh Fabric": ("Reload available rectangles.", "Refresh the source list before generating or confirming a plan."),
    "Apply": ("Validate and apply this dialog's settings.", "Apply the current criteria or sort "
              "and close the dialog. Invalid input leaves the dialog open for correction."),
    "Clear Fields": ("Reset this dialog's input fields.", "Clear optional inputs and restore field "
                     "defaults. Nothing is applied until you choose Apply."),
    "Cancel": ("Close without applying unfinished changes.", "Abandon this dialog's unsaved input. "
               "Already committed actions, such as saving a selection set, are not undone."),
    "Close": ("Close this help or history window.", "Return to the underlying operation without "
              "changing inventory or applying unfinished input."),
    "Save Current": ("Save all working-list IDs as a named set.", "Enter a unique Set Name. "
                     "The snapshot is saved immediately and includes all records in the working list."),
    "Apply Saved": ("Recall the selected snapshot.", "Choose a saved set. Its member IDs become "
                    "the working list, with other filters and highlight restrictions cleared."),
    "Delete Saved": ("Delete the selected set, keeping fabric.", "After confirmation, remove only "
                     "the saved selection snapshot. The current working list remains unchanged."),
    "Reset Selection": ("Clear list filters and saved-set restrictions.", "Restore all rows in the "
                        "current list's scope and clear filters and highlighted-row restrictions."),
}

SCREEN_FIELDS = {
    "Quilt": (Field("QuiltName"), Field("SavedQuilt"), Field("ApprovedBlock"), Field("Quantity"),
              Field("PartColor"), Field("InventoryColor"), Field("SavedQuiltPlan"), Field("QuiltReportFormat"),
              Field("QuiltPlanDetails")),
    "QuiltBlock": BLOCK_FIELDS,
    "Block Parts": PART_FIELDS,
    "Block Sketch": (Field("BlockSketch"), Field("Placement"), Field("PositionX"), Field("PositionY"),
                     Field("Rotation"), Field("Mirror")),
    "QuiltBlock Filter": BLOCK_FILTER_FIELDS,
    "QuiltBlock Sort": tuple(field for index in range(1, len(BLOCK_COLUMNS) + 1) for field in (
        Field(f"SortField{index}"), Field(f"Direction{index}"))),
    "QuiltBlock Set": (Field("SavedSet"), Field("SetName")),
    "ErrorMessage": ERROR_FIELDS,
    "Error Filter": ERROR_FILTER_FIELDS,
    "Error Sort": tuple(field for index in range(1, len(ERROR_COLUMNS) + 1) for field in (
        Field(f"SortField{index}"), Field(f"Direction{index}"))),
    "Error Set": (Field("SavedSet"), Field("SetName")),
    "Fabric": FABRIC_FIELDS,
    "Quilt Backs": (
        Field("BackName", required=True),
        Field("QuiltWidth", "length", required=True),
        Field("QuiltLength", "length", required=True),
        Field("Margin", "length", default="4"),
        Field("SeamAllowance", "length", default="1/2"),
    ),
    "Quilt Backs Filter": BACK_FILTER_FIELDS,
    "Quilt Backs Sort": tuple(field for index in range(1, len(BACK_COLUMNS) + 1) for field in (
        Field(f"SortField{index}"), Field(f"Direction{index}"))),
    "Quilt Backs Set": (Field("SavedSet"), Field("SetName")),
    "Filter": FILTER_FIELDS,
    "DropDown": DROPDOWN_FORM_FIELDS,
    "DropDown Filter": DROPDOWN_FILTER_FIELDS,
    "DropDown Sort": tuple(field for index in range(1, len(DROPDOWN_COLUMNS) + 1) for field in (
        Field(f"SortField{index}"), Field(f"Direction{index}"))),
    "DropDown Set": (Field("SavedSet"), Field("SetName")),
    "HelpText": HELP_FIELDS,
    "HelpText Filter": HELP_FILTER_FIELDS,
    "HelpText Sort": tuple(field for index in range(1, len(HELP_COLUMNS) + 1) for field in (
        Field(f"SortField{index}"), Field(f"Direction{index}"))),
    "HelpText Set": (Field("SavedSet"), Field("SetName")),
    "Sort": tuple(field for index in range(1, len(SORT_FIELDS) + 1) for field in (
        Field(f"SortField{index}"), Field(f"Direction{index}"))),
    "Set Selection": (Field("SavedSet"), Field("SetName")),
    "Add Item": (Field("ListItem"), Field("Def")),
    "History Filter": HISTORY_FILTER_FIELDS,
    "History Sort": tuple(field for index in range(1, len(HISTORY_COLUMNS) + 1) for field in (
        Field(f"SortField{index}"), Field(f"Direction{index}"))),
    "History Set": (Field("SavedSet"), Field("SetName")),
    "History": (Field("HistoryValues"),),
    "Screen Help": (Field("HelpContent"),),
}
SCREEN_COLUMNS = {
    "QuiltBlock": BLOCK_COLUMNS,
    "Block Parts": ("ID", "PartName", "Shape", "PartColor", "NumberInBlock"),
    "ErrorMessage": ERROR_COLUMNS,
    "Fabric": LIST_COLUMNS,
    "DropDown": DROPDOWN_COLUMNS,
    "HelpText": HELP_COLUMNS,
    "History": ("ID", "Action", "DateCreated"),
    "Quilt Backs": tuple(dict.fromkeys((
        *LIST_COLUMNS, *BACK_LAYOUT_COLUMNS, "BackName", "BackWidth", "BackLength",
        "Status", "DateModified",
    ))),
}
SCREEN_BUTTONS = {
    "Quilt": ("Add Quilt", "Set Block Quantity", "Remove Block", "Map Color", "Remove Mapping",
              "Plan Quilt", "Print Quilt Plan"),
    "QuiltBlock": ("Add", "Update", "Delete", "Clear", "New Version", "Parts", "Sketch", "Approve",
                   "Select Highlighted", "Filter", "Set Selection", "Sort", "Reset Selection", "Refresh"),
    "Block Parts": ("Add", "Update", "Delete", "Clear", "Close"),
    "Block Sketch": ("Save Placement", "Print Sketch", "Close"),
    "QuiltBlock Filter": ("Apply", "Clear Fields", "Cancel"),
    "QuiltBlock Sort": ("Apply", "Clear Fields", "Cancel"),
    "QuiltBlock Set": ("Save Current", "Apply Saved", "Delete Saved", "Cancel"),
    "ErrorMessage": ("Add", "Update", "Delete", "Clear", "Select Highlighted", "Filter",
                     "Set Selection", "Reset Selection", "Sort", "Refresh", "Print"),
    "Error Filter": ("Apply", "Clear Fields", "Cancel"),
    "Error Sort": ("Apply", "Clear Fields", "Cancel"),
    "Error Set": ("Save Current", "Apply Saved", "Delete Saved", "Cancel"),
    "Fabric": ("Add", "Update", "Clear", "History", "Select Highlighted", "Filter",
               "Set Selection", "Sort", "Reset Selection", "Refresh"),
    "Quilt Backs": ("Generate Plans", "Set Sketch Color", "Preview Sketch", "Save Draft",
                    "Confirm Cuts", "Mark Assembled", "Print Plan", "Refresh Fabric",
                    "Select Highlighted", "Filter", "Set Selection", "Reset Selection", "Sort"),
    "Quilt Backs Filter": ("Apply", "Clear Fields", "Cancel"),
    "Quilt Backs Sort": ("Apply", "Clear Fields", "Cancel"),
    "Quilt Backs Set": ("Save Current", "Apply Saved", "Delete Saved", "Cancel"),
    "DropDown": ("Select Highlighted", "Filter", "Set Selection", "Reset Selection", "Sort",
                 "Add", "Update", "Delete"),
    "Add Item": ("Add Item", "Cancel"),
    "HelpText": ("Update", "Clear", "Select Highlighted", "Filter", "Set Selection",
                 "Reset Selection", "Sort"),
    "Setup": ("Backup Database", "Restore Database"),
    "Filter": ("Apply", "Clear Fields", "Cancel"),
    "Sort": ("Apply", "Clear Fields", "Cancel"),
    "Set Selection": ("Save Current", "Apply Saved", "Delete Saved", "Cancel"),
    "History": ("Select Highlighted", "Filter", "Set Selection", "Reset Selection", "Sort", "Close"),
    "DropDown Filter": ("Apply", "Clear Fields", "Cancel"),
    "DropDown Sort": ("Apply", "Clear Fields", "Cancel"),
    "DropDown Set": ("Save Current", "Apply Saved", "Delete Saved", "Cancel"),
    "HelpText Filter": ("Apply", "Clear Fields", "Cancel"),
    "HelpText Sort": ("Apply", "Clear Fields", "Cancel"),
    "HelpText Set": ("Save Current", "Apply Saved", "Delete Saved", "Cancel"),
    "History Filter": ("Apply", "Clear Fields", "Cancel"),
    "History Sort": ("Apply", "Clear Fields", "Cancel"),
    "History Set": ("Save Current", "Apply Saved", "Delete Saved", "Cancel"),
    "Screen Help": ("Close",),
}
SYSTEM_DROPDOWNS = {
    ("FabricPiece", "GrainDirection"): (GRAIN_DIRECTIONS, "Unknown"),
    ("FabricPiece", "PrintDirection"): (PRINT_DIRECTIONS, "Unknown"),
    ("FabricPiece", "Status"): (STATUSES, "Available"),
    ("Block Parts", "Shape"): (SHAPES, ""),
    ("Block Parts", "PartColor"): (COLORS, ""),
    ("QuiltBlock Filter", "Status"): (("Draft", "Approved"), ""),
    ("Quilt Backs Filter", "Status"): (("", "Draft", "Cut", "Assembled"), ""),
    ("Quilt", "PartColor"): (COLORS, ""),
    ("Quilt", "QuiltReportFormat"): (("Entire Quilt", "By Block"), "Entire Quilt"),
    ("Block Sketch", "Mirror"): (("No", "Yes"), "No"),
    ("DropDown Filter", "Default"): (("", "Yes", "No"), ""),
    ("History Filter", "Action"): (("", "Added", "Updated"), ""),
}
DROPDOWN_LIST_FIELDS = {"FabricPiece": ("FabricName", "Color", "PatternName", "StorageLocation")}
for _table, _ in SYSTEM_DROPDOWNS:
    DROPDOWN_LIST_FIELDS[_table] = tuple(dict.fromkeys((
        *DROPDOWN_LIST_FIELDS.get(_table, ()),
        *(field for owner, field in SYSTEM_DROPDOWNS if owner == _table),
    )))
DYNAMIC_LIST_HELP = {
    ("Quilt", "SavedQuilt"),
    ("Quilt", "ApprovedBlock"),
    ("Quilt", "InventoryColor"),
    ("Quilt", "SavedQuiltPlan"),
    ("Block Sketch", "Placement"),
    ("QuiltBlock Set", "SavedSet"),
    ("Error Set", "SavedSet"),
    ("Quilt Backs Set", "SavedSet"),
    ("DropDown Set", "SavedSet"),
    ("HelpText Set", "SavedSet"),
    ("Set Selection", "SavedSet"),
    ("History Set", "SavedSet"),
}
PROTECTED_LIST_HELP = {
    ("Fabric", "GrainDirection"),
    ("Fabric", "PrintDirection"),
    ("Fabric", "Status"),
    ("Block Parts", "Shape"),
    ("Block Parts", "PartColor"),
    ("QuiltBlock Filter", "Status"),
    ("Quilt Backs Filter", "Status"),
    ("Quilt", "PartColor"),
    ("Quilt", "QuiltReportFormat"),
    ("Block Sketch", "Mirror"),
    ("DropDown Filter", "Default"),
    ("History Filter", "Action"),
}
COLUMN_HELP = {
    "Revision": ("Saved revision number.", "Changes whenever this block or its parts are saved."),
    "ID": ("Unique saved record number.", "Database-generated identity for this record; not a row "
           "count or list position. The identity remains stable when the list is sorted."),
    "Def": ("Whether this item is the key's default.", "1 marks a default; 0 means it "
            "is not a default. If multiple defaults exist, the first active item encountered is used."),
    "Use": ("Whether this dropdown value is active.", "1 means the value is active and appears "
            "in its associated selection list. Inactive values remain visible in the maintenance list."),
    "UserModified": ("Whether users may maintain this item.",
                     "1 means the list item can be changed or deleted. 0 means only its default "
                     "can be changed; the item is system-defined."),
    "ListItem": ("Saved value for this key.", "The exact stored spelling for the selected "
                 "Table Name and Field Name. FabricPiece field values appear in fabric forms."),
    "Action": ("Type of saved inventory change.", "Added creates a new physical rectangle; Updated "
               "changes an existing one. Highlight the row to review Before and After values."),
    "DateCreated": ("When this change was committed.", "Displayed in local time to the minute. "
                    "The database retains the complete timestamp."),
    "DateModified": ("When this plan was last changed.", "Displayed in local time to the minute."),
    "BackWidth": ("Finished backing width.", "Quilt width plus twice the uniform side margin."),
    "BackLength": ("Finished backing length.", "Quilt length plus twice the uniform end margin."),
    "Layout": ("How the backing panels are joined.", "Vertical panels are joined side by side; "
               "horizontal panels are joined end to end."),
    "Parts": ("Number of panels in this candidate.", "Fewer panels generally mean less assembly work."),
    "Seams": ("Number of seams between panels.", "Each seam uses the uniform seam allowance entered for this back."),
    "Grain": ("Whether panel grain directions agree.", "Unknown source grain is shown explicitly in the sketch."),
    "Minimum": ("Smallest-panel target reached.", "20% is preferred, then 10%; every panel must be at least five inches."),
    "FabricArea": ("Total area of source pieces.", "This favors smaller available source rectangles; actual remainder is measured by the operator."),
}


def default_help():
    """Generate a complete catalog without replacing stored user text."""
    rows = {}
    for screen, pair in SCREEN_HELP.items():
        rows[screen, "ScreenHelp"] = pair
        for button in (*NAVIGATION, *SCREEN_BUTTONS.get(screen, ())):
            hover, full = BUTTON_HELP[button]
            if button in NAVIGATION[:-1]:
                full += (" Before switching, confirm discarding unsaved work. Unfinished dialogs "
                         "are closed and their grabs released; committed changes remain saved.")
            if screen == "HelpText" and button == "Update":
                hover, full = "Save the selected help pair.", (
                    "Save Hover Text and Full Text for the selected generated key. Keys stay "
                    "unchanged. New tooltip and F1 lookups use the saved text immediately.")
            if screen == "DropDown" and button in ("Add", "Update", "Delete"):
                hover, full = (f"{button} a dropdown value.",
                               "Add requires an item and explicit Def and Use choices. Highlight one row "
                               "to update or delete it. Update can ignore either flag.")
            if screen == "HelpText" and button == "Set Selection":
                hover, full = "Save or recall a HelpText list snapshot.", SCREEN_HELP["HelpText Set"][1]
            if screen == "ErrorMessage" and button in (
                    "Add", "Update", "Filter", "Sort", "Reset Selection", "Set Selection"):
                hover, full = {
                    "Add": ("Save a new reference message.", "Validate all three text fields and "
                            "save a new message with a generated ID, even when copying an existing row."),
                    "Update": ("Save the highlighted reference message.", "Select exactly one row. "
                               "Save the form; stale changes are rejected. Runtime errors are unchanged."),
                    "Filter": SCREEN_HELP["Error Filter"],
                    "Sort": SCREEN_HELP["Error Sort"],
                    "Set Selection": ("Save or recall an error-message working list.", SCREEN_HELP["Error Set"][1]),
                    "Reset Selection": ("Show all saved reference messages.", "Clear text filters "
                                        "and saved-set/highlight restrictions without deleting messages."),
                }[button]
            if screen == "QuiltBlock" and button in ("Add", "Update", "Delete", "Filter", "Sort"):
                hover, full = {
                    "Add": ("Save a new block draft.", "Save the entered block as a new independent draft."),
                    "Update": ("Save the selected draft.", "Save block details if the revision is current. "
                               "Approved versions cannot be changed."),
                    "Delete": ("Delete the selected draft.", "After confirmation, delete this draft and its "
                               "parts. Approved versions cannot be deleted."),
                    "Filter": SCREEN_HELP["QuiltBlock Filter"],
                    "Sort": SCREEN_HELP["QuiltBlock Sort"],
                }[button]
            if screen == "Block Parts" and button in ("Add", "Update", "Delete", "Clear"):
                hover, full = (f"{button} a part definition.", "Maintain a draft's finished-size part "
                               "definitions and their individual placements.")
            if screen in ("DropDown", "HelpText", "History", "Quilt Backs") and button in (
                    "Filter", "Set Selection", "Sort", "Reset Selection"):
                if button == "Set Selection":
                    hover, full = "Save or recall a working-list snapshot.", SCREEN_HELP[f"{screen} Set"][1]
                elif button == "Reset Selection":
                    hover, full = BUTTON_HELP[button]
                else:
                    hover, full = SCREEN_HELP[f"{screen} {button}"]
            if screen == "Error Set" and button == "Delete Saved":
                hover, full = ("Delete only the selected message set.",
                               "After confirmation, remove the named snapshot. Messages and the "
                               "current working list remain unchanged.")
            rows[screen, f"Button:{button}"] = hover, full
        for field in SCREEN_FIELDS.get(screen, ()):
            if screen in ("Sort", "Error Sort", "DropDown Sort", "HelpText Sort", "History Sort",
                          "QuiltBlock Sort", "Quilt Backs Sort"):
                pair = (("Choose a distinct field for this priority.",
                         "Choose a list column; earlier rows have higher priority. Leave unused "
                         "rows blank. ID is appended as a tie-breaker.") if field.name.startswith("SortField")
                        else ("Choose ascending or descending order.",
                              "asc sorts smallest to largest or A to Z; desc reverses the order. "
                              "This direction applies to the field on the same row."))
            elif screen == "DropDown":
                pair = {
                    "TableName": ("Choose a database table or application screen.",
                                  "Choose the owner of a supported list. Dynamic menus are not listed."),
                    "FieldName": ("Choose a supported field within the selected owner.",
                                  "The available names depend on Table Name."),
                    "ListItem": COLUMN_HELP["ListItem"],
                    "Def": ("Choose how to change the default flag.",
                            "Choose Set Default or Clear Default for Add; Update may ignore the flag."),
                    "Use": ("Choose how to change the active flag.",
                            "Choose Set Use or Clear Use for Add; Update may ignore the flag."),
                }[field.name]
            elif screen == "Add Item" and field.name == "Def":
                pair = ("Choose whether this item is the default.",
                        "Set Default marks the added item as a default. You can clear the other defaults.")
            elif (screen, field.name) in DYNAMIC_LIST_HELP:
                pair = (FIELD_HELP.get(field.name, (f"Choose {field.label}.", ""))[0],
                        FIELD_HELP.get(field.name, (f"Choose {field.label}.", ""))[1]
                        + " This is a dynamic list whose values come directly from the data. "
                        "This list does not use the DropDown system for setting or updating values.")
            elif (screen, field.name) in PROTECTED_LIST_HELP:
                pair = (FIELD_HELP.get(field.name, (f"Choose {field.label}.", ""))[0],
                        FIELD_HELP.get(field.name, (f"Choose {field.label}.", ""))[1]
                        + " This is a system-generated protected list. The values are used in internal "
                        "program logic and changing values can interfere with program operation. "
                        "The user may change the default value using the DropDown system.")
            elif screen == "QuiltBlock" and field.name == "Description":
                pair = ("Describe this block.", "Optional block description, up to 4,000 characters.")
            elif screen == "QuiltBlock Filter":
                pair = SCREEN_HELP["QuiltBlock Filter"]
            elif screen == "Error Filter":
                pair = (f"Search {field.label.lower()}.",
                        "Blank means no restriction. Match literal text anywhere in this field, "
                        "ignoring ASCII case. Nonblank fields are combined with AND.")
            elif screen == "DropDown Filter" and field.name == "Default":
                pair = ("Show default choices or all other choices.", SCREEN_HELP[screen][1])
            elif screen == "History Filter" and field.name == "Action":
                pair = ("Match a saved inventory action.", SCREEN_HELP[screen][1])
            elif screen == "History Filter" and field.name == "Values":
                pair = ("Search saved Before and After values.", SCREEN_HELP[screen][1])
            elif screen in ("DropDown Filter", "HelpText Filter", "History Filter", "Quilt Backs Filter"):
                pair = (f"Filter by {field.label.lower()}.", SCREEN_HELP[screen][1])
            elif screen.endswith(" Set") and field.name == "SavedSet":
                pair = ("Choose a saved working-list snapshot.", SCREEN_HELP[screen][1])
            elif screen == "Filter" and field.name not in ("MinimumWidth", "MinimumLength"):
                pair = (f"Filter fabric by {field.label.lower()}.",
                        "Blank means no restriction. " + (
                            "Choose Available or Retired for an exact status match."
                            if field.name == "Status" else
                            "Match text anywhere in this field, ignoring case. Percent and "
                            "underscore are literal text, not wildcard characters."))
            else:
                pair = FIELD_HELP[field.name]
            rows[screen, field.name] = pair
        for column in SCREEN_COLUMNS.get(screen, ()):
            pair = COLUMN_HELP.get(column) or FIELD_HELP[column]
            if column == "TableName" and screen == "DropDown":
                pair = ("Database table or screen owning this value.",
                        "Identifies the table or application screen paired with Field Name.")
            if column == "FieldName" and screen == "DropDown":
                pair = ("Field or button owning this value list.",
                        "The field or button paired with the Table Name or application screen.")
            hover, full = pair
            if screen == "HelpText":
                full += " Use Sort to configure the saved multi-column HelpText order."
            rows[screen, f"Column:{column}"] = hover, full
    return rows
