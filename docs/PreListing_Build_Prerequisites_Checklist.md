# Build-Prerequisites Checklist

Everything you prepare before handing the project to a coding agent (Cursor / Claude Code / Codex). These are the assets the agent must never invent. If it isn't on this list and prepared by you, the agent will hallucinate it.

## How to use this
Each item has an ID (e.g. REF-01) so you can reference it from the other docs and from your code. Columns: what it is, format, **static** (reference data you own, changes rarely) or **fetched** (property-specific, pulled then cached), where it's specced, and status (`prefilled` = I've seeded real values for you to verify; `schema` = columns defined, you fill; `account` = sign-up needed; `todo` = you build).

A item is "done" only when you've verified or gathered it. Pre-filled items still need your eyes before they're trusted.

---

## Group A: Static Reference Data (you own, reusable across any property)

These are the spine. The coding agent reads them, never generates them.

### REF-01 Component Taxonomy
- **What:** the master list of every home component the tool reasons about, the spine everything else joins to.
- **Per row:** component_id, display_name, category/zone, default_severity, safety_flag, lender_flag, defect_or_upgrade.
- **Format:** CSV or JSON.
- **Type:** static.
- **Specced in:** Framework S2, S4.
- **Status:** `prefilled` (delivered next doc, seeded from the 130 Kingfisher item set; verify and extend).
- **Verify:** that the flags are right, especially lender_flag and safety_flag, since the Floor layer is computed from them.

### REF-02 Cost Table
- **What:** repair and replace cost ranges per component for the South Atlantic.
- **Per row:** component_id, repair_cost_low, repair_cost_high, replace_cost_low, replace_cost_high, repairable, creditable, notes.
- **Format:** CSV or JSON.
- **Type:** static.
- **Specced in:** Framework S3.
- **Status:** `prefilled` (real South Atlantic ranges, verify).
- **Verify:** ranges against any real quotes you have or can get. No unit-cost/lumber columns (dropped for v1).

### REF-03 Recoup / ROI Table
- **What:** the percentage of each option's cost that returns at sale, with provenance.
- **Per row:** component_id, recoup_pct, source ("CvV-anchored" or "estimate"), notes.
- **Format:** CSV or JSON (can be columns on REF-02).
- **Type:** static.
- **Specced in:** Framework S4.
- **Status:** `prefilled` (5 CvV-anchored values + estimates, source labeled).
- **Verify:** the anchored 5 (garage door 217.8%, steel entry door 153.2%, minor kitchen 102.2%, wood deck 82.4%, vinyl window 61.0%). Respect Zonda excerpt limits; do not reproduce its table layout in-product.

### REF-04 Lender / Safety Rules
- **What:** which conditions trigger a lender-required repair (FHA/VA/conventional minimum property requirements) and which are safety hazards.
- **Per row:** condition/component_id, fha_required, va_required, conventional_required, safety_hazard, rationale.
- **Format:** CSV or JSON.
- **Type:** static (maintained as rules change).
- **Specced in:** Framework S4, S7 (buyer-pool hard constraint).
- **Status:** `prefilled` (the common ones, incl. deck safety hazards, missing detectors, scalding water, open junction boxes).
- **Verify:** against current HUD/VA minimum property requirements. This drives the Floor; getting it wrong puts non-mandatory items in the Floor or omits mandatory ones.

### REF-05 SC Closing-Constants File
- **What:** every SC-specific closing cost and rule, for the Net Proceeds math.
- **Holds:** attorney-closing fee range; deed recording fees; SC transfer tax rate (per $500); title insurance basis; property-tax proration with the 4% owner-occupied vs 6% other ratio and how to choose; survey; CL-100 termite letter; HOA estoppel/transfer; default commission (adjustable); concession logic; carrying-cost components.
- **Format:** JSON (keyed constants) plus notes.
- **Type:** static (review cadence: it changes).
- **Specced in:** Framework S5.
- **Status:** `prefilled` (current SC values to your best knowledge, verify rates).
- **Verify:** the transfer-tax rate and the 4%/6% proration logic specifically. These are the SC gotchas.

### REF-06 DOM Baseline + Seasonality Factors
- **What:** local average days-on-market and the adjustments that move it.
- **Holds:** base_dom (local avg), condition_adjustment (move-in-ready vs as-is multipliers), seasonality_factor by month/season.
- **Format:** JSON.
- **Type:** static seed (sharpened by MLS later).
- **Specced in:** Framework S5, S7.
- **Status:** `prefilled` (Greenville/Simpsonville baseline + seasonality, verify).
- **Verify:** the base DOM against any local figure you trust. Flagged as estimate in-product until MLS.

### REF-07 Questionnaire Bank
- **What:** the guided condition questions, their branching, and when each appears.
- **Per row:** question_id, prompt_text, answer_type (yes/no, single-select, range), triggers (what condition/photo-gap surfaces it), branches (what each answer reveals next), tightens (which recommendation this narrows), maps_to (component_id/tag).
- **Format:** JSON.
- **Type:** static content.
- **Specced in:** Framework S2, S6; UX Part 7.
- **Status:** `schema` (structure defined; I'll seed the core questions in the reference-data doc, you expand).
- **Verify/build:** the wording and the tightening logic. This plus REF-01 are the two assets the framework flagged as must-build-first.

---

### REF-08 Instance Schema (per-property, BLANK)
- **What:** the empty per-property schema the capture pipeline fills. Headers only; no data.
- **Per row (filled at run time):** component_id, present, condition_detected, severity_detected, defect_qualifies_floor, chosen_path, source, confidence, notes.
- **Format:** CSV (headers only).
- **Type:** per-property, starts blank. NEVER pre-filled for a real run.
- **Specced in:** Technical Handoff (BLIND RULE, data model).
- **Status:** `schema` (delivered as instance_schema.csv).

> NOTE: REF-01 through REF-04 are delivered MERGED as `components_library.csv` (the general common-house library), not a house-shaped list. The earlier `components.csv` was superseded and deleted.

## Group B: Fetched-Then-Cached Property Data (per property; seed 130 Kingfisher today)

These are pulled from sources, then cached so the prototype survives the ATTOM trial.

### SEED-01 County Parcel / Tax Facts
- **What:** beds, baths, sqft, lot, year, subdivision, assessed value, millage, tax.
- **Source:** Greenville County Real Property Search. No uniform SC API; pull manually, cache.
- **Format:** JSON per parcel.
- **Type:** fetched then cached.
- **Specced in:** Framework S1, S5.
- **Status:** `prefilled` for 130 Kingfisher (from the report images you provided).

### SEED-02 AVMs
- **What:** ATTOM + Zillow + Redfin + Realtor.com estimates.
- **Source:** ATTOM API (your trial) + 3 portals (manual for v1).
- **Format:** JSON.
- **Type:** fetched/seeded then cached.
- **Specced in:** Framework S1.
- **Status:** `prefilled` for 130 Kingfisher ($276,810 / $282,986 / $290,500 / $296,945).
- **Action:** **pull anything else you want from ATTOM during the trial and cache it now**, before the 30 days lapse.

### SEED-03 Comps + Actives + County Sold Records
- **What:** recent solds and active listings for the size band.
- **Source:** ATTOM comp endpoint + county deed transfers.
- **Format:** JSON list.
- **Type:** fetched then cached.
- **Specced in:** Framework S1.
- **Status:** `prefilled` for River Ridge (the comp set we built).
- **Note:** MLS-only metrics (precise DOM, sale-to-list) flagged unavailable in v1.

### SEED-04 Condition Data (130 Kingfisher) -- MOVED TO ANSWER KEY, NOT A TOOL INPUT
- **What:** the structured defect list from the real inspection.
- **CHANGED:** the tool is genuinely blind. Condition is NOT pre-seeded and NOT a tool input. It is produced by the capture pipeline (photos + questionnaire) at run time.
- **Where it lives now:** `validation/answer_key_130_kingfisher.json`, quarantined. The running tool must NEVER read it. It is used only to score the blind validation run.
- **Replaces this item:** the blank `instance_schema.csv` (per-property, headers only) is what the tool fills via capture. See REF-08 below.

### SEED-05 Constraints (130 Kingfisher)
- **What:** payoff and timeline for the seed run.
- **Source:** you.
- **Format:** JSON.
- **Type:** user input.
- **Status:** `prefilled` (mortgage payoff $150,000; vacant; room to do work; repairs paid up front).

---

## Group C: Accounts and Keys

### ACC-01 ATTOM Data API
- **Status:** `account` done (30-day trial active).
- **Action:** pull and cache during the trial (see SEED-02/03). Note the expiry date.

### ACC-02 Vision Model API (Tier 2 photo tagging)
- **Status:** `account` needed for the photo-tagging path.
- **v1:** scaffolded; not required to run the seed prototype.

### ACC-03 Supabase project
- **Status:** `account` needed (stored state, resumable sessions).
- **You have prior Supabase experience; this is the state store.**

### ACC-04 Railway + GitHub
- **Status:** `account` you have. Set up the GitHub repo and connect Railway to auto-deploy on push.

### ACC-05 MLS / RESO license
- **Status:** `todo` later (long-pole). Not in v1.

### ACC-06 (optional, later)
- RSMeans-style cost license; Zonda/CvV license; portal AVM partner; title/closing-cost partner.

---

## Group D: Things the Coding Agent Builds (not your prep, listed so the boundary is clear)

You do not prepare these; the agent does, from the specs:
- The React front end (hub, sections, popups, the live knob, intake flow).
- The FastAPI back end and the optimizer logic (Floor computation, presets, reverse net-goal mode, DOM-into-net).
- Supabase wiring for resumable state.
- The recompute engine and the progressive-input loop.
- Print/share/export.
- Accessibility implementation to WCAG 2.2 AA.

---

## Build-First Order (what to prepare before you touch code)

1. **REF-01 Component Taxonomy** and **REF-07 Questionnaire Bank.** The framework flagged these as foundational; everything joins to them.
2. **REF-02 / REF-03 / REF-04.** Cost, ROI, and the lender/safety rules that compute the Floor.
3. **REF-05 / REF-06.** SC closing constants and DOM/seasonality.
4. **SEED-01 through SEED-05.** The 130 Kingfisher seed, so the prototype runs on a real house. **Pull ATTOM now, before the trial ends.**
5. **ACC-03 / ACC-04.** Supabase project and the GitHub-to-Railway pipeline.

Items 1-4 are delivered pre-filled in the next document for you to verify. Item 5 is your setup.

---

## What This Document Is Not
The checklist of what you prepare. The pre-filled data itself is the next document. The repo structure, data model, and deployment are the Technical Handoff doc.
