"""One-page PDF district risk brief (ReportLab)."""

from __future__ import annotations

import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from suraksha.agent.tools import district_context


def build_brief(district_id: str) -> bytes:
    """Render a one-page situation brief; returns PDF bytes."""
    ctx = district_context(district_id)
    if not ctx:
        raise ValueError(f"Unknown district: {district_id}")
    d = ctx["district"]

    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    sub_style = styles["Normal"]
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, textColor=colors.grey)

    story: list = []
    story.append(Paragraph("🛡️ Suraksha District Risk Brief", title_style))
    story.append(
        Paragraph(
            f"{d['name_en']} ({d['state']}) · generated {date.today().isoformat()} · "
            f"population ≈ {d['population']:,}",
            sub_style,
        )
    )
    story.append(Spacer(1, 6 * mm))

    # Latest risk table
    rows = [["Hazard", "Score", "Band", "Key drivers"]]
    band_color = {"low": colors.HexColor("#dcfce7"), "moderate": colors.HexColor("#fef9c3"), "high": colors.HexColor("#fee2e2")}
    latest = _latest_risks(ctx)
    for hazard, res in latest.items():
        if res is None:
            continue
        drivers = "; ".join(f"{k}={v}" for k, v in (res.get("detail") or {}).items()) or "-"
        rows.append(
            [
                hazard.title(),
                f"{res.get('score'):.0f}" if res.get("score") is not None else "-",
                res.get("band", "-"),
                Paragraph(drivers, small),
            ]
        )
    tbl = Table(rows, colWidths=[28 * mm, 18 * mm, 24 * mm, 95 * mm])
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f766e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]
    for i, hazard in enumerate([r[0].lower() for r in rows[1:]], start=1):
        band = latest.get(hazard, {}).get("band")
        if band in band_color:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), band_color[band]))
    tbl.setStyle(TableStyle(style_cmds))
    story.append(tbl)
    story.append(Spacer(1, 6 * mm))

    # 7-day outlook table
    story.append(Paragraph("<b>7-day outlook (forecast)</b>", sub_style))
    fc_rows = [["Day", "Tavg °C", "Tmax °C", "Rain mm"]]
    for fday in ctx.get("forecast", [])[:7]:
        fc_rows.append(
            [
                fday["day"],
                f"{fday['tavg']:.1f}" if fday.get("tavg") is not None else "-",
                f"{fday['tmax']:.1f}" if fday.get("tmax") is not None else "-",
                f"{fday['precipitation']:.1f}" if fday.get("precipitation") is not None else "-",
            ]
        )
    story.append(Table(fc_rows, colWidths=[40 * mm, 30 * mm, 30 * mm, 30 * mm]))
    story.append(Spacer(1, 4 * mm))

    # Anomalies
    if ctx.get("anomalies"):
        story.append(Paragraph("<b>Anomalies vs 30-year climatology</b>", sub_style))
        for e in ctx["anomalies"][:4]:
            story.append(Paragraph(f"• [{e['kind']}] {e['message']}", small))

    story.append(Spacer(1, 4 * mm))
    story.append(
        Paragraph(
            "Sources: Open-Meteo (ERA5 reanalysis + forecast), Open-Meteo Air Quality (CAMS), "
            "US-EPA AQI bands, NDMA playbooks. Flood risk is a rainfall-based proxy, not a "
            "hydrological simulation.",
            small,
        )
    )

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, topMargin=12 * mm, bottomMargin=12 * mm).build(story)
    return buf.getvalue()


def _latest_risks(ctx: dict) -> dict:
    """Most recent risk per hazard from the context risks map."""
    out: dict[str, dict | None] = {"heat": None, "flood": None, "air": None}
    for day in sorted(ctx.get("risks", {}).keys()):
        for hazard, res in ctx["risks"][day].items():
            if out.get(hazard) is None or (res.get("score") or 0) >= (out[hazard].get("score") or 0):
                out[hazard] = res
    return out

