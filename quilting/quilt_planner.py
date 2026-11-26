"""Conservative rectangle packing for quilt-part cutting outlines."""

import math
from decimal import Decimal

from shapely import affinity

from .blocks import cutting_shape
from .model import UNITS_PER_INCH, FieldError


def matches_color_value(part, source):
    minimum, maximum = part["MinimumColorValue"], part["MaximumColorValue"]
    value = source["ColorValue"]
    return minimum is None or (value is not None and minimum <= value <= maximum)


def plan_quilt(uses, mappings, sources, assignments):
    """Pack cut-outline bounding rectangles; leave inventory untouched and report shortages."""
    demands = []
    for use in uses:
        scale = float(Decimal(use["block"]["Scale"]) / 100)
        allowance = use["block"]["SeamAllowance"]
        for part in use["parts"]:
            count = use["quantity"] * part["NumberInBlock"]
            if count > 10000 or len(demands) + count > 10000:
                raise FieldError("Database", "Quilt", detail="A cutting plan supports at most 10,000 parts.")
            outline = cutting_shape(part, scale, allowance)
            minx, miny, maxx, maxy = outline.bounds
            width = math.ceil((maxx - minx) * UNITS_PER_INCH)
            length = math.ceil((maxy - miny) * UNITS_PER_INCH)
            demand = {"block_id": use["block"]["ID"], "block_name": use["block"]["BlockName"],
                      "part_id": part["ID"], "part_name": part["PartName"], "shape": part["Shape"],
                      "color": part["PartColor"], "cut_width": width, "cut_length": length,
                      "MinimumColorValue": part["MinimumColorValue"],
                      "MaximumColorValue": part["MaximumColorValue"]}
            placements = [p for p in use["placements"] if p["BlockPartID"] == part["ID"]]
            for block_number in range(1, use["quantity"] + 1):
                for placement in placements:
                    cut_outline = affinity.scale(outline, xfact=-1, yfact=1, origin=(0, 0)) if placement["Mirrored"] else outline
                    left, top, _, _ = cut_outline.bounds
                    demands.append({
                        **demand, "block_number": block_number, "instance": placement["Instance"],
                        "mirrored": bool(placement["Mirrored"]), "block_rotation": placement["Rotation"],
                        "outline": [(x - left, y - top) for x, y in cut_outline.exterior.coords],
                    })
    demands.sort(key=lambda d: (-d["cut_width"] * d["cut_length"],
                                0 if d["part_id"] in assignments else 1,
                                d["MaximumColorValue"] - d["MinimumColorValue"]
                                if d["MinimumColorValue"] is not None else 10,
                                d["block_id"], d["part_id"]))
    stocks = [{"source": dict(row), "free": [(0, 0, row["UsableWidth"], row["UsableLength"])],
               "cuts": []} for row in sources if row["Status"] == "Available"]
    missing = {}
    for item in demands:
        colors = {value.casefold() for value in mappings.get(item["color"], ())}
        candidates = []
        for index, stock in enumerate(stocks):
            if item["part_id"] in assignments and stock["source"]["ID"] not in assignments[item["part_id"]]:
                continue
            color = stock["source"]["Color"]
            if not color or color.casefold() not in colors:
                continue
            if not matches_color_value(item, stock["source"]):
                continue
            for free_index, (x, y, width, length) in enumerate(stock["free"]):
                for rotated in (False, True):
                    w, h = ((item["cut_length"], item["cut_width"]) if rotated
                            else (item["cut_width"], item["cut_length"]))
                    if w <= width and h <= length:
                        candidates.append(((not bool(stock["cuts"]), width * length - w * h,
                                            stock["source"]["UsableWidth"] * stock["source"]["UsableLength"],
                                            stock["source"]["ID"], free_index, rotated),
                                           index, free_index, x, y, width, length, w, h, rotated))
        if not candidates:
            key = (item["block_id"], item["part_id"], item["mirrored"])
            if key not in missing:
                missing[key] = {**item, "count": 0}
            missing[key]["count"] += 1
            continue
        _, index, free_index, x, y, width, length, w, h, rotated = min(candidates)
        stock = stocks[index]
        stock["free"].pop(free_index)
        if width > w:
            stock["free"].append((x + w, y, width - w, length))
        if length > h:
            stock["free"].append((x, y + h, w, length - h))
        stock["cuts"].append({**item, "x": x, "y": y, "source_width": w, "source_length": h,
                              "rotated": rotated})
    return {"sources": [{"source": stock["source"], "cuts": stock["cuts"], "free": stock["free"]}
                        for stock in stocks if stock["cuts"]],
            "missing": list(missing.values()), "part_count": len(demands)}
