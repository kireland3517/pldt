"""
net_proceeds.py — computes seller net proceeds for a given plan.

Formula (all from sc_closing_constants.json + seller inputs):
  net = sale_price
      - mortgage_payoff
      - commission (seller input or default 6%)
      - sc_transfer_tax (rate_per_500 * ceiling(sale_price / 500))
      - attorney_closing_fee (use midpoint)
      - deed_recording_fee (flat)
      - cl100_termite_letter (use midpoint — standard in SC)
      - hoa_estoppel_transfer (only if seller says HOA exists)
      - repair_cost_for_plan (mid of floor, recommended, or all items)
      - carrying_cost (from dom.py)
      - concessions (if plan uses credit path)

Blindness: sale_price comes from valuation.py output (OLS comps), never
from validation/. All SC rates from sc_closing_constants.json.
"""

from __future__ import annotations

import math
from typing import Optional


def compute_net_proceeds(
    sale_price: float,
    closing_constants: dict,
    seller_inputs: dict,
    plan_repair_cost_mid: float,
    carrying_cost_total: float,
    concessions_total: float = 0.0,
    commission_rate: Optional[float] = None,
    has_hoa: bool = False,
) -> dict:
    """
    Compute seller net proceeds.

    Parameters
    ----------
    sale_price            : OLS-derived valuation mid (or plan-adjusted)
    closing_constants     : sc_closing_constants.json dict
    seller_inputs         : seller constraints from seed (mortgage_payoff, etc.)
    plan_repair_cost_mid  : mid-point cost of repairs the seller will do for this plan
    carrying_cost_total   : total carrying cost from dom.py
    concessions_total     : buyer concessions credited instead of repairs
    commission_rate       : override; defaults to constants["commission"]["default_rate"]
    has_hoa               : seller confirms HOA; adds estoppel fee

    Returns
    -------
    dict with line_items list and net_proceeds float.
    """
    line_items = []

    def deduct(label: str, amount: float, note: str = ""):
        line_items.append({
            "label":  label,
            "amount": round(amount, 2),
            "note":   note,
        })
        return amount

    gross = sale_price
    total_deductions = 0.0

    # 1. Mortgage payoff
    payoff = float(seller_inputs.get("mortgage_payoff", 0))
    total_deductions += deduct("Mortgage payoff", payoff)

    # 2. Commission
    rate = commission_rate if commission_rate is not None else \
           closing_constants["commission"]["default_rate"]
    commission = gross * rate
    total_deductions += deduct(
        "Agent commission",
        commission,
        f"{rate*100:.1f}% — adjustable",
    )

    # 3. SC transfer tax ($1.85 per $500 of sale price)
    rate_per_500 = closing_constants["sc_transfer_tax"]["rate_per_500"]
    transfer_tax = math.ceil(gross / 500) * rate_per_500
    total_deductions += deduct(
        "SC transfer tax",
        transfer_tax,
        closing_constants["sc_transfer_tax"]["note"],
    )

    # 4. Attorney closing fee (midpoint)
    atty = closing_constants["attorney_closing_fee"]
    atty_fee = (atty["low"] + atty["high"]) / 2
    total_deductions += deduct(
        "Attorney closing fee",
        atty_fee,
        atty["note"],
    )

    # 5. Deed recording fee
    deed_fee = closing_constants["deed_recording_fee"]["flat"]
    total_deductions += deduct(
        "Deed recording fee",
        float(deed_fee),
        closing_constants["deed_recording_fee"]["note"],
    )

    # 6. CL-100 termite letter (standard in SC; use midpoint)
    cl100 = closing_constants["cl100_termite_letter"]
    cl100_fee = (cl100["low"] + cl100["high"]) / 2
    total_deductions += deduct(
        "CL-100 termite letter",
        cl100_fee,
        cl100["note"],
    )

    # 7. HOA estoppel / transfer fee (only if seller confirms HOA)
    if has_hoa:
        hoa = closing_constants["hoa_estoppel_transfer"]
        hoa_fee = (hoa["low"] + hoa["high"]) / 2
        total_deductions += deduct(
            "HOA estoppel / transfer fee",
            hoa_fee,
            hoa["note"],
        )

    # 8. Plan repair cost (seller pays before close)
    if plan_repair_cost_mid > 0:
        total_deductions += deduct(
            "Pre-listing repairs (plan)",
            plan_repair_cost_mid,
            "Mid-point of library cost range",
        )

    # 9. Buyer concessions (credits offered instead of repairs)
    if concessions_total > 0:
        total_deductions += deduct(
            "Buyer concessions / credits",
            concessions_total,
        )

    # 10. Carrying cost
    if carrying_cost_total > 0:
        total_deductions += deduct(
            "Estimated carrying cost",
            carrying_cost_total,
            "Interest + tax + insurance + utilities during DOM",
        )

    # 11. Seller-entered buyer credits / concessions (C-CREDITS)
    seller_credits = float(seller_inputs.get("seller_credits", 0) or 0)
    if seller_credits > 0:
        total_deductions += deduct(
            "Buyer credits / concessions",
            seller_credits,
            "Entered by seller",
        )

    # 12. Other seller costs (C-OTHER-COSTS): moving, staging, extra attorney, etc.
    other_seller_costs = float(seller_inputs.get("other_seller_costs", 0) or 0)
    if other_seller_costs > 0:
        total_deductions += deduct(
            "Other seller costs",
            other_seller_costs,
            "Moving, staging, extra attorney work, etc.",
        )

    net = gross - total_deductions

    return {
        "gross_sale_price":  round(gross, 2),
        "total_deductions":  round(total_deductions, 2),
        "net_proceeds":      round(net, 2),
        "line_items":        line_items,
        "commission_rate":   rate,
        "has_hoa":           has_hoa,
        "repair_spend":      round(plan_repair_cost_mid, 2),  # A2: direct field, not scraped from label
    }


def net_for_plan(
    valuation: dict,
    plan_level: str,            # "leaner" | "recommended" | "do_everything"
    floor_result: dict,         # from floor.py
    enriched_rows: list,        # from recoup.py
    dom_result: dict,
    carrying_cost_result: dict,
    closing_constants: dict,
    seller_inputs: dict,
    commission_rate: Optional[float] = None,
    has_hoa: bool = False,
) -> dict:
    """
    High-level helper: picks the right repair cost basis for each plan level
    and calls compute_net_proceeds.

    plan_level:
      "leaner"        → Floor items only (mid cost from floor_result)
      "recommended"   → Floor + high-recoup items better_value in (repair, replace)
      "do_everything" → all items with better_value != "leave"
    """
    # Sale price: always the as-is mid (seller hasn't done work yet; value
    # for "recommended" and "do_everything" should be adjusted upward by the
    # optimizer, but that's optimizer.py's job — here we use as-is mid as
    # the conservative baseline so net_proceeds is clear about what's baked in).
    sale_price = valuation["mid"]

    repair_cost_mid = 0.0
    concessions_total = 0.0

    if plan_level == "leaner":
        repair_cost_mid = floor_result["cost_mid"]

    elif plan_level == "recommended":
        # Floor cost + items with better_value=repair/replace and recoup>=75%
        repair_cost_mid = floor_result["cost_mid"]
        for row in enriched_rows:
            if row.get("defect_qualifies_floor"):
                continue  # already in floor cost
            bv = row.get("better_value")
            if bv in ("repair", "replace"):
                rp = row.get("recoup_pct", 0)
                if rp >= 75:
                    mid = (
                        row.get("cost_mid_repair") if bv == "repair"
                        else row.get("cost_mid_replace")
                    )
                    if mid:
                        repair_cost_mid += mid
            elif bv == "upgrade":
                # Upgrade items generate value lift; their cost must also be deducted.
                # A2: any item contributing uplift must count its seller-paid cost.
                mid = row.get("cost_mid_repair") or 0
                if mid:
                    repair_cost_mid += mid
            elif bv == "credit":
                mid = row.get("cost_mid_repair") or row.get("cost_mid_replace") or 0
                concessions_total += mid / 2  # credit is typically ~50% of repair

    else:  # do_everything
        for row in enriched_rows:
            bv = row.get("better_value")
            if bv in ("repair", "replace"):
                mid = (
                    row.get("cost_mid_repair") if bv == "repair"
                    else row.get("cost_mid_replace")
                ) or 0
                repair_cost_mid += mid
            elif bv == "upgrade":
                mid = row.get("cost_mid_repair") or 0
                repair_cost_mid += mid
            elif bv == "credit":
                mid = row.get("cost_mid_repair") or row.get("cost_mid_replace") or 0
                concessions_total += mid / 2

    result = compute_net_proceeds(
        sale_price=sale_price,
        closing_constants=closing_constants,
        seller_inputs=seller_inputs,
        plan_repair_cost_mid=repair_cost_mid,
        carrying_cost_total=carrying_cost_result["total"],
        concessions_total=concessions_total,
        commission_rate=commission_rate,
        has_hoa=has_hoa,
    )
    result["plan_level"] = plan_level
    result["dom_days"]   = dom_result["estimated_dom"]
    return result
