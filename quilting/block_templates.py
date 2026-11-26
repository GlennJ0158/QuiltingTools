"""Editable starter layouts for common quilt blocks."""

import math
from collections import OrderedDict

from .model import display_measurement

BLOCK_TEMPLATES = {
    "Four Patch": "A two-by-two checkerboard of equal rectangular patches.",
    "Nine Patch": "A three-by-three grid with contrasting corner/center and side patches.",
    "Flying Geese": "One large triangle with two background triangles in a rectangular unit.",
    "Log Cabin (Square)": "A center patch surrounded by two alternating rounds of rectangular logs.",
    "Log Cabin (Spiral)": "Spiral logs with light top/left and dark bottom/right sides.",
    "Half-Square Triangle": "Four two-triangle units arranged in a two-by-two grid.",
}


def _integer_grid(length, divisions):
    return [index * length // divisions for index in range(divisions + 1)]


def _specs_for_template(name, width, length):
    parts = OrderedDict()

    def add(part_name, shape, color, dimensions, x, y, rotation=0, mirrored=False, color_range=None):
        key = (part_name, shape, color, tuple(dimensions.items()), color_range)
        if key not in parts:
            parts[key] = {"dimensions": dimensions, "placements": [], "color_range": color_range}
        parts[key]["placements"].append((x, y, rotation, mirrored))

    def rectangle(part_name, color, x0, y0, x1, y1, color_range=None):
        add(part_name, "Rectangle", color,
            {"PartWidth": x1 - x0, "PartLength": y1 - y0}, x0, y0, color_range=color_range)

    def right_triangle(part_name, color, leg_x, leg_y, x, y, rotation=0, mirrored=False):
        add(part_name, "Right Triangle", color,
            {"SideA": leg_x, "SideB": leg_y, "SideC": round(math.hypot(leg_x, leg_y))},
            x, y, rotation, mirrored)

    def isosceles_triangle(part_name, color, base, half_height, x, y, rotation=0):
        side = round(math.hypot(base / 2, half_height))
        add(part_name, "Isosceles Triangle", color,
            {"SideA": base, "SideB": side, "SideC": side}, x, y, rotation)

    if name in ("Four Patch", "Nine Patch"):
        divisions = 2 if name == "Four Patch" else 3
        xs, ys = _integer_grid(width, divisions), _integer_grid(length, divisions)
        for row in range(divisions):
            for col in range(divisions):
                if name == "Four Patch":
                    color = "Red" if (row + col) % 2 == 0 else "Yellow"
                    part_name = "Patch"
                else:
                    color = "Red" if row == col or row + col == 2 else "Yellow"
                    part_name = "Corner and center" if color == "Red" else "Side"
                rectangle(part_name, color, xs[col], ys[row], xs[col + 1], ys[row + 1])

    elif name == "Flying Geese":
        half_width = width // 2
        other_half = width - half_width
        goose_side = round(math.hypot(width / 2, length))
        add("Goose", "Isosceles Triangle", "Red",
            {"SideA": width, "SideB": goose_side, "SideC": goose_side},
            0, 0, 180)
        right_triangle("Background left", "Blue", half_width, length, 0, 0)
        right_triangle("Background right", "Blue", other_half, length, half_width, 0, mirrored=True)

    elif name == "Log Cabin (Square)":
        xs, ys = _integer_grid(width, 5), _integer_grid(length, 5)
        rectangle("Center", "Yellow", xs[2], ys[2], xs[3], ys[3])
        logs = (
            ("Inner top log", "Red", xs[1], ys[1], xs[4], ys[2]),
            ("Inner right log", "Red", xs[3], ys[2], xs[4], ys[3]),
            ("Inner bottom log", "Red", xs[1], ys[3], xs[4], ys[4]),
            ("Inner left log", "Red", xs[1], ys[2], xs[2], ys[3]),
            ("Outer top log", "Blue", xs[0], ys[0], xs[5], ys[1]),
            ("Outer right log", "Blue", xs[4], ys[1], xs[5], ys[4]),
            ("Outer bottom log", "Blue", xs[0], ys[4], xs[5], ys[5]),
            ("Outer left log", "Blue", xs[0], ys[1], xs[1], ys[4]),
        )
        for part_name, color, x0, y0, x1, y1 in logs:
            rectangle(part_name, color, x0, y0, x1, y1)

    elif name == "Log Cabin (Spiral)":
        xs, ys = _integer_grid(width, 5), _integer_grid(length, 5)
        center_width, center_length = xs[3] - xs[2], ys[3] - ys[2]
        add("Center", "Square" if center_width == center_length else "Rectangle", "Yellow",
            {"PartWidth": center_width, "PartLength": center_length}, xs[2], ys[2])
        logs = (
            ("Inner right log", "Black", 7, 10, 3, 2, 4, 3),
            ("Inner bottom log", "Black", 7, 10, 2, 3, 4, 4),
            ("Inner left log", "White", 1, 4, 1, 2, 2, 4),
            ("Inner top log", "White", 1, 4, 1, 1, 4, 2),
            ("Outer right log", "Black", 7, 10, 4, 1, 5, 4),
            ("Outer bottom log", "Black", 7, 10, 1, 4, 5, 5),
            ("Outer left log", "White", 1, 4, 0, 1, 1, 5),
            ("Outer top log", "White", 1, 4, 0, 0, 5, 1),
        )
        for part_name, color, low, high, x0, y0, x1, y1 in logs:
            rectangle(part_name, color, xs[x0], ys[y0], xs[x1], ys[y1], (low, high))

    elif name == "Half-Square Triangle":
        xs, ys = _integer_grid(width, 2), _integer_grid(length, 2)
        for row in range(2):
            for col in range(2):
                first = "Red" if (row + col) % 2 == 0 else "Blue"
                second = "Blue" if first == "Red" else "Red"
                x, y = xs[col], ys[row]
                leg_x, leg_y = xs[col + 1] - x, ys[row + 1] - y
                right_triangle("Half-square triangle", first, leg_x, leg_y, x, y)
                right_triangle("Half-square triangle", second, leg_x, leg_y, x, y, rotation=180)

    else:
        raise ValueError(f"Unknown block template: {name}")

    result = []
    for (part_name, shape, color, _, _), part in parts.items():
        values = {
            "PartName": part_name,
            "Shape": shape,
            "PartColor": color,
            "NumberInBlock": str(len(part["placements"])),
            "PartWidth": "",
            "PartLength": "",
            "SideA": "",
            "SideB": "",
            "SideC": "",
            "Diameter": "",
            "MinimumColorValue": str(part["color_range"][0]) if part["color_range"] else "",
            "MaximumColorValue": str(part["color_range"][1]) if part["color_range"] else "",
        }
        for field, value in part["dimensions"].items():
            values[field] = display_measurement(value)
        result.append({"values": values, "placements": part["placements"]})
    return result


def build_block_template(name, width, length):
    """Return parsed part inputs and unscaled placements for a finished block size."""
    if name not in BLOCK_TEMPLATES:
        raise ValueError(f"Unknown block template: {name}")
    return _specs_for_template(name, width, length)
