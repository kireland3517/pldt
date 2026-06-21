# START HERE

Single source of truth for this project. Read this first, then do Step 0 before anything else.

## Project
A pre-listing decision tool for home sellers. It takes a property's photos and a seller questionnaire, prices every repair / replace / credit option, and outputs a three-layer recommendation: a mandatory **Floor** of work, **discretionary** options, and **3-4 named plans** plus a **live knob** and a **reverse net-goal mode**.

## Where we are
All planning docs and the general reference data are written and pre-filled. No code yet. Next step is to build the v1 prototype, leading with the **capture pipeline**, then run the **blind validation test** on 130 Kingfisher Dr, Simpsonville SC.

## The tool is GENUINELY BLIND
It knows what a home CAN have (the **library**), not what any specific home DOES have until photos and the questionnaire tell it. There is no "load condition from a file" path. Condition enters only through capture. The 130 Kingfisher inspection is an answer key the running tool must NEVER read.

---

## Step 0: Set up the folder (do this before building)
The files are currently flat. The quarantine and the data loader depend on structure. Create these subfolders and move files in:

```
reference/      <- components_library.csv, instance_schema.csv,
                   sc_closing_constants.json, dom_seasonality.json,
                   questionnaire_bank.json, README_data_dictionary.md
seed/           <- property_inputs_130_kingfisher.json
validation/     <- answer_key_130_kingfisher.json, README_validation_protocol.md
docs/           <- Framework.md, UX_UI_Spec.md,
                   Build_Prerequisites_Checklist.md,
                   PreListing_Tool_Technical_Handoff.md
(root)          <- START_HERE.md
```

The one that MUST happen for blindness: `answer_key_130_kingfisher.json` and `README_validation_protocol.md` go into `validation/`, which the running tool's data loader is never pointed at. The rest is tidiness that matches the handoff's repo structure.

If using Cowork to do it:
> Create subfolders reference/, seed/, validation/, and docs/. Move files per the Step 0 list in START_HERE.md. The validation/ move is mandatory. Confirm when done.

---

## Read in this order
1. docs/Framework.md
2. docs/UX_UI_Spec.md
3. docs/Build_Prerequisites_Checklist.md
4. docs/PreListing_Tool_Technical_Handoff.md  (start with the BLIND RULE at the top)
5. reference/README_data_dictionary.md, then components_library.csv, instance_schema.csv, and the JSONs
6. seed/property_inputs_130_kingfisher.json  (front-door inputs only)
7. validation/README_validation_protocol.md and validation/answer_key_130_kingfisher.json  (running tool must NEVER read these)

## Stack
React front end, FastAPI/Python back end, Supabase for session state, Railway deploy via GitHub auto-push.

## Locked decisions
- Hub-and-sections UX.
- Three-layer output: mandatory Floor, discretionary work, 3-4 presets + live knob + reverse net-goal mode.
- Genuinely blind: a general common-house library + a blank instance layer filled only by capture.
- WCAG 2.2 AA. South Atlantic / SC-specific. v1 validates on 130 Kingfisher.

## Verify before trusting the data
1. The eligibility flags and `floor_trigger` in components_library.csv (they define the Floor across ALL houses now).
2. Cost ranges are general market figures, not reverse-engineered from 130 Kingfisher.
3. SC transfer-tax rate and the 4% vs 6% proration in sc_closing_constants.json.
4. base_dom (60) in dom_seasonality.json.
5. The 5 CvV-anchored recoup values (GAR-01, XDR-01, KIT-01, DECK-01, WIN-01); respect Zonda excerpt limits.

## Next action
Follow the Build Order in the Technical Handoff:
1. Scaffold the repo, load the LIBRARY from reference/, create a BLANK instance, do not load anything from validation/.
2. Build CAPTURE FIRST (photos -> presence/condition tags + questionnaire). This is the tool's core function and the test depends on it.
3. Backend logic: condition -> repair_replace -> recoup -> floor -> dom -> net_proceeds -> optimizer.
4. Endpoints, then resumable state.
5. Front end: capture/intake flow, then the hub + knob, then sections, then popups and export.
6. Wire Supabase, deploy to Railway.
7. Run the BLIND validation test on 130 Kingfisher and score against the quarantined answer key. Never feed the tool answers a normal seller wouldn't know.
