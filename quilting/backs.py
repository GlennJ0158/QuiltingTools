"""Rectangular quilt-back layout candidates and printable plan sketches."""

from dataclasses import dataclass
from html import escape

from .model import FieldError

INCH = 1_000_000
MINIMUM_PART = 5 * INCH
MAX_PANELS = 20

PALETTE = {
    "Red": "#d64b4b",
    "Orange": "#e38b35",
    "Yellow": "#e6c84f",
    "Green": "#5c9e64",
    "Teal": "#43a6a0",
    "Blue": "#5285c5",
    "Purple": "#8867ac",
    "Pink": "#d979a5",
    "Brown": "#96704f",
    "Black": "#3b3b3b",
    "Gray": "#92979d",
    "White": "#f4f2ec",
    "Cream": "#e9d8a6",
    "Multicolor": "#b45c91",
}


@dataclass(frozen=True)
class Panel:
    number: int
    source_id: int
    source_revision: int
    source_name: str
    source_color: str
    palette_color: str
    cut_width: int
    cut_length: int
    finished_width: int
    finished_length: int
    grain_axis: str | None
    source_x: int
    source_y: int
    x: int
    y: int


@dataclass(frozen=True)
class Layout:
    direction: str
    target_width: int
    target_length: int
    seam_allowance: int
    panels: tuple[Panel, ...]
    grain_consistent: bool
    grain_unknown: bool
    ratio_tier: int
    stock_area: int

    @property
    def seam_count(self):
        return len(self.panels) - 1


def palette_suggestion(description):
    """Suggest a controlled sketch color from a description; never changes inventory."""
    text = (description or "").casefold()
    matches = (
        (("multi", "print", "floral", "variegated"), "Multicolor"),
        (("cream", "ivory", "ecru"), "Cream"),
        (("white", "snow"), "White"),
        (("black", "charcoal"), "Black"),
        (("gray", "grey", "silver"), "Gray"),
        (("brown", "tan", "beige", "khaki"), "Brown"),
        (("pink", "rose", "magenta"), "Pink"),
        (("purple", "violet", "lavender"), "Purple"),
        (("teal", "aqua", "turquoise"), "Teal"),
        (("blue", "navy", "indigo"), "Blue"),
        (("green", "sage", "olive"), "Green"),
        (("yellow", "gold"), "Yellow"),
        (("orange", "rust"), "Orange"),
        (("red", "crimson", "burgundy"), "Red"),
    )
    return next((color for words, color in matches if any(word in text for word in words)), "Gray")


def _grain_axis(piece):
    direction = piece["GrainDirection"]
    if direction == "Unknown":
        return None
    return "x" if direction == "Along Width" else "y"


def _fits(piece, cut_width, cut_length):
    return piece["UsableWidth"] >= cut_width and piece["UsableLength"] >= cut_length


def _place_on_source(piece, state, cut_width, cut_length):
    x, y, row_height = state
    if x + cut_width > piece["UsableWidth"]:
        x, y, row_height = 0, y + row_height, 0
    if y + cut_length > piece["UsableLength"]:
        return None
    return x, y, (x + cut_width, y, max(row_height, cut_length))


def _tier(panels, quilt_width, quilt_length):
    if any(panel.finished_width < MINIMUM_PART or panel.finished_length < MINIMUM_PART
           for panel in panels):
        return -1
    if all(panel.finished_width * 5 >= quilt_width and panel.finished_length * 5 >= quilt_length
           for panel in panels):
        return 2
    if all(panel.finished_width * 10 >= quilt_width and panel.finished_length * 10 >= quilt_length
           for panel in panels):
        return 1
    return 0


def generate_layouts(pieces, quilt_width, quilt_length, margin, seam_allowance,
                     palette_by_piece=None):
    """Rank up to twenty-panel, single-axis straight-cut plans from selected stock rectangles."""
    if min(quilt_width, quilt_length) <= 0 or margin < 0 or seam_allowance < 0:
        raise FieldError("Measurement", "QuiltDimensions")
    target_width = quilt_width + 2 * margin
    target_length = quilt_length + 2 * margin
    stock = sorted(
        (dict(piece) for piece in pieces if piece["Status"] == "Available"),
        key=lambda piece: (piece["UsableWidth"] * piece["UsableLength"], piece["ID"]),
    )
    if not stock:
        return []
    palette_by_piece = palette_by_piece or {}
    candidates = []
    for direction in ("vertical", "horizontal"):
        span = target_width if direction == "vertical" else target_length
        full = target_length if direction == "vertical" else target_width
        max_parts = min(MAX_PANELS, span // MINIMUM_PART)
        for count in range(1, max_parts + 1):
            base, extra = divmod(span, count)
            finished_spans = [base + (index < extra) for index in range(count)]
            specs = []
            for index, finished_span in enumerate(finished_spans):
                joins = int(index > 0) + int(index < count - 1)
                cut_span = finished_span + seam_allowance * joins
                cut_width, cut_length = (
                    (cut_span, full) if direction == "vertical" else (full, cut_span)
                )
                finished_width, finished_length = (
                    (finished_span, full) if direction == "vertical" else (full, finished_span)
                )
                specs.append((cut_width, cut_length, finished_width, finished_length))
            if any(width < MINIMUM_PART or length < MINIMUM_PART
                   for _, _, width, length in specs):
                continue
            narrowest_cut = min(spec[0] for spec in specs)
            shortest_cut = min(spec[1] for spec in specs)
            capacity = sum(
                (piece["UsableWidth"] // narrowest_cut)
                * (piece["UsableLength"] // shortest_cut)
                for piece in stock
            )
            if capacity < count:
                continue
            options = []
            for cut_width, cut_length, _, _ in specs:
                feasible = []
                for piece in stock:
                    if _fits(piece, cut_width, cut_length):
                        feasible.append(piece)
                feasible.sort(key=lambda item: (
                    item["UsableWidth"] * item["UsableLength"], item["ID"],
                ))
                options.append(feasible[:MAX_PANELS])

            generated = 0

            def assign(index, selected, panels, source_states):
                nonlocal generated
                if generated >= 30:
                    return
                if index == count:
                    tier = _tier(panels, quilt_width, quilt_length)
                    grains = [panel.grain_axis for panel in panels]
                    known = {axis for axis in grains if axis is not None}
                    candidates.append(Layout(
                        "single" if count == 1 else direction,
                        target_width, target_length, seam_allowance, tuple(panels),
                        len(known) <= 1, any(axis is None for axis in grains), tier,
                        sum(piece["UsableWidth"] * piece["UsableLength"]
                            for piece in {item["ID"]: item for item in selected}.values()),
                    ))
                    generated += 1
                    return
                cut_width, cut_length, finished_width, finished_length = specs[index]
                panel_x = sum(item[2] for item in specs[:index]) if direction == "vertical" else 0
                panel_y = sum(item[3] for item in specs[:index]) if direction == "horizontal" else 0
                for piece in options[index]:
                    placement = _place_on_source(
                        piece, source_states.get(piece["ID"], (0, 0, 0)),
                        cut_width, cut_length,
                    )
                    if placement is None:
                        continue
                    source_x, source_y, next_state = placement
                    panel = Panel(
                        index + 1, piece["ID"], piece["Revision"], piece["FabricName"],
                        piece["Color"], palette_by_piece.get(
                            piece["ID"], palette_suggestion(piece["Color"]),
                        ), cut_width, cut_length, finished_width, finished_length,
                        _grain_axis(piece), source_x, source_y, panel_x, panel_y,
                    )
                    next_states = dict(source_states)
                    next_states[piece["ID"]] = next_state
                    assign(index + 1, (*selected, piece), (*panels, panel), next_states)

            assign(0, (), (), {})
    candidates.sort(key=lambda layout: (
        -layout.ratio_tier, not layout.grain_consistent, layout.grain_unknown,
        len(layout.panels), layout.stock_area,
        tuple(panel.source_id for panel in layout.panels),
    ))
    unique = []
    seen = set()
    for layout in candidates:
        key = (layout.direction, tuple(
            (panel.source_id, panel.source_x, panel.source_y, panel.cut_width,
             panel.cut_length, panel.grain_axis)
            for panel in layout.panels
        ))
        if key not in seen:
            seen.add(key)
            unique.append(layout)
        if len(unique) == 100:
            break
    best_tier = max((layout.ratio_tier for layout in unique), default=-1)
    return [layout for layout in unique if layout.ratio_tier == best_tier]


def ratio_label(tier):
    return {2: "20% target met", 1: "10% target met", 0: "5 in minimum only"}.get(
        tier, "Below minimum",
    )


def layout_svg(layout):
    """Create a scaled SVG assembly sketch with panel color and grain direction."""
    scale = min(780 / layout.target_width, 520 / layout.target_length)
    width, length = layout.target_width * scale, layout.target_length * scale
    gutter = 12
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width + 2*gutter:.1f}" '
        f'height="{length + 2*gutter:.1f}" viewBox="0 0 {width + 2*gutter:.1f} '
        f'{length + 2*gutter:.1f}">',
        '<rect width="100%" height="100%" fill="white"/>',
    ]
    for panel in layout.panels:
        x, y = gutter + panel.x * scale, gutter + panel.y * scale
        w, h = panel.finished_width * scale, panel.finished_length * scale
        color = PALETTE.get(panel.palette_color, PALETTE["Gray"])
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'fill="{color}" stroke="#222" stroke-width="2"/>'
        )
        text_color = "#fff" if panel.palette_color in ("Black", "Blue", "Purple", "Brown") else "#222"
        parts.append(
            f'<text x="{x + w/2:.1f}" y="{y + h/2:.1f}" text-anchor="middle" '
            f'fill="{text_color}" font-family="sans-serif" font-size="14">'
            f'Part {panel.number}</text>'
        )
        if panel.grain_axis:
            if panel.grain_axis == "x":
                x1, y1, x2, y2 = x + w * .30, y + h * .70, x + w * .70, y + h * .70
            else:
                x1, y1, x2, y2 = x + w * .70, y + h * .30, x + w * .70, y + h * .70
            parts.append(
                f'<path d="M{x1:.1f},{y1:.1f} L{x2:.1f},{y2:.1f}" stroke="#111" '
                'stroke-width="3" marker-end="url(#arrow)"/>'
            )
        else:
            parts.append(
                f'<text x="{x + w/2:.1f}" y="{y + h*.7:.1f}" text-anchor="middle" '
                'fill="#111" font-family="sans-serif" font-size="14">Grain unknown</text>'
            )
    parts.append(
        '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" '
        'orient="auto"><path d="M0,0 L0,6 L7,3 z" fill="#111"/></marker></defs></svg>'
    )
    return "".join(parts)


def layout_legend(layout):
    return [
        {
            "number": panel.number,
            "source_id": panel.source_id,
            "fabric_name": panel.source_name,
            "inventory_color": panel.source_color or "(no color recorded)",
            "palette_color": panel.palette_color,
            "grain_axis": panel.grain_axis or "unknown",
            "cut_width": panel.cut_width,
            "cut_length": panel.cut_length,
            "finished_width": panel.finished_width,
            "finished_length": panel.finished_length,
            "source_x": panel.source_x,
            "source_y": panel.source_y,
        }
        for panel in layout.panels
    ]


def layout_from_record(back):
    panels = tuple(Panel(
        panel["PanelNumber"], panel["FabricPieceID"], panel["SourceRevision"],
        panel["FabricName"], panel["InventoryColor"], panel["PaletteColor"], panel["CutWidth"],
        panel["CutLength"], panel["FinishedWidth"], panel["FinishedLength"],
        panel["GrainAxis"], panel["SourceX"], panel["SourceY"], panel["X"], panel["Y"],
    ) for panel in back["Panels"])
    grains = [panel.grain_axis for panel in panels]
    return Layout(
        back["LayoutDirection"],
        back["BackWidth"], back["BackLength"], back["SeamAllowance"], panels,
        len({axis for axis in grains if axis is not None}) <= 1,
        any(axis is None for axis in grains), back["RatioTier"],
        sum(
            panel["SourceWidth"] * panel["SourceLength"]
            for panel in {item["FabricPieceID"]: item for item in back["Panels"]}.values()
        ),
    )


def escaped_legend(layout):
    rows = []
    for item in layout_legend(layout):
        swatch = PALETTE.get(item["palette_color"], PALETTE["Gray"])
        rows.append(
            "<tr><td>" + str(item["number"]) + "</td>"
            f'<td><span style="display:inline-block;width:1em;height:1em;background:{swatch};'
            'border:1px solid #444"></span> ' + escape(item["palette_color"]) + "</td>"
                "<td>" + escape(item["fabric_name"]) + " — " + escape(item["inventory_color"]) + "</td>"
                f'<td>{escape(item["grain_axis"])}</td>'
            f'<td>{item["finished_width"] / INCH:g} × {item["finished_length"] / INCH:g} in</td>'
                f'<td>{item["cut_width"] / INCH:g} × {item["cut_length"] / INCH:g} in</td>'
                f'<td>{item["source_x"] / INCH:g}, {item["source_y"] / INCH:g} in</td></tr>'
        )
    return (
        "<table><thead><tr><th>Part</th><th>Sketch color</th><th>Inventory fabric</th>"
        "<th>Grain axis</th><th>Finished panel</th><th>Cut size</th>"
        "<th>Cut origin in source</th></tr></thead><tbody>"
        + "".join(rows) + "</tbody></table>"
    )
