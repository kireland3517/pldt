# Claude Project Guardrails

This is a real estate pre-listing decision tool. The product goal is not a pretty dashboard first. The product goal is financially correct repair decision support for a seller deciding what to do before listing.

## Read first

1. `START_HERE.md`
2. `docs/Financial_Logic_Contract.md`
3. `docs/Scenario_Definitions.md`
4. `docs/PreListing_Tool_Technical_Handoff.md`

## Non-negotiable rules

- Do not change financial formulas without updating `docs/Financial_Logic_Contract.md` and tests in the same change.
- Do not change scenario membership rules without updating `docs/Scenario_Definitions.md` and tests in the same change.
- Do not make UI changes that redefine the meaning of net proceeds, repair spend, cash required, ROI, or inspection risk.
- Do not invent costs, recoup percentages, South Carolina closing costs, DOM assumptions, or property facts. Surface a TODO instead.
- Do not read from `validation/` in runtime code. Validation files are answer keys only.
- Do not let positive ROI override safety, code, lender, inspection, or deal-breaker risk.
- Do not let negative ROI remove a must-do item.
- Do not treat buyer credits as seller-paid pre-listing cash.

## Required workflow for meaningful changes

Before editing files, produce this plan:

1. Business rule being changed
2. Files/functions affected
3. Current behavior
4. Desired behavior
5. Test that will catch regression
6. Minimal implementation plan

Then implement the smallest change that satisfies the rule.

## Financial terms

- Gross sale price: expected sale price before deductions.
- Net proceeds: money left after mortgage payoff, selling costs, repair spend, concessions, carrying cost, seller credits, and other seller costs.
- Repair spend: seller-paid work before listing or closing.
- Cash required before listing: selected seller-paid work that must be paid before sale.
- Buyer credit/concession: seller cost at closing, not pre-listing cash.
- ROI: value lift minus cost, divided by cost. ROI can be negative.
- Must-do/Floor: safety, code, lender, essential function, or major inspection/deal risk. This is not optional just because ROI is negative.

## Coding standards for this repo

- Backend calculation logic belongs in `backend/app/logic/`.
- Calculation tests belong in `backend/tests/`.
- Keep formulas centralized. Do not duplicate financial math in React.
- Frontend should display calculation results from the backend, not recalculate money logic.
- Use plain explicit names for money fields: `mortgage_payoff`, `repair_spend`, `cash_required_before_listing`, `net_proceeds`, `seller_credits`, `concessions_total`.

## When asked to improve the app

Prioritize in this order:

1. Correct calculations
2. Scenario and tier logic
3. Regression tests
4. Clear labels in the UI
5. Visual polish
