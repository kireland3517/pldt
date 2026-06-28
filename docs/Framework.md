# Pre-Listing Decision Tool: Framework Specification

What the tool does and what it needs, section by section. Folded current with all decisions through today. Paired with the UX/UI Spec, the Build-Prerequisites Checklist, and the Technical Handoff doc.

## Scope and Settled Decisions

Locked. Every section inherits these.

- **User:** the home seller, self-serve. Inputs are automated or made foolproof.
- **This document:** describes the full ideal, and marks the v1 cut for today's build. v1 means: runnable for 130 Kingfisher, handed to a coding agent (Cursor / Claude Code / Codex), pushed to GitHub, auto-deployed by Railway.
- **Stack:** React front end, FastAPI/Python back end, Supabase for stored state, Railway deploy via GitHub auto-push.
- **Image input:** Tier 2. A vision model tags obvious conditions from seller photos and pre-fills the questionnaire. It does not set cost or severity.
- **Geography:** South Atlantic, tuned for South Carolina (Greenville/Simpsonville). SC rules built in.
- **Architecture:** hub and sections, with a progressive-input loop. A ranged answer always shows now; the single most useful next question is offered to tighten it; recompute; stop when only a quote or inspection can resolve the rest.
- **Output model:** three layers. A mandatory floor of work, a discretionary set, and a small number of named plans plus a live knob and a reverse net-goal mode (Section 7).
- **Data rule:** reference data is static and seller-owned; property data is fetched then cached. Marked per item below.
- **Cost granularity:** repair range and replace range per component. No unit-cost/lumber modeling in v1 (false precision pre-quote).

### How to read each section
1. **What it does.** 2. **Data needed.** 3. **Data source** (static / fetched / user input). 4. **Keys / accounts.** 5. **User-facing checklist.** 6. **Fallback.** 7. **v1 cut** (what's runnable today vs scaffolded).

---

## Section 1: As-Is Valuation Baseline

**What it does.** Establishes today's value before any work. Reconciles multiple AVMs, pulls and size-adjusts comps, outputs a defensible range, not a point.

**Data needed.** Property facts (address, beds, baths, sqft, lot, year, subdivision); multiple AVMs; recent sold comps; actives/pendings; price-per-sqft by size band (larger homes sell at lower per-sqft, so the model size-adjusts).

**Data source.**
- Property facts: county assessor record. No uniform SC API; **cache county parcel data to a static seed file keyed by parcel ID.** (Fetched then cached.)
- AVMs: ATTOM API, plus Zillow/Redfin/Realtor.com estimates. **v1: hand-seed the three portal AVMs and ATTOM into a seed file. Automate later.** (Fetched/seeded then cached.)
- Comps and actives: ATTOM comp endpoint plus county sold records (deed transfers carry price and date). **v1 triangulates from these; full MLS feed is later.** (Fetched then cached.)
- Size-adjustment curve: your logic, computed from the comp set. (Static logic.)

**Keys / accounts.** ATTOM key (you have a 30-day trial). MLS/RESO license is the long-pole, later.

**User-facing checklist.** Confirm address. Confirm/correct beds, baths, sqft, lot (pre-filled from county data).

**Fallback.** No MLS means lean on ATTOM comps plus county sold data and widen the range. MLS-only metrics (precise DOM, sale-to-list) are flagged "estimated/unavailable" in v1.

**v1 cut.** Runnable on seeded ATTOM + portal AVMs + county sold data for 130 Kingfisher. **Pull ATTOM during the trial and cache to seed files so the prototype outlives the trial.**

---

## Section 2: Condition Capture

**What it does.** Builds a structured condition list. Accepts an inspection report if one exists, accepts seller photos (Tier 2 vision tags), runs a guided questionnaire for gaps. Every item tagged three ways: severity, safety, lender impact.

**Data needed.** Inspection report (if any); seller photos (rooms, exterior, deck, crawlspace, panel, HVAC, water heater, roof); questionnaire answers; a canonical component taxonomy every input maps to.

**Data source.**
- Inspection: user upload, parsed. Build parsers for common SC report platforms plus a generic PDF fallback. (User input.)
- Photos: user upload through a vision model that tags presence of conditions (popcorn, worn deck, dated kitchen, water staining). Tags pre-fill the questionnaire; they never set cost. (User input + model.)
- Questionnaire: user input, dynamically ordered (Section 6).
- Taxonomy: **static reference file** mapping each component to severity defaults, safety flag, lender flag. (Static.)

**Keys / accounts.** A vision-capable model API.

**User-facing checklist.** "Do you have an inspection report?" Yes/No. If yes, upload it. If no, the tool proceeds on photos plus questionnaire, **recommends getting one**, and **visibly lowers confidence on condition-driven numbers** ("Without an inspection, these estimates are wider. An inspection tightens them."). Then: upload photos by area; answer the guided questions surfaced.

**Fallback.** No report leans on photos and questionnaire with wider ranges. No photo for an item asks directly. "I don't know" is allowed and treated as maximum uncertainty, ranked for follow-up.

**v1 cut.** Seed 130 Kingfisher's condition from the real inspection already in hand. Photo-upload and vision tagging scaffolded with clear TODOs. Inspection yes/no and the confidence-lowering logic are live.

---

## Section 3: Repair vs Replace vs Credit Options

**What it does.** For each item, prices every viable path (repair, replace, credit, leave) with local South Atlantic costs. The canonical Repair Plan table.

**Data needed.** Per-item repair range and replace range; viability flags; recoup/ROI.

**Data source.** **Static cost table.** Each row holds:
- component id (joins to taxonomy)
- repair_cost_low, repair_cost_high
- replace_cost_low, replace_cost_high
- repairable (bool), creditable (bool)
- recoup_pct (ROI; sourced per Section 4)
- safety_flag (bool), lender_flag (bool)
- notes

No unit-cost columns in v1. (Static, pre-filled then verified.)

**Keys / accounts.** None for v1 (self-maintained static table). RSMeans-style license is a later option.

**User-facing checklist.** None new. Runs on Section 2 output plus the cost table. Seller sees results in the Repair Plan section.

**Fallback.** Thin data for an item shows a wider range labeled "estimate pending quote."

**v1 cut.** Pre-fill the table with real South Atlantic ranges for every 130 Kingfisher item (verify before build). Credit-path value modeled as avoided cost minus likely buyer negotiation premium.

---

## Section 4: Recoup Scoring

**What it does.** Scores how much of each option's cost returns at sale. Separates defect-clearing (protects the whole sale) from upgrading (returns a fraction), because they recoup against different baselines.

**Data needed.** Recoup percentages by project type, localized; a defect-vs-upgrade classifier; buyer-pool logic (which fixes change who can buy).

**Data source.**
- Recoup: **prefer fetched/computed where a real source exists.** Anchor the items that map to Cost vs Value Greenville figures (garage door 217.8%, steel entry door 153.2%, minor kitchen 102.2%, wood deck 82.4%, vinyl window 61.0%); hand-estimate the residue; **label each value's source.** Observe Zonda's excerpt/licensing limits: do not reproduce its table layout in-product; use percentages as one calibration input. (Static, with sourced provenance.)
- Classifier: the taxonomy carries the defect/upgrade flag. (Static.)
- Buyer-pool: HUD/VA/conventional minimum property requirements, kept current. (Static, maintained.)

**Keys / accounts.** A Cost vs Value (Zonda) license only if used in-product at scale; calibration-only use observes excerpt limits.

**User-facing checklist.** None. Seller sees results.

**Fallback.** Missing local recoup falls back to South Atlantic, then national, widening confidence and labeling the source.

**v1 cut.** Pre-fill recoup_pct for every 130 Kingfisher item: anchored where it maps to CvV, estimated otherwise, source labeled in the table.

---

## Section 5: Seller Constraints and Net Proceeds (Financial Layer)

**What it does.** Two halves at two times. Captures constraints early, disguised as context. Reveals the full SC net-proceeds breakdown late, as the payoff. Sets the hard floor below which no plan may net the seller. Connects DOM to carrying cost to net.

**Data needed.** Total owed against the home; ability/willingness to fund repairs; timeline; disclosure-risk tolerance; full SC closing components; DOM baseline and its drivers.

**Constraints intake (rewritten, honest).**
- "Roughly what's left on your mortgage?" One field. **Seller sums everything owed against the home: first mortgage, second, HELOC, liens.** A prompt lists what to include and notes unpaid property taxes, judgments, or liens surface at closing and belong in this figure. No separate second-mortgage field.
- "Could you pay for repairs up front?" Yes/No.
- If No: "Are you prepared to finance the cost of repairs?" Yes/No.
- If No: a strongly-worded recommendation. **Do not steer toward "take it out of the sale,"** which is unrealistic since contractors want paying before closing.
- "How soon do you need to sell?" (feeds DOM/seasonality and the repair-vs-credit lean).

**Days on market, modeled.** DOM is the bridge between condition and money. Each plan carries an estimated time-to-sell; that time drives carrying cost (mortgage, taxes, insurance, utilities on a vacant home) into the net, plus negotiating leverage (a slower house concedes a bigger buyer credit). A cheaper plan that sits longer can net less than a pricier plan that sells fast. **v1:** baseline = local average DOM (static seed), adjusted by the plan's condition level (move-in-ready sells faster than as-is) and a seasonality factor (a summer seller faces buyers who expect move-in-ready, which speeds a clean home and slows a rough one). Flagged as an estimate; sharpened by MLS later.

**SC-specific components (the EVERYTHING-SC list).**
- **Attorney-conducted closing** (SC requires attorney supervision; the *Matrix* rulings). A real line item, not generic "title."
- **Deed recording fees** at the county Register of Deeds.
- **SC deed recording fee / transfer tax** (state + county per $500 of value; confirm current rate). Customarily seller-paid.
- **Title insurance** (owner's custom varies; lender's if buyer finances).
- **Property tax proration** at the correct ratio. SC owner-occupied 4%, other/second home 6%. Flag the 4%-vs-6% question; it depends on assessment status. Uses county millage.
- **Survey** (varies by lender/buyer).
- **Wood-infestation (CL-100) / termite letter**, common in SC, especially FHA/VA. Tie to Section 2: crawlspace moisture raises CL-100 risk.
- **HOA estoppel / transfer fees** where an HOA exists (River Ridge does).
- **Commission** (adjustable; never hard-coded).
- **Seller concessions** the model may recommend instead of repairs.
- **Carrying costs** while pre-listing work happens, and across DOM.
- **Permits.** Flag which recommended work needs a permit in the jurisdiction, and that unpermitted past work can surface at closing/disclosure. **Per-jurisdiction static reference.**

**Data source.** Constraints, payoff, timeline, risk tolerance: user input. SC closing constants, assessment ratios, transfer-tax rate, CL-100, recording, permit rules: **static SC rules file, maintained.** Millage: county tax data, cached. DOM baseline and seasonality factors: **static seed.**

**Keys / accounts.** None external required for v1. Optional later: a title/closing-cost data partner.

**User-facing checklist (early, as context).** The rewritten constraints questions above.
**User-facing checklist (late, as results).** Review the full net-proceeds breakdown per plan.

**Fallback.** No payoff given: proceed without the floor, warn that plans are unconstrained until provided, show floor as "not set." Unknown closing specifics: estimate from SC defaults, labeled.

**v1 cut.** Constraints intake live. SC closing breakdown computed from a pre-filled SC constants file (verify). DOM-driven carrying cost live in the net. Permit lookups scaffolded.

---

## Section 6: The Progressive-Input Engine

**What it does.** Always gives a ranged answer now. Offers the single next question that removes the most uncertainty. Recomputes per answer. Stops when only a quote or inspection can resolve the rest, and says so.

**Data needed.** A confidence range on every recommendation; an uncertainty-contribution score per unknown; a stopping rule per item.

**Data source.** Internal logic, reading Sections 1-5. (Static logic.)

**Keys / accounts.** None.

**User-facing checklist.** Experienced as: an answer now, then "answer this one thing to tighten it," repeated. Never a long upfront form.

**Fallback.** If the seller stops, deliver the best ranged answer, labeled by confidence, and list the open questions that would tighten it.

**v1 cut.** Question-ranking and confidence ranges are the product's IP; build the ranking logic and stopping rule deliberately. Live in v1 for the Repair Plan and net.

---

## Section 7: Optimization and Output (the three-layer model)

**What it does.** Turns costs, recoup, constraints, DOM, and buyer-pool logic into the thing the seller leaves holding. Not one plan: a small set built on a shared floor, plus a knob and a reverse mode.

**The three layers.**
1. **Floor (mandatory, computed, never chosen).** Lender blockers and safety hazards plus essential remediation (smoke). Shown once, plainly: "These happen in every plan. You can't skip them and still sell cleanly." Computed from safety_flag and lender_flag, not selected.
2. **Discretionary work.** Everything else, each with repair / replace / credit / leave.
3. **Plans.** Floor plus a chosen discretionary bundle plus a net number. The seller picks among a few.

**Two directions, one engine.**
- **Forward:** "Given your cash and timeline, here's the smart plan." The recommended plan.
- **Reverse:** "To net $X, here's the lightest path, and what you can drop." Seller sets the target net; the tool finds the minimum discretionary work that reaches it; floor stays mandatory. **Reverse mode is in v1.**

**Presets plus a knob (no sprawl).** Three or four named presets (recommended, leaner, do-everything) plus a live knob: the seller checks/unchecks discretionary items and watches spend, net, and ROI move in real time. Presets for the anxious; the knob for the hands-on. Same engine. Not ten plans.

**Buyer-pool / financing as hard constraint.** A safety hazard (e.g., the deck's open risers and loose railings) can trigger an FHA/VA appraiser-required repair; the loan won't close until it's fixed, so "take it off the price" fails for those buyers regardless of credit. This is hard constraint, in v1. Soft buyer psychology (staging, emotional appeal) is deferred. The one soft factor kept is seasonality, modeled as a DOM/expectation input.

**Self-contained output.** The artifact must read cold. A spouse or helper who never did intake should understand it: each plan carries its own short why, the floor is explained in plain terms, and the net shows its math. No dashboard-only output that needs the live tool to make sense.

**Data source.** Internal optimizer reading all prior sections. (Static logic.)

**v1 cut.** Live: floor layer, 3-4 presets, the live knob, reverse net-goal mode, DOM-driven net, the canonical table. Stay in the legal lane: flag a disclosure obligation, never advise whether to disclose (that's the seller's attorney, SC).

---

## Cross-Cutting: Static Reference Assets to Build (seller-owned)

Pre-filled then verified, these are what the coding agent must never invent:
- Component taxonomy (the spine everything joins to).
- Cost table (repair/replace ranges, viability, flags, per component).
- Recoup/ROI table (sourced: CvV-anchored or estimated, labeled).
- Lender/safety flag rules (FHA/VA/conventional minimum property requirements).
- SC closing-constants file (attorney closing, transfer tax, 4%/6% ratios, CL-100, recording, HOA estoppel).
- Per-jurisdiction permit reference.
- DOM baseline + seasonality factors.
- Questionnaire bank (the guided condition questions, with branching and when each appears).

## Cross-Cutting: Fetched-Then-Cached Assets (property-specific)
- County parcel/tax facts (no uniform SC API; cache).
- AVMs (ATTOM + 3 portals; seed for v1).
- Comps, actives, county sold records (ATTOM + county; seed for v1).
- DOM baseline for the local market.

## Cross-Cutting: External Accounts (full ideal)
- ATTOM Data API (have trial; pull and cache during it).
- Vision model API (Tier 2 tagging).
- MLS/RESO license (long-pole, later).
- Optional later: RSMeans-style cost license; Zonda/CvV license; portal AVM partner; title/closing-cost partner.

## What This Document Is Not
The framework. Not the UX/UI spec (flow, screens, voice, accessibility), not the build-prerequisites checklist (the assets you prepare), not the technical handoff (repo, data model, deployment). Those are the companion docs.
