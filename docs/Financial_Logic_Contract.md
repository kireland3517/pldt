# Financial Logic Contract

This file is the source of truth for seller financial calculations. Any change to the formulas below must update this file and add or update backend tests in the same change.

## Core formula

Net proceeds must be calculated as:

```text
net_proceeds = gross_sale_price
  - mortgage_payoff
  - agent_commission
  - required_seller_closing_costs
  - seller_paid_repair_spend
  - buyer_credits_or_concessions
  - carrying_cost
  - other_seller_costs
```

Current implementation location: `backend/app/logic/net_proceeds.py`.

## Required deductions

Every net proceeds calculation must include these deductions when applicable:

| Deduction | Rule |
|---|---|
| Mortgage payoff | Always deduct `seller_inputs.mortgage_payoff`; default to 0 only if missing. |
| Agent commission | Deduct `gross_sale_price * commission_rate`; default from `sc_closing_constants.json`. |
| SC transfer tax | Deduct `ceil(gross_sale_price / 500) * rate_per_500`. |
| Attorney closing fee | Deduct midpoint from reference constants unless a seller-specific value exists. |
| Deed recording fee | Deduct flat reference value. |
| CL-100 termite letter | Deduct midpoint from reference constants. |
| HOA estoppel / transfer | Deduct only if seller confirms HOA. |
| Pre-listing repairs | Deduct selected seller-paid repair, replace, and upgrade costs. |
| Buyer credits / concessions | Deduct as closing cost, not pre-listing cash. |
| Carrying cost | Deduct estimated carrying cost from DOM logic. |
| Other seller costs | Deduct seller-entered extra costs. |

## Hard invariants

These must always be true:

1. Increasing `mortgage_payoff` lowers `net_proceeds` by exactly the same amount, all else equal.
2. Increasing seller-paid repair spend lowers `net_proceeds` unless gross sale price is also explicitly raised by valuation/optimizer logic.
3. Buyer credits/concessions lower `net_proceeds` but do not increase `cash_required_before_listing`.
4. Sell As-Is has `seller_paid_repair_spend = 0`.
5. A selected upgrade cannot increase sale price unless its cost is also included in repair spend.
6. Must-do/Floor items are included because of risk, not because of ROI.
7. Negative ROI does not remove a must-do/Floor item.
8. Positive ROI does not make a non-risk cosmetic item mandatory.
9. React must not duplicate backend money formulas.
10. Any new money field must be named so its timing is clear: before listing, at closing, or after sale.

## ROI definitions

Item ROI:

```text
item_roi_pct = (estimated_value_lift - selected_cost) / selected_cost * 100
```

Plan ROI:

```text
plan_roi_pct = (value_lift_capped - seller_paid_repair_spend) / seller_paid_repair_spend * 100
```

ROI can be negative. Negative ROI is still useful information.

## Cash timing

Cash required before listing:

```text
cash_required_before_listing = sum(selected seller-paid work due before listing or before sale)
```

Do not include:

- mortgage payoff
- agent commission
- transfer tax
- closing attorney fee
- buyer concessions paid at closing
- seller credits paid at closing

## Scenario comparison output

Every scenario comparison should expose these fields:

| Field | Meaning |
|---|---|
| `scenario_key` | Stable scenario identifier. |
| `gross_sale_price` | Estimated sale price before deductions. |
| `seller_paid_repair_spend` | Work the seller pays for. |
| `cash_required_before_listing` | Cash the seller needs before listing/sale. |
| `buyer_credits_or_concessions` | Credits paid at closing. |
| `mortgage_payoff` | Loan payoff deduction. |
| `total_selling_costs` | Commission and seller closing costs. |
| `carrying_cost` | DOM-driven carrying estimate. |
| `net_proceeds` | Final seller net. |
| `dom_days` | Estimated days on market. |
| `inspection_risk_remaining` | Risk left unresolved. |
| `buyer_renegotiation_risk` | Likely buyer objection or credit pressure. |

## Regression tests required

The backend test suite must cover at least:

- mortgage payoff affects net proceeds dollar-for-dollar
- seller credits reduce net proceeds
- repair spend reduces net proceeds
- upgrade spend is not treated as free
- buyer concessions are not treated as pre-listing cash
- negative ROI items can still be must-do/Floor
- scenario output includes all required comparison fields
