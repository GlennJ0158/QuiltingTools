"""Default help catalog, keyed by screen and field, column or button."""

from .model import FABRIC_FIELDS, FILTER_FIELDS, LIST_COLUMNS, SORT_FIELDS, Field
from .errors import ERROR_COLUMNS, ERROR_FIELDS, ERROR_FILTER_FIELDS

NAVIGATION = ("Fabric", "DropDown", "HelpText", "ErrorMessage", "Setup", "Screen Help")
DROPDOWN_FORM_FIELDS = (
    Field("FieldName", "choice"),
    Field("ListItem"),
)
HELP_FIELDS = (
    Field("TableName", required=True),
    Field("FieldName", required=True),
    Field("HoverText", required=True, limit=4000, kind="memo", width=80),
    Field("FullText", required=True, limit=16000, kind="memo", width=80),
)
HELP_COLUMNS = ("ID", "TableName", "FieldName", "HoverText", "FullText")

SCREEN_HELP = {
    "Fabric": (
        "Maintain one record for each physical usable fabric rectangle.",
        "Enter usable dimensions in inches, excluding selvage and damaged edges. Highlight one row "
        "to edit it. Add makes a separate rectangle; Update changes the highlighted rectangle. "
        "History shows saved changes. Retire a piece instead of deleting its history. "
        "Select Highlighted, Filter and Set Selection restrict the working list; Reset Selection "
        "shows all records. Sort saves an ordered list of sort fields. Cutting plans and cutting "
        "transactions are not implemented. Navigation cancels unfinished work after confirmation; "
        "committed records are never undone.",
    ),
    "DropDown": (
        "Maintain fabric choices and defaults for new records.",
        "Choose a fabric field to list its active choices. Add Item saves a new choice immediately. "
        "Highlight one row and choose Set Default to use it on the next new or cleared fabric form. "
        "Blank can be a default. Grain Direction, Print Direction and Status have fixed choices "
        "that cannot be extended. Existing fabric records are not changed.",
    ),
    "Add Item": (
        "Add a fabric choice without saving the fabric form.",
        "Enter one nonblank choice and choose Add Item. The choice is saved immediately and "
        "selected in the Fabric form, but no fabric record is saved. Cancel restores the previous "
        "choice. Navigation abandons unfinished input after confirmation; a successfully saved "
        "choice is not removed when later fabric edits are discarded.",
    ),
    "HelpText": (
        "Edit the tooltip and detailed help for application controls.",
        "Highlight one help record. Table Name identifies its screen; Field Name identifies its "
        "field, Column: name, Button: caption, or ScreenHelp entry. Edit Hover Text and Full Text, "
        "then choose Update. Hover Text appears as a tooltip and Full Text appears with F1. "
        "ScreenHelp entries supply Screen Help. Generated keys are read-only; user edits are "
        "preserved when the application restarts or new help objects are added. Click a column "
        "title to sort ascending or descending; the order is saved independently of Fabric.",
    ),
    "ErrorMessage": (
        "Maintain a searchable troubleshooting reference.",
        "Add, Update or Delete reference messages using Error Text, Likely Cause and Description. "
        "Numbered fixes in Description correspond to numbered likely causes. ID is generated. "
        "Select Highlighted restricts the working list; Filter searches text in all three fields; "
        "Set saves or recalls named snapshots; Sort saves multi-column ordering. Reset Selection "
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
        "Highlight a history row to see its Before and After values. Each inventory save and its "
        "history commit together. Measurements display in inches and timestamps display local "
        "time to the minute. This screen is read-only.",
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
    "ErrorText": ("Enter the error message or template.", "Required plain text up to 4,000 characters. "
                  "Braces identify variable runtime details. Editing this troubleshooting reference "
                  "does not change the message displayed by the program."),
    "LikelyCause": ("Describe why this error may occur.", "Required plain text up to 4,000 characters. "
                    "Number separate likely causes so Description can give a matching fix for each."),
    "Description": ("Describe a likely fix for each cause.", "Required plain text up to 16,000 "
                    "characters. Use the same numbering as Likely Cause and explain safe recovery."),
    "FabricName": ("Identify this physical rectangle.", "Required fabric name, up to 120 characters. "
                   "Several physical rectangles can share a name; each remains a separate record."),
    "Color": ("Describe the fabric color.", "Optional color description. Choose an existing value "
              "or Add Item. Fabric filters match text contained anywhere in this value."),
    "PatternName": ("Name the fabric print or design.", "Optional print or design name, not a quilt "
                    "construction pattern. Choose an existing value or Add Item."),
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
                        "location. Choose an existing value or Add Item; maximum 120 characters."),
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
    "ListItem": ("Enter a new dropdown choice.", "Required nonblank text, up to 120 characters. "
                 "Choose Add Item to save it. Existing choices differing only in ASCII case or "
                 "surrounding spaces reuse the existing spelling."),
    "HistoryValues": ("Before and After values for the highlighted change.", "Read-only details of "
                       "the selected history row. Added records have no Before snapshot."),
    "HelpContent": ("Detailed help for the selected screen or control.", "Read-only Full Text "
                    "from the selected HelpText record. Close this window to resume your work."),
}

BUTTON_HELP = {
    "ErrorMessage": ("Open error-message maintenance.", "Switch to the searchable troubleshooting reference."),
    "Delete": ("Delete the highlighted reference message.", "Highlight exactly one message. After "
               "confirmation, delete its reference entry and saved-set memberships, not runtime ErrorText."),
    "Set": ("Save or recall an error-message working list.", "Manage named snapshots of all currently "
            "listed message IDs. These sets are independent of Fabric selections."),
    "Print": ("Print exactly the listed messages in their current order.", "Save an HTML report, "
              "then use the browser print dialog. All listed messages are included, not just "
              "highlights; unsaved form edits are excluded. If the browser does not open, open "
              "the saved report manually. An empty list produces a headings-only report."),
    "Fabric": ("Open Fabric inventory.", "Switch to the Fabric working list and entry form."),
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
    "Reset Selection": ("Show all saved fabric rectangles.", "Clear filters and selection-set "
                        "restrictions, including the initial Available-only restriction."),
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
    "Set Default": ("Use the highlighted item on new fabric forms.", "Select exactly one active "
                    "dropdown record. Save its default immediately without modifying saved fabric."),
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
}

SCREEN_FIELDS = {
    "ErrorMessage": ERROR_FIELDS,
    "Error Filter": ERROR_FILTER_FIELDS,
    "Error Sort": tuple(field for index in range(1, len(ERROR_COLUMNS) + 1) for field in (
        Field(f"SortField{index}"), Field(f"Direction{index}"))),
    "Error Set": (Field("SavedSet"), Field("SetName")),
    "Fabric": FABRIC_FIELDS,
    "Filter": FILTER_FIELDS,
    "DropDown": DROPDOWN_FORM_FIELDS,
    "HelpText": HELP_FIELDS,
    "Sort": tuple(field for index in range(1, len(SORT_FIELDS) + 1) for field in (
        Field(f"SortField{index}"), Field(f"Direction{index}"))),
    "Set Selection": (Field("SavedSet"), Field("SetName")),
    "Add Item": (Field("ListItem"),),
    "History": (Field("HistoryValues"),),
    "Screen Help": (Field("HelpContent"),),
}
SCREEN_COLUMNS = {
    "ErrorMessage": ERROR_COLUMNS,
    "Fabric": LIST_COLUMNS,
    "DropDown": ("ID", "FieldName", "ListItem", "Def", "Use"),
    "HelpText": HELP_COLUMNS,
    "History": ("ID", "Action", "DateCreated"),
}
SCREEN_BUTTONS = {
    "ErrorMessage": ("Add", "Update", "Delete", "Clear", "Select Highlighted", "Filter",
                     "Set", "Sort", "Reset Selection", "Refresh", "Print"),
    "Error Filter": ("Apply", "Clear Fields", "Cancel"),
    "Error Sort": ("Apply", "Clear Fields", "Cancel"),
    "Error Set": ("Save Current", "Apply Saved", "Delete Saved", "Cancel"),
    "Fabric": ("Add", "Update", "Clear", "History", "Select Highlighted", "Filter",
               "Set Selection", "Sort", "Reset Selection", "Refresh"),
    "DropDown": ("Add Item", "Set Default"),
    "Add Item": ("Add Item", "Cancel"),
    "HelpText": ("Update", "Clear"),
    "Setup": ("Backup Database", "Restore Database"),
    "Filter": ("Apply", "Clear Fields", "Cancel"),
    "Sort": ("Apply", "Clear Fields", "Cancel"),
    "Set Selection": ("Save Current", "Apply Saved", "Delete Saved", "Cancel"),
    "History": ("Close",),
    "Screen Help": ("Close",),
}
COLUMN_HELP = {
    "ID": ("Unique saved record number.", "Database-generated identity for this record; not a row "
           "count or list position. The identity remains stable when the list is sorted."),
    "Def": ("Whether this item is the field's default.", "1 marks the active default; 0 means it "
            "is not the default. Use Set Default to change the value used by new fabric forms."),
    "Use": ("Whether this dropdown choice is active.", "1 means the choice is active and available "
            "to fabric entry forms. This maintenance screen lists active choices."),
    "ListItem": ("Saved dropdown choice.", "The exact stored spelling offered in fabric forms. "
                 "Blank is permitted as a default; use Add Item for new nonblank choices."),
    "Action": ("Type of saved inventory change.", "Added creates a new physical rectangle; Updated "
               "changes an existing one. Highlight the row to review Before and After values."),
    "DateCreated": ("When this change was committed.", "Displayed in local time to the minute. "
                    "The database retains the complete timestamp."),
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
            if screen == "ErrorMessage" and button in (
                    "Add", "Update", "Filter", "Sort", "Reset Selection"):
                hover, full = {
                    "Add": ("Save a new reference message.", "Validate all three text fields and "
                            "save a new message with a generated ID, even when copying an existing row."),
                    "Update": ("Save the highlighted reference message.", "Select exactly one row. "
                               "Save the form; stale changes are rejected. Runtime errors are unchanged."),
                    "Filter": SCREEN_HELP["Error Filter"],
                    "Sort": SCREEN_HELP["Error Sort"],
                    "Reset Selection": ("Show all saved reference messages.", "Clear text filters "
                                        "and saved-set/highlight restrictions without deleting messages."),
                }[button]
            if screen == "Error Set" and button == "Delete Saved":
                hover, full = ("Delete only the selected message set.",
                               "After confirmation, remove the named snapshot. Messages and the "
                               "current working list remain unchanged.")
            rows[screen, f"Button:{button}"] = hover, full
        for field in SCREEN_FIELDS.get(screen, ()):
            if screen in ("Sort", "Error Sort"):
                pair = (("Choose a distinct field for this priority.",
                         "Choose a list column; earlier rows have higher priority. Leave unused "
                         "rows blank. ID is appended as a tie-breaker.") if field.name.startswith("SortField")
                        else ("Choose ascending or descending order.",
                              "asc sorts smallest to largest or A to Z; desc reverses the order. "
                              "This direction applies to the field on the same row."))
            elif screen == "DropDown":
                pair = (("Choose the fabric field to maintain.",
                         "Select a field to list its active choices and default. Changing this "
                         "selection does not modify any saved fabric.") if field.name == "FieldName"
                        else COLUMN_HELP["ListItem"])
            elif screen == "Error Filter":
                pair = (f"Search {field.label.lower()}.",
                        "Blank means no restriction. Match literal text anywhere in this field, "
                        "ignoring ASCII case. Nonblank fields are combined with AND.")
            elif screen == "Error Set" and field.name == "SavedSet":
                pair = ("Choose a saved message snapshot.", SCREEN_HELP["Error Set"][1])
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
            if column == "FieldName" and screen == "DropDown":
                pair = ("Fabric field owning this choice.",
                        "The fabric field whose dropdown list contains this item.")
            hover, full = pair
            if screen == "HelpText":
                full += " Click this heading to toggle ascending/descending saved HelpText sorting."
            rows[screen, f"Column:{column}"] = hover, full
    return rows
