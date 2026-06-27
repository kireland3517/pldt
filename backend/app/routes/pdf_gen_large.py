"""
pdf_gen_large.py — 18 pt large-print variant of the pre-listing report.

Layout is the same financial-table structure as the normal report.
Changes from the standard PDF:
  * Body / cell text: 18 pt (vs 8.5 pt)
  * Headings proportionally larger (section 24 pt, sub-section 20 pt)
  * Leading ~1.45× font size throughout
  * Cell padding 6 pt top/bottom (vs 3 pt)
  * Notes column in repair tables widened to give wrapped text more room
  * All cell content wrapped in Paragraph objects — wraps at col boundary,
    never overflows
  * Same color palette as normal report
  * Same page size and margins (0.75 in) — more pages, that's expected
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
)

from ..db import get_db, TABLE

# ── Page geometry ─────────────────────────────────────────────────────────────

PAGE_W, PAGE_H = letter
MARGIN    = 0.75 * inch
CONTENT_W = PAGE_W - 2 * MARGIN      # 7.0 inches

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

# ── Document-level paragraph styles ──────────────────────────────────────────

def _ps(name, **kw) -> ParagraphStyle:
    base = dict(fontName=F, fontSize=12, leading=17, textColor=C_BLACK,
                spaceBefore=0, spaceAfter=0)
    base.update(kw)
    return ParagraphStyle(name, **base)

S = {
    "tool":    _ps("lp_tool",   fontSize=9,  leading=13, textColor=C_GRAY,     spaceAfter=2),
    "address": _ps("lp_addr",   fontSize=24, leading=30, fontName=FB,           spaceAfter=6),
    "summary": _ps("lp_sum",    fontSize=14, leading=20),
    "custom":  _ps("lp_cust",   fontSize=13, leading=18, fontName=FI, textColor=C_MUTED, spaceAfter=2),
    "sec":     _ps("lp_sec",    fontSize=24, leading=30, fontName=FB, spaceBefore=18, spaceAfter=6),
    "subsec":  _ps("lp_sub",    fontSize=20, leading=26, fontName=FB, spaceBefore=14, spaceAfter=4),
    "body":    _ps("lp_body",   fontSize=16, leading=22, spaceAfter=3),
    "muted":   _ps("lp_muted",  fontSize=14, leading=20, textColor=C_MUTED,    spaceAfter=3),
    "caveat":  _ps("lp_cav",    fontSize=13, leading=18, fontName=FI, textColor=C_CAVEAT_CLR, spaceAfter=3),
}

# ── Table-cell paragraph styles (18 pt body) ──────────────────────────────────

def _cs(name, **kw) -> ParagraphStyle:
    base = dict(fontName=F, fontSize=18, leading=24, textColor=C_BLACK)
    base.update(kw)
    return ParagraphStyle(name, **base)

CS = {
    "n":    _cs("lcn"),
    "b":    _cs("lcb",   fontName=FB),
    "r":    _cs("lcr",   alignment=TA_RIGHT),
    "rb":   _cs("lcrb",  fontName=FB, alignment=TA_RIGHT),
    "sm":   _cs("lcsm",  fontSize=15, leading=20),          # notes column
    "mu":   _cs("lcmu",  textColor=C_MUTED),
    "rmu":  _cs("lcrmu", textColor=C_MUTED, alignment=TA_RIGHT),
    "req":  _cs("lcreq", fontName=FB, textColor=C_REQ),
    "rsn":  _cs("lcrsn", textColor=C_REQ_REASON),
    "opt":  _cs("lcopt", fontName=FB, textColor=C_OPT),
    "grn":  _cs("lcgrn", textColor=C_GREEN,  alignment=TA_RIGHT),
    "grnb": _cs("lcgb",  fontName=FB, textColor=C_GREEN, alignment=TA_RIGHT),
    "red":  _cs("lcred", textColor=C_RED,    alignment=TA_RIGHT),
    "redb": _cs("lcrdb", fontName=FB, textColor=C_RED,   alignment=TA_RIGHT),
    "vret": _cs("lcvr",  textColor=C_GREEN),
    "gry":  _cs("lcgry", textColor=C_GRAY),
}

# ── Cell helpers ──────────────────────────────────────────────────────────────

def _p(text, style="n") -> Paragraph:
    txt = str(text).strip() if text else "—"
    return Paragraph(txt, CS[style])

def _amt(value, bold=False) -> Paragraph:
    try:
        v   = float(value)
        txt = f"${v:,.0f}"
        return Paragraph(txt, CS["redb" if bold else "red"] if v < 0
                         else CS["grnb" if bold else "grn"])
    except (TypeError, ValueError):
        return _p("—", "r")

def _neutral_amt(value, bold=False) -> Paragraph:
    try:
        v = float(value)
        return Paragraph(f"${v:,.0f}", CS["rb" if bold else "r"])
    except (TypeError, ValueError):
        return _p("—", "r")

# ── Table style ───────────────────────────────────────────────────────────────

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

def _recoup_cell(item) -> Paragraph:
    label = item.get("effective_recoup_label")
    if not label:
        r = item.get("recoup_pct")
        label = f"{r:.0f}%" if r is not None else "—"
    return _p(label, "vret" if "enables sale" in label else "n")

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
    if r is not None and r < 75:              return f"Below ROI threshold — {r:.0f}% returns at sale"
    return "Below ROI threshold for this plan"

# ── Repair-plan splitter ──────────────────────────────────────────────────────

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
        canvas.drawString(MARGIN, 0.35 * inch, address or "Pre-Listing Decision Report")
        canvas.drawRightString(PAGE_W - MARGIN, 0.35 * inch, f"Page {doc.page}")
        canvas.restoreState()
    return draw

# ── Story helpers ─────────────────────────────────────────────────────────────

def _section(title: str) -> list:
    return [
        Paragraph(title, S["sec"]),
        HRFlowable(width=CONTENT_W, thickness=0.75, color=C_BLACK, spaceAfter=10),
    ]

def _subsection(title: str, color=C_BLACK, note: str = "") -> list:
    out = [
        Paragraph(title, _ps("lp_sh_dyn", fontSize=20, leading=26,
                              fontName=FB, spaceBefore=14, spaceAfter=4,
                              textColor=color)),
        HRFlowable(width=CONTENT_W, thickness=0.5, color=color, spaceAfter=6),
    ]
    if note:
        out.append(Paragraph(note, S["muted"]))
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

    # ════════════════════════════════════════════════════════════════════════
    # Title block
    # ════════════════════════════════════════════════════════════════════════
    story.append(Paragraph("PRE-LISTING DECISION TOOL — LARGE PRINT", S["tool"]))
    story.append(Paragraph(address, S["address"]))
    story.append(HRFlowable(width=CONTENT_W, thickness=1.5, color=C_BLACK, spaceAfter=8))
    story.append(Paragraph(
        f"Date: {today_str}  |  "
        f"As-is value (mid): {_fmt(val.get('mid'))}  |  "
        f"Plan: {plan_label}  |  "
        f"Est. net: {_fmt(display_net)}",
        S["summary"],
    ))
    if is_customized:
        story.append(Spacer(1, 4))
        story.append(Paragraph(
            "Net reflects custom adjustments (items toggled / quotes entered).", S["custom"]
        ))
    story.append(Spacer(1, 20))

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
            _p(f"► {lbl}" if sel else lbl, "b" if sel else "n"),
            _p(PLAN_DESCS.get(key, ""), "n"),
            _amt(nv, bold=sel),
        ])

    plan_tbl = Table(plan_rows, colWidths=[1.3*inch, 3.8*inch, 1.9*inch], repeatRows=1)
    plan_tbl.setStyle(_tbl(len(plan_rows)))
    story.append(plan_tbl)
    story.append(Spacer(1, 6))
    story.append(Paragraph("► = currently selected plan.", S["muted"]))
    story.append(Spacer(1, 22))

    # ════════════════════════════════════════════════════════════════════════
    # As-Is Value
    # ════════════════════════════════════════════════════════════════════════
    story += _section("As-Is Value Estimate")

    conf_str = f"{val.get('confidence', 0) * 100:.0f}%" if val.get("confidence") else "—"
    cw = CONTENT_W / 4
    stat_tbl = Table(
        [[_p("Low","b"), _p("Mid (used)","b"), _p("High","b"), _p("Confidence","b")],
         [_p(_fmt(val.get("low")),"n"),
          _p(_fmt(val.get("mid")),"b"),
          _p(_fmt(val.get("high")),"n"),
          _p(conf_str,"n")]],
        colWidths=[cw]*4,
    )
    stat_tbl.setStyle(TableStyle([
        ("FONTSIZE",      (0, 0), (-1, -1), 20),
        ("FONTSIZE",      (0, 1), (-1, 1),  26),
        ("LINEBELOW",     (0, 0), (-1, 0),  0.75, C_BLACK),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("BACKGROUND",    (0, 0), (-1, -1), C_WHITE),
    ]))
    story.append(stat_tbl)

    if val.get("note"):
        story.append(Spacer(1, 6))
        story.append(Paragraph(val["note"], S["muted"]))

    comps = val.get("comp_detail") or []
    if comps:
        story.append(Spacer(1, 14))
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
                _p(c.get("note","—"), "sm"),
            ])
        c_tbl = Table(c_data, colWidths=[2.3*inch, 1.0*inch, 0.7*inch, 0.7*inch, 2.3*inch],
                      repeatRows=1)
        c_tbl.setStyle(_tbl(len(c_data)))
        story.append(c_tbl)

    story.append(Spacer(1, 22))

    # ════════════════════════════════════════════════════════════════════════
    # Repair Plan
    # ════════════════════════════════════════════════════════════════════════
    story += _section("Repair Plan")
    story.append(Paragraph(f"{plan_label} — {plan_desc}", S["muted"]))
    story.append(Spacer(1, 10))

    # ── Required to Sell ─────────────────────────────────────────────────
    # Column widths at 18pt: give notes more room, tighten action col.
    # [Component, Reason, Action, Cost, Condition, Notes] = 7.0 in
    F_COLS = [1.35*inch, 1.25*inch, 0.65*inch, 0.9*inch, 0.9*inch, 1.95*inch]

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
                   _p("Cost","rb"),     _p("Condition","b"),       _p("Notes","b")]]
        for item in floor_items:
            f_data.append([
                _p(item.get("display_name","—"),     "b"),
                _p(item.get("floor_reason","required"), "rsn"),
                _p(PATH_LABELS.get(item.get("better_value",""), item.get("better_value") or "—"), "n"),
                _p(eff_cost(item), "r"),
                _p(item.get("condition_detected") or "—", "n"),
                _p(item.get("notes") or "—", "sm"),
            ])
        f_tbl = Table(f_data, colWidths=F_COLS, repeatRows=1)
        f_tbl.setStyle(_tbl(len(f_data)))
        story.append(f_tbl)
        cost_note = (
            f"Required-to-sell total: "
            f"{_fmt_range(floor_result.get('cost_low'), floor_result.get('cost_high'))}"
        )
        if floor_result.get("cost_mid"):
            cost_note += f"  (mid {_fmt(floor_result['cost_mid'])})"
        story.append(Spacer(1, 6))
        story.append(Paragraph(cost_note, S["muted"]))

    # ── Optional Improvements ─────────────────────────────────────────────
    # [Component, Condition, Action, Cost, Value Return, Notes] = 7.0 in
    D_COLS = [1.4*inch, 1.05*inch, 0.65*inch, 0.85*inch, 0.85*inch, 2.2*inch]

    if disc:
        n_disc = len(disc)
        story.append(Spacer(1, 14))
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
        d_tbl = Table(d_data, colWidths=D_COLS, repeatRows=1)
        d_tbl.setStyle(_tbl(len(d_data)))
        story.append(d_tbl)

    if not floor_items and not disc:
        story.append(Paragraph(
            "No repair items found. Ensure photos are tagged and the questionnaire is submitted.",
            S["muted"],
        ))

    # ── Items Not in This Plan ────────────────────────────────────────────
    if not_in:
        story.append(Spacer(1, 14))
        story += _subsection(f"Items Not in This Plan — {len(not_in)}", color=C_MUTED)
        ni_data = [[_p("Component","b"), _p("Why Not Included","b"),
                    _p("Cost","rb"),     _p("Value Return","b")]]
        for item in not_in:
            ni_data.append([
                _p(item.get("display_name","—"), "n"),
                _p(_skip_reason(item, plan_key), "gry"),
                _p(_cost_range(item), "r"),
                _recoup_cell(item),
            ])
        ni_tbl = Table(ni_data, colWidths=[1.5*inch, 2.85*inch, 1.0*inch, 1.65*inch],
                       repeatRows=1)
        ni_tbl.setStyle(_tbl(len(ni_data)))
        story.append(ni_tbl)

    story.append(Spacer(1, 22))

    # ════════════════════════════════════════════════════════════════════════
    # Net Proceeds Breakdown
    # ════════════════════════════════════════════════════════════════════════
    story += _section("Estimated Net Proceeds")

    line_items = base_np.get("line_items") or []
    if line_items:
        np_data = [[_p("Item","b"), _p("Amount","rb")]]
        for i, li in enumerate(line_items):
            is_last = i == len(line_items) - 1
            label   = li.get("label", "")
            amount  = li.get("amount")
            if is_last:
                np_data.append([_p(label, "rb"), _amt(amount, bold=True)])
            else:
                np_data.append([_p(label, "n"), _neutral_amt(amount)])

        if is_customized and live_net is not None and abs(live_net - base_net) > 0.5:
            delta = live_net - base_net
            np_data.append([_p("Custom plan adjustment (items / quotes)", "mu"), _neutral_amt(delta)])
            np_data.append([_p("Adjusted Net Proceeds", "rb"), _amt(live_net, bold=True)])

        np_tbl = Table(np_data, colWidths=[5.0*inch, 2.0*inch], repeatRows=1)
        np_tbl.setStyle(_tbl(len(np_data), bold_last=True))
        story.append(np_tbl)

        if bool(custom_costs) and any(
            item["component_id"] in custom_costs for item in floor_items + disc
        ):
            story.append(Spacer(1, 6))
            story.append(Paragraph(
                "* Cost marked with asterisk reflects an entered quote. "
                "Line-item breakdown uses original plan costs; adjusted net incorporates entered quotes.",
                S["muted"],
            ))
    else:
        story.append(Paragraph(
            f"Estimated net proceeds ({plan_label}): {_fmt(display_net)}", S["body"]
        ))

    story.append(Spacer(1, 24))

    # ════════════════════════════════════════════════════════════════════════
    # Caveats
    # ════════════════════════════════════════════════════════════════════════
    story.append(HRFlowable(width=CONTENT_W, thickness=0.5, color=C_RULE, spaceAfter=8))
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


class LargePDFRequest(BaseModel):
    plan_key: str = "recommended"
    custom_items: Optional[List[str]] = None
    custom_costs: Optional[Dict[str, float]] = None
    live_net: Optional[float] = None


@router.post("/{session_id}/pdf/large")
def get_large_pdf(session_id: str, req: LargePDFRequest):
    """Generate and return a large-print PDF report (18 pt body text)."""
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
