"""
pdf_gen.py — Server-side PDF generation for the pre-listing report.

Library: ReportLab 4.x (pure Python, no system deps).
Font:    Helvetica (built-in Type 1).
"""

from __future__ import annotations

import io
from datetime import date
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ..db import get_db, TABLE

# ── Page geometry ─────────────────────────────────────────────────────────────

PAGE_W, PAGE_H = letter
MARGIN = 0.75 * inch
CONTENT_W = PAGE_W - 2 * MARGIN

# ── Typeface constants ────────────────────────────────────────────────────────

F  = "Helvetica"
FB = "Helvetica-Bold"
FI = "Helvetica-Oblique"

# ── Color palette ─────────────────────────────────────────────────────────────

C_BLACK  = colors.HexColor("#000000")
C_RULE   = colors.HexColor("#cccccc")
C_HEAVY  = colors.HexColor("#000000")
C_MUTED  = colors.HexColor("#555555")
C_WHITE  = colors.white

# ── Paragraph styles ──────────────────────────────────────────────────────────

def _ps(name, **kw):
    base = dict(fontName=F, fontSize=9, leading=13, textColor=C_BLACK, spaceAfter=0)
    base.update(kw)
    return ParagraphStyle(name, **base)

S = {
    "tool":     _ps("tool",    fontName=F,  fontSize=8,  leading=10, textColor=C_MUTED, spaceAfter=2),
    "address":  _ps("address", fontName=FB, fontSize=20, leading=24, spaceAfter=4),
    "summary":  _ps("summary", fontName=F,  fontSize=9,  leading=13, spaceAfter=0),
    "custom":   _ps("custom",  fontName=FI, fontSize=8,  leading=11, textColor=C_MUTED, spaceAfter=0),
    "sec":      _ps("sec",     fontName=FB, fontSize=12, leading=15, spaceBefore=14, spaceAfter=4),
    "subsec":   _ps("subsec",  fontName=FB, fontSize=10, leading=13, spaceBefore=10, spaceAfter=3),
    "body":     _ps("body",    fontName=F,  fontSize=9,  leading=13, spaceAfter=2),
    "muted":    _ps("muted",   fontName=F,  fontSize=8,  leading=11, textColor=C_MUTED, spaceAfter=2),
    "caveat":   _ps("caveat",  fontName=FI, fontSize=7.5, leading=10, textColor=C_MUTED, spaceAfter=2),
    "total":    _ps("total",   fontName=FB, fontSize=9,  leading=13, spaceAfter=0),
}

# ── Financial table style ─────────────────────────────────────────────────────

def _tblstyle(n_rows: int, right_cols=(), bold_last=False) -> TableStyle:
    """
    Light horizontal-rules-only table style.
    - Header row: bold, heavy bottom rule.
    - Body rows: light inter-row rules, no fills.
    - Last row: heavy bottom rule; bold if bold_last=True.
    """
    cmds = [
        # Typography
        ("FONTNAME",      (0, 0), (-1, 0),   FB),
        ("FONTSIZE",      (0, 0), (-1, 0),   8.5),
        ("FONTNAME",      (0, 1), (-1, -1),  F),
        ("FONTSIZE",      (0, 1), (-1, -1),  8.5),
        # Alignment
        ("VALIGN",        (0, 0), (-1, -1),  "TOP"),
        ("ALIGN",         (0, 0), (-1, -1),  "LEFT"),
        # Padding
        ("TOPPADDING",    (0, 0), (-1, -1),  3),
        ("BOTTOMPADDING", (0, 0), (-1, -1),  3),
        ("LEFTPADDING",   (0, 0), (-1, -1),  5),
        ("RIGHTPADDING",  (0, 0), (-1, -1),  5),
        # Rules
        ("LINEBELOW",     (0, 0), (-1, 0),   0.75, C_BLACK),
        ("LINEBELOW",     (0, -1), (-1, -1), 0.75, C_BLACK),
        # No fills
        ("BACKGROUND",    (0, 0), (-1, -1),  C_WHITE),
        ("ROWBACKGROUNDS",(0, 0), (-1, -1),  [C_WHITE]),
    ]
    # Light rules between body rows
    for r in range(1, n_rows - 1):
        cmds.append(("LINEBELOW", (0, r), (-1, r), 0.25, C_RULE))
    # Right-align numeric columns
    for col in right_cols:
        cmds.append(("ALIGN", (col, 0), (col, -1), "RIGHT"))
    if bold_last:
        cmds += [
            ("FONTNAME",  (0, -1), (-1, -1), FB),
            ("LINEABOVE", (0, -1), (-1, -1), 0.75, C_BLACK),
        ]
    return TableStyle(cmds)

# ── Currency helpers ──────────────────────────────────────────────────────────

def _fmt(n) -> str:
    try:
        v = float(n)
        return f"${v:,.0f}"
    except (TypeError, ValueError):
        return "—"

def _fmt_range(lo, hi) -> str:
    if lo is None and hi is None: return "—"
    if lo is None:  return f"up to {_fmt(hi)}"
    if hi is None:  return f"{_fmt(lo)}+"
    return f"{_fmt(lo)} – {_fmt(hi)}"

def _item_cost_mid(item: dict) -> float:
    if item.get("better_value") == "replace":
        return float(item.get("cost_mid_replace") or 0)
    return float(item.get("cost_mid_repair") or item.get("cost_mid_replace") or 0)

def _cost_range(item: dict) -> str:
    if item.get("better_value") == "replace":
        return _fmt_range(item.get("replace_low"), item.get("replace_high"))
    return _fmt_range(item.get("repair_low"), item.get("repair_high"))

# ── Domain labels ─────────────────────────────────────────────────────────────

PLAN_LABELS = {
    "leaner": "Leaner",
    "recommended": "Recommended",
    "do_everything": "Do Everything",
}
PLAN_DESCS = {
    "leaner": "Required-to-sell items only.",
    "recommended": "Required + improvements that pay back ≥ 75% at sale.",
    "do_everything": "Every actionable item.",
}
PATH_LABELS = {
    "repair": "Repair", "replace": "Replace",
    "credit": "Buyer credit", "leave": "Leave as-is", "upgrade": "Refresh",
}

def _skip_reason(item: dict, plan_key: str) -> str:
    if item.get("better_value") == "leave":     return "Good condition — no action needed"
    if item.get("recent_replacement"):           return "Recently replaced — no action needed"
    if not item.get("condition_detected"):       return "No defect detected"
    if plan_key == "leaner":                     return "Leaner plan: required-to-sell items only"
    r = item.get("recoup_pct")
    if r is not None and r < 75:                 return f"Below ROI threshold ({r:.0f}% returns at sale)"
    return "Below ROI threshold for this plan"

# ── Repair plan splitter (mirrors frontend buildRepairPlan) ───────────────────

def _split_repair(repair_table, floor_result, effective_ids):
    floor_ids = set(i["component_id"] for i in (floor_result.get("items") or []))
    floor_ids.update(r["component_id"] for r in repair_table if r.get("in_floor"))
    floor_meta = {i["component_id"]: i for i in (floor_result.get("items") or [])}

    floor_items, disc, not_in = [], [], []
    for row in repair_table:
        sev = row.get("severity_detected")
        if (sev is None or sev == "none") and not row.get("in_floor") and row.get("better_value") != "upgrade":
            continue
        cid = row["component_id"]
        in_floor  = row.get("in_floor") or cid in floor_ids
        is_upgrade = row.get("better_value") == "upgrade"
        if in_floor and not is_upgrade:
            floor_items.append({**row, "floor_reason": floor_meta.get(cid, {}).get("reason", "required")})
        elif cid in effective_ids:
            disc.append(row)
        elif row.get("better_value") != "leave":
            not_in.append(row)
    return floor_items, disc, not_in

# ── Per-page footer ───────────────────────────────────────────────────────────

def _page_fn(address: str):
    def draw(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(C_RULE)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, 0.55 * inch, PAGE_W - MARGIN, 0.55 * inch)
        canvas.setFont(F, 7.5)
        canvas.setFillColor(C_MUTED)
        canvas.drawString(MARGIN, 0.35 * inch, address or "Pre-Listing Decision Report")
        canvas.drawRightString(PAGE_W - MARGIN, 0.35 * inch, f"Page {doc.page}")
        canvas.restoreState()
    return draw

# ── Section heading helper ────────────────────────────────────────────────────

def _sec(title: str) -> list:
    return [
        Paragraph(title, S["sec"]),
        HRFlowable(width=CONTENT_W, thickness=0.75, color=C_BLACK, spaceAfter=8),
    ]

def _subsec(title: str, note: str = "") -> list:
    out = [Paragraph(title, S["subsec"])]
    if note:
        out.append(Paragraph(note, S["muted"]))
    return out

# ── PDF generation ────────────────────────────────────────────────────────────

def generate_pdf(
    session: dict,
    plan_key: str,
    custom_items: Optional[List[str]],
    custom_costs: Optional[Dict[str, float]],
    live_net: Optional[float],
) -> bytes:

    result          = session.get("compute_result") or {}
    address         = session.get("address") or "—"
    commission_rate = session.get("commission_rate") or 0.06
    val             = result.get("valuation") or {}
    plans           = result.get("plans") or {}
    floor_result    = result.get("floor") or {}
    repair_table    = result.get("repair_table") or []
    plan            = plans.get(plan_key) or {}
    base_np         = plan.get("net_proceeds") or {}
    base_net        = float(base_np.get("net_proceeds") or 0)

    # ── Effective item set ────────────────────────────────────────────────
    floor_ids = set(i["component_id"] for i in (floor_result.get("items") or []))
    floor_ids.update(r["component_id"] for r in repair_table if r.get("in_floor"))

    plan_non_floor = set(plan.get("included_items") or []) - floor_ids
    effective_non_floor = (set(custom_items) - floor_ids) if custom_items is not None else plan_non_floor
    effective_ids = floor_ids | effective_non_floor

    is_customized = custom_items is not None or bool(custom_costs)
    display_net   = live_net if (is_customized and live_net is not None) else base_net

    floor_items, disc, not_in = _split_repair(repair_table, floor_result, effective_ids)

    def eff_cost(item) -> str:
        cid = item["component_id"]
        if custom_costs and cid in custom_costs:
            return f"{_fmt(custom_costs[cid])}*"   # * = entered quote
        return _cost_range(item)

    plan_label  = PLAN_LABELS.get(plan_key, plan_key)
    plan_desc   = PLAN_DESCS.get(plan_key, "")
    today_str   = date.today().strftime("%B %-d, %Y")

    # ── Document setup ────────────────────────────────────────────────────
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN + 0.45 * inch,   # space for footer
        title=f"Pre-Listing Report — {address}",
        author="Pre-Listing Decision Tool",
    )
    fn   = _page_fn(address)
    story = []

    # ════════════════════════════════════════════════════════════════════════
    # Title block
    # ════════════════════════════════════════════════════════════════════════
    story.append(Paragraph("PRE-LISTING DECISION TOOL", S["tool"]))
    story.append(Paragraph(address, S["address"]))
    story.append(HRFlowable(width=CONTENT_W, thickness=1.5, color=C_BLACK, spaceAfter=6))
    story.append(Paragraph(
        f"Date: {today_str}  |  "
        f"As-is value (mid): {_fmt(val.get('mid'))}  |  "
        f"Plan: {plan_label}  |  "
        f"Est. net proceeds: {_fmt(display_net)}",
        S["summary"]
    ))
    if is_customized:
        story.append(Spacer(1, 2))
        story.append(Paragraph(
            "Net reflects your custom plan adjustments (items toggled / quotes entered).",
            S["custom"]
        ))
    story.append(Spacer(1, 16))

    # ════════════════════════════════════════════════════════════════════════
    # Plans — All Three
    # ════════════════════════════════════════════════════════════════════════
    story += _sec("Plans — Estimated Net Proceeds")
    plan_rows = [["Plan", "Description", "Est. Net Proceeds"]]
    for key, lbl in PLAN_LABELS.items():
        p = plans.get(key)
        if not p:
            continue
        net_val = p.get("net_proceeds", {}).get("net_proceeds")
        name_cell = f"► {lbl}" if key == plan_key else lbl  # mark selected plan
        plan_rows.append([name_cell, PLAN_DESCS.get(key, ""), _fmt(net_val)])
    plan_tbl = Table(plan_rows, colWidths=[1.4*inch, 3.8*inch, 1.8*inch], repeatRows=1)
    plan_tbl.setStyle(_tblstyle(len(plan_rows), right_cols=[2]))
    story.append(plan_tbl)
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "► = currently selected plan.",
        S["muted"]
    ))
    story.append(Spacer(1, 18))

    # ════════════════════════════════════════════════════════════════════════
    # As-Is Value Estimate
    # ════════════════════════════════════════════════════════════════════════
    story += _sec("As-Is Value Estimate")

    # Summary stat row
    conf_str = f"{val.get('confidence', 0) * 100:.0f}%" if val.get("confidence") else "—"
    cw = CONTENT_W / 4
    stat_tbl = Table(
        [["Low", "Mid (used)", "High", "Confidence"],
         [_fmt(val.get("low")), _fmt(val.get("mid")), _fmt(val.get("high")), conf_str]],
        colWidths=[cw] * 4,
    )
    stat_tbl.setStyle(TableStyle([
        ("FONTNAME",      (0, 0), (-1, 0),  FB),
        ("FONTSIZE",      (0, 0), (-1, 0),  8),
        ("FONTNAME",      (0, 1), (-1, 1),  FB),
        ("FONTSIZE",      (0, 1), (-1, 1),  13),
        ("LINEBELOW",     (0, 0), (-1, 0),  0.75, C_BLACK),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BACKGROUND",    (0, 0), (-1, -1), C_WHITE),
    ]))
    story.append(stat_tbl)

    if val.get("note"):
        story.append(Spacer(1, 4))
        story.append(Paragraph(val["note"], S["muted"]))

    # Comps
    comps = val.get("comp_detail") or []
    if comps:
        story.append(Spacer(1, 10))
        story += _subsec("Comparable Sales")
        comp_data = [["Address", "Sale Price", "$/sqft", "Weight", "Note"]]
        for c in comps:
            ppsf = c.get("actual_ppsf")
            comp_data.append([
                c.get("address", "—"),
                _fmt(c.get("price")),
                f"${ppsf:.0f}" if ppsf else "—",
                f"{c.get('weight', 0) * 100:.1f}%",
                c.get("note", "—"),
            ])
        comp_tbl = Table(
            comp_data,
            colWidths=[2.6*inch, 0.85*inch, 0.65*inch, 0.6*inch, 2.3*inch],
            repeatRows=1,
        )
        comp_tbl.setStyle(_tblstyle(len(comp_data), right_cols=[1, 2, 3]))
        story.append(comp_tbl)

    story.append(Spacer(1, 18))

    # ════════════════════════════════════════════════════════════════════════
    # Repair Plan
    # ════════════════════════════════════════════════════════════════════════
    story += _sec("Repair Plan")
    story.append(Paragraph(f"{plan_label} — {plan_desc}", S["muted"]))
    story.append(Spacer(1, 8))

    # ── Required to sell ──────────────────────────────────────────────────
    if floor_items:
        story += _subsec(
            f"Required to Sell — {len(floor_items)} item{'s' if len(floor_items) != 1 else ''}",
            "These must be addressed before listing. Lenders require them fixed before approving a "
            "buyer's loan, or they are safety issues flagged during inspection. In every plan.",
        )
        f_data = [["Component", "Reason Required", "Action", "Cost", "Condition", "Notes"]]
        for item in floor_items:
            f_data.append([
                item.get("display_name", "—"),
                item.get("floor_reason", "required"),
                PATH_LABELS.get(item.get("better_value", ""), item.get("better_value") or "—"),
                eff_cost(item),
                item.get("condition_detected") or "—",
                item.get("notes") or "—",
            ])
        f_tbl = Table(f_data,
                      colWidths=[1.45*inch, 1.3*inch, 0.7*inch, 0.9*inch, 0.9*inch, 1.75*inch],
                      repeatRows=1)
        f_tbl.setStyle(_tblstyle(len(f_data), right_cols=[3]))
        story.append(f_tbl)
        cost_note = (
            f"Required-to-sell total: "
            f"{_fmt_range(floor_result.get('cost_low'), floor_result.get('cost_high'))}"
        )
        if floor_result.get("cost_mid"):
            cost_note += f"  (mid {_fmt(floor_result['cost_mid'])})"
        story.append(Spacer(1, 4))
        story.append(Paragraph(cost_note, S["muted"]))

    # ── Optional improvements ─────────────────────────────────────────────
    if disc:
        story.append(Spacer(1, 10))
        story += _subsec(
            f"Optional Improvements — {len(disc)} item{'s' if len(disc) != 1 else ''} in this plan",
            "Not required to sell. Included because the value return justifies the spend.",
        )
        d_data = [["Component", "Condition", "Action", "Cost", "Value Return", "Notes"]]
        for item in disc:
            recoup = item.get("effective_recoup_label") or (
                f"{item['recoup_pct']:.0f}%" if item.get("recoup_pct") is not None else "—"
            )
            d_data.append([
                item.get("display_name", "—"),
                item.get("condition_detected") or "—",
                PATH_LABELS.get(item.get("better_value", ""), item.get("better_value") or "—"),
                eff_cost(item),
                recoup,
                item.get("notes") or "—",
            ])
        d_tbl = Table(d_data,
                      colWidths=[1.5*inch, 1.0*inch, 0.7*inch, 0.85*inch, 0.85*inch, 2.1*inch],
                      repeatRows=1)
        d_tbl.setStyle(_tblstyle(len(d_data), right_cols=[3]))
        story.append(d_tbl)

    if not floor_items and not disc:
        story.append(Paragraph(
            "No repair items found. Ensure photos have been tagged and the questionnaire submitted.",
            S["muted"],
        ))

    # ── Items not in this plan ────────────────────────────────────────────
    if not_in:
        story.append(Spacer(1, 10))
        story += _subsec(f"Items Not in This Plan — {len(not_in)}")
        ni_data = [["Component", "Why Not Included", "Cost", "Value Return"]]
        for item in not_in:
            recoup = item.get("effective_recoup_label") or (
                f"{item['recoup_pct']:.0f}%" if item.get("recoup_pct") is not None else "—"
            )
            ni_data.append([
                item.get("display_name", "—"),
                _skip_reason(item, plan_key),
                _cost_range(item),
                recoup,
            ])
        ni_tbl = Table(ni_data,
                       colWidths=[1.5*inch, 2.95*inch, 0.95*inch, 1.6*inch],
                       repeatRows=1)
        ni_tbl.setStyle(_tblstyle(len(ni_data), right_cols=[2]))
        story.append(ni_tbl)

    story.append(Spacer(1, 18))

    # ════════════════════════════════════════════════════════════════════════
    # Net Proceeds Breakdown
    # ════════════════════════════════════════════════════════════════════════
    story += _sec("Estimated Net Proceeds")

    line_items = base_np.get("line_items") or []
    if line_items:
        np_data = [["", "Amount"]]           # column headers (blank label col)
        np_data = [["Item", "Amount"]]
        for li in line_items:
            np_data.append([li.get("label", ""), _fmt(li.get("amount"))])

        if is_customized and live_net is not None and abs(live_net - base_net) > 0.5:
            delta = live_net - base_net
            np_data.append(["Custom plan adjustment (items / quotes)", _fmt(delta)])
            np_data.append(["Adjusted Net Proceeds", _fmt(live_net)])
            np_tbl = Table(np_data, colWidths=[5.0*inch, 2.0*inch], repeatRows=1)
            ts = _tblstyle(len(np_data), right_cols=[1], bold_last=True)
            # Also bold the original base net line
            base_net_row = len(line_items)   # 0=header, 1..n=items, last item = net line
            ts.add("FONTNAME", (0, base_net_row), (-1, base_net_row), FB)
            np_tbl.setStyle(ts)
        else:
            np_tbl = Table(np_data, colWidths=[5.0*inch, 2.0*inch], repeatRows=1)
            np_tbl.setStyle(_tblstyle(len(np_data), right_cols=[1], bold_last=True))
        story.append(np_tbl)
        if custom_costs and any(cid in custom_costs for item in floor_items + disc for cid in [item["component_id"]]):
            story.append(Spacer(1, 4))
            story.append(Paragraph(
                "* Cost marked with asterisk reflects an entered quote, not the library estimate. "
                "Breakdown line items are based on the original plan; adjusted net is live.",
                S["muted"],
            ))
    else:
        story.append(Paragraph(
            f"Estimated net proceeds ({plan_label}): {_fmt(display_net)}",
            S["body"],
        ))

    story.append(Spacer(1, 20))

    # ════════════════════════════════════════════════════════════════════════
    # Caveats
    # ════════════════════════════════════════════════════════════════════════
    story.append(HRFlowable(width=CONTENT_W, thickness=0.5, color=C_RULE, spaceAfter=6))
    for txt in [
        "This is a planning estimate, not an appraisal. All figures are based on available "
        "comparable sales and regional cost data. Confirm exact payoff balances with your "
        "lender before making decisions.",
        "Days-on-market is based on historical averages and seasonality. "
        "A hot or slow market will shift this significantly.",
        "Time-to-sell is listing to closing only. It does not include time to complete "
        "major construction — actual carrying costs will be higher while work is underway.",
        f"Commission rate used: {commission_rate * 100:.1f}%.",
    ]:
        story.append(Paragraph(txt, S["caveat"]))

    # ── Build ─────────────────────────────────────────────────────────────
    doc.build(story, onFirstPage=fn, onLaterPages=fn)
    buf.seek(0)
    return buf.read()


# ── FastAPI router ────────────────────────────────────────────────────────────

router = APIRouter()


class PDFRequest(BaseModel):
    plan_key: str = "recommended"
    custom_items: Optional[List[str]] = None
    custom_costs: Optional[Dict[str, float]] = None
    live_net: Optional[float] = None


@router.post("/{session_id}/pdf")
def get_pdf(session_id: str, req: PDFRequest):
    """Generate and return a server-side PDF report for the session."""
    db  = get_db()
    row = db.table(TABLE).select("*").eq("id", session_id).maybe_single().execute()
    if not row.data:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found.")

    session = row.data
    if not session.get("compute_result"):
        raise HTTPException(
            status_code=400,
            detail="Session not yet computed. Call GET /{session_id}/compute first.",
        )

    pdf_bytes = generate_pdf(
        session=session,
        plan_key=req.plan_key,
        custom_items=req.custom_items,
        custom_costs=req.custom_costs,
        live_net=req.live_net,
    )

    # Sanitise address for filename
    raw = (session.get("address") or "report").replace(",", "").replace(" ", "-")
    fname = f"pldt-{raw[:40]}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
