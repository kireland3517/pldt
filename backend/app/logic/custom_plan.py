"""
custom_plan.py — Stage 2 Step 1: the Custom plan, item-set-driven.

Builds one plan-shaped result (same shape as optimizer.build_plans()'s
per-level entries) from an arbitrary set of checked item ids, instead of one
of the three fixed levels (leaner/recommended/do_everything).

Item-scope decision (see net_proceeds._repair_cost_and_concessions_for_items
docstring for the full reasoning): Custom uses ONE unified scope for both
value lift and repair cost -- whatever is in the checked item set is in,
full stop. No recoup-based re-filtering on top of what the user checked.
This is a deliberate departure from the three standard plans, which use
three different (intentionally asymmetric) scopes internally.

GUARDRAIL (explicit product decision, 2026-06-30): plan_roi_pct and
value_lift_capped are reported AS COMPUTED, never floored at zero or
suppressed. A low-recoup checked item can and should show a negative ROI --
that's the honest tradeoff of overriding the standard plans' recoup>=75
curation. Nothing in this module clips or hides a negative number.

Value lift stays library-anchored (item_cost_overrides never reaches
_adjusted_sale_price_for_items) -- a seller's own repair quote must never
inflate the projected sale price. This mirrors the existing rule already in
optimizer.py for the three standard plans.

DOM / carrying cost: not estimated for Custom (parked product decision).
dom is returned None; carrying cost is omitted (not fabricated as $0) by
passing carrying_cost_total=0.0, which compute_net_proceeds already treats
as "no line" rather than a zero-dollar line, since that line is gated on
> 0 or an explicit override.
"""

from __future__ import annotations

from typing import Optional

from .optimizer import _adjusted_sale_price_for_items, INVESTOR_CAP_RATE
from .net_proceeds import compute_net_proceeds, _repair_cost_and_concessions_for_items


def build_custom_plan(
    enriched_rows: list,
    floor_result: dict,
    valuation: dict,
    closing_constants: dict,
    seller_inputs: dict,
    item_ids: list,
    item_cost_overrides: Optional[dict] = None,
    commission_rate: Optional[float] = None,
    has_hoa: bool = False,
    overrides: Optional[dict] = None,
) -> dict:
    """
    Build the Custom plan for an arbitrary checked-item set.

    item_ids: component_ids the user checked (optional items only, or the
    full set including required items -- either way, floor items are
    force-unioned in below, so the caller does not need to worry about
    accidentally dropping a required item).

    item_cost_overrides: {component_id: dollar_amount}. Affects repair-cost
    math only (see module docstring) -- never value lift.

    overrides: PER-PLAN line overrides, same mechanism as the three standard
    plans (see net_proceeds.compute_net_proceeds). Optional; Custom supports
    the same override lines for parity, though Step 3's UI may not wire this
    up for Custom initially.

    Returns a dict in the same shape as one entry of
    optimizer.build_plans()'s return value (plans["leaner"], etc.), with
    dom=None and carrying=None (not estimated for Custom -- parked decision).
    """
    item_cost_overrides = item_cost_overrides or {}

    floor_ids = {i["component_id"] for i in floor_result.get("items", [])}
    effective_ids = floor_ids | set(item_ids)

    base_mid = valuation["mid"]
    ceiling  = valuation.get("high", float("inf"))

    adjusted_price, raw_uplift, cap_was_binding, lender_gate_items = (
        _adjusted_sale_price_for_items(base_mid, ceiling, enriched_rows, effective_ids)
    )
    value_lift_capped = round(adjusted_price - base_mid, 2)

    repair_cost_mid, concessions_total = _repair_cost_and_concessions_for_items(
        enriched_rows, floor_result, effective_ids, item_cost_overrides,
    )

    np_result = compute_net_proceeds(
        sale_price=adjusted_price,
        closing_constants=closing_constants,
        seller_inputs=seller_inputs,
        plan_repair_cost_mid=repair_cost_mid,
        carrying_cost_total=0.0,   # DOM not estimated for Custom -- see module docstring
        concessions_total=concessions_total,
        commission_rate=commission_rate,
        has_hoa=has_hoa,
        overrides=overrides,
    )
    np_result["plan_level"] = "custom"
    np_result["dom_days"]   = None

    # Included items, in the same row-iteration order the three standard
    # plans use for their included_items lists (not set order).
    included = [row["component_id"] for row in enriched_rows
                if row["component_id"] in effective_ids]

    repair_spend = np_result.get("repair_spend", 0.0)
    # GUARDRAIL: report ROI as computed. Do not floor at zero, do not hide a
    # loss -- a checked low-recoup item is an honest negative-ROI tradeoff.
    if repair_spend > 0:
        plan_roi_pct = round(
            (value_lift_capped - repair_spend) / repair_spend * 100, 1
        )
    else:
        plan_roi_pct = None  # nothing spent; ROI undefined (same rule as build_plans)

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

    return {
        "plan_level":               "custom",
        "adjusted_sale_price":      round(adjusted_price, 2),
        "as_is_price":              valuation["mid"],
        "improved_listing_ceiling": round(ceiling, 2),
        "value_lift_capped":        value_lift_capped,
        "value_lift_cap_binding":   cap_was_binding,
        "total_repair_cost_mid":    round(repair_cost_mid, 2),
        "plan_roi_pct":             plan_roi_pct,
        "dom":                      None,
        "carrying":                 None,
        "net_proceeds":             np_result,
        "included_items":           included,
        "item_count":               len(included),
        "lender_gate":              lender_gate,
    }
