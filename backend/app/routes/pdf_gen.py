"""
pdf_gen.py — Server-side PDF generation for the pre-listing report.

Library : ReportLab 4.x (pure Python, no system deps).
Font    : Helvetica (built-in Type 1 — no font files needed).

Fix notes
---------
* All cell content is wrapped in Paragraph objects so long text wraps at
  column boundaries instead of overflowing the page.
* Colors match the on-screen report exactly (hex values pulled from
  ResultsStep.jsx / sectionHeadStyle calls).
"""

from __future__ import annotations

import io
from datetime import date
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
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
MARGIN     = 0.75 * inch
CONTENT_W  = PAGE_W - 2 * MARGIN   # 7.0 inches

# ── Typeface constants ────────────────────────────────────────────────────────

F   = "Helvetica"
FB  = "Helvetica-Bold"
FI  = "Helvetica-Oblique"
FBI = "Helvetica-BoldOblique"

# ── Color palette  (hex values from ResultsStep.jsx) ─────────────────────────
#
#  Required-to-sell section text : #7c2d12
#  Required floor reason text    : #92400e
#  Optional section text         : #14532d
#  Quick-refresh section text    : #065f46
#  Positive net / value lift     : #1a7f37
#  Negative net                  : #c00  → full form #cc0000
#  Muted body                    : #555555
#  Very muted / captions         : #888888
#  Caveat / footnote             : #999999
#  Value-lift capped accent      : #b45309

C_BLACK       = colors.HexColor("#000000")
C_RULE        = colors.HexColor("#cccccc")
C_WHITE       = colors.white

C_REQ         = colors.HexColor("#7c2d12")   # Required-to-sell heading
C_REQ_REASON  = colors.HexColor("#92400e")   # Floor reason text
C_OPT         = colors.HexColor("#14532d")   # Optional heading
C_REFRESH     = colors.HexColor("#065f46")   # Quick refresh heading
C_GREEN       = colors.HexColor("#1a7f37")   # Positive money / value return
C_RED         = colors.HexColor("#cc0000")   # Negative money
C_MUTED       = colors.HexColor("#555555")
C_GRAY        = colors.HexColor("#888888")
C_CAVEAT      = colors.HexColor("#999999")
C_CAPPED      = colors.HexColor("#b45309")   # Value-lift-capped accent

# ── Paragraph style factory ───────────────────────────────────────────────────

def _ps(name, **kw) -> ParagraphStyle:
    base = dict(fontName=F, fontSize=9, leading=13, textColor=C_BLACK, spaceAfter=0,
                spaceBefore=0)
    base.update(kw)
    return ParagraphStyle(name, **base)

# Document-level styles
S = {
    "tool":    _ps("tool",   fontName=F,  fontSize=8,  leading=10, textColor=C_MUTED, spaceAfter=2),
    "address": _ps("addr",   fontName=FB, fontSize=20, leading=24, spaceAfter=4),
    "summary": _ps("sum",    fontName=F,  fontSize=9,  leading=13),
    "custom":  _ps("cust",   fontName=FI, fontSize=8,  leading=11, textColor=C_MUTED),
    "sec":     _ps("sec",    fontName=FB, fontSize=12, leading=15, spaceBefore=14, spaceAfter=4),
    "subsec":  _ps("sub",    fontName=FB, fontSize=10, leading=13, spaceBefore=10, spaceAfter=3),
    "body":    _ps("body",   fontName=F,  fontSize=9,  leading=13, spaceAfter=2),
    "muted":   _ps("muted",  fontName=F,  fontSize=8,  leading=11, textColor=C_MUTED, spaceAfter=2),
    "caveat":  _ps("cav",    fontName=FI, fontSize=7.5, leading=10, textColor=C_CAVEAT, spaceAfter=2),
}

# Table-cell styles  (no spaceBefore/After — padding is handled by TableStyle)
CS = {
    # Text alignment × weight × colour
    "b":    _ps("cb",   fontName=FB, fontSize=8.5, leading=11),
    "n":    _ps("cn",   fontName=F,  fontSize=8.5, leading=11),
    "r":    _ps("cr",   fontName=F,  fontSize=8.5, leading=11, alignment=TA_RIGHT),
    "rb":   _ps("crb",  fontName=FB, fontSize=8.5, leading=11, alignment=TA_RIGHT),
    "sm":   _ps("csm",  fontName=F,  fontSize=7.5, leading=10),
    "mu":   _ps("cmu",  fontName=F,  fontSize=8.5, leading=11, textColor=C_MUTED),
    "rmu":  _ps("crmu", fontName=F,  fontSize=8.5, leading=11, textColor=C_MUTED, alignment=TA_RIGHT),
    # Semantic / coloured
    "req":  _ps("creq", fontName=FB, fontSize=8.5, leading=11, textColor=C_REQ),
    "rsn":  _ps("crsn", fontName=F,  fontSize=8.5, leading=11, textColor=C_REQ_REASON),
    "opt":  _ps("copt", fontName=FB, fontSize=8.5, leading=11, textColor=C_OPT),
    "grn":  _ps("cgrn", fontName=F,  fontSize=8.5, leading=11, textColor=C_GREEN,   alignment=TA_RIGHT),
    "grnb": _ps("cgb",  fontName=FB, fontSize=8.5, leading=11, textColor=C_GREEN,   alignment=TA_RIGHT),
    "red":  _ps("cred", fontName=F,  fontSize=8.5, leading=11, textColor=C_RED,     alignment=TA_RIGHT),
    "redb": _ps("crdb", fontName=FB, fontSize=8.5, leading=11, textColor=C_RED,     alignment=TA_RIGHT),
    "vret": _ps("cvr",  fontName=F,  fontSize=8.5, leading=11, textColor=C_GREEN),   # value return
    "gry":  _ps("cgry", fontName=F,  fontSize=8.5, leading=11, textColor=C_GRAY),
}

# ── Cell helpers ─────────────────────────────────────────────────────────────

def _p(text, style="n") -> Paragraph:
    """Wrap text in a Paragraph with the named CS style.  Handles None → '—'."""
    txt = str(text).strip() if text else "—"
    return Paragraph(txt, CS[style])

def _amt(value, bold=False) -> Paragraph:
    """Right-aligned amount: green if ≥ 0, red if < 0."""
    try:
        v = float(value)
        txt = f"${v:,.0f}"
        if v < 0:
            return Paragraph(txt, CS["redb" if bold else "red"])
        return Paragraph(txt, CS["grnb" if bold else "grn"])
    except (TypeError, ValueError):
        return _p("—", "r")

def _neutral_amt(value, bold=False) -> Paragraph:
    """Right-aligned black amount (for line-items that can be negative but aren't bad)."""
    try:
        v = float(value)
        txt = f"${v:,.0f}"
        return Paragraph(txt, CS["rb" if bold else "r"])
    except (TypeError, ValueError):
        return _p("—", "r")

# ── Financial table style ─────────────────────────────────────────────────────

def _tbl(n: int, bold_last=False) -> TableStyle:
    """
    Horizontal-rules-only style.  Right-alignment and colouring are carried
    by the Paragraph objects inside each cell, not by TableStyle.
    """
    cmds = [
        ("FONTNAME",      (0, 0), (-1, 0),   FB),
        ("FONTSIZE",      (0, 0), (-1, -1),  8.5),
        ("FONTNAME",      (0, 1), (-1, -1),  F),
        ("VALIGN",        (0, 0), (-1, -1),  "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1),  3),
        ("BOTTOMPADDING", (0, 0), (-1, -1),  3),
        ("LEFTPADDING",   (0, 0), (-1, -1),  5),
        ("RIGHTPADDING",  (0, 0), (-1, -1),  5),
        ("LINEBELOW",     (0, 0), (-1, 0),   0.75, C_BLACK),
        ("LINEBELOW",     (0, -1), (-1, -1), 0.75, C_BLACK),
        ("BACKGROUND",    (0, 0), (-1, -1),  C_WHITE),
        ("ROWBACKGROUNDS",(0, 0), (-1, -1),  [C_WHITE]),
    ]
    for r in range(1, n - 1):
        cmds.append(("LINEBELOW", (0, r), (-1, r), 0.25, C_RULE))
    if bold_last:
        cmds += [
            ("FONTNAME",  (0, -1), (-1, -1), FB),
            ("LINEABOVE", (0, -1), (-1, -1), 0.75, C_BLACK),
        ]
    return TableStyle(cmds)

# ── Currency helpers ──────────────────────────────────────────────────────────

def _fmt(n) -> str:
    try:    return f"${float(n):,.0f}"
    except: return "—"

def _fmt_range(lo, hi) -> str:
    if lo is None and hi is None: return "—"
    if lo is None:  return f"up to {_fmt(hi)}"
    if hi is None:  return f"{_fmt(lo)}+"
    return f"{_fmt(lo)} – {_fmt(hi)}"

def _cost_mid(item: dict) -> float:
    if item.get("better_value") == "replace":
        return float(item.get("cost_mid_replace") or 0)
    return float(item.get("cost_mid_repair") or item.get("cost_mid_replace") or 0)

def _cost_range(item: dict) -> str:
    if item.get("better_value") == "replace":
        return _fmt_range(item.get("replace_low"), item.get("replace_high"))
    return _fmt_range(item.get("repair_low"), item.get("repair_high"))

# ── Domain labels ─────────────────────────────────────────────────────────────

PLAN_LABELS = {"leaner": "Leaner", "recommended": "Recommended", "do_everything": "Do Everything"}
PLAN_DESCS  = {
    "leaner":        "Required-to-sell items only.",
    "recommended":   "Required + improvements that pay back ≥ 75% at sale.",
    "do_everything": "Every actionable item.",
}
PATH_LABELS = {
    "repair": "Repair", "replace": "Replace",
    "credit": "Buyer credit", "leave": "Leave as-is", "upgrade": "Refresh",
}

def _skip_reason(item: dict, plan_key: str) -> str:
    if item.get("better_value") == "leave":  return "Good condition — no action needed"
    if item.get("recent_replacement"):        return "Recently replaced — no action needed"
    if not item.get("condition_detected"):    return "No defect detected"
    if plan_key == "leaner":                  return "Leaner plan: required-to-sell items only"
    r = item.get("recoup_pct")
    if r is not None and r < 75:              return f"Below ROI threshold — {r:.0f}% returns at sale"
    return "Below ROI threshold for this plan"

def _recoup_cell(item: dict) -> Paragraph:
    label = item.get("effective_recoup_label")
    if not label:
        r = item.get("recoup_pct")
        label = f"{r:.0f}%" if r is not None else "—"
    if "enables sale" in label:
        return _p(label, "vret")   # green — same as screen
    return _p(label, "n")

# ── Repair plan splitter ──────────────────────────────────────────────────────

def _split(repair_table, floor_result, effective_ids):
    floor_ids  = set(i["component_id"] for i in (floor_result.get("items") or []))
    floor_ids.update(r["component_id"] for r in repair_table if r.get("in_floor"))
    floor_meta = {i["component_id"]: i for i in (floor_result.get("items") or [])}

    floor_items, disc, not_in = [], [], []
    for row in repair_table:
        sev = row.get("severity_detected")
        if (sev is None or sev == "none") and not row.get("in_floor") and row.get("better_value") != "upgrade":
            continue
        cid      = row["component_id"]
        in_floor = row.get("in_floor") or cid in floor_ids
        is_upg   = row.get("better_value") == "upgrade"
        if in_floor and not is_upg:
            floor_items.append({**row, "floor_reason": floor_meta.get(cid, {}).get("reason", "required")})
        elif cid in effective_ids:
            disc.append(row)
        elif row.get("better_value") != "leave":
            not_in.append(row)
    return floor_items, disc, not_in

# ── Per-page footer ───────────────────────────────────────────────────────────

def _footer(address: str):
    def draw(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(C_RULE)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, 0.55 * inch, PAGE_W - MARGIN, 0.55 * inch)
        canvas.setFont(F, 7.5)
        canvas.setFillColor(C_CAVEAT)
        canvas.drawString(MARGIN, 0.35 * inch, address or "Pre-Listing Decision Report")
        canvas.drawRightString(PAGE_W - MARGIN, 0.35 * inch, f"Page {doc.page}")
        canvas.restoreState()
    return draw

# ── Story-building helpers ────────────────────────────────────────────────────

def _section(title: str) -> list:
    return [
        Paragraph(title, S["sec"]),
        HRFlowable(width=CONTENT_W, thickness=0.75, color=C_BLACK, spaceAfter=8),
    ]

def _subsection(title: str, color=C_BLACK, note: str = "") -> list:
    out = [
        Paragraph(title, _ps("sh", fontName=FB, fontSize=10, leading=13,
                              spaceBefore=10, spaceAfter=2, textColor=color)),
        HRFlowable(width=CONTENT_W, thickness=0.5, color=color, spaceAfter=4),
    ]
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
    plan_non_floor       = set(plan.get("included_items") or []) - floor_ids
    effective_non_floor  = (set(custom_items) - floor_ids) if custom_items is not None else plan_non_floor
    effective_ids        = floor_ids | effective_non_floor

    is_customized = custom_items is not None or bool(custom_costs)
    display_net   = live_net if (is_customized and live_net is not None) else base_net

    floor_items, disc, not_in = _split(repair_table, floor_result, effective_ids)

    def eff_cost(item) -> str:
        cid = item["component_id"]
        if custom_costs and cid in custom_costs:
            return f"{_fmt(custom_costs[cid])}*"
        return _cost_range(item)

    plan_label = PLAN_LABELS.get(plan_key, plan_key)
    plan_desc  = PLAN_DESCS.get(plan_key, "")
    today_str  = date.today().strftime("%B %-d, %Y")

    # ── Document ──────────────────────────────────────────────────────────
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=MARGIN + 0.45 * inch,
        title=f"Pre-Listing Report — {address}",
        author="Pre-Listing Decision Tool",
    )
    fn    = _footer(address)
    story = []

    # ════════════════════════════════════════════════════════════════════════
    # Title block
    # ════════════════════════════════════════════════════════════════════════
    story.append(Paragraph("PRE-LISTING DECISION TOOL", S["tool"]))
    story.append(Paragraph(address, S["address"]))
    story.append(HRFlowable(width=CONTENT_W, thickness=1.5, color=C_BLACK, spaceAfter=6))
    story.append(Paragraph(
        f"Date: {today_str}  |  "
        f"As-is value (mid): {_fmt(val.get('mid'))}  |  "
        f"Plan: {plan_label}  |  "
        f"Est. net: {_fmt(display_net)}",
        S["summary"],
    ))
    if is_customized:
        story.append(Spacer(1, 2))
        story.append(Paragraph(
            "Net reflects custom adjustments (items toggled / quotes entered).", S["custom"]
        ))
    story.append(Spacer(1, 16))

    # ════════════════════════════════════════════════════════════════════════
    # Plans comparison
    # ════════════════════════════════════════════════════════════════════════
    story += _section("Plans — Estimated Net Proceeds")

    plan_rows = [[_p("Plan", "b"), _p("Description", "b"), _p("Est. Net Proceeds", "rb")]]
    for key, lbl in PLAN_LABELS.items():
        p = plans.get(key)
        if not p:
            continue
        nv  = p.get("net_proceeds", {}).get("net_proceeds")
        sel = key == plan_key
        plan_rows.append([
            _p(f"► {lbl}" if sel else lbl,  "b" if sel else "n"),
            _p(PLAN_DESCS.get(key, ""),      "n"),
            _amt(nv, bold=sel),
        ])

    plan_tbl = Table(plan_rows, colWidths=[1.4*inch, 3.7*inch, 1.9*inch], repeatRows=1)
    plan_tbl.setStyle(_tbl(len(plan_rows)))
    story.append(plan_tbl)
    story.append(Spacer(1, 4))
    story.append(Paragraph("► = currently selected plan.", S["muted"]))
    story.append(Spacer(1, 18))

    # ════════════════════════════════════════════════════════════════════════
    # As-Is Value
    # ════════════════════════════════════════════════════════════════════════
    story += _section("As-Is Value Estimate")

    conf_str = f"{val.get('confidence', 0) * 100:.0f}%" if val.get("confidence") else "—"
    cw = CONTENT_W / 4
    stat_tbl = Table(
        [[_p("Low","b"),  _p("Mid (used)","b"), _p("High","b"),  _p("Confidence","b")],
         [_p(_fmt(val.get("low")),"n"),
          _p(_fmt(val.get("mid")),"b"),    # mid in bold — the key figure
          _p(_fmt(val.get("high")),"n"),
          _p(conf_str,"n")]],
        colWidths=[cw]*4,
    )
    stat_tbl.setStyle(TableStyle([
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("FONTSIZE",      (0, 1), (-1, 1),  13),
        ("LINEBELOW",     (0, 0), (-1, 0),  0.75, C_BLACK),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("BACKGROUND",    (0, 0), (-1, -1), C_WHITE),
    ]))
    story.append(stat_tbl)

    if val.get("note"):
        story.append(Spacer(1, 4))
        story.append(Paragraph(val["note"], S["muted"]))

    comps = val.get("comp_detail") or []
    if comps:
        story.append(Spacer(1, 10))
        story += _subsection("Comparable Sales")
        c_data = [[_p("Address","b"), _p("Sale Price","rb"), _p("$/sqft","rb"),
                   _p("Weight","rb"), _p("Note","b")]]
        for c in comps:
            ppsf = c.get("actual_ppsf")
            c_data.append([
                _p(c.get("address","—"), "n"),
                _neutral_amt(c.get("price")),
                _p(f"${ppsf:.0f}" if ppsf else "—", "r"),
                _p(f"{c.get('weight',0)*100:.1f}%", "r"),
                _p(c.get("note","—"), "n"),
            ])
        c_tbl = Table(c_data, colWidths=[2.55*inch, 0.9*inch, 0.65*inch, 0.6*inch, 2.3*inch],
                      repeatRows=1)
        c_tbl.setStyle(_tbl(len(c_data)))
        story.append(c_tbl)

    story.append(Spacer(1, 18))

    # ════════════════════════════════════════════════════════════════════════
    # Repair Plan
    # ════════════════════════════════════════════════════════════════════════
    story += _section("Repair Plan")
    story.append(Paragraph(f"{plan_label} — {plan_desc}", S["muted"]))
    story.append(Spacer(1, 8))

    # ── Required to Sell ─────────────────────────────────────────────────
    if floor_items:
        n_req = len(floor_items)
        story += _subsection(
            f"Required to Sell — {n_req} item{'s' if n_req != 1 else ''}",
            color=C_REQ,
            note=(
                "These must be addressed before listing. Lenders require them fixed before "
                "approving a buyer's loan, or they are safety issues flagged during inspection. "
                "Included in every plan."
            ),
        )
        f_data = [[_p("Component","b"), _p("Reason Required","b"), _p("Action","b"),
                   _p("Cost","rb"),      _p("Condition","b"),       _p("Notes","b")]]
        for item in floor_items:
            f_data.append([
                _p(item.get("display_name","—"),     "b"),
                _p(item.get("floor_reason","required"), "rsn"),   # amber-700 text
                _p(PATH_LABELS.get(item.get("better_value",""), item.get("better_value") or "—"), "n"),
                _p(eff_cost(item), "r"),
                _p(item.get("condition_detected") or "—", "n"),
                _p(item.get("notes") or "—", "sm"),
            ])
        f_tbl = Table(f_data,
                      colWidths=[1.45*inch, 1.3*inch, 0.7*inch, 0.9*inch, 0.9*inch, 1.75*inch],
                      repeatRows=1)
        f_tbl.setStyle(_tbl(len(f_data)))
        story.append(f_tbl)
        cost_note = (
            f"Required-to-sell total: "
            f"{_fmt_range(floor_result.get('cost_low'), floor_result.get('cost_high'))}"
        )
        if floor_result.get("cost_mid"):
            cost_note += f"  (mid {_fmt(floor_result['cost_mid'])})"
        story.append(Spacer(1, 4))
        story.append(Paragraph(cost_note, S["muted"]))

    # ── Optional Improvements ─────────────────────────────────────────────
    if disc:
        n_disc = len(disc)
        story.append(Spacer(1, 10))
        story += _subsection(
            f"Optional Improvements — {n_disc} item{'s' if n_disc != 1 else ''} in this plan",
            color=C_OPT,
            note="Not required to sell. Included because the value return justifies the spend.",
        )
        d_data = [[_p("Component","b"), _p("Condition","b"), _p("Action","b"),
                   _p("Cost","rb"),     _p("Value Return","b"), _p("Notes","b")]]
        for item in disc:
            d_data.append([
                _p(item.get("display_name","—"), "b"),
                _p(item.get("condition_detected") or "—", "n"),
                _p(PATH_LABELS.get(item.get("better_value",""), item.get("better_value") or "—"), "n"),
                _p(eff_cost(item), "r"),
                _recoup_cell(item),
                _p(item.get("notes") or "—", "sm"),
            ])
        d_tbl = Table(d_data,
                      colWidths=[1.5*inch, 1.0*inch, 0.7*inch, 0.85*inch, 0.85*inch, 2.1*inch],
                      repeatRows=1)
        d_tbl.setStyle(_tbl(len(d_data)))
        story.append(d_tbl)

    if not floor_items and not disc:
        story.append(Paragraph(
            "No repair items found. Ensure photos have been tagged and the questionnaire submitted.",
            S["muted"],
        ))

    # ── Items Not in This Plan ────────────────────────────────────────────
    if not_in:
        story.append(Spacer(1, 10))
        story += _subsection(f"Items Not in This Plan — {len(not_in)}", color=C_MUTED)
        ni_data = [[_p("Component","b"), _p("Why Not Included","b"),
                    _p("Cost","rb"),     _p("Value Return","b")]]
        for item in not_in:
            ni_data.append([
                _p(item.get("display_name","—"), "n"),
                _p(_skip_reason(item, plan_key),  "gry"),   # muted gray — below threshold
                _p(_cost_range(item),              "r"),
                _recoup_cell(item),
            ])
        ni_tbl = Table(ni_data,
                       colWidths=[1.5*inch, 3.0*inch, 0.9*inch, 1.6*inch],
                       repeatRows=1)
        ni_tbl.setStyle(_tbl(len(ni_data)))
        story.append(ni_tbl)

    story.append(Spacer(1, 18))

    # ════════════════════════════════════════════════════════════════════════
    # Net Proceeds Breakdown
    # ════════════════════════════════════════════════════════════════════════
    story += _section("Estimated Net Proceeds")

    line_items = base_np.get("line_items") or []
    if line_items:
        np_data = [[_p("Item","b"), _p("Amount","rb")]]
        for i, li in enumerate(line_items):
            is_last = i == len(line_items) - 1
            label  = li.get("label", "")
            amount = li.get("amount")
            # Net proceeds row (last item) gets colour treatment
            if is_last:
                np_data.append([
                    _p(label, "rb"),
                    _amt(amount, bold=True),
                ])
            else:
                np_data.append([_p(label, "n"), _neutral_amt(amount)])

        if is_customized and live_net is not None and abs(live_net - base_net) > 0.5:
            delta = live_net - base_net
            np_data.append([_p("Custom plan adjustment (items / quotes)", "mu"), _neutral_amt(delta)])
            np_data.append([_p("Adjusted Net Proceeds", "rb"), _amt(live_net, bold=True)])
            np_tbl = Table(np_data, colWidths=[5.0*inch, 2.0*inch], repeatRows=1)
            ts = _tbl(len(np_data), bold_last=True)
            # Bold the base net line too (second-to-last before delta rows)
            base_row = len(line_items)
            ts.add("FONTNAME", (0, base_row), (-1, base_row), FB)
            np_tbl.setStyle(ts)
        else:
            np_tbl = Table(np_data, colWidths=[5.0*inch, 2.0*inch], repeatRows=1)
            np_tbl.setStyle(_tbl(len(np_data), bold_last=True))

        story.append(np_tbl)

        uses_custom_cost = bool(custom_costs) and any(
            item["component_id"] in custom_costs
            for item in floor_items + disc
        )
        if uses_custom_cost:
            story.append(Spacer(1, 4))
            story.append(Paragraph(
                "* Cost marked with asterisk reflects an entered quote. "
                "Line-item breakdown uses original plan costs; adjusted net incorporates entered quotes.",
                S["muted"],
            ))
    else:
        story.append(Paragraph(
            f"Estimated net proceeds ({plan_label}): {_fmt(display_net)}", S["body"]
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

    doc.build(story, onFirstPage=fn, onLaterPages=fn)
    buf.seek(0)
    return buf.read()


# ── Router ────────────────────────────────────────────────────────────────────

router = APIRouter()


class PDFRequest(BaseModel):
    plan_key: str = "recommended"
    custom_items: Optional[List[str]] = None
    custom_costs: Optional[Dict[str, float]] = None
    live_net: Optional[float] = None


@router.post("/{session_id}/pdf")
def get_pdf(session_id: str, req: PDFRequest):
    """Generate and return a server-side PDF report."""
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

    raw   = (session.get("address") or "report").replace(",", "").replace(" ", "-")
    fname = f"pldt-{raw[:40]}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
