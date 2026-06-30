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

STAGE 2 STEP 1 — override layer
--------------------------------
Every line item now carries three numbers instead of one:
  calculated_amount  — what the engine computes. NEVER overwritten.
  override_amount    — user value, or None if not overridden.
  amount             — the EFFECTIVE value used in the net sum
                        (override_amount if set, else calculated_amount).

Two override mechanisms, by design (see CLAUDE.md "Override engine" section):
  - GLOBAL facts/rates (commission_rate, mortgage_payoff, seller_credits,
    other_seller_costs, has_hoa) are carried in `seller_inputs` /
    `commission_rate` — the same arguments this function already took.
    Those argument VALUES are themselves the effective/override values;
    this function derives calculated_amount as the baseline those would
    take with no override (0 for pure facts, default-rate dollars for
    commission) purely for display, and does not re-apply a second
    override layer on top of them.
  - PER-PLAN calculated lines (transfer_tax, attorney_fee, deed_fee,
    cl100, hoa_estoppel, repair_cost, concessions, carrying_cost) take
    their override through the new `overrides` dict, keyed by line key,
    amount or absent/None = not overridden. This dict is per-plan: the
    caller (net_for_plan / optimizer.build_plans) supplies a different
    dict per plan level.

At overrides={} (and commission_rate/seller_inputs unchanged from today),
every calculated_amount and amount is byte-identical to the pre-override
engine. See backend/tests/test_override_engine.py.
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
    overrides: Optional[dict] = None,
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
    overrides             : PER-PLAN line overrides. dict of
                             line_key -> amount (or absent/None = not overridden).
                             Valid keys: transfer_tax, attorney_fee, deed_fee,
                             cl100, hoa_estoppel, repair_cost, concessions,
                             carrying_cost. Unknown keys are ignored.

    Returns
    -------
    dict with line_items list (each item: key, label, calculated_amount,
    override_amount, amount, note) and net_proceeds float.
    """
    overrides = overrides or {}
    line_items = []

    def deduct(key: str, label: str, calculated_amount: float,
               override_amount: Optional[float] = None, note: str = ""):
        effective = override_amount if override_amount is not None else calculated_amount
        line_items.append({
            "key":               key,
            "label":             label,
            "calculated_amount": round(calculated_amount, 2),
            "override_amount":   round(override_amount, 2) if override_amount is not None else None,
            "amount":            round(effective, 2),
            "note":              note,
        })
        return effective

    gross = sale_price
    total_deductions = 0.0

    # 1. Mortgage payoff — GLOBAL fact. The engine has no way to derive this;
    #    calculated baseline is $0. seller_inputs["mortgage_payoff"] is itself
    #    the global override value (set via PATCH /session/{id}/inputs).
    payoff = float(seller_inputs.get("mortgage_payoff", 0))
    total_deductions += deduct(
        "mortgage_payoff", "Mortgage payoff",
        calculated_amount=0.0,
        override_amount=(payoff if payoff else None),
    )

    # 2. Commission — GLOBAL rate. calculated_amount uses the library default
    #    rate; override_amount is populated only when the effective rate
    #    (commission_rate arg) differs from that default.
    default_rate = closing_constants["commission"]["default_rate"]
    rate = commission_rate if commission_rate is not None else default_rate
    calc_commission = gross * default_rate
    eff_commission  = gross * rate
    commission_override = eff_commission if abs(rate - default_rate) > 1e-9 else None
    total_deductions += deduct(
        "commission", "Agent commission",
        calculated_amount=calc_commission,
        override_amount=commission_override,
        note=f"{rate*100:.1f}% — adjustable",
    )

    # 3. SC transfer tax ($1.85 per $500 of sale price) — per-plan overridable
    rate_per_500 = closing_constants["sc_transfer_tax"]["rate_per_500"]
    transfer_tax_calc = math.ceil(gross / 500) * rate_per_500
    total_deductions += deduct(
        "transfer_tax", "SC transfer tax",
        calculated_amount=transfer_tax_calc,
        override_amount=overrides.get("transfer_tax"),
        note=closing_constants["sc_transfer_tax"]["note"],
    )

    # 4. Attorney closing fee (midpoint) — per-plan overridable
    atty = closing_constants["attorney_closing_fee"]
    atty_fee_calc = (atty["low"] + atty["high"]) / 2
    total_deductions += deduct(
        "attorney_fee", "Attorney closing fee",
        calculated_amount=atty_fee_calc,
        override_amount=overrides.get("attorney_fee"),
        note=atty["note"],
    )

    # 5. Deed recording fee — per-plan overridable
    deed_fee_calc = float(closing_constants["deed_recording_fee"]["flat"])
    total_deductions += deduct(
        "deed_fee", "Deed recording fee",
        calculated_amount=deed_fee_calc,
        override_amount=overrides.get("deed_fee"),
        note=closing_constants["deed_recording_fee"]["note"],
    )

    # 6. CL-100 termite letter (standard in SC; use midpoint) — per-plan overridable
    cl100 = closing_constants["cl100_termite_letter"]
    cl100_fee_calc = (cl100["low"] + cl100["high"]) / 2
    total_deductions += deduct(
        "cl100", "CL-100 termite letter",
        calculated_amount=cl100_fee_calc,
        override_amount=overrides.get("cl100"),
        note=cl100["note"],
    )

    # 7. HOA estoppel / transfer fee (only if seller confirms HOA — has_hoa is
    #    a GLOBAL toggle, unchanged) — per-plan overridable when applicable
    if has_hoa:
        hoa = closing_constants["hoa_estoppel_transfer"]
        hoa_fee_calc = (hoa["low"] + hoa["high"]) / 2
        total_deductions += deduct(
            "hoa_estoppel", "HOA estoppel / transfer fee",
            calculated_amount=hoa_fee_calc,
            override_amount=overrides.get("hoa_estoppel"),
            note=hoa["note"],
        )

    # 8. Plan repair cost (seller pays before close) — per-plan overridable.
    #    Line shows if the engine calculated a cost OR an override is set
    #    (so a seller's actual quote can populate this even when the engine
    #    found $0, or zero it out when the engine found a cost).
    repair_override = overrides.get("repair_cost")
    if plan_repair_cost_mid > 0 or repair_override is not None:
        total_deductions += deduct(
            "repair_cost", "Pre-listing repairs (plan)",
            calculated_amount=plan_repair_cost_mid,
            override_amount=repair_override,
            note="Mid-point of library cost range",
        )

    # 9. Buyer concessions (credits offered instead of repairs) — per-plan overridable
    concessions_override = overrides.get("concessions")
    if concessions_total > 0 or concessions_override is not None:
        total_deductions += deduct(
            "concessions", "Buyer concessions / credits",
            calculated_amount=concessions_total,
            override_amount=concessions_override,
        )

    # 10. Carrying cost — per-plan overridable
    carrying_override = overrides.get("carrying_cost")
    if carrying_cost_total > 0 or carrying_override is not None:
        total_deductions += deduct(
            "carrying_cost", "Estimated carrying cost",
            calculated_amount=carrying_cost_total,
            override_amount=carrying_override,
            note="Interest + tax + insurance + utilities during DOM",
        )

    # 11. Seller-entered buyer credits / concessions (C-CREDITS) — GLOBAL fact
    seller_credits = float(seller_inputs.get("seller_credits", 0) or 0)
    if seller_credits > 0:
        total_deductions += deduct(
            "seller_credits", "Buyer credits / concessions",
            calculated_amount=0.0,
            override_amount=seller_credits,
            note="Entered by seller",
        )

    # 12. Other seller costs (C-OTHER-COSTS) — GLOBAL fact
    other_seller_costs = float(seller_inputs.get("other_seller_costs", 0) or 0)
    if other_seller_costs > 0:
        total_deductions += deduct(
            "other_seller_costs", "Other seller costs",
            calculated_amount=0.0,
            override_amount=other_seller_costs,
            note="Moving, staging, extra attorney work, etc.",
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
    overrides: Optional[dict] = None,
) -> dict:
    """
    High-level helper: picks the right repair cost basis for each plan level
    and calls compute_net_proceeds.

    plan_level:
      "leaner"        → Floor items only (mid cost from floor_result)
      "recommended"   → Floor + high-recoup items better_value in (repair, replace)
      "do_everything" → all items with better_value != "leave"

    overrides: this plan's per-plan line overrides (see compute_net_proceeds).
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
        overrides=overrides,
    )
    result["plan_level"] = plan_level
    result["dom_days"]   = dom_result["estimated_dom"]
    return result
