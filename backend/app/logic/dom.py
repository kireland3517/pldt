"""
dom.py — estimates days-on-market and carrying cost for a given plan.

Formula:
  estimated_dom = base_dom * condition_multiplier(plan_level) * seasonality_factor(month)

Carrying cost:
  monthly_cost = mortgage_interest + property_tax_monthly + insurance_monthly
                 + utilities_vacant_monthly
  total_carrying = (estimated_dom / 30) * monthly_cost

All constants from dom_seasonality.json and sc_closing_constants.json (library).
Mortgage interest estimated from payoff balance (seller may not provide payment).

Blindness: all multipliers come from dom_seasonality.json (library). No
property-specific DOM data is loaded from validation/.
"""

from __future__ import annotations

import datetime
from typing import Optional

# Estimated monthly rates for carrying cost components not directly provided
_INSURANCE_MONTHLY_ESTIMATE   = 100.0   # homeowners; vacant may be higher
_UTILITIES_VACANT_MONTHLY      = 125.0   # minimal: electric, water
_ANNUAL_INTEREST_RATE_ASSUMED  = 0.07   # 7% — conservative; seller can override


# Plan-level to condition-multiplier key mapping
_PLAN_CONDITION_LEVEL: dict = {
    "leaner":       "as_is_with_defects",   # floor only; discretionary defects remain
    "recommended":  "average",
    "do_everything":"move_in_ready",
}


def estimate_dom(
    dom_data: dict,
    plan_level: str,
    listing_month: Optional[int] = None,
) -> dict:
    """
    Estimate DOM for a plan.

    dom_data: the dom_seasonality.json dict.
    plan_level: "leaner" | "recommended" | "do_everything"
    listing_month: 1-12. Defaults to current month.

    Returns: {"estimated_dom": int, "condition_multiplier": float,
              "seasonality_factor": float}
    """
    if listing_month is None:
        listing_month = datetime.date.today().month

    base_dom = float(dom_data["base_dom_days"])
    month_key = datetime.date(2000, listing_month, 1).strftime("%b").lower()
    seasonality = float(dom_data["seasonality_factor"].get(month_key, 1.0))

    cond_level = _PLAN_CONDITION_LEVEL.get(plan_level, "average")
    cond_mult  = float(dom_data["condition_multiplier"].get(cond_level, 1.0))

    raw_dom = base_dom * cond_mult * seasonality
    estimated_dom = max(14, round(raw_dom))      # floor of 14 days

    return {
        "estimated_dom":        estimated_dom,
        "condition_multiplier": cond_mult,
        "seasonality_factor":   seasonality,
        "base_dom":             base_dom,
        "listing_month":        listing_month,
    }


def estimate_carrying_cost(
    dom_result: dict,
    property_inputs: dict,
    seller_inputs: dict,
) -> dict:
    """
    Estimate monthly and total carrying cost.

    property_inputs: the seed dict (has public_county_facts with annual_tax).
    seller_inputs: the session inputs dict (has mortgage_payoff, etc.).

    Returns: {"monthly": float, "total": float, "dom": int,
              "components": {mortgage, tax, insurance, utilities}}
    """
    dom = dom_result["estimated_dom"]
    months = dom / 30.0

    # Mortgage: interest portion on remaining balance (P&I payment unknown without
    # amortization schedule; use interest-only as carrying cost proxy)
    payoff = float(seller_inputs.get("mortgage_payoff", 0))
    mortgage_monthly = payoff * (_ANNUAL_INTEREST_RATE_ASSUMED / 12)

    # Property tax
    annual_tax = float(
        property_inputs.get("public_county_facts", {}).get("annual_tax", 0)
    )
    tax_monthly = annual_tax / 12

    insurance_monthly = _INSURANCE_MONTHLY_ESTIMATE
    utilities_monthly = _UTILITIES_VACANT_MONTHLY

    total_monthly = (
        mortgage_monthly + tax_monthly + insurance_monthly + utilities_monthly
    )
    total_carrying = total_monthly * months

    return {
        "dom":     dom,
        "months":  round(months, 2),
        "monthly": round(total_monthly, 2),
        "total":   round(total_carrying, 2),
        "components": {
            "mortgage_interest": round(mortgage_monthly, 2),
            "property_tax":      round(tax_monthly, 2),
            "insurance":         round(insurance_monthly, 2),
            "utilities_vacant":  round(utilities_monthly, 2),
        },
        "note": (
            "Mortgage carrying cost is interest-only on remaining balance "
            f"at {_ANNUAL_INTEREST_RATE_ASSUMED:.0%} assumed rate. "
            "Actual P&I payment may differ."
        ),
    }
