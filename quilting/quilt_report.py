"""Summaries of the allocations in a saved quilt cutting plan."""

from decimal import Decimal

from .model import display_fractional_measurement as _measurement


def cutting_list_description(plan, mode):
    if mode not in ("Entire Quilt", "By Block"):
        raise ValueError(f"Unknown cutting list format: {mode}")

    data = plan["PlanData"]
    uses = {use["block"]["ID"]: use for use in data["uses"]}
    parts = {part["ID"]: (use["block"], part)
             for use in data["uses"] for part in use["parts"]}
    groups = {}
    block_groups = {block_id: [] for block_id in uses}

    def add(item, count, source=None):
        block, part = parts[item["part_id"]]
        scale = Decimal(block["Scale"]) / 100
        fields = (("PartWidth", "PartLength") if part["Shape"] in ("Rectangle", "Square")
                  else ("SideA", "SideB", "SideC") if "Triangle" in part["Shape"]
                  else ("Diameter",))
        dimensions = tuple(Decimal(part[field]) * scale for field in fields)
        key = (part["Shape"], part["PartColor"], dimensions, block["SeamAllowance"],
               item["cut_width"], item["cut_length"], item["mirrored"],
               part.get("MinimumColorValue"), part.get("MaximumColorValue"))
        if mode == "By Block":
            key = (block["ID"], part["ID"], *key)
        if key not in groups:
            groups[key] = {"block": block, "part": part, "fields": fields,
                           "dimensions": dimensions, "item": item,
                           "required": 0, "missing": 0, "sources": {}}
            block_groups[block["ID"]].append(groups[key])
        group = groups[key]
        group["required"] += count
        if source is None:
            group["missing"] += count
        else:
            source_id = source["ID"]
            if source_id not in group["sources"]:
                group["sources"][source_id] = [source, 0]
            group["sources"][source_id][1] += count

    for entry in data["sources"]:
        for cut in entry["cuts"]:
            add(cut, 1, entry["source"])
    for item in data["missing"]:
        add(item, item["count"])

    lines = [f"Cutting list: {mode}",
             f"Quilt: {data['quilt']['QuiltName']} (revision {plan['QuiltRevision']}); plan {plan['ID']}",
             f"Total blocks: {sum(use['quantity'] for use in data['uses'])}; "
             f"required parts: {data['part_count']}",
             "Informational snapshot: inventory is not reserved or changed.",
             "~ marks dimensions rounded to 1/16 in; cut sizes round up. "
             "The plan uses exact sizes and positions: verify rounded cuts fit without overlap "
             "and check allocations before cutting."]

    def append_group(group):
        part, item = group["part"], group["item"]
        labels = {"PartWidth": "width", "PartLength": "length",
                  "SideA": "a", "SideB": "b", "SideC": "c", "Diameter": "diameter"}
        finished = ", ".join(f"{labels[field]} {_measurement(value)}"
                             for field, value in zip(group["fields"], group["dimensions"]))
        name = f"{part['PartName']} (part ID {part['ID']}): " if mode == "By Block" else ""
        value_range = (f"; color value {part['MinimumColorValue']}-{part['MaximumColorValue']}"
                       if part.get("MinimumColorValue") is not None else "")
        lines.append(f"  {name}{group['required']} {part['PartColor']} {part['Shape']}; "
                     f"finished {finished} in; seam allowance "
                     f"{_measurement(group['block']['SeamAllowance'])} in; "
                     f"cut bounding size {_measurement(item['cut_width'], round_up=True)} x "
                     f"{_measurement(item['cut_length'], round_up=True)} in; "
                     f"{'mirrored' if item['mirrored'] else 'not mirrored'}{value_range}")
        for source, count in group["sources"].values():
            value = source.get("ColorValue")
            lines.append(f"    {count} from Fabric {source['ID']}: {source['FabricName']} / "
                         f"{source['Color']}, {_measurement(source['UsableWidth'])} x "
                         f"{_measurement(source['UsableLength'])} in (revision {source['Revision']}); "
                         f"color value {value if value is not None else 'unknown'}")
        if group["missing"]:
            lines.append(f"    Missing: {group['missing']}")

    if mode == "Entire Quilt":
        for group in groups.values():
            append_group(group)
    else:
        for block_id, use in uses.items():
            block = use["block"]
            lines.append(f"\nBlock {block['BlockName']} (ID {block_id}), quantity {use['quantity']}")
            for group in block_groups[block_id]:
                append_group(group)
    return "\n".join(lines)
