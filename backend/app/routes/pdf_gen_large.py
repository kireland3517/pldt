"""
pdf_gen_large.py — Large-print PDF variant of the pre-listing report.

Design rules
============
* Body text 24 pt, item names 28 pt bold, section heads 32 pt bold.
  All text is genuinely large-print, not just the normal report scaled up.
* Multi-column tables are replaced by stacked blocks: one repair item per
  block, label:value pairs stacked vertically. Wide tables don't survive at
  this font size without truncation.
* Net-proceeds breakdown stays as a simple two-column list (label | amount)
  because it has only two columns and works fine at large size.
* Expect more pages. That is correct behavior for large print.
* Colors match the normal report (same hex palette from ResultsStep.jsx).
* Generous margins and line-spacing; one idea per visual area.
"""

from __future__ import annotations

import io
from datetime import date
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
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
    KeepTogether,
)

from ..db import get_db, TABLE

# ── Page geometry ─────────────────────────────────────────────────────────────

PAGE_W, PAGE_H = letter
MARGIN    = 1.0 * inch        # generous margins for large print
CONTENT_W = PAGE_W - 2 * MARGIN   # 6.5 inches

# ── Type scale ────────────────────────────────────────────────────────────────

F   = "Helvetica"
FB  = "Helvetica-Bold"
FI  = "Helvetica-Oblique"
FBI = "Helvetica-BoldOblique"

SZ_TITLE   = 36
SZ_SECTION = 32
SZ_ITEM    = 28
SZ_BODY    = 24
SZ_LABEL   = 22    # field labels within stacked blocks
SZ_MUTED   = 18
SZ_CAVEAT  = 16

LEAD_TITLE   = 44
LEAD_SECTION = 40
LEAD_ITEM    = 36
LEAD_BODY    = 32
LEAD_LABEL   = 28
LEAD_MUTED   = 24
LEAD_CAVEAT  = 21

# ── Color palette (hex values from ResultsStep.jsx) ───────────────────────────

C_BLACK      = colors.HexColor("#000000")
C_WHITE      = colors.white
C_RULE       = colors.HexColor("#cccccc")
C_REQ        = colors.HexColor("#7c2d12")   # Required-to-sell headings
C_REQ_REASON = colors.HexColor("#92400e")   # floor reason text
C_OPT        = colors.HexColor("#14532d")   # Optional improvements
C_REFRESH    = colors.HexColor("#065f46")   # Quick refresh
C_GREEN      = colors.HexColor("#1a7f37")   # positive net / value return
C_RED        = colors.HexColor("#cc0000")   # negative net
C_MUTED      = colors.HexColor("#555555")
C_GRAY       = colors.HexColor("#888888")
C_CAVEAT_CLR = colors.HexColor("#999999")

# ── Style factory ─────────────────────────────────────────────────────────────

def _ps(name, size, lead, font=F, color=C_BLACK, align=TA_LEFT,
        before=0, after=0) -> ParagraphStyle:
    return ParagraphStyle(
        name, fontName=font, fontSize=size, leading=lead,
        textColor=color, alignment=align,
        spaceBefore=before, spaceAfter=after,
    )

S_TOOL    = _ps("lp_tool",    10, 14, color=C_GRAY,     after=4)
S_ADDR    = _ps("lp_addr",    SZ_TITLE,   LEAD_TITLE,   font=FB, after=6)
S_SUMMARY = _ps("lp_summary", SZ_BODY,    LEAD_BODY,    after=4)
S_CUSTOM  = _ps("lp_custom",  SZ_MUTED,   LEAD_MUTED,   font=FI, color=C_MUTED, after=4)
S_SECTION = _ps("lp_section", SZ_SECTION, LEAD_SECTION, font=FB, before=20, after=8)
S_SUBHEAD = _ps("lp_subhead", SZ_ITEM,    LEAD_ITEM,    font=FB, before=18, after=6)

# Section color variants
def _colored_subhead(color) -> ParagraphStyle:
    return _ps("lp_sh_" + str(id(color)), SZ_ITEM, LEAD_ITEM, font=FB,
               color=color, before=18, after=6)

S_REQ_HEAD     = _colored_subhead(C_REQ)
S_OPT_HEAD     = _colored_subhead(C_OPT)
S_REFRESH_HEAD = _colored_subhead(C_REFRESH)
S_MUTED_HEAD   = _colored_subhead(C_MUTED)

S_ITEM_NAME  = _ps("lp_iname",  SZ_ITEM,    LEAD_ITEM,    font=FB, after=4)
S_BODY       = _ps("lp_body",   SZ_BODY,    LEAD_BODY,    after=4)
S_LABEL      = _ps("lp_label",  SZ_LABEL,   LEAD_LABEL,   font=FB, color=C_MUTED)
S_VALUE      = _ps("lp_value",  SZ_BODY,    LEAD_BODY)
S_VALUE_R    = _ps("lp_valr",   SZ_BODY,    LEAD_BODY,    align=TA_RIGHT)
S_MUTED      = _ps("lp_muted",  SZ_MUTED,   LEAD_MUTED,   color=C_MUTED, after=4)
S_CAVEAT     = _ps("lp_caveat", SZ_CAVEAT,  LEAD_CAVEAT,  font=FI, color=C_CAVEAT_CLR, after=4)
S_GREEN      = _ps("lp_green",  SZ_BODY,    LEAD_BODY,    color=C_GREEN)
S_GREEN_R    = _ps("lp_greenr", SZ_BODY,    LEAD_BODY,    color=C_GREEN, align=TA_RIGHT)
S_GREEN_RB   = _ps("lp_greenrb",SZ_BODY,    LEAD_BODY,    font=FB, color=C_GREEN, align=TA_RIGHT)
S_RED_R      = _ps("lp_redr",   SZ_BODY,    LEAD_BODY,    color=C_RED,   align=TA_RIGHT)
S_RED_RB     = _ps("lp_redrb",  SZ_BODY,    LEAD_BODY,    font=FB, color=C_RED,   align=TA_RIGHT)
S_NEUTRAL_R  = _ps("lp_neutr",  SZ_BODY,    LEAD_BODY,    align=TA_RIGHT)
S_NEUTRAL_RB = _ps("lp_neutrb", SZ_BODY,    LEAD_BODY,    font=FB, align=TA_RIGHT)
S_REASON     = _ps("lp_rsn",    SZ_BODY,    LEAD_BODY,    color=C_REQ_REASON)
S_VRET       = _ps("lp_vret",   SZ_BODY,    LEAD_BODY,    color=C_GREEN)
S_GRAY       = _ps("lp_gray",   SZ_BODY,    LEAD_BODY,    color=C_GRAY)

# ── Currency helpers ──────────────────────────────────────────────────────────

def _fmt(n) -> str:
    try:    return f"${float(n):,.0f}"
    except: return "—"

def _fmt_range(lo, hi) -> str:
    if lo is None and hi is None: return "—"
    if lo is None:  return f"up to {_fmt(hi)}"
    if hi is None:  return f"{_fmt(lo)}+"
    return f"{_fmt(lo)} – {_fmt(hi)}"

def _cost_range(item) -> str:
    if item.get("better_value") == "replace":
        return _fmt_range(item.get("replace_low"), item.get("replace_high"))
    return _fmt_range(item.get("repair_low"), item.get("repair_high"))

def _amt_para(value, bold=False) -> Paragraph:
    try:
        v = float(value)
        txt = f"${v:,.0f}"
        if v < 0:
            return Paragraph(txt, S_RED_RB if bold else S_RED_R)
        return Paragraph(txt, S_GREEN_RB if bold else S_GREEN_R)
    except (TypeError, ValueError):
        return Paragraph("—", S_NEUTRAL_R)

def _neutral_amt(value, bold=False) -> Paragraph:
    try:
        v = float(value)
        return Paragraph(f"${v:,.0f}", S_NEUTRAL_RB if bold else S_NEUTRAL_R)
    except:
        return Paragraph("—", S_NEUTRAL_R)

# ── Domain lookups ────────────────────────────────────────────────────────────

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

def _skip_reason(item, plan_key) -> str:
    if item.get("better_value") == "leave":  return "Good condition — no action needed"
    if item.get("recent_replacement"):        return "Recently replaced — no action needed"
    if not item.get("condition_detected"):    return "No defect detected"
    if plan_key == "leaner":                  return "Leaner plan: required-to-sell items only"
    r = item.get("recoup_pct")
    if r is not None and r < 75:              return f"Below ROI threshold ({r:.0f}% returns at sale)"
    return "Below ROI threshold for this plan"

def _recoup_text(item) -> str:
    lbl = item.get("effective_recoup_label")
    if lbl: return lbl
    r = item.get("recoup_pct")
    return f"{r:.0f}%" if r is not None else "—"

# ── Repair plan splitter (mirrors frontend logic) ─────────────────────────────

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
        canvas.line(MARGIN, 0.6 * inch, PAGE_W - MARGIN, 0.6 * inch)
        canvas.setFont(F, 12)
        canvas.setFillColor(C_CAVEAT_CLR)
        canvas.drawString(MARGIN, 0.38 * inch, address or "Pre-Listing Decision Report — Large Print")
        canvas.drawRightString(PAGE_W - MARGIN, 0.38 * inch, f"Page {doc.page}")
        canvas.restoreState()
    return draw

# ── Story helpers ─────────────────────────────────────────────────────────────

def _section(title: str) -> list:
    return [
        Paragraph(title, S_SECTION),
        HRFlowable(width=CONTENT_W, thickness=1.0, color=C_BLACK, spaceAfter=10),
    ]

def _lv_table(rows: list, label_w=1.7*inch) -> Table:
    """
    Two-column label:value table for stacked item blocks and net-proceeds list.
    rows = [(label_str, value_para_or_str), ...]
    """
    tbl_data = []
    for lbl, val in rows:
        lbl_para = Paragraph(lbl, S_LABEL)
        val_para = val if isinstance(val, Paragraph) else Paragraph(str(val), S_VALUE)
        tbl_data.append([lbl_para, val_para])

    tbl = Table(tbl_data, colWidths=[label_w, CONTENT_W - label_w])
    tbl.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("BACKGROUND",    (0, 0), (-1, -1), C_WHITE),
    ]))
    return tbl

def _item_block(name: str, rows: list, name_style=None) -> list:
    """
    One stacked block: bold item name, thin rule, label:value rows, spacer.
    Kept together so a block doesn't split across pages mid-item.
    """
    ns = name_style or S_ITEM_NAME
    block = [
        Paragraph(name, ns),
        HRFlowable(width=CONTENT_W, thickness=0.5, color=C_RULE, spaceAfter=6),
        _lv_table(rows),
        Spacer(1, 20),
    ]
    return [KeepTogether(block)]

# ── Main generator ────────────────────────────────────────────────────────────

def generate_large_pdf(
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

    # Effective item set
    floor_ids = set(i["component_id"] for i in (floor_result.get("items") or []))
    floor_ids.update(r["component_id"] for r in repair_table if r.get("in_floor"))
    plan_non_floor      = set(plan.get("included_items") or []) - floor_ids
    effective_non_floor = (set(custom_items) - floor_ids) if custom_items is not None else plan_non_floor
    effective_ids       = floor_ids | effective_non_floor

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

    # ── Document setup ────────────────────────────────────────────────────
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=MARGIN + 0.5 * inch,
        title=f"Pre-Listing Report (Large Print) — {address}",
        author="Pre-Listing Decision Tool",
    )
    fn    = _footer(address)
    story = []

    # ════════════════════════════════════════════════════════════════════════
    # Title block
    # ════════════════════════════════════════════════════════════════════════
    story.append(Paragraph("PRE-LISTING DECISION TOOL — LARGE PRINT", S_TOOL))
    story.append(Spacer(1, 4))
    story.append(Paragraph(address, S_ADDR))
    story.append(HRFlowable(width=CONTENT_W, thickness=1.5, color=C_BLACK, spaceAfter=10))

    story.append(_lv_table([
        ("Date",     Paragraph(today_str, S_VALUE)),
        ("Plan",     Paragraph(f"{plan_label} — {plan_desc}", S_VALUE)),
        ("As-Is Mid",Paragraph(_fmt(val.get("mid")), S_VALUE)),
        ("Est. Net", _amt_para(display_net, bold=True)),
    ], label_w=1.9*inch))

    if is_customized:
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            "Net reflects custom adjustments (items toggled / quotes entered).", S_CUSTOM
        ))
    story.append(Spacer(1, 28))

    # ════════════════════════════════════════════════════════════════════════
    # Plans comparison — stacked cards (no table)
    # ════════════════════════════════════════════════════════════════════════
    story += _section("Plans — Estimated Net Proceeds")

    for key, lbl in PLAN_LABELS.items():
        p  = plans.get(key)
        if not p: continue
        nv  = p.get("net_proceeds", {}).get("net_proceeds")
        sel = key == plan_key
        # card: plan name | net | description
        card_name = (f"► {lbl}" if sel else lbl)
        card_rows = [
            ("Plan",        Paragraph(card_name, S_VALUE)),
            ("Net Proceeds",_amt_para(nv, bold=True)),
            ("Description", Paragraph(PLAN_DESCS.get(key, ""), S_VALUE)),
        ]
        block = [
            HRFlowable(width=CONTENT_W, thickness=0.5,
                       color=C_BLACK if sel else C_RULE, spaceAfter=6),
            _lv_table(card_rows, label_w=2.1*inch),
            Spacer(1, 14),
        ]
        story += [KeepTogether(block)]

    story.append(Paragraph("► = currently selected plan.", S_MUTED))
    story.append(Spacer(1, 28))

    # ════════════════════════════════════════════════════════════════════════
    # As-Is Value
    # ════════════════════════════════════════════════════════════════════════
    story += _section("As-Is Value Estimate")

    conf_str = f"{val.get('confidence', 0) * 100:.0f}%" if val.get("confidence") else "—"
    story.append(_lv_table([
        ("Low",        Paragraph(_fmt(val.get("low")),  S_VALUE)),
        ("Mid (used)", Paragraph(_fmt(val.get("mid")),  _ps("lp_mid", SZ_BODY, LEAD_BODY, font=FB))),
        ("High",       Paragraph(_fmt(val.get("high")), S_VALUE)),
        ("Confidence", Paragraph(conf_str,              S_VALUE)),
    ], label_w=1.9*inch))

    if val.get("note"):
        story.append(Spacer(1, 8))
        story.append(Paragraph(val["note"], S_MUTED))

    comps = val.get("comp_detail") or []
    if comps:
        story.append(Spacer(1, 18))
        story.append(Paragraph("Comparable Sales", S_SUBHEAD))
        story.append(HRFlowable(width=CONTENT_W, thickness=0.5, color=C_BLACK, spaceAfter=10))
        for c in comps:
            ppsf = c.get("actual_ppsf")
            rows = [
                ("Address",    Paragraph(c.get("address", "—"), S_VALUE)),
                ("Sale Price", _neutral_amt(c.get("price"))),
                ("$/sqft",     Paragraph(f"${ppsf:.0f}" if ppsf else "—", S_VALUE)),
                ("Weight",     Paragraph(f"{c.get('weight', 0)*100:.1f}%", S_VALUE)),
                ("Note",       Paragraph(c.get("note", "—"), S_VALUE)),
            ]
            story += _item_block(c.get("address", "—"), rows)

    story.append(Spacer(1, 28))

    # ════════════════════════════════════════════════════════════════════════
    # Repair Plan
    # ════════════════════════════════════════════════════════════════════════
    story += _section("Repair Plan")
    story.append(Paragraph(f"{plan_label} — {plan_desc}", S_MUTED))
    story.append(Spacer(1, 12))

    # ── Required to Sell ─────────────────────────────────────────────────
    if floor_items:
        n = len(floor_items)
        story.append(Paragraph(
            f"Required to Sell — {n} item{'s' if n != 1 else ''}",
            S_REQ_HEAD,
        ))
        story.append(HRFlowable(width=CONTENT_W, thickness=0.75, color=C_REQ, spaceAfter=6))
        story.append(Paragraph(
            "These must be addressed before listing. Lenders require them fixed before "
            "approving a buyer's loan, or they are safety issues that will be flagged at "
            "inspection. Included in every plan.",
            S_MUTED,
        ))
        story.append(Spacer(1, 14))

        for item in floor_items:
            reason_para = Paragraph(item.get("floor_reason", "required"), S_REASON)
            rows = [
                ("Reason",       reason_para),
                ("Condition",    Paragraph(item.get("condition_detected") or "—", S_VALUE)),
                ("Action",       Paragraph(PATH_LABELS.get(item.get("better_value",""),
                                           item.get("better_value") or "—"), S_VALUE)),
                ("Cost",         Paragraph(eff_cost(item), S_VALUE)),
                ("Notes",        Paragraph(item.get("notes") or "—", S_VALUE)),
            ]
            story += _item_block(item.get("display_name", "—"), rows,
                                 name_style=_ps("lp_req_nm", SZ_ITEM, LEAD_ITEM,
                                                font=FB, color=C_REQ))

    # ── Optional Improvements ─────────────────────────────────────────────
    if disc:
        n = len(disc)
        story.append(Paragraph(
            f"Optional Improvements — {n} item{'s' if n != 1 else ''} in this plan",
            S_OPT_HEAD,
        ))
        story.append(HRFlowable(width=CONTENT_W, thickness=0.75, color=C_OPT, spaceAfter=6))
        story.append(Paragraph(
            "Not required to sell. Included because the value return justifies the spend.",
            S_MUTED,
        ))
        story.append(Spacer(1, 14))

        for item in disc:
            vret_txt  = _recoup_text(item)
            vret_para = Paragraph(vret_txt, S_VRET if "enables" in vret_txt else S_VALUE)
            rows = [
                ("Condition",    Paragraph(item.get("condition_detected") or "—", S_VALUE)),
                ("Action",       Paragraph(PATH_LABELS.get(item.get("better_value",""),
                                           item.get("better_value") or "—"), S_VALUE)),
                ("Cost",         Paragraph(eff_cost(item), S_VALUE)),
                ("Value Return", vret_para),
                ("Notes",        Paragraph(item.get("notes") or "—", S_VALUE)),
            ]
            story += _item_block(item.get("display_name", "—"), rows,
                                 name_style=_ps("lp_opt_nm", SZ_ITEM, LEAD_ITEM,
                                                font=FB, color=C_OPT))

    if not floor_items and not disc:
        story.append(Paragraph(
            "No repair items found. Ensure photos are tagged and the questionnaire is submitted.",
            S_MUTED,
        ))

    # ── Items Not in This Plan ────────────────────────────────────────────
    if not_in:
        story.append(Paragraph(
            f"Items Not in This Plan — {len(not_in)}",
            S_MUTED_HEAD,
        ))
        story.append(HRFlowable(width=CONTENT_W, thickness=0.75, color=C_MUTED, spaceAfter=6))
        story.append(Spacer(1, 10))

        for item in not_in:
            vret_txt  = _recoup_text(item)
            rows = [
                ("Why excluded",  Paragraph(_skip_reason(item, plan_key), S_GRAY)),
                ("Cost (est.)",   Paragraph(_cost_range(item), S_VALUE)),
                ("Value Return",  Paragraph(vret_txt, S_VALUE)),
            ]
            story += _item_block(item.get("display_name", "—"), rows)

    story.append(Spacer(1, 28))

    # ════════════════════════════════════════════════════════════════════════
    # Net Proceeds Breakdown — simple two-column list
    # ════════════════════════════════════════════════════════════════════════
    story += _section("Estimated Net Proceeds")

    line_items = base_np.get("line_items") or []
    if line_items:
        np_rows = []
        for i, li in enumerate(line_items):
            is_last = i == len(line_items) - 1
            lbl = li.get("label", "")
            amt = li.get("amount")
            if is_last:
                np_rows.append((lbl, _amt_para(amt, bold=True)))
            else:
                np_rows.append((lbl, _neutral_amt(amt)))

        if is_customized and live_net is not None and abs(live_net - base_net) > 0.5:
            delta = live_net - base_net
            np_rows.append(("Custom plan adjustment (items / quotes)", _neutral_amt(delta)))
            np_rows.append(("Adjusted Net Proceeds", _amt_para(live_net, bold=True)))

        # Two-col net proceeds table: label col 4.5in, amount col 2.0in
        np_data = []
        for lbl_txt, amt_para in np_rows:
            np_data.append([Paragraph(lbl_txt, S_BODY), amt_para])

        np_tbl = Table(np_data, colWidths=[4.5*inch, 2.0*inch])
        np_tbl.setStyle(TableStyle([
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("ALIGN",         (1, 0), (1,  -1), "RIGHT"),
            ("TOPPADDING",    (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING",   (0, 0), (-1, -1), 0),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
            ("LINEBELOW",     (0, -1), (-1, -1), 1.0, C_BLACK),
            ("LINEABOVE",     (0, -1), (-1, -1), 0.5, C_BLACK),
            ("BACKGROUND",    (0, 0), (-1, -1), C_WHITE),
            ("ROWBACKGROUNDS",(0, 0), (-1, -1), [C_WHITE]),
        ]))
        for r in range(len(np_data) - 1):
            np_tbl.setStyle(TableStyle([
                ("LINEBELOW", (0, r), (-1, r), 0.25, C_RULE),
            ]))
        story.append(np_tbl)

        if bool(custom_costs):
            story.append(Spacer(1, 8))
            story.append(Paragraph(
                "* Cost marked with asterisk reflects an entered quote.",
                S_MUTED,
            ))
    else:
        story.append(Paragraph(
            f"Estimated net proceeds ({plan_label}): {_fmt(display_net)}", S_BODY
        ))

    story.append(Spacer(1, 28))

    # ════════════════════════════════════════════════════════════════════════
    # Caveats
    # ════════════════════════════════════════════════════════════════════════
    story.append(HRFlowable(width=CONTENT_W, thickness=0.5, color=C_RULE, spaceAfter=8))
    for txt in [
        "This is a planning estimate, not an appraisal. All figures are based on "
        "available comparable sales and regional cost data. Confirm exact payoff "
        "balances with your lender before making decisions.",
        "Days-on-market is based on historical averages and seasonality. A hot or "
        "slow market will shift this significantly.",
        f"Commission rate used: {commission_rate * 100:.1f}%.",
    ]:
        story.append(Paragraph(txt, S_CAVEAT))

    doc.build(story, onFirstPage=fn, onLaterPages=fn)
    buf.seek(0)
    return buf.read()


# ── Router ────────────────────────────────────────────────────────────────────

router = APIRouter()


class LargePDFRequest(BaseModel):
    plan_key: str = "recommended"
    custom_items: Optional[List[str]] = None
    custom_costs: Optional[Dict[str, float]] = None
    live_net: Optional[float] = None


@router.post("/{session_id}/pdf/large")
def get_large_pdf(session_id: str, req: LargePDFRequest):
    """Generate and return a large-print PDF report."""
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

    pdf_bytes = generate_large_pdf(
        session=session,
        plan_key=req.plan_key,
        custom_items=req.custom_items,
        custom_costs=req.custom_costs,
        live_net=req.live_net,
    )

    raw   = (session.get("address") or "report").replace(",", "").replace(" ", "-")
    fname = f"pldt-{raw[:40]}-large-print.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
