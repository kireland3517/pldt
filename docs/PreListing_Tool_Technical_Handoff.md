# Pre-Listing Decision Tool: Technical Handoff

The build-ready document. Repo structure, data model, core logic, API surface, and deployment. A coding agent (Cursor / Claude Code / Codex) executes against this plus the prepared reference data. Where data is needed, it comes from the prepared files. The agent must not invent values.

## Stack
- **Front end:** React (the hub, four sections, popups, the live knob, intake flow).
- **Back end:** FastAPI (Python). Holds the optimizer and all compute logic.
- **State:** Supabase (Postgres) for resumable sessions and stored inputs/results.
- **Reference data:** the prepared files in /data (loaded at startup or seeded into Supabase). Not generated.
- **Deploy:** GitHub repo, Railway watches it, auto-deploys on push.


## BLIND RULE (read before anything)
The tool must be genuinely blind to any specific property. It knows what a home CAN have (the **library**), never what a home DOES have until capture tells it. Two layers, never mixed:
- **Library** (`data/reference/components_library.csv`): universal common-house catalog. Cost ranges, recoup, eligibility flags. No house facts.
- **Instance** (`data/reference/instance_schema.csv`): per-property, starts BLANK. Filled only by the capture pipeline (photos + questionnaire).

There is NO "load condition from file" path in the running app. Condition enters only through capture. The 130 Kingfisher inspection lives in `validation/` as an answer key the running tool must never read. See validation/README_validation_protocol.md.

## Hard rule for the coding agent
Any number that describes a component cost, a recoup percentage, an SC closing rate, a DOM factor, or the 130 Kingfisher property comes from /data. If a value is missing, surface a TODO; do not fabricate. The reference data is the source of truth.

---

## Repo Structure

```
prelisting-tool/
  README.md                      # points to /docs, START_HERE first
  docs/                          # the spec set (framework, ux, checklist, this doc)
  data/
    reference/
      components_library.csv     # GENERAL library (universal; not any one house)
      instance_schema.csv        # per-property, BLANK; capture fills it
      sc_closing_constants.json
      dom_seasonality.json
      questionnaire_bank.json    # presence + condition + constraints
      README_data_dictionary.md
    seed/
      property_inputs_130_kingfisher.json   # FRONT-DOOR inputs only
  validation/                    # QUARANTINED. running tool must never read this
    answer_key_130_kingfisher.json
    README_validation_protocol.md
  backend/
    app/
      main.py                    # FastAPI entry, routes
      models.py                  # pydantic schemas
      data_loader.py             # loads /data/reference + seed into memory/DB
      logic/
        capture.py               # photos->presence/condition tags (Tier 2 vision) + questionnaire intake
        valuation.py             # as-is range from comps (size-adjusted); AVM avg as reference
        condition.py             # assembles instance condition from capture; applies library eligibility
        repair_replace.py        # per-item options from cost table
        recoup.py                # ROI scoring, defect vs upgrade
        floor.py                 # computes the mandatory Floor
        dom.py                   # estimated days-on-market + carrying cost
        net_proceeds.py          # SC closing math
        optimizer.py             # presets (forward) + reverse net-goal
      db.py                      # Supabase client
    requirements.txt
    railway.json                 # or Procfile
  frontend/
    src/
      App.jsx
      api/                       # calls to backend
      components/
        SummaryBar.jsx           # global net / spend / floor
        ScenarioComparison.jsx   # the hub
        RepairPlanTable.jsx      # canonical table + the live knob
        sections/                # MarketData, Condition, RepairPlan, NetProceeds
        Popup.jsx                # self-complete, hover+click+keyboard
        Intake/                  # linear, chunked, resumable
      state/                     # session state, resumable
    package.json
  .env.example
```

---

## Data Model (Supabase)

Static reference data does not need DB tables in v1; load it from /data into memory at startup. Persist only what is per-session and mutable.

**sessions**
- id (uuid, pk), created_at, updated_at, status (intake | active | complete)
- property_id (the address/parcel being evaluated)

**inputs** (everything the seller provided, editable)
- id, session_id (fk), key (e.g. mortgage_payoff, timeline, pay_up_front), value (jsonb)
- one row per input so any single value is editable without rewriting the rest

**condition_items** (per session, from inspection/photos/questionnaire)
- id, session_id, component_id (joins components.csv), present (bool), severity, chosen_path (repair|replace|credit|leave), source (inspection|photo|questionnaire), confidence

**results_cache** (recomputed on edit; cache for speed and for resumable view)
- id, session_id, scenario_key, spend, net, estimated_dom, payload (jsonb of the full plan)

The LIBRARY (components_library.csv, sc constants, dom, questionnaire) loads from /data at startup; files stay the source of truth. The INSTANCE is per-session, created BLANK, and filled only by capture. Never seed instance/condition from a property file.

---

## Core Logic (the modules)

### valuation.py
Input: fetched comps + AVMs (public, legitimately available from the address). Output: as-is range, COMPUTED, not loaded.
Rule (confirmed): drive the range from size-adjusted comps (larger sqft sells at lower $/sqft). Show the AVM average alongside as a reference point, not blended in. If comps and AVM average diverge sharply, widen the range and lower confidence. For 130 Kingfisher this computes ~$293k-$303k with the $286,810 AVM average shown as reference. The tool must PRODUCE this; never load a pre-computed range.

### capture.py  (BUILD FIRST - the tool's core function)
Turns seller input into the instance layer. Photos run through Tier 2 vision to set component PRESENCE (does this house have a deck) and visible condition. The questionnaire (presence questions then condition questions from questionnaire_bank.json) fills what photos cannot see. Output: a filled instance (which library components are present, their detected condition). Starts from a BLANK instance every run.

### condition.py
Reads the filled instance from capture, joins to components_library.csv for eligibility, and produces the per-component condition with severity and Floor-eligibility. No file-loading of condition; capture is the only source. Confidence is lower when fewer inputs were given (no inspection).

### repair_replace.py
For each present component, returns repair range and replace range from components.csv, plus repairable/creditable. This feeds the canonical table.

### recoup.py
Attaches recoup_pct and recoup_source. Separates defect_or_upgrade so the scoring uses the right baseline (defect-clearing protects the whole sale; upgrade returns a fraction).

### floor.py
Computes the mandatory Floor from the instance + library, never chosen:
`floor_member = present AND defect_detected AND (safety_eligible OR lender_eligible OR essential_when_needed) AND defect_matches(floor_trigger)`.
This uses the library eligibility flags plus the detected instance defect. REM-01 (smoke remediation) has essential_when_needed=True and only enters the Floor when smoke is detected. The earlier hardcoded-flag and over-tagging issues are resolved in the library.

### dom.py
estimated_dom = base_dom * condition_multiplier(plan) * seasonality_factor(listing_month).
Carrying cost = estimated_dom (in months) * monthly carrying components. A slower plan can net less than a faster, pricier one. All from dom_seasonality.json and sc_closing_constants.json.

### net_proceeds.py
net = sale_price - payoff - commission - SC closing costs - carrying cost - chosen repair spend + (credits handled as price reductions).
SC closing costs from sc_closing_constants.json: attorney closing, transfer tax (per $500), recording, title (if applicable), proration at the correct 4%/6% ratio, CL-100, HOA estoppel, survey. The floor = payoff + selling costs is the line no plan may net below.

### optimizer.py
- **Forward (presets):** build 3-4 named plans (recommended, leaner, do-everything). Recommended = Floor plus the discretionary items whose recoup and constraint fit maximize net under the seller's cash/timeline.
- **Reverse (net-goal):** given a target net, find the lightest discretionary bundle that reaches it; Floor stays mandatory; report what was dropped.
- **The knob:** the front end toggles discretionary items and re-calls the compute endpoint; the optimizer returns updated spend/net/dom/roi live.

---

## API Surface (FastAPI)

- `POST /session` — create a session.
- `GET /session/{id}` — resume (returns inputs, condition, cached results).
- `PUT /session/{id}/input` — upsert one input (editable model).
- `PUT /session/{id}/condition/{component_id}` — set chosen_path for one item (the knob).
- `POST /session/{id}/compute` — recompute; returns plans (presets), Floor, summary numbers.
- `POST /session/{id}/compute/reverse` — body: target_net; returns lightest bundle + dropped items.
- `GET /session/{id}/export?format=pdf|csv&section=...` — self-contained artifact.

Every compute response carries confidence ranges, not just point values (the progressive-input model). The front end shows an answer always; ranges narrow as inputs arrive.

---

## Deployment (GitHub to Railway)

1. Push the repo to GitHub.
2. In Railway, create a project from the GitHub repo. Add two services: `backend` (FastAPI) and `frontend` (React build), or serve the built front end from the backend if you prefer one service.
3. Railway auto-deploys on every push to the tracked branch.
4. Env vars (see .env.example): `SUPABASE_URL`, `SUPABASE_KEY`, `ATTOM_API_KEY`, `VISION_API_KEY` (later), `ALLOWED_ORIGINS`.
5. Supabase: create the project, run the schema (sessions, inputs, condition_items, results_cache), connect via env vars.
6. ATTOM trial: cache pulls into /data/seed now; do not rely on the live key after the trial.

---

## v1 Cut (what runs today vs scaffolded)

**Live in v1 (the blind end-to-end run):**
- The CAPTURE pipeline (photo upload + Tier 2 vision presence/condition tagging + presence/condition questionnaire); valuation computed from comps; condition assembled from capture; Floor computation; repair/replace table; 3-4 presets; the live knob; reverse net-goal; DOM-driven net; SC closing math; resumable state.

**Scaffolded (clear TODOs):**
- Inspection-report parsing (optional input, not required); live AVM/comp fetch (cached for v1); per-jurisdiction permit lookups; MLS metrics.

**Run target (the validation test):** start from front-door inputs only, upload Kingfisher's photos, answer the questionnaire, and have the tool PRODUCE the condition, Floor, plans, net, and report. Then score against validation/answer_key_130_kingfisher.json. The tool never reads the answer key. See validation/README_validation_protocol.md.

---

## Build Order for the Agent
1. Scaffold repo + load the LIBRARY from /data/reference (data_loader.py reads components_library.csv etc.). Create the BLANK instance schema. Do NOT load anything from /validation.
2. Build CAPTURE FIRST: photo upload + Tier 2 vision presence/condition tagging + the presence/condition questionnaire. This is the tool's core function and the test depends on it.
3. backend logic: condition (from capture) -> repair_replace -> recoup -> floor -> dom -> net_proceeds -> optimizer.
4. Compute endpoints, then resumable session endpoints.
5. Front end: the intake/capture flow; then SummaryBar + ScenarioComparison + RepairPlanTable (hub and knob); then sections; popups and export last.
6. Wire Supabase; deploy to Railway.
7. Run the BLIND validation test on 130 Kingfisher (front-door inputs + real photos + honest questionnaire answers), then score against the quarantined answer key.

## What This Document Is Not
The build doc. The full ideal and rationale live in the Framework; the experience in the UX/UI Spec; the assets you prepare in the Checklist; the data itself in /data.
