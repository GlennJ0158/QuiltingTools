"""Finished block geometry and uniform cutting offsets, independent of the UI."""

import math
import re
from decimal import Decimal, InvalidOperation

from shapely import affinity
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

from .model import Field, FieldError, UNITS_PER_INCH, measurement, validate_fields

SHAPES = ("Rectangle", "Square", "Right Triangle", "Isosceles Triangle", "Circle", "Semicircle")
COLORS = ("Red", "Yellow", "Blue", "Green", "Orange", "Purple", "Black", "White", "Gray")
BLOCK_FIELDS = (
    Field("BlockName", required=True), Field("Description", limit=4000),
    Field("FinishedWidth", "length", required=True, width=8),
    Field("FinishedLength", "length", required=True, width=8),
    Field("Scale", required=True, default="100", width=8),
    Field("SeamAllowance", required=True, default="1/4", width=8),
)
PART_FIELDS = (
    Field("PartName", required=True), Field("Shape", "choice", required=True, choices=SHAPES),
    Field("PartColor", "choice", required=True, choices=COLORS),
    Field("NumberInBlock", required=True, default="1", width=8),
    Field("PartWidth", width=8), Field("PartLength", width=8),
    Field("SideA", width=8), Field("SideB", width=8), Field("SideC", width=8),
    Field("Diameter", width=8),
)
BLOCK_COLUMNS = ("ID", "BlockName", "FinishedWidth", "FinishedLength", "Scale", "Status", "Revision")
BLOCK_FILTER_FIELDS = (Field("BlockName"), Field("Status", "choice", choices=("", "Draft", "Approved")))


def parse_block(values):
    clean = validate_fields(BLOCK_FIELDS, values)
    try:
        scale = Decimal(clean["Scale"])
        if not scale.is_finite() or not (Decimal("0") < scale <= Decimal("10000")):
            raise InvalidOperation
        if min(clean["FinishedWidth"], clean["FinishedLength"]) * scale / 100 < 1:
            raise InvalidOperation
    except InvalidOperation as error:
        raise FieldError("Measurement", "Scale") from error
    clean["Scale"] = str(scale.normalize())
    clean["SeamAllowance"] = (
        0 if re.fullmatch(r"0(?:\.0{1,6})?", clean["SeamAllowance"])
        else measurement(clean["SeamAllowance"], "SeamAllowance")
    )
    return clean


def parse_part(values, choices=None):
    clean = validate_fields(PART_FIELDS, values, choices)
    try:
        count = int(clean["NumberInBlock"])
        if str(count) != clean["NumberInBlock"] or not 1 <= count <= 1000:
            raise ValueError
    except ValueError as error:
        raise FieldError("Choice", "NumberInBlock") from error
    clean["NumberInBlock"] = count
    shape = clean["Shape"]
    required = (("PartWidth", "PartLength") if shape in ("Rectangle", "Square")
                else ("SideA", "SideB", "SideC") if "Triangle" in shape else ("Diameter",))
    for name in ("PartWidth", "PartLength", "SideA", "SideB", "SideC", "Diameter"):
        if name in required:
            clean[name] = measurement(clean[name], name)
        elif clean[name]:
            raise FieldError("Choice", name)
        else:
            clean[name] = None
    if shape == "Square" and clean["PartWidth"] != clean["PartLength"]:
        raise FieldError("Choice", "PartWidth")
    if "Triangle" in shape:
        a, b, c = clean["SideA"], clean["SideB"], clean["SideC"]
        if min(a, b, c) <= 0 or a + b <= c or a + c <= b or b + c <= a:
            raise FieldError("Choice", "SideA")
        if shape == "Isosceles Triangle" and len({a, b, c}) == 3:
            raise FieldError("Choice", "SideA")
        if shape == "Right Triangle":
            sides = sorted((a, b, c))
            if not math.isclose(sides[0] ** 2 + sides[1] ** 2, sides[2] ** 2, rel_tol=1e-6):
                raise FieldError("Choice", "SideC")
    return clean


def finished_shape(part, scale=1):
    """Triangle a is the horizontal base; b and c meet its left and right ends."""
    shape = part["Shape"]
    unit = scale / UNITS_PER_INCH
    if shape in ("Rectangle", "Square"):
        return box(0, 0, part["PartWidth"] * unit, part["PartLength"] * unit)
    if "Triangle" in shape:
        a, b, c = (part[name] * unit for name in ("SideA", "SideB", "SideC"))
        x = (a * a + b * b - c * c) / (2 * a)
        return Polygon(((0, 0), (a, 0), (x, math.sqrt(max(0, b * b - x * x)))))
    radius = part["Diameter"] * unit / 2
    circle = Point(radius, radius).buffer(radius, quad_segs=64)
    if shape == "Circle":
        return circle
    if shape == "Semicircle":
        return circle.intersection(box(0, radius, 2 * radius, 2 * radius))
    raise FieldError("Choice", "Shape")


def placed_shape(part, placement, scale=1):
    geom = finished_shape(part, scale)
    if placement["Mirrored"]:
        geom = affinity.scale(geom, xfact=-1, yfact=1, origin=(0, 0))
    geom = affinity.rotate(geom, placement["Rotation"], origin=(0, 0))
    minx, miny, _, _ = geom.bounds
    return affinity.translate(geom, xoff=placement["X"] / UNITS_PER_INCH * scale - minx,
                              yoff=placement["Y"] / UNITS_PER_INCH * scale - miny)


def cutting_shape(part, scale, allowance):
    """Mitred corners provide the intersection of parallel seam-offset edges."""
    return finished_shape(part, scale).buffer(
        allowance / UNITS_PER_INCH, join_style="mitre", mitre_limit=1e6, quad_segs=64)


def validate_layout(block, parts, placements):
    scale = float(Decimal(block["Scale"]) / 100)
    width = block["FinishedWidth"] / UNITS_PER_INCH * scale
    length = block["FinishedLength"] / UNITS_PER_INCH * scale
    target = box(0, 0, width, length)
    expected = {(part["ID"], index) for part in parts for index in range(1, part["NumberInBlock"] + 1)}
    actual = {(item["BlockPartID"], item["Instance"]) for item in placements}
    if not expected or actual != expected or len(actual) != len(placements):
        return ["Each required part instance must have exactly one placement."]
    lookup = {part["ID"]: part for part in parts}
    geometries = [placed_shape(lookup[p["BlockPartID"]], p, scale) for p in placements]
    union = unary_union(geometries)
    # Triangle-side rounding is in unscaled inches, so scale its area tolerance too.
    tolerance = max(1e-10, target.length * 5e-7 * scale)
    issues = []
    if sum(g.area for g in geometries) - union.area > tolerance:
        issues.append("Parts overlap.")
    if union.difference(target).area > tolerance:
        issues.append("Parts extend outside the block.")
    if target.difference(union).area > tolerance:
        issues.append("Parts do not completely cover the block.")
    return issues
