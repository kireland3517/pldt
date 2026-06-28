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
        adjusted_price, raw_uplift, cap_was_binding, lender_gate_items = _adjusted_sale_price(
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

        # Repair spend: read direct field (A2 — not scraped from display label)
        repair_spend = np_result.get("repair_spend", 0.0)

        # Plan-level ROI%: (value_lift - repair_spend) / repair_spend * 100
        # Positive = seller gains more than they spend; capped at ceiling.
        if repair_spend > 0:
            plan_roi_pct = round(
                (value_lift_capped - repair_spend) / repair_spend * 100, 1
            )
        else:
            plan_roi_pct = None  # nothing spent; ROI undefined

        # Lender gate: annotate major lender items with retail vs investor pricing.
        # investor_price = 75% of retail adjusted price (approximate).
        # Only major+lender items; moderate/minor lender items (e.g. garage door)
        # do NOT trigger investor-regime pricing — they take tier multiplier only.
        lender_gate = None
        if lender_gate_items:
            investor_price = round(adjusted_price * INVESTOR_CAP_RATE, -2)
            lender_gate = {
                "has_major_lender_items": True,
                "retail_price":           round(adjusted_price, 2),
                "investor_price":         investor_price,
                "investor_gap":           round(adjusted_price - investor_price, 2),
                "items":                  lender_gate_items,
            }

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
            "lender_gate":              lender_gate,
        }

    # Add a simple scorecard comparing plans
    plans["scorecard"] = _scorecard(plans)
    return plans


# Haircut-model tier multipliers (A5 fix).
# Floor/defect-clearing items use these instead of recoup_pct.
# Recovery = library_cost_mid × multiplier.
# Anchoring to library cost (not contractor quote) prevents quote inflation
# from inflating the projected sale price.
#
# major (1.5×): foundation, active roof leak, electrical panel — true buyer-pool
#   collapse if unrepaired; large uncertainty discount removed by repair.
# moderate (1.15×): HVAC, deck-structural, garage door, active plumbing leak —
#   expensive but defined scope; moderate psychological discount.
# minor (1.0×): handrails, GFCI outlets, detectors — cheap code items;
#   trivial discount, basically cost recovery.
#
# Investor-cap rule: only major+lender items trigger the 75%-ARV investor regime.
# A $3k garage door (moderate lender item) does NOT crater the whole valuation.
TIER_MULTIPLIERS = {"major": 1.5, "moderate": 1.15, "minor": 1.0}
INVESTOR_CAP_RATE = 0.75   # 75% of retail ARV for investor/cash-only scenario


def _adjusted_sale_price(
    base_mid: float,
    ceiling: float,
    enriched_rows: list,
    level: str,
) -> tuple:
    """
    Estimate value uplift for a given plan level, capped at comp ceiling.

    Floor/defect-clearing items (A5 haircut model):
      Recovery = library_cost_mid × tier_multiplier
      Tier multipliers: major 1.5×, moderate 1.15×, minor 1.0×
      Library cost is the anchor — a higher contractor quote cannot inflate recovery.
      Tiers assigned per component in components_library.csv severity_tier field.

    Upgrade (discretionary) items:
      uplift = library_cost_mid × recoup_pct   (unchanged from original model)

    Investor-cap lender gate (major+lender items only):
      When a major lender-eligible item IS in the plan, we record the retail price.
      If it were unrepaired, the investor price would be ≈75% of retail.
      Returned in lender_gate_items for the frontend to surface as a two-path choice.
      Minor/moderate lender items do NOT trigger the investor cap.

    Returns (adjusted_price, uncapped_uplift, cap_was_binding, lender_gate_items).
    """
    uplift = 0.0
    lender_gate_items = []   # major+lender items in this plan level

    for row in enriched_rows:
        bv = row.get("better_value")
        if bv not in ("repair", "replace", "upgrade"):
            continue

        is_floor = row.get("defect_qualifies_floor", False)

        # Library-anchored cost — never use contractor quote for recovery math
        lib_mid = (
            row.get("library_cost_mid_repair")   if bv in ("repair", "upgrade")
            else row.get("library_cost_mid_replace")
        )
        # Fallback to instance cost if library anchor missing (data gap)
        mid = lib_mid or (
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
            if bv == "upgrade" and row.get("recoup_pct", 0) >= RECOMMENDED_RECOUP_THRESHOLD:
                include = True
        elif level == "do_everything":
            include = True

        if include:
            if is_floor:
                # Tier-multiplier recovery (A5 haircut model)
                tier = row.get("severity_tier") or "minor"
                mult = TIER_MULTIPLIERS.get(tier, 1.0)
                uplift += mid * mult

                # Lender gate: investor_cap_eligible is set in recoup.py by comparing
                # the DETECTED severity against per-component threshold from the library.
                # A minor defect in ELEC-01 (missing cover) has investor_cap_eligible=False.
                # An unsafe panel in ELEC-01 has investor_cap_eligible=True.
                # GAR-01/HVAC-01 etc. always False — no threshold in library.
                if (row.get("investor_cap_eligible")
                        and row.get("in_floor")):
                    lender_gate_items.append({
                        "component_id":       row["component_id"],
                        "display_name":       row.get("display_name", row["component_id"]),
                        "severity_tier":      tier,
                        "severity_detected":  row.get("severity_detected", ""),
                        "library_cost_mid":   round(mid, 0),
                        "recovery_uplift":    round(mid * mult, 0),
                    })
            else:
                # Discretionary upgrades: recoup_pct unchanged
                recoup_pct = row.get("recoup_pct", 0) / 100.0
                uplift += mid * recoup_pct

    raw_price       = base_mid + uplift
    adjusted_price  = min(raw_price, ceiling)
    cap_was_binding = raw_price > ceiling

    return adjusted_price, uplift, cap_was_binding, lender_gate_items


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
