# Reference Data: Dictionary and Provenance

Pre-filled, verify before build. The tool is GENUINELY BLIND: it knows what a home CAN have (the library), not what any specific home DOES have (the instance, filled by capture).

## The two-layer model (read this first)
- **Library layer = `components_library.csv`.** Universal common-house catalog. Each row is a component that a South Atlantic single-family home MIGHT have, present or not. Holds cost ranges, recoup, and ELIGIBILITY flags. References no specific house. Pre-filled, verify.
- **Instance layer = `instance_schema.csv`.** Per-property, starts BLANK (headers only). The capture pipeline (photos + questionnaire) fills it for a given house. Never pre-filled for a real run.

A component enters the mandatory Floor only when the instance layer records a DETECTED qualifying defect on a component whose library flag makes it Floor-eligible.

## Files
- **components_library.csv** — the general library (37 rows, broader than any one house).
- **instance_schema.csv** — empty per-property schema (headers only).
- **sc_closing_constants.json** — SC closing rules and rates.
- **dom_seasonality.json** — days-on-market baseline and adjustments.
- **questionnaire_bank.json** — presence questions (which components exist) + condition questions (assess those present) + constraints intake.
- **../seed_data/property_inputs_130_kingfisher.json** — front-door inputs only (address, public data, seller constraints). NO condition, NO as-is range.
- **../validation/answer_key_130_kingfisher.json** — QUARANTINED ground truth. The running tool must never read it.

## components_library.csv columns
- component_id, display_name, zone
- typical_in_home — always | common | sometimes (drives presence questions; NOT instance state)
- work_type_default — major | minor | clean
- repair_low/high, replace_low/high — general South Atlantic ranges (no unit costs in v1)
- repairable, creditable
- recoup_pct, recoup_source — "CvV-anchored" (5 rows) or "estimate"
- **safety_eligible, lender_eligible, essential_when_needed** — ELIGIBILITY, not state. A defect here CAN enter the Floor. The instance layer decides whether it actually does.
- **floor_trigger** — the detected condition that makes this component a Floor item ("none (discretionary)" means it never is).
- notes

## Floor logic (for floor.py)
For each component present with a detected defect:
`floor_member = (safety_eligible OR lender_eligible OR essential_when_needed) AND defect_matches(floor_trigger)`
This replaces the old hardcoded-flag approach and removes the earlier EXT-05/OTH-01 over-tagging and the REM-01 special case. REM-01 carries essential_when_needed=True with floor_trigger="heavy smoke detected", so it joins the Floor only when smoke is detected, not by default.

## Must-verify before build
1. **The eligibility flags and floor_trigger** on every row. These define the Floor across ALL houses now, not one. Verify they read as general rules.
2. **The 5 CvV-anchored recoup values:** GAR-01 (217.8), XDR-01 (153.2), KIT-01 (102.2), DECK-01 (82.4), WIN-01 (61.0). Respect Zonda excerpt limits.
3. **SC transfer-tax rate and 4%/6% proration** in sc_closing_constants.json.
4. **base_dom (60)** in dom_seasonality.json.
5. **Cost ranges** are general market figures, NOT reverse-engineered from 130 Kingfisher. Audit for leakage.

## What changed from the earlier draft (and why)
The earlier components.csv was the 31 things wrong with 130 Kingfisher, with house-specific notes and over-eager safety flags. That contaminated the tool with the answer's shape. This version is a general library, the instance layer starts blank, and the house's real condition moved to the quarantined answer key. The tool now meets 130 Kingfisher blind.
