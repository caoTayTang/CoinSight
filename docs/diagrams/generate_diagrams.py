"""Generate the warehouse EERD and relational schema diagrams.

Writes, next to this script:
  dw_eerd.{drawio,svg,png,pdf}        Chen-notation EERD
  dw_relational.{drawio,svg,png,pdf}  EERD-to-relational mapping

The .drawio files open in diagrams.net (or the VS Code Draw.io extension) for
manual editing. PNG and PDF export need Inkscape on PATH.

Run: python docs/diagrams/generate_diagrams.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
import os
import shutil
import subprocess
from xml.sax.saxutils import escape


OUT_DIR = Path(__file__).parent
FONT = "Helvetica, Arial, sans-serif"
FONT_SIZE = 12
CHAR_WIDTH = 6.8

ENTITY_FILL, ENTITY_STROKE = "#dae8fc", "#6c8ebf"
WEAK_FILL, WEAK_STROKE = "#fff2cc", "#d6b656"
REL_FILL, REL_STROKE = "#e1d5e7", "#9673a6"
META_FILL = "#f8cecc"


def text_width(text: str, size: float = FONT_SIZE) -> float:
    return len(text) * CHAR_WIDTH * size / FONT_SIZE


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


@dataclass
class Drawing:
    width: float
    height: float
    svg: list[str] = field(default_factory=list)
    svg_top: list[str] = field(default_factory=list)
    cells: list[str] = field(default_factory=list)
    next_id: int = 2

    def new_id(self) -> str:
        self.next_id += 1
        return f"c{self.next_id}"

    def vertex(self, label: str, style: str, x: float, y: float, w: float, h: float) -> str:
        cell_id = self.new_id()
        self.cells.append(
            f'<mxCell id="{cell_id}" value="{escape(label, {chr(34): "&quot;"})}" '
            f'style="{style}" vertex="1" parent="1">'
            f'<mxGeometry x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" as="geometry"/>'
            "</mxCell>"
        )
        return cell_id

    def edge(
        self,
        style: str,
        source: str | None = None,
        target: str | None = None,
        points: list[tuple[float, float]] | None = None,
    ) -> None:
        cell_id = self.new_id()
        attrs = f'id="{cell_id}" style="{style}" edge="1" parent="1"'
        if source:
            attrs += f' source="{source}"'
        if target:
            attrs += f' target="{target}"'
        geometry = '<mxGeometry relative="1" as="geometry">'
        if points and not source:
            geometry += f'<mxPoint x="{points[0][0]:.1f}" y="{points[0][1]:.1f}" as="sourcePoint"/>'
            geometry += f'<mxPoint x="{points[-1][0]:.1f}" y="{points[-1][1]:.1f}" as="targetPoint"/>'
            if len(points) > 2:
                geometry += '<Array as="points">'
                geometry += "".join(f'<mxPoint x="{x:.1f}" y="{y:.1f}"/>' for x, y in points[1:-1])
                geometry += "</Array>"
        geometry += "</mxGeometry>"
        self.cells.append(f"<mxCell {attrs}>{geometry}</mxCell>")

    def save(self, name: str, title: str) -> None:
        drawio = (
            f'<mxfile host="CoinSight"><diagram name="{title}" id="{name}">'
            f'<mxGraphModel dx="{self.width:.0f}" dy="{self.height:.0f}" grid="0" '
            f'gridSize="10" guides="1" page="0" math="0" shadow="0">'
            '<root><mxCell id="0"/><mxCell id="1" parent="0"/>'
            + "".join(self.cells)
            + "</root></mxGraphModel></diagram></mxfile>\n"
        )
        (OUT_DIR / f"{name}.drawio").write_text(drawio)

        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width:.0f}" '
            f'height="{self.height:.0f}" viewBox="0 0 {self.width:.0f} {self.height:.0f}" '
            f'font-family="{FONT}" font-size="{FONT_SIZE}">'
            f'<rect width="100%" height="100%" fill="white"/>'
            '<defs><marker id="arrow" viewBox="0 0 10 10" refX="10" refY="5" '
            'markerWidth="8" markerHeight="8" orient="auto-start-reverse">'
            '<path d="M0,0 L10,5 L0,10 z" fill="black"/></marker></defs>'
            + "".join(self.svg)
            + "".join(self.svg_top)
            + "</svg>\n"
        )
        svg_path = OUT_DIR / f"{name}.svg"
        svg_path.write_text(svg)

        if shutil.which("inkscape"):
            subprocess.run(
                [
                    "inkscape",
                    str(svg_path),
                    "--export-type=png,pdf",
                    "--export-dpi=150",
                ],
                check=True,
                capture_output=True,
                # A clean environment keeps editor snap libraries out of Inkscape.
                env={"HOME": os.environ.get("HOME", ""), "PATH": "/usr/bin:/bin"},
            )


def svg_text(
    x: float,
    y: float,
    text: str,
    *,
    anchor: str = "middle",
    weight: str = "normal",
    size: float = FONT_SIZE,
) -> str:
    return (
        f'<text x="{x:.1f}" y="{y + size * 0.35:.1f}" text-anchor="{anchor}" '
        f'font-weight="{weight}" font-size="{size}">{escape(text)}</text>'
    )


def svg_underline(x: float, y: float, text: str, dashed: bool = False) -> str:
    half = text_width(text) * 0.86 / 2
    dash = ' stroke-dasharray="3,2"' if dashed else ""
    return (
        f'<line x1="{x - half:.1f}" y1="{y + 7:.1f}" x2="{x + half:.1f}" y2="{y + 7:.1f}" '
        f'stroke="black" stroke-width="1"{dash}/>'
    )


# ---------------------------------------------------------------------------
# EERD (Chen notation)
# ---------------------------------------------------------------------------

ENTITY_W, ENTITY_H = 150, 44
REL_W, REL_H = 130, 64
ATTR_H = 32


@dataclass
class Node:
    name: str
    kind: str
    x: float
    y: float
    w: float
    h: float
    cell: str = ""


class Chen:
    def __init__(self, width: float, height: float) -> None:
        self.drawing = Drawing(width, height)
        self.nodes: dict[str, Node] = {}
        self.lines: list[tuple[str, str, bool]] = []
        self.labels: list[tuple[float, float, str]] = []

    def entity(self, name: str, x: float, y: float, weak: bool = False) -> None:
        self.nodes[name] = Node(name, "weak" if weak else "entity", x, y, ENTITY_W, ENTITY_H)

    def relationship(
        self,
        name: str,
        one: str,
        many: str,
        identifying: bool = False,
        at: float = 0.5,
        many_total: bool = True,
    ) -> None:
        a, b = self.nodes[one], self.nodes[many]
        x, y = a.x + (b.x - a.x) * at, a.y + (b.y - a.y) * at
        kind = "idrel" if identifying else "rel"
        self.nodes[name] = Node(name, kind, x, y, REL_W, REL_H)
        self.lines.append((one, name, False))
        self.lines.append((name, many, many_total))
        self.cardinality(name, one, "1")
        self.cardinality(name, many, "N")

    def cardinality(self, rel: str, entity: str, text: str) -> None:
        r, e = self.nodes[rel], self.nodes[entity]
        dx, dy = e.x - r.x, e.y - r.y
        length = math.hypot(dx, dy)
        ux, uy = dx / length, dy / length
        distance = 58 if abs(ux) > abs(uy) else 44
        self.labels.append((r.x + ux * distance - uy * 11, r.y + uy * distance + ux * 11, text))

    def attributes(
        self,
        owner: str,
        specs: list[str],
        angles: list[float],
        rx: float,
        ry: float,
    ) -> None:
        """specs: name, or prefix '*' key, '~' partial key, '/' derived."""
        o = self.nodes[owner]
        for spec, angle in zip(specs, angles, strict=True):
            kind = {"*": "key", "~": "partial", "/": "derived"}.get(spec[0], "attr")
            label = spec[1:] if kind != "attr" else spec
            radians = math.radians(angle)
            x = o.x + rx * math.cos(radians)
            y = o.y - ry * math.sin(radians)
            node_name = f"{owner}.{label}"
            width = max(84, text_width(label) + 26)
            self.nodes[node_name] = Node(label, kind, x, y, width, ATTR_H)
            self.lines.append((owner, node_name, False))

    def render(self, name: str) -> None:
        d = self.drawing

        for a, b, double in self.lines:
            p, q = self.nodes[a], self.nodes[b]
            if double:
                length = math.hypot(q.x - p.x, q.y - p.y)
                nx, ny = -(q.y - p.y) / length * 2.2, (q.x - p.x) / length * 2.2
                for sign in (1, -1):
                    d.svg.append(
                        f'<line x1="{p.x + sign * nx:.1f}" y1="{p.y + sign * ny:.1f}" '
                        f'x2="{q.x + sign * nx:.1f}" y2="{q.y + sign * ny:.1f}" '
                        'stroke="black" stroke-width="1.2"/>'
                    )
            else:
                d.svg.append(
                    f'<line x1="{p.x:.1f}" y1="{p.y:.1f}" x2="{q.x:.1f}" y2="{q.y:.1f}" '
                    'stroke="black" stroke-width="1.2"/>'
                )

        for node in self.nodes.values():
            left, top = node.x - node.w / 2, node.y - node.h / 2
            if node.kind in ("entity", "weak"):
                fill, stroke = (WEAK_FILL, WEAK_STROKE) if node.kind == "weak" else (ENTITY_FILL, ENTITY_STROKE)
                d.svg.append(
                    f'<rect x="{left:.1f}" y="{top:.1f}" width="{node.w}" height="{node.h}" '
                    f'fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>'
                )
                if node.kind == "weak":
                    d.svg.append(
                        f'<rect x="{left + 4:.1f}" y="{top + 4:.1f}" width="{node.w - 8}" '
                        f'height="{node.h - 8}" fill="none" stroke="{stroke}" stroke-width="1.2"/>'
                    )
                d.svg.append(svg_text(node.x, node.y, node.name, weight="bold"))
                style = (
                    "shape=ext;margin=3;double=1;" if node.kind == "weak" else ""
                ) + (
                    f"whiteSpace=wrap;html=1;align=center;fontStyle=1;"
                    f"fillColor={fill};strokeColor={stroke};"
                )
                node.cell = d.vertex(node.name, style, left, top, node.w, node.h)
            elif node.kind in ("rel", "idrel"):
                points = [
                    (node.x, top),
                    (node.x + node.w / 2, node.y),
                    (node.x, node.y + node.h / 2),
                    (left, node.y),
                ]
                d.svg.append(
                    '<polygon points="'
                    + " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
                    + f'" fill="{REL_FILL}" stroke="{REL_STROKE}" stroke-width="1.5"/>'
                )
                if node.kind == "idrel":
                    inner = [
                        (node.x, top + 6),
                        (node.x + node.w / 2 - 11, node.y),
                        (node.x, node.y + node.h / 2 - 6),
                        (left + 11, node.y),
                    ]
                    d.svg.append(
                        '<polygon points="'
                        + " ".join(f"{x:.1f},{y:.1f}" for x, y in inner)
                        + f'" fill="none" stroke="{REL_STROKE}" stroke-width="1.2"/>'
                    )
                d.svg.append(svg_text(node.x, node.y, node.name, size=11))
                style = (
                    "shape=rhombus;perimeter=rhombusPerimeter;"
                    + ("double=1;" if node.kind == "idrel" else "")
                    + f"whiteSpace=wrap;html=1;align=center;fontSize=11;"
                    f"fillColor={REL_FILL};strokeColor={REL_STROKE};"
                )
                node.cell = d.vertex(node.name, style, left, top, node.w, node.h)
            else:
                dash = ' stroke-dasharray="5,3"' if node.kind == "derived" else ""
                d.svg.append(
                    f'<ellipse cx="{node.x:.1f}" cy="{node.y:.1f}" rx="{node.w / 2:.1f}" '
                    f'ry="{node.h / 2:.1f}" fill="white" stroke="black" stroke-width="1.2"{dash}/>'
                )
                d.svg.append(svg_text(node.x, node.y, node.name))
                label = node.name
                style = "ellipse;whiteSpace=wrap;html=1;align=center;"
                if node.kind == "key":
                    d.svg.append(svg_underline(node.x, node.y, node.name))
                    style += "fontStyle=4;"
                elif node.kind == "partial":
                    d.svg.append(svg_underline(node.x, node.y, node.name, dashed=True))
                    label = f'<span style="border-bottom: 1px dashed">{escape(node.name)}</span>'
                elif node.kind == "derived":
                    style += "dashed=1;"
                node.cell = d.vertex(label, style, left, top, node.w, node.h)

        for a, b, double in self.lines:
            style = "endArrow=none;html=1;rounded=0;" + ("shape=link;" if double else "")
            d.edge(style, self.nodes[a].cell, self.nodes[b].cell)

        for x, y, text in self.labels:
            d.svg_top.append(svg_text(x, y, text, weight="bold"))
            d.vertex(text, "text;html=1;align=center;verticalAlign=middle;fontStyle=1;", x - 8, y - 9, 16, 18)

        d.save(name, "EERD")


def spread(start: float, end: float, count: int) -> list[float]:
    if count == 1:
        return [(start + end) / 2]
    return [start + (end - start) * i / (count - 1) for i in range(count)]


def build_eerd() -> None:
    chen = Chen(3000, 2060)

    chen.entity("Fact_OHLCV_Daily", 1500, 380, weak=True)
    chen.entity("Fact_OHLCV_Hourly", 1500, 1680, weak=True)
    chen.entity("Dim_Asset", 660, 1030)
    chen.entity("Dim_Source", 1140, 1030)
    chen.entity("Dim_Date", 1860, 1030)
    chen.entity("ETL_Batch", 2400, 1030)
    chen.entity("Dim_Time", 2450, 1760)
    chen.entity("Fact_Live_Metric", 330, 400, weak=True)
    chen.entity("Fact_Forecast", 330, 1660, weak=True)
    chen.entity("DQ_Result", 2700, 330)

    for fact, suffix in (("Fact_OHLCV_Daily", "Daily"), ("Fact_OHLCV_Hourly", "Hourly")):
        chen.relationship(f"Asset_{suffix}", "Dim_Asset", fact, identifying=True)
        chen.relationship(f"Source_{suffix}", "Dim_Source", fact, identifying=True)
        chen.relationship(f"Date_{suffix}", "Dim_Date", fact, identifying=True)
        chen.relationship(f"Batch_{suffix}", "ETL_Batch", fact)
    chen.relationship("Time_Hourly", "Dim_Time", "Fact_OHLCV_Hourly", identifying=True)
    chen.relationship("Monitors", "Dim_Asset", "Fact_Live_Metric", identifying=True)
    chen.relationship("Predicts", "Dim_Asset", "Fact_Forecast", identifying=True)
    chen.relationship("Records", "ETL_Batch", "DQ_Result")

    measures = [
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume_base",
        "volume_quote",
        "trade_count",
        "loaded_at",
    ]
    chen.attributes("Fact_OHLCV_Daily", measures, spread(160, 20, 8), 420, 250)
    chen.attributes(
        "Fact_OHLCV_Hourly", ["open_time"] + measures, spread(195, 325, 9), 470, 250
    )
    chen.attributes(
        "Dim_Asset",
        ["*asset_key", "*symbol", "name", "category", "is_stablecoin", "created_at", "updated_at"],
        spread(135, 225, 7),
        270,
        300,
    )
    chen.attributes(
        "Dim_Source",
        ["*source_key", "*source_code", "source_name", "source_type", "source_url"],
        spread(-40, 40, 5),
        240,
        200,
    )
    chen.attributes(
        "Dim_Date",
        ["*date_key", "*full_date", "/day_of_month", "/day_of_week", "/day_name", "/is_weekend"],
        spread(135, 225, 6),
        235,
        195,
    )
    chen.attributes(
        "Dim_Date",
        ["/week_of_year", "/month", "/month_name", "/quarter", "/year", "/year_month"],
        spread(-58, 58, 6),
        225,
        300,
    )
    chen.attributes(
        "ETL_Batch",
        [
            "*batch_id",
            "pipeline",
            "source_code",
            "started_at",
            "finished_at",
            "status",
            "rows_extracted",
            "rows_loaded",
            "rows_rejected",
            "message",
        ],
        spread(88, 128, 3) + spread(40, -125, 7),
        300,
        330,
    )
    chen.attributes(
        "Dim_Time",
        ["*time_key", "/hour_label", "/day_part", "/trading_session"],
        spread(60, -60, 4),
        260,
        130,
    )
    chen.attributes(
        "Fact_Live_Metric",
        [
            "~window_start",
            "~window_end",
            "avg_price_usd",
            "price_volatility",
            "total_volume",
            "event_count",
            "updated_at",
        ],
        spread(0, 200, 7),
        240,
        260,
    )
    chen.attributes(
        "Fact_Forecast",
        ["~ts", "~model_name", "forecast_price_usd", "created_at"],
        spread(-10, -170, 4),
        230,
        230,
    )
    chen.attributes(
        "DQ_Result",
        [
            "*dq_result_id",
            "check_name",
            "target_table",
            "severity",
            "failed_rows",
            "passed",
            "details",
            "checked_at",
        ],
        spread(170, -40, 8),
        230,
        240,
    )

    chen.render("dw_eerd")


# ---------------------------------------------------------------------------
# Relational schema
# ---------------------------------------------------------------------------

HEADER_H, CELL_H = 22, 26
LANE_GAP = 9


@dataclass
class Table:
    name: str
    columns: list[str]
    keys: set[str]
    fill: str
    x: float = 0
    y: float = 0
    widths: list[float] = field(default_factory=list)
    lanes: int = 0

    def __post_init__(self) -> None:
        self.widths = [max(64, text_width(column, 11) + 18) for column in self.columns]

    @property
    def width(self) -> float:
        return sum(self.widths)

    @property
    def bottom(self) -> float:
        return self.y + HEADER_H + CELL_H

    def cell_center(self, column: str) -> float:
        index = self.columns.index(column)
        return self.x + sum(self.widths[:index]) + self.widths[index] / 2


TABLES = [
    Table(
        "dim_asset",
        ["asset_key", "symbol", "name", "category", "is_stablecoin", "created_at", "updated_at"],
        {"asset_key"},
        ENTITY_FILL,
    ),
    Table(
        "dim_date",
        [
            "date_key",
            "full_date",
            "day_of_month",
            "day_of_week",
            "day_name",
            "is_weekend",
            "week_of_year",
            "month",
            "month_name",
            "quarter",
            "year",
            "year_month",
        ],
        {"date_key"},
        ENTITY_FILL,
    ),
    Table("dim_time", ["time_key", "hour_label", "day_part", "trading_session"], {"time_key"}, ENTITY_FILL),
    Table(
        "dim_source",
        ["source_key", "source_code", "source_name", "source_type", "source_url"],
        {"source_key"},
        ENTITY_FILL,
    ),
    Table(
        "etl_batch",
        [
            "batch_id",
            "pipeline",
            "source_code",
            "started_at",
            "finished_at",
            "status",
            "rows_extracted",
            "rows_loaded",
            "rows_rejected",
            "message",
        ],
        {"batch_id"},
        META_FILL,
    ),
    Table(
        "dq_result",
        [
            "dq_result_id",
            "batch_id",
            "check_name",
            "target_table",
            "severity",
            "failed_rows",
            "passed",
            "details",
            "checked_at",
        ],
        {"dq_result_id"},
        META_FILL,
    ),
    Table(
        "fact_ohlcv_daily",
        [
            "asset_key",
            "date_key",
            "source_key",
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "volume_base",
            "volume_quote",
            "trade_count",
            "batch_id",
            "loaded_at",
        ],
        {"asset_key", "date_key", "source_key"},
        REL_FILL,
    ),
    Table(
        "fact_ohlcv_hourly",
        [
            "asset_key",
            "date_key",
            "time_key",
            "source_key",
            "open_time",
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "volume_base",
            "volume_quote",
            "trade_count",
            "batch_id",
            "loaded_at",
        ],
        {"asset_key", "date_key", "time_key", "source_key"},
        REL_FILL,
    ),
    Table(
        "fact_live_metric",
        [
            "symbol",
            "window_start",
            "window_end",
            "avg_price_usd",
            "price_volatility",
            "total_volume",
            "event_count",
            "updated_at",
        ],
        {"symbol", "window_start", "window_end"},
        REL_FILL,
    ),
    Table(
        "fact_forecast",
        ["symbol", "ts", "model_name", "forecast_price_usd", "created_at"],
        {"symbol", "ts", "model_name"},
        REL_FILL,
    ),
]

FOREIGN_KEYS = [
    ("fact_ohlcv_daily", "asset_key", "dim_asset", "asset_key"),
    ("fact_ohlcv_daily", "date_key", "dim_date", "date_key"),
    ("fact_ohlcv_daily", "source_key", "dim_source", "source_key"),
    ("fact_ohlcv_daily", "batch_id", "etl_batch", "batch_id"),
    ("fact_ohlcv_hourly", "asset_key", "dim_asset", "asset_key"),
    ("fact_ohlcv_hourly", "date_key", "dim_date", "date_key"),
    ("fact_ohlcv_hourly", "time_key", "dim_time", "time_key"),
    ("fact_ohlcv_hourly", "source_key", "dim_source", "source_key"),
    ("fact_ohlcv_hourly", "batch_id", "etl_batch", "batch_id"),
    ("fact_live_metric", "symbol", "dim_asset", "symbol"),
    ("fact_forecast", "symbol", "dim_asset", "symbol"),
    ("dq_result", "batch_id", "etl_batch", "batch_id"),
]

# Tables are stacked in one column so the diagram fits a portrait page; foreign
# key arrows run in channels along the left margin.
TABLE_ORDER = [
    "dim_asset",
    "dim_date",
    "dim_time",
    "dim_source",
    "fact_ohlcv_daily",
    "fact_ohlcv_hourly",
    "fact_live_metric",
    "fact_forecast",
    "etl_batch",
    "dq_result",
]


def build_relational() -> None:
    tables = {table.name: table for table in TABLES}
    for source, _, target, _ in FOREIGN_KEYS:
        tables[source].lanes += 1
        tables[target].lanes += 1

    margin = 40 + LANE_GAP * len(FOREIGN_KEYS)
    y = 40.0
    for name in TABLE_ORDER:
        table = tables[name]
        table.x, table.y = margin, y
        y = table.bottom + 34 + table.lanes * LANE_GAP
    height = y
    width = margin + max(table.width for table in tables.values()) + 40
    d = Drawing(width, height)

    for table in tables.values():
        d.svg.append(
            f'<rect x="{table.x:.1f}" y="{table.y:.1f}" width="{table.width:.1f}" '
            f'height="{HEADER_H}" fill="{table.fill}" stroke="#666" stroke-width="1"/>'
        )
        d.svg.append(
            svg_text(table.x + 6, table.y + HEADER_H / 2, table.name, anchor="start", weight="bold")
        )
        d.vertex(
            table.name,
            f"rounded=0;whiteSpace=wrap;html=1;align=left;spacingLeft=6;fontStyle=1;"
            f"fillColor={table.fill};strokeColor=#666666;",
            table.x,
            table.y,
            table.width,
            HEADER_H,
        )
        x = table.x
        for column, cell_width in zip(table.columns, table.widths):
            top = table.y + HEADER_H
            d.svg.append(
                f'<rect x="{x:.1f}" y="{top:.1f}" width="{cell_width:.1f}" height="{CELL_H}" '
                'fill="white" stroke="#666" stroke-width="1"/>'
            )
            center = x + cell_width / 2
            d.svg.append(svg_text(center, top + CELL_H / 2, column, size=11))
            is_key = column in table.keys
            if is_key:
                half = text_width(column, 11) * 0.86 / 2
                d.svg.append(
                    f'<line x1="{center - half:.1f}" y1="{top + CELL_H / 2 + 7:.1f}" '
                    f'x2="{center + half:.1f}" y2="{top + CELL_H / 2 + 7:.1f}" stroke="black"/>'
                )
            d.vertex(
                column,
                "rounded=0;whiteSpace=wrap;html=1;fontSize=11;strokeColor=#666666;"
                + ("fontStyle=4;" if is_key else ""),
                x,
                top,
                cell_width,
                CELL_H,
            )
            x += cell_width

    # Shorter spans get the channels nearest the tables to limit crossings.
    rows = {name: index for index, name in enumerate(TABLE_ORDER)}
    ordered = sorted(FOREIGN_KEYS, key=lambda fk: abs(rows[fk[0]] - rows[fk[2]]))
    used_lanes = {name: 0 for name in tables}
    for channel_index, (source_name, source_column, target_name, target_column) in enumerate(ordered):
        source, target = tables[source_name], tables[target_name]
        used_lanes[source_name] += 1
        used_lanes[target_name] += 1
        source_lane = source.bottom + 12 + (used_lanes[source_name] - 1) * LANE_GAP
        target_lane = target.bottom + 12 + (used_lanes[target_name] - 1) * LANE_GAP
        channel = margin - 16 - channel_index * LANE_GAP

        sx, tx = source.cell_center(source_column), target.cell_center(target_column)
        points = [
            (sx, source.bottom),
            (sx, source_lane),
            (channel, source_lane),
            (channel, target_lane),
            (tx, target_lane),
            (tx, target.bottom),
        ]
        d.svg.append(
            '<polyline points="'
            + " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
            + '" fill="none" stroke="black" stroke-width="1" marker-end="url(#arrow)"/>'
        )
        d.edge(
            "endArrow=block;endFill=1;html=1;rounded=0;edgeStyle=none;",
            points=points,
        )

    d.save("dw_relational", "Relational schema")


if __name__ == "__main__":
    build_eerd()
    build_relational()
    print(f"wrote diagrams to {OUT_DIR}")
