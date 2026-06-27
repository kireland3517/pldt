"""
pdf_gen_large.py — 18 pt large-print variant of the pre-listing report.

Layout rules
============
* 18 pt body text, proportionally larger headings.
* Tables with 4+ columns become stacked blocks: one item per block,
  label:value pairs stacked vertically. This is the only layout that
  works at 18 pt — wide tables can't fit enough columns at this size.
* Tables with 2–3 columns (plans comparison, net proceeds, as-is stats)
  stay as tables since they work fine at 18 pt.
* Same color palette and content as the normal report.
* Endpoint: POST /session/{session_id}/pdf/large
"""

from __future__ import annotations

import io
from datetime import date
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable, KeepTogether, Paragraph,
    SimpleDocTemplate, Spacer, Table, TableStyle,
)

from ..db import get_db, TABLE

# ── Page geometry ─────────────────────────────────────────────────────────────

PAGE_W, PAGE_H = letter
MARGIN    = 0.75 * inch
CONTENT_W = PAGE_W - 2 * MARGIN      # 7.0 inches
LABEL_W   = 1.9 * inch               # label col in stacked blocks
VALUE_W   = CONTENT_W - LABEL_W      # 5.1 inches

# ── Fonts ────────────────────────────────────────────────────────────────────

F   = "Helvetica"
FB  = "Helvetica-Bold"
FI  = "Helvetica-Oblique"
FBI = "Helvetica-BoldOblique"

# ── Colors (hex values from ResultsStep.jsx) ─────────────────────────────────

C_BLACK      = colors.HexColor("#000000")
C_WHITE      = colors.white
C_RULE       = colors.HexColor("#cccccc")
C_REQ        = colors.HexColor("#7c2d12")
C_REQ_REASON = colors.HexColor("#92400e")
C_OPT        = colors.HexColor("#14532d")
C_REFRESH    = colors.HexColor("#065f46")
C_GREEN      = colors.HexColor("#1a7f37")
C_RED        = colors.HexColor("#cc0000")
C_MUTED      = colors.HexColor("#555555")
C_GRAY       = colors.HexColor("#888888")
C_CAVEAT_CLR = colors.HexColor("#999999")

# ── Style helpers ─────────────────────────────────────────────────────────────

def _ps(name, size, lead, font=F, color=C_BLACK, align=TA_LEFT,
        before=0, after=0) -> ParagraphStyle:
    return ParagraphStyle(name, fontName=font, fontSize=size, leading=lead,
                          textColor=color, alignment=align,
                          spaceBefore=before, spaceAfter=after)

# Document-level styles
S_TOOL    = _ps("lp_tool",  9,  13, color=C_GRAY,     after=2)
S_ADDR    = _ps("lp_addr",  22, 28, font=FB,           after=6)
S_SUM     = _ps("lp_sum",   14, 20,                    after=4)
S_CUST    = _ps("lp_cust",  13, 18, font=FI, color=C_MUTED, after=4)
S_SEC     = _ps("lp_sec",   22, 28, font=FB, before=18, after=8)
S_BODY    = _ps("lp_body",  16, 22,                    after=3)
S_MUTED   = _ps("lp_muted", 13, 18, color=C_MUTED,    after=3)
S_CAVEAT  = _ps("lp_cav",   12, 17, font=FI, color=C_CAVEAT_CLR, after=3)

def _subhead_style(color=C_BLACK):
    return _ps(f"lp_sh_{id(color)}", 18, 24, font=FB,
               color=color, before=14, after=6)

# Stacked-block cell styles (18 pt)
def _cs(name, **kw):
    base = dict(fontName=F, fontSize=18, leading=24, textColor=C_BLACK)
    base.update(kw)
    return ParagraphStyle(name, **base)

CS = {
    "n":    _cs("lcn"),
    "b":    _cs("lcb",   fontName=FB),
    "r":    _cs("lcr",   alignment=TA_RIGHT),
    "rb":   _cs("lcrb",  fontName=FB, alignment=TA_RIGHT),
    "lbl":  _cs("lcl",   fontSize=14, leading=19, fontName=FB, textColor=C_MUTED),
    "sm":   _cs("lcsm",  fontSize=15, leading=20),
    "mu":   _cs("lcmu",  textColor=C_MUTED),
    "rsn":  _cs("lcrsn", textColor=C_REQ_REASON),
    "grn":  _cs("lcgrn", textColor=C_GREEN, alignment=TA_RIGHT),
    "grnb": _cs("lcgb",  fontName=FB, textColor=C_GREEN, alignment=TA_RIGHT),
    "red":  _cs("lcred", textColor=C_RED, alignment=TA_RIGHT),
    "redb": _cs("lcrdb", fontName=FB, textColor=C_RED, alignment=TA_RIGHT),
    "vret": _cs("lcvr",  textColor=C_GREEN),
    "gry":  _cs("lcgry", textColor=C_GRAY),
    "pend": _cs("lcpnd", textColor=C_REQ_REASON),
    "act":  _cs("lcact", textColor=C_OPT),
}

# Table-level styles (for 2–3 col tables that stay as tables)
def _tbl(n: int, bold_last=False) -> TableStyle:
    cmds = [
        ("FONTNAME",      (0, 0), (-1, 0),   FB),
        ("FONTSIZE",      (0, 0), (-1, -1),  18),
        ("FONTNAME",      (0, 1), (-1, -1),  F),
        ("VALIGN",        (0, 0), (-1, -1),  "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1),  6),
        ("BOTTOMPADDING", (0, 0), (-1, -1),  6),
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

# ── Paragraph cell shortcuts ──────────────────────────────────────────────────

def _p(text, style="n") -> Paragraph:
    return Paragraph(str(text).strip() if text else "—", CS[style])

def _amt(value, bold=False) -> Paragraph:
    try:
        v = float(value)
        txt = f"${v:,.0f}"
        return Paragraph(txt, CS["redb" if bold else "red"] if v < 0
                         else CS["grnb" if bold else "grn"])
    except (TypeError, ValueError):
        return _p("—", "r")

def _neutral_amt(value, bold=False) -> Paragraph:
    try:
        return Paragraph(f"${float(value):,.0f}", CS["rb" if bold else "r"])
    except (TypeError, ValueError):
        return _p("—", "r")

# ── Stacked-block helpers ─────────────────────────────────────────────────────

def _lv_table(rows: list) -> Table:
    """Two-column label:value table for stacked blocks."""
    data = []
    for lbl, val in rows:
        lbl_p = Paragraph(lbl, CS["lbl"])
        val_p = val if isinstance(val, Paragraph) else Paragraph(str(val), CS["n"])
        data.append([lbl_p, val_p])
    tbl = Table(data, colWidths=[LABEL_W, VALUE_W])
    tbl.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("BACKGROUND",    (0, 0), (-1, -1), C_WHITE),
    ]))
    return tbl

def _block(name: str, rows: list, name_style=None) -> list:
    """One stacked block: bold name, thin rule, label:value rows, spacer."""
    ns = name_style or _ps("lp_bn", 18, 24, font=FB)
    return [KeepTogether([
        Paragraph(name, ns),
        HRFlowable(width=CONTENT_W, thickness=0.5, color=C_RULE, spaceAfter=5),
        _lv_table(rows),
        Spacer(1, 16),
    ])]

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

def _recoup_text(item) -> str:
    lbl = item.get("effective_recoup_label")
    if lbl: return lbl
    r = item.get("recoup_pct")
    return f"{r:.0f}%" if r is not None else "—"

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

def _skip_reason(item, plan_key) -> str:
    if item.get("better_value") == "leave":  return "Good condition — no action needed"
    if item.get("recent_replacement"):        return "Recently replaced — no action needed"
    if not item.get("condition_detected"):    return "No defect detected"
    if plan_key == "leaner":                  return "Leaner plan: required-to-sell only"
    r = item.get("recoup_pct")
    if r is not None and r < 75:              return f"Below ROI threshold — {r:.0f}% at sale"
    return "Below ROI threshold for this plan"

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
        canvas.setFont(F, 9)
        canvas.setFillColor(C_CAVEAT_CLR)
        canvas.drawString(MARGIN, 0.35 * inch, address or "Pre-Listing Decision Report — Large Print")
        canvas.drawRightString(PAGE_W - MARGIN, 0.35 * inch, f"Page {doc.page}")
        canvas.restoreState()
    return draw

# ── Section helpers ───────────────────────────────────────────────────────────

def _section(title: str) -> list:
    return [
        Paragraph(title, S_SEC),
        HRFlowable(width=CONTENT_W, thickness=1.0, color=C_BLACK, spaceAfter=10),
    ]

def _subsection(title: str, color=C_BLACK, note: str = "") -> list:
    out = [
        Paragraph(title, _subhead_style(color)),
        HRFlowable(width=CONTENT_W, thickness=0.5, color=color, spaceAfter=6),
    ]
    if note:
        out.append(Paragraph(note, S_MUTED))
    return out

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
    active_listings = result.get("active_listings") or []
    sales_history   = result.get("sales_history_5yr") or []

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

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=MARGIN + 0.45 * inch,
        title=f"Pre-Listing Report (Large Print) — {address}",
        author="Pre-Listing Decision Tool",
    )
    fn    = _footer(address)
    story = []

    # ── Title ─────────────────────────────────────────────────────────────
    story.append(Paragraph("PRE-LISTING DECISION TOOL — LARGE PRINT", S_TOOL))
    story.append(Paragraph(address, S_ADDR))
    story.append(HRFlowable(width=CONTENT_W, thickness=1.5, color=C_BLACK, spaceAfter=8))
    story.append(Paragraph(
        f"Date: {today_str}  |  Plan: {plan_label}  |  "
        f"As-is mid: {_fmt(val.get('mid'))}  |  Est. net: {_fmt(display_net)}",
        S_SUM,
    ))
    if is_customized:
        story.append(Paragraph(
            "Net reflects custom adjustments (items toggled / quotes entered).", S_CUST
        ))
    story.append(Spacer(1, 20))

    # ════════════════════════════════════════════════════════════════════════
    # Plans — 3-col table (works fine at 18 pt)
    # ════════════════════════════════════════════════════════════════════════
    story += _section("Plans — Estimated Net Proceeds")
    plan_rows = [[_p("Plan","b"), _p("Description","b"), _p("Est. Net","rb")]]
    for key, lbl in PLAN_LABELS.items():
        p = plans.get(key)
        if not p: continue
        nv  = p.get("net_proceeds", {}).get("net_proceeds")
        sel = key == plan_key
        plan_rows.append([
            _p(f"► {lbl}" if sel else lbl, "b" if sel else "n"),
            _p(PLAN_DESCS.get(key, ""), "n"),
            _amt(nv, bold=sel),
        ])
    plan_tbl = Table(plan_rows, colWidths=[1.4*inch, 3.7*inch, 1.9*inch], repeatRows=1)
    plan_tbl.setStyle(_tbl(len(plan_rows)))
    story.append(plan_tbl)
    story.append(Spacer(1, 6))
    story.append(Paragraph("► = currently selected plan.", S_MUTED))
    story.append(Spacer(1, 22))

    # ════════════════════════════════════════════════════════════════════════
    # As-Is Value — stat row (2–3 cols, stays as table) + comps as blocks
    # ════════════════════════════════════════════════════════════════════════
    story += _section("As-Is Value Estimate")

    conf_str = f"{val.get('confidence', 0)*100:.0f}%" if val.get("confidence") else "—"
    cw = CONTENT_W / 4
    stat_tbl = Table(
        [[_p("Low","b"), _p("Mid (used)","b"), _p("High","b"), _p("Confidence","b")],
         [_p(_fmt(val.get("low")),"n"), _p(_fmt(val.get("mid")),"b"),
          _p(_fmt(val.get("high")),"n"), _p(conf_str,"n")]],
        colWidths=[cw]*4,
    )
    stat_tbl.setStyle(TableStyle([
        ("FONTSIZE",      (0, 0), (-1, -1), 18),
        ("FONTSIZE",      (0, 1), (-1, 1),  22),
        ("FONTNAME",      (0, 0), (-1, 0),  FB),
        ("LINEBELOW",     (0, 0), (-1, 0),  0.75, C_BLACK),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("BACKGROUND",    (0, 0), (-1, -1), C_WHITE),
    ]))
    story.append(stat_tbl)
    if val.get("note"):
        story.append(Spacer(1, 6))
        story.append(Paragraph(val["note"], S_MUTED))

    # Comps → stacked blocks
    comps = val.get("comp_detail") or []
    if comps:
        story.append(Spacer(1, 14))
        story += _subsection("Comparable Sales Used in Valuation")
        for c in comps:
            ppsf = c.get("actual_ppsf")
            story += _block(c.get("address","—"), [
                ("Sold",       _p(c.get("sold","—"))),
                ("Sale Price", _neutral_amt(c.get("price"))),
                ("$/sqft",     _p(f"${ppsf:.0f}" if ppsf else "—")),
                ("Weight",     _p(f"{c.get('weight',0)*100:.1f}%")),
                ("Note",       _p(c.get("note") or "—")),
            ])

    # Active listings → stacked blocks
    if active_listings:
        story.append(Spacer(1, 10))
        story += _subsection(
            "Active Listings — Current Competition",
            note="Homes currently on the market. Active = listed; Pending = under contract.",
        )
        for l in active_listings:
            sqft = l.get("sqft")
            ppsf = f"${round(l['list_price']/sqft)}" if sqft else "—"
            status_style = "pend" if l.get("status") == "Pending" else "act"
            story += _block(l.get("address","—"), [
                ("List Price", _neutral_amt(l.get("list_price"))),
                ("$/sqft",     _p(ppsf)),
                ("Sqft",       _p(f"{sqft:,}" if sqft else "—")),
                ("Beds/Baths", _p(f"{l.get('beds','?')}/{l.get('baths','?')}")),
                ("Days on Mkt",_p(str(l.get("dom","—")))),
                ("Status",     _p(l.get("status","—"), status_style)),
            ])

    # 5-year history → stacked blocks
    if sales_history:
        story.append(Spacer(1, 10))
        story += _subsection("5-Year Neighborhood Sales History — Context Only")
        story.append(Paragraph(
            "CONTEXT ONLY — not used in the valuation. The as-is estimate uses recent "
            "comparable sales only. This history shows how the neighborhood has trended.",
            _ps("lp_ctx", 14, 19, font=FBI, color=C_REQ_REASON, after=8),
        ))
        for s in sorted(sales_history, key=lambda x: x.get("sold",""), reverse=True):
            sqft  = s.get("sqft")
            ppsf_v = s.get("ppsf") or (round(s["price"]/sqft) if sqft else None)
            story += _block(f"{s.get('sold','—')}  —  {s.get('address','—')}", [
                ("Price",      _neutral_amt(s.get("price"))),
                ("$/sqft",     _p(f"${ppsf_v}" if ppsf_v else "—")),
                ("Sqft",       _p(f"{sqft:,}" if sqft else "—")),
                ("Beds/Baths", _p(f"{s.get('beds','?')}/{s.get('baths','?')}")),
            ])

    story.append(Spacer(1, 22))

    # ════════════════════════════════════════════════════════════════════════
    # Repair Plan — all sub-tables → stacked blocks
    # ════════════════════════════════════════════════════════════════════════
    story += _section("Repair Plan")
    story.append(Paragraph(f"{plan_label} — {plan_desc}", S_MUTED))
    story.append(Spacer(1, 12))

    # Required to Sell
    if floor_items:
        n = len(floor_items)
        story += _subsection(
            f"Required to Sell — {n} item{'s' if n!=1 else ''}",
            color=C_REQ,
            note="These must be addressed before listing. Lenders require them fixed or "
                 "they are safety issues flagged at inspection. Included in every plan.",
        )
        story.append(Spacer(1, 10))
        for item in floor_items:
            nm_style = _ps("lp_req_nm", 18, 24, font=FB, color=C_REQ)
            story += _block(item.get("display_name","—"), [
                ("Reason",       _p(item.get("floor_reason","required"), "rsn")),
                ("Condition",    _p(item.get("condition_detected") or "—")),
                ("Action",       _p(PATH_LABELS.get(item.get("better_value",""), item.get("better_value") or "—"))),
                ("Cost",         _p(eff_cost(item))),
                ("Notes",        _p(item.get("notes") or "—", "sm")),
            ], name_style=nm_style)

    # Optional Improvements
    if disc:
        n = len(disc)
        story.append(Spacer(1, 8))
        story += _subsection(
            f"Optional Improvements — {n} item{'s' if n!=1 else ''} in this plan",
            color=C_OPT,
            note="Not required to sell. Included because the value return justifies the spend.",
        )
        story.append(Spacer(1, 10))
        for item in disc:
            vret = _recoup_text(item)
            nm_style = _ps("lp_opt_nm", 18, 24, font=FB, color=C_OPT)
            story += _block(item.get("display_name","—"), [
                ("Condition",    _p(item.get("condition_detected") or "—")),
                ("Action",       _p(PATH_LABELS.get(item.get("better_value",""), item.get("better_value") or "—"))),
                ("Cost",         _p(eff_cost(item))),
                ("Value Return", _p(vret, "vret" if "enables" in vret else "n")),
                ("Notes",        _p(item.get("notes") or "—", "sm")),
            ], name_style=nm_style)

    if not floor_items and not disc:
        story.append(Paragraph(
            "No repair items found. Ensure photos are tagged and the questionnaire is submitted.",
            S_MUTED,
        ))

    # Items Not in This Plan
    if not_in:
        story.append(Spacer(1, 8))
        story += _subsection(f"Items Not in This Plan — {len(not_in)}", color=C_MUTED)
        story.append(Spacer(1, 10))
        for item in not_in:
            vret = _recoup_text(item)
            story += _block(item.get("display_name","—"), [
                ("Why excluded", _p(_skip_reason(item, plan_key), "gry")),
                ("Cost (est.)",  _p(_cost_range(item))),
                ("Value Return", _p(vret)),
            ])

    story.append(Spacer(1, 22))

    # ════════════════════════════════════════════════════════════════════════
    # Net Proceeds — 2-col table (works fine at 18 pt)
    # ════════════════════════════════════════════════════════════════════════
    story += _section("Estimated Net Proceeds")

    line_items = base_np.get("line_items") or []
    if line_items:
        np_data = [[_p("Item","b"), _p("Amount","rb")]]
        for i, li in enumerate(line_items):
            is_last = i == len(line_items) - 1
            lbl = li.get("label","")
            amt = li.get("amount")
            if is_last:
                np_data.append([_p(lbl,"rb"), _amt(amt, bold=True)])
            else:
                np_data.append([_p(lbl,"n"), _neutral_amt(amt)])

        if is_customized and live_net is not None and abs(live_net - base_net) > 0.5:
            delta = live_net - base_net
            np_data.append([_p("Custom plan adjustment","mu"), _neutral_amt(delta)])
            np_data.append([_p("Adjusted Net Proceeds","rb"), _amt(live_net, bold=True)])

        np_tbl = Table(np_data, colWidths=[5.0*inch, 2.0*inch], repeatRows=1)
        np_tbl.setStyle(_tbl(len(np_data), bold_last=True))
        story.append(np_tbl)
    else:
        story.append(Paragraph(
            f"Estimated net proceeds ({plan_label}): {_fmt(display_net)}", S_BODY
        ))

    story.append(Spacer(1, 24))

    # ── Caveats ───────────────────────────────────────────────────────────
    story.append(HRFlowable(width=CONTENT_W, thickness=0.5, color=C_RULE, spaceAfter=8))
    for txt in [
        "This is a planning estimate, not an appraisal. All figures are based on available "
        "comparable sales and regional cost data. Confirm exact payoff balances with your "
        "lender before making decisions.",
        "Days-on-market is based on historical averages and seasonality. "
        "A hot or slow market will shift this significantly.",
        f"Commission rate used: {commission_rate*100:.1f}%.",
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
    """Generate and return a large-print PDF report (18 pt, stacked blocks for wide tables)."""
    db  = get_db()
    row = db.table(TABLE).select("*").eq("id", session_id).maybe_single().execute()
    if not row.data:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found.")
    session = row.data
    if not session.get("compute_result"):
        raise HTTPException(status_code=400,
            detail="Session not yet computed. Call GET /{session_id}/compute first.")
    pdf_bytes = generate_large_pdf(
        session=session, plan_key=req.plan_key,
        custom_items=req.custom_items, custom_costs=req.custom_costs, live_net=req.live_net,
    )
    raw   = (session.get("address") or "report").replace(",","").replace(" ","-")
    fname = f"pldt-{raw[:40]}-large-print.pdf"
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})
