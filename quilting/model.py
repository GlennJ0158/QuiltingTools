"""Shared field definitions and exact, UI-independent validation."""

import re
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

UNITS_PER_INCH = 1_000_000
MAX_INCHES = 10_800
ADD_ITEM = "Add Item"
COLOR_VALUES = tuple(str(value) for value in range(1, 11))
GRAIN_DIRECTIONS = ("Unknown", "Along Length", "Along Width")
PRINT_DIRECTIONS = ("Non-directional", "Along Length", "Along Width", "Unknown")
STATUSES = ("Available", "Retired")


class FieldError(ValueError):
    def __init__(self, key, field, **details):
        self.key, self.field, self.details = key, field, details
        super().__init__(f"{field}: {key} {details}")


def caption(name):
    return re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", name)


def display_fabric_name(name, piece_id):
    return f"{name} ({piece_id})"


def display_label_measurement(value):
    return display_fractional_measurement(value, round_up=True).removeprefix("~")


def label_id_font_size(piece_id):
    return min(52, max(12, 80 // len(str(piece_id))))


@dataclass(frozen=True)
class Field:
    name: str
    kind: str = "text"
    required: bool = False
    choices: tuple[str, ...] = ()
    limit: int = 120
    default: str = ""
    width: int = 24

    @property
    def label(self):
        return caption(self.name) + (" (in)" if self.kind == "length" else "")


FABRIC_FIELDS = (
    Field("FabricName", "dropdown", required=True),
    Field("Color", "dropdown"),
    Field("FabricPattern", "dropdown"),
    Field("UsableWidth", "length", True, width=6),
    Field("UsableLength", "length", True, width=6),
    Field("GrainDirection", "choice", True, GRAIN_DIRECTIONS, default="Unknown"),
    Field("PrintDirection", "choice", True, PRINT_DIRECTIONS, default="Unknown"),
    Field("StorageLocation", "dropdown"),
    Field("Status", "choice", True, STATUSES, default="Available"),
    Field("ColorValue", "choice", choices=("", *COLOR_VALUES), width=4),
    Field("Notes", "memo", limit=4000, width=40),
)
FILTER_FIELDS = (
    Field("FabricName"),
    Field("Color", "dropdown"),
    Field("FabricPattern"),
    Field("StorageLocation"),
    Field("MinimumWidth", "length", width=6),
    Field("MaximumWidth", "length", width=6),
    Field("MinimumLength", "length", width=6),
    Field("MaximumLength", "length", width=6),
    Field("Status", "choice", choices=("", *STATUSES)),
)
FABRIC_NAMES = tuple(field.name for field in FABRIC_FIELDS)
DROPDOWN_FIELDS = {field.name: field for field in FABRIC_FIELDS if field.kind in ("dropdown", "choice")}
NUMERIC_COLUMNS = frozenset(("ID", "UsableWidth", "UsableLength", "BackWidth", "BackLength",
                             "Revision", "RecordCount", "Def", "Use",
                             "FinishedWidth", "FinishedLength", "Scale", "NumberInBlock", "ColorValue"))
LIST_COLUMNS = (
    "ID", "FabricName", "Color", "ColorValue", "FabricPattern", "UsableWidth", "UsableLength",
    "GrainDirection", "PrintDirection", "StorageLocation", "Status",
)
SORT_FIELDS = (*LIST_COLUMNS, "DateCreated", "DateModified")
DEFAULT_SORT = (("FabricName", "asc"), ("ID", "asc"))

MESSAGES = (
    ("Required", "A required field was left blank.", "A value is required.", "Enter a value."),
    ("TooLong", "Text exceeds the supported field size.",
     "The value exceeds {limit} characters.", "Shorten the text."),
    ("Choice", "A choice is not in the field's permitted list.",
     "The value is not one of the permitted choices.", "Choose a value from the list."),
    ("Measurement", "A dimension cannot be parsed exactly as a positive inch measurement.",
     "Enter a positive measurement no larger than 10,800 inches, using at most six decimal "
     "places or a fraction in halves through sixty-fourths.",
     "Examples: 42, 42.5, 42 1/2, or 1/4. Do not include unit symbols."),
    ("Binding", "A form control is missing a variable or a supplied field is unrecognized.",
     "The form field is not correctly connected: {detail}.",
     "Do not save this form; report the problem."),
    ("MissingRecord", "A referenced inventory record or saved set no longer exists.",
     "The requested record no longer exists.", "Refresh the list and select a current record."),
    ("Conflict", "The record changed after its details were loaded.",
     "Another operation changed this record.", "Reload the record before editing again."),
    ("NoHighlight", "An operation requires at least one highlighted row.",
     "No records are highlighted.", "Highlight one or more rows in the list."),
    ("OneRecord", "An update requires exactly one highlighted inventory row.",
     "Exactly one record must be highlighted.", "Highlight the record to update."),
    ("EmptySet", "A selection set cannot be saved from an empty working list.",
     "No records are selected.", "Adjust the working selection before saving a set."),
    ("DuplicateSet", "The supplied selection-set name is already in use.",
     "A selection set with this name already exists.", "Choose another name."),
    ("Sort", "The sort contains an invalid field, direction or duplicate.",
     "Choose distinct sort fields and an ascending or descending direction.",
     "Clear unused sort rows. ID is added as a final tie-breaker."),
    ("Database", "A database or file operation failed.",
     "{detail}", "Check the database path, permissions and available disk space."),
    ("DatabaseFormat", "A database is unsupported, incomplete or fails integrity checks.",
     "{detail}", "Use a Quilting Tools version compatible with this database or a verified backup."),
    ("Unexpected", "An unexpected application failure occurred; a traceback is also written to stderr.",
     "{detail}", "Do not repeat a save blindly. Reload the affected record and report the problem."),
)


def measurement(value, field):
    if not isinstance(value, str) or not value.strip():
        raise FieldError("Required", field)
    text = value.strip()
    if len(text) > 120:
        raise FieldError("Measurement", field)
    if re.fullmatch(r"\d+(?:\.\d{1,6})?", text):
        inches = Fraction(Decimal(text))
    else:
        match = re.fullmatch(r"(?:(\d+)\s+)?(\d+)/(2|4|8|16|32|64)", text)
        if not match:
            raise FieldError("Measurement", field)
        whole, numerator, denominator = match.groups()
        if not 0 < int(numerator) < int(denominator):
            raise FieldError("Measurement", field)
        inches = Fraction(int(whole or 0)) + Fraction(int(numerator), int(denominator))
    if not 0 < inches <= MAX_INCHES:
        raise FieldError("Measurement", field)
    return int(inches * UNITS_PER_INCH)


def display_measurement(value):
    inches = Fraction(value, UNITS_PER_INCH)
    if inches.denominator in (1, 2, 4, 8, 16, 32, 64):
        whole, remainder = divmod(inches.numerator, inches.denominator)
        if not remainder:
            return str(whole)
        fraction = f"{remainder}/{inches.denominator}"
        return f"{whole} {fraction}" if whole else fraction
    return format(Decimal(value) / UNITS_PER_INCH, "f").rstrip("0").rstrip(".")


def display_fractional_measurement(value, *, round_up=False):
    """Format millionths of an inch to sixteenths, marking rounded values."""
    sixteenths = Fraction(value) * 16 / UNITS_PER_INCH
    if round_up:
        rounded = -(-sixteenths.numerator // sixteenths.denominator)
    else:
        rounded = (2 * sixteenths.numerator + sixteenths.denominator) // (2 * sixteenths.denominator)
    inches = Fraction(rounded, 16)
    whole, numerator = divmod(inches.numerator, inches.denominator)
    fraction = f"{numerator}/{inches.denominator}" if numerator else ""
    text = f"{whole} {fraction}" if whole and fraction else str(whole) if whole or not fraction else fraction
    return ("~" if sixteenths != rounded else "") + text


def validate_fields(fields, values, choices=None):
    expected = {field.name for field in fields}
    if set(values) != expected:
        detail = f"missing {sorted(expected - set(values))}; unknown {sorted(set(values) - expected)}"
        raise FieldError("Binding", "Form", detail=detail)
    result = {}
    for field in fields:
        value = values[field.name]
        if not isinstance(value, str):
            raise FieldError("Binding", field.name, detail="expected text from the form variable")
        value = value.strip()
        if field.required and not value:
            raise FieldError("Required", field.name)
        if len(value) > field.limit:
            raise FieldError("TooLong", field.name, limit=field.limit)
        if field.kind == "length":
            result[field.name] = measurement(value, field.name) if value else None
        elif field.kind == "choice":
            allowed = (choices or {}).get(field.name, field.choices)
            if value and value not in allowed:
                raise FieldError("Choice", field.name)
            result[field.name] = value
        else:
            result[field.name] = value
    return result


def normalize_sort(sort, fields=SORT_FIELDS):
    if not isinstance(sort, (list, tuple)) or not sort:
        raise FieldError("Sort", "Sort")
    result = []
    for pair in sort:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise FieldError("Sort", "Sort")
        field, direction = pair
        if field not in fields or direction not in ("asc", "desc"):
            raise FieldError("Sort", "Sort")
        if field in [item[0] for item in result]:
            raise FieldError("Sort", field)
        result.append((field, direction))
    if not any(field == "ID" for field, _ in result):
        result.append(("ID", "asc"))
    return tuple(result)
