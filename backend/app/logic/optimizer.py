"""
optimizer.py — generates and scores the three seller plans.

Plans:
  leaner        → mandatory Floor items only
  recommended   → Floor + high-ROI improvements (recoup >= 75%)
  do_everything → all non-leave items

For each plan, optimizer adjusts the sale price upward if seller is doing
upgrades, estimates net proceeds, and scores plans on:
  - Net proceeds after all costs
  - Time to close (DOM)
  - Effort (repair cost the seller must manage)

Blindness: sale price adjustments are computed from library recoup_pct,
not from any pre-computed answer in validation/.
"""

from __future__ import annotations

from typing import List, Optional

from .valuation import compute_as_is_range
from .dom import estimate_dom, estimate_carrying_cost
from .net_proceeds import net_for_plan
from .floor import compute_floor


# Recoup threshold for "recommended" plan
RECOMMENDED_RECOUP_THRESHOLD = 75.0
# Value uplift multiplier: library recoup_pct of money spent on an upgrade
# adds that fraction back to sale price (e.g. 60% recoup on $5k spend → +$3k)
# For defect-clearing items, full as-is price is assumed (avoids haircut).


def build_plans(
    enriched_rows: List[dict],
    floor_result: dict,
    valuation: dict,
    dom_data: dict,
    closing_constants: dict,
    property_inputs: dict,
    seller_inputs: dict,
    listing_month: Optional[int] = None,
    commission_rate: Optional[float] = None,
    has_hoa: bool = False,
) -> dict:
    """
    Build and score all three plans.

    Returns dict with keys "leaner", "recommended", "do_everything",
    each containing: plan metadata, net_proceeds result, dom result,
    carrying cost, and a summary scorecard.
    """
    plans = {}

    for level in ("leaner", "recommended", "do_everything"):
        dom_result = estimate_dom(dom_data, level, listing_month)
        carrying   = estimate_carrying_cost(dom_result, property_inputs, seller_inputs)

        # Adjusted sale price: as-is base + recoup value of plan upgrades,
        # capped at the comps ceiling so we never project above market top.
        ceiling = valuation.get("high", float("inf"))
        adjusted_price, raw_uplift, cap_was_binding = _adjusted_sale_price(
            valuation["mid"], ceiling, enriched_rows, level
        )
        value_lift_capped = round(adjusted_price - valuation["mid"], 2)

        adjusted_val = dict(valuation)
        adjusted_val["mid"] = adjusted_price

        np_result = net_for_plan(
            valuation=adjusted_val,
            plan_level=level,
            floor_result=floor_result,
            enriched_rows=enriched_rows,
            dom_result=dom_result,
            carrying_cost_result=carrying,
            closing_constants=closing_constants,
            seller_inputs=seller_inputs,
            commission_rate=commission_rate,
            has_hoa=has_hoa,
        )

        # Summarize which items are included in this plan
        included = _items_for_level(enriched_rows, floor_result, level)

        # Repair spend: pull from net_proceeds line_items for accuracy
        repair_spend = next(
            (li["amount"] for li in np_result.get("line_items", [])
             if li["label"] == "Pre-listing repairs (plan)"),
            0.0,
        )

        # Plan-level ROI%: (value_lift - repair_spend) / repair_spend * 100
        # Positive = seller gains more than they spend; capped at ceiling.
        if repair_spend > 0:
            plan_roi_pct = round(
                (value_lift_capped - repair_spend) / repair_spend * 100, 1
            )
        else:
            plan_roi_pct = None  # nothing spent; ROI undefined

        plans[level] = {
            "plan_level":               level,
            "adjusted_sale_price":      round(adjusted_price, 2),
            "as_is_price":              valuation["mid"],
            "improved_listing_ceiling": round(ceiling, 2),
            "value_lift_capped":        value_lift_capped,
            "value_lift_cap_binding":   cap_was_binding,
            "total_repair_cost_mid":    round(repair_spend, 2),
            "plan_roi_pct":             plan_roi_pct,
            "dom":                      dom_result,
            "carrying":                 carrying,
            "net_proceeds":             np_result,
            "included_items":           included,
            "item_count":               len(included),
        }

    # Add a simple scorecard comparing plans
    plans["scorecard"] = _scorecard(plans)
    return plans


def _adjusted_sale_price(
    base_mid: float,
    ceiling: float,
    enriched_rows: list,
    level: str,
) -> tuple:
    """
    Estimate value uplift for a given plan level, capped at comp ceiling.

    Defect-clearing items: their "discount removal" is already baked into
    the base as-is valuation (the comps reflect move-in-ready homes; a
    defective home sells for less). We model the uplift for defect-clearing
    as recovering the buyer haircut, estimated at library recoup_pct of mid
    repair cost (recoup_pct is typically set to 100% for Floor items).

    Upgrades: library recoup_pct fraction of mid repair cost.

    For the "leaner" plan (Floor only), only defect-clearing uplift applies.

    Returns (adjusted_price, uncapped_uplift, cap_was_binding).
    cap_was_binding is True when the raw uplift would have exceeded ceiling.
    """
    uplift = 0.0

    for row in enriched_rows:
        bv = row.get("better_value")
        if bv not in ("repair", "replace", "upgrade"):
            continue

        recoup_pct = row.get("recoup_pct", 0) / 100.0
        is_floor   = row.get("defect_qualifies_floor", False)
        mid = (
            row.get("cost_mid_repair") if bv in ("repair", "upgrade")
            else row.get("cost_mid_replace")
        )
        if not mid:
            continue

        include = False
        if level == "leaner" and is_floor:
            include = True
        elif level == "recommended":
            if is_floor or row.get("recoup_pct", 0) >= RECOMMENDED_RECOUP_THRESHOLD:
                include = True
            # Upgrade items with high recoup also appear in recommended
            if bv == "upgrade" and row.get("recoup_pct", 0) >= RECOMMENDED_RECOUP_THRESHOLD:
                include = True
        elif level == "do_everything":
            include = True

        if include:
            if is_floor:
                # Floor items remove a buyer discount already baked into as-is comps;
                # they do not add a premium above baseline. Cap uplift at the repair
                # cost so a larger quote never inflates the sale price above cost.
                # NOTE: this is the interim fix. The proper model (fixed haircut
                # recovery from the library, independent of actual quote) is a
                # separate design decision — do not treat this cap as final.
                uplift += min(mid * recoup_pct, mid)
            else:
                uplift += mid * recoup_pct

    raw_price       = base_mid + uplift
    adjusted_price  = min(raw_price, ceiling)
    cap_was_binding = raw_price > ceiling

    return adjusted_price, uplift, cap_was_binding


def _items_for_level(enriched_rows: list, floor_result: dict, level: str) -> list:
    """Return list of component_ids included in this plan."""
    included = []
    floor_ids = {i["component_id"] for i in floor_result.get("items", [])}

    for row in enriched_rows:
        cid = row["component_id"]
        bv  = row.get("better_value")
        if bv == "leave":
            continue

        in_floor = cid in floor_ids
        recoup   = row.get("recoup_pct", 0)

        if level == "leaner" and in_floor:
            included.append(cid)
        elif level == "recommended" and (in_floor or recoup >= RECOMMENDED_RECOUP_THRESHOLD):
            if bv in ("repair", "replace", "credit", "upgrade"):
                included.append(cid)
        elif level == "do_everything":
            included.append(cid)

    return included


def _scorecard(plans: dict) -> dict:
    """Compare plans on net proceeds, DOM, and effort."""
    levels = ("leaner", "recommended", "do_everything")
    rows = []
    for lv in levels:
        p = plans[lv]
        np_val = p["net_proceeds"]["net_proceeds"]
        dom    = p["dom"]["estimated_dom"]
        cost   = p["net_proceeds"].get("total_deductions", 0)
        rows.append({
            "plan":         lv,
            "net_proceeds": np_val,
            "dom_days":     dom,
            "total_cost_to_seller": cost,
        })

    # Rank by net proceeds (highest = best)
    sorted_by_net = sorted(rows, key=lambda r: r["net_proceeds"], reverse=True)
    for i, r in enumerate(sorted_by_net):
        r["net_proceeds_rank"] = i + 1

    # Rank by DOM (lowest = fastest)
    sorted_by_dom = sorted(rows, key=lambda r: r["dom_days"])
    for i, r in enumerate(sorted_by_dom):
        r["dom_rank"] = i + 1

    return {"plans": rows}
