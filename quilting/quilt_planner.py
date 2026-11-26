"""Conservative rectangle packing for quilt-part cutting outlines."""

import math
from decimal import Decimal

from shapely import affinity

from .blocks import cutting_shape
from .model import UNITS_PER_INCH, FieldError


class PlanningCancelled(Exception):
    """The user declined to reuse fabric in a block."""


def matches_color_value(part, source):
    minimum, maximum = part["MinimumColorValue"], part["MaximumColorValue"]
    value = source["ColorValue"]
    return minimum is None or (value is not None and minimum <= value <= maximum)


def plan_quilt(uses, mappings, sources, assignments, reuse_decision=None):
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
                        "rule": use.get("fabric_rule", {}).get("mode", "Legacy"),
                        "group": use.get("fabric_rule", {}).get("groups", {}).get(placement["ID"]),
                        "placement_id": placement["ID"],
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

    def candidates_for(item, available, fabric_name=None, distinct=False):
        colors = {value.casefold() for value in mappings.get(item["color"], ())}
        candidates = []
        for index, stock in enumerate(available):
            if item["part_id"] in assignments and stock["source"]["ID"] not in assignments[item["part_id"]]:
                continue
            if fabric_name is not None and stock["source"]["FabricName"].strip().casefold() != fabric_name:
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
                        area = stock["source"]["UsableWidth"] * stock["source"]["UsableLength"]
                        candidates.append((((area, width * length - w * h) if distinct else
                                            (not bool(stock["cuts"]), width * length - w * h, area))
                                           + (stock["source"]["ID"], free_index, rotated),
                                           index, free_index, x, y, width, length, w, h, rotated))
        return candidates

    def place(item, available, candidate):
        _, index, free_index, x, y, width, length, w, h, rotated = candidate
        stock = available[index]
        stock["free"].pop(free_index)
        if width > w:
            stock["free"].append((x + w, y, width - w, length))
        if length > h:
            stock["free"].append((x, y + h, w, length - h))
        stock["cuts"].append({**item, "x": x, "y": y, "source_width": w, "source_length": h,
                              "rotated": rotated})

    units, grouped = [], {}
    for item in demands:
        if item["rule"] == "Legacy":
            units.append([item])
            continue
        group = ("group", item["group"].casefold()) if item["group"] else ("placement", item["placement_id"])
        key = (item["block_id"], item["block_number"], group)
        if key not in grouped:
            grouped[key] = []
            units.append(grouped[key])
        grouped[key].append(item)

    used = {}
    for unit in units:
        item = unit[0]
        if item["rule"] == "Legacy":
            candidates = candidates_for(item, stocks)
            if candidates:
                place(item, stocks, min(candidates))
                continue
            key = (item["block_id"], item["part_id"], item["mirrored"])
            if key not in missing:
                missing[key] = {**item, "count": 0}
            missing[key]["count"] += 1
            continue
        block_key = (item["block_id"], item["block_number"])
        used_names = used.setdefault(block_key, set())

        def find_group(excluded):
            names = []
            for candidate in sorted(candidates_for(item, stocks, distinct=True)):
                source = stocks[candidate[1]]["source"]
                name = source["FabricName"].strip().casefold()
                if name not in excluded and name not in names:
                    names.append(name)
            for name in names:
                trial = [{"source": stock["source"], "free": list(stock["free"]),
                          "cuts": []} for stock in stocks]
                for member in unit:
                    candidates = candidates_for(member, trial, name, distinct=True)
                    if not candidates:
                        break
                    place(member, trial, min(candidates))
                else:
                    return name, trial
            return None

        excluded = used_names if item["rule"] == "Distinct" else set()
        result = find_group(excluded)
        if result is None and excluded:
            result = find_group(set())
            if result is not None:
                if reuse_decision is None:
                    raise FieldError("Database", "Quilt", reason="planning", detail=(
                        f"Block {item['block_name']} copy {item['block_number']} needs fabric reuse "
                        f"for {item['part_name']}; retry with a reuse decision."))
                if not reuse_decision(item):
                    raise PlanningCancelled()
                used_names.clear()
        if result is None:
            raise FieldError("Database", "Quilt", reason="planning", detail=(
                f"Cannot fit {item['part_name']} in block {item['block_name']} copy "
                f"{item['block_number']} using the selected, mapped and eligible fabrics. "
                "No plan was saved; adjust the choices or add fabric and try again."))
        name, trial = result
        for stock, staged in zip(stocks, trial):
            stock["free"] = staged["free"]
            stock["cuts"].extend(staged["cuts"])
        used_names.add(name)
    return {"sources": [{"source": stock["source"], "cuts": stock["cuts"], "free": stock["free"]}
                        for stock in stocks if stock["cuts"]],
            "missing": list(missing.values()), "part_count": len(demands)}
