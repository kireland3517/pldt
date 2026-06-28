# Pre-Listing Decision Tool: UX/UI Specification

How the seller experiences the tool: architecture, navigation, screens, the output model, interaction patterns, voice, accessibility. Folded current with all decisions through today. Paired with the Framework, the Build-Prerequisites Checklist, and the Technical Handoff.

## Settled UX Decisions
- **Device:** desktop-first, responsive. Photo capture is the mobile-strong moment.
- **Session:** resumable, persistent state.
- **Seller mindset:** anxious, overwhelmed. Control through clarity, not cheerleading.
- **Voice:** calm, plain, direct. Sentence case. No filler. No cheerleading.
- **Architecture:** hub and sections. One hub synthesizes; four sections hold substance; popups are self-complete answers that can offer a door to a section.
- **Output model:** three layers (mandatory floor, discretionary work, plans), shown as 3-4 presets plus a live knob plus a reverse net-goal mode.
- **Editing:** linear intake once, then everything is a live editable model. No "start over."
- **Agent stance:** neutral. Print, share, export first-class, mapped to sections.
- **Accessibility:** WCAG 2.2 AA, with frontend-design principles for the visual identity.

---

## Part 1: Architecture (hub and sections)

**Hub: Scenario Comparison.** Synthesizes everything into the plans the seller chooses among. Holds no source data of its own.

**Sections (four real destinations).** Each a place worth standing in, navigable directly, with its own export unit:
1. **Market Data** — valuation, AVMs reconciled, comps, actives, trends, DOM.
2. **Condition** — the defect list from photos, inspection, questionnaire, with severity/safety/lender tags.
3. **Repair Plan** — the canonical line-item table and the live-editing surface.
4. **Net Proceeds** — full SC closing breakdown and bottom-line math.

**Popups.** Self-complete: conclusion, plain-language why, confidence, key inputs. The end of the road for the typical seller. Some popups offer a door to a section, labeled as evidence ("See the comps"), only when that section is worth standing in. Trivial answers get no door. This prevents tab sprawl.

So: one hub, four sections, popups that are answers, not stepping stones.

---

## Part 2: The Output Model (the thing the seller leaves holding)

The most important part. The output is three layers, presented as a small set of plans plus a knob.

**Layer 1: the Floor.** The work that happens in every plan: lender blockers, safety hazards, smoke remediation. Computed from safety/lender flags, never chosen. Shown once, plainly: "These happen in every plan. You can't skip them and still sell cleanly." Not repeated inside each plan. It is the shared base.

**Layer 2: Discretionary work.** Everything else, each with repair / replace / credit / leave.

**Layer 3: Plans.** Floor plus a discretionary bundle plus a net number. A plan reads: "Floor (always) + these choices = spend $X, net $Y, sells in ~Z days."

**Presented as 3-4 presets plus a knob.**
- **Presets:** recommended, leaner, do-everything. Named, with a one-line tradeoff each. The recommended one is marked (text + marker, not color alone).
- **The knob:** the seller steps off a preset and checks/unchecks discretionary items on the canonical table, watching spend, net, and ROI update in real time. Presets for the anxious; the knob for the hands-on. Same engine.
- **Reverse net-goal mode:** the seller types a target net; the tool finds the lightest discretionary bundle that reaches it and shows what was dropped. Floor stays mandatory.

**Discipline:** 3-4 presets and a knob. Never ten plans. Choice overload is poison for an anxious seller.

**Self-contained rule:** the output must read cold. A spouse or helper who never did intake understands it. Each plan carries its own short why; the floor is explained in plain terms; the net shows its math. No dashboard-only output that needs the live tool to make sense. This is also the export artifact.

**The canonical table layout (the Repair Plan section and the knob surface):**
component | repair range | replace range | better-value call | recoup / ROI % | notes

Every column is plain-readable. ROI is shown as a percentage with its source on hover (CvV-anchored or estimated).

---

## Part 3: Navigation Model
- **Persistent primary nav** to the hub and four sections. Never more than one click away.
- **Hub is home.** Default landing after intake; every section has a clear path back.
- **Popup doors are shortcuts, not the only route.** Market Data is reachable from the comp popup, the valuation card, or the nav.
- **Global summary bar** (net, spend, floor) rides across the hub and all sections. The mandatory numbers never disappear.
- Orientation comes from the persistent nav and the summary bar, not a back-button trail, because after intake the tool is a live model, not a wizard.

---

## Part 4: The Experience Arc
1. **Orient** — "this will help, and it won't be painful." The whole path shown before heavy input.
2. **Intake** — "this is manageable." Linear, chunked, resumable. The mortgage trust moment lives here.
3. **Reveal** — "now I understand my options." The hub and its plans.
4. **Decide and act** — "I know what to do and I can take it with me." Commit, edit freely, export.

Intake is linear and finite. Everything after the first reveal is a live, navigable workspace.

---

## Part 5: Screen-by-Screen

### 5.1 Landing / Orient
Plain headline naming the payoff (what you net, what's worth doing). A real three-step "how it works." One primary action: start. A reassurance line: stop anytime, resume later.
Voice: "See what your home could net, and exactly what's worth doing before you list. About 15 minutes. Stop and resume anytime."

### 5.2 Intake (linear, chunked, resumable)
1. **Address.** One field; county facts pulled behind the scenes.
2. **Confirm basics.** Beds, baths, sqft, lot, pre-filled; seller corrects. High trust, low effort.
3. **Condition capture:**
   - **"Do you have an inspection report?" Yes/No.** If yes, upload. If no, proceed on photos plus questionnaire, recommend getting one, and **visibly lower confidence on condition-driven numbers** ("Without an inspection, these estimates are wider. An inspection tightens them.").
   - **Photo upload.** Mobile-strong moment: offer a "continue on your phone" handoff (QR or plain link), then return to desktop. Tier 2 vision tags pre-fill the questionnaire.
   - **Guided questions.** Only the gaps photos and report couldn't resolve. Dynamically ordered (Part 7).
4. **Your situation (constraints, as context):**
   - "Roughly what's left on your mortgage?" One field. **Prompt: include everything owed against the home, first, second, HELOC, liens; unpaid taxes/judgments belong here too.** No separate second-mortgage field.
   - "Could you pay for repairs up front?" Yes/No.
   - If No: "Are you prepared to finance the cost of repairs?" Yes/No.
   - If No: a strongly-worded recommendation. **Never frame costs as coming out of the sale.**
   - "How soon do you need to sell?" (feeds DOM and seasonality).

Persistent progress indicator; each step writes state; a returning seller lands on the next unfinished step intact.

### 5.3 The Hub: Scenario Comparison
**A. Pinned summary bar (global):** net proceeds (largest), total spend, your floor. Net always shown against the floor. Nearing the floor signals with text + icon + color, never color alone.
**B. Plan presets, side by side:** recommended (distinguished), leaner, do-everything. Each shows spend, net, estimated time-to-sell, and a one-line tradeoff. The Floor is shown once above or beside the presets, marked mandatory.
**C. The knob:** selecting a preset reveals its discretionary choices on the canonical table; the seller checks/unchecks and watches the summary bar move. A reverse-mode control lets the seller set a target net instead.
**Transparency:** each model number carries a "why" affordance. Hover reveals a self-complete popup (conclusion, why, confidence, inputs); the same target is clickable and keyboard-focusable (hover is the accelerator, click the guarantee). Section-level evidence gets a door, never a second popup.
**Accessibility:** popups dismissible (Esc, click-away), persistent on hover (1.4.13); the comparison also exists as a real data table for screen readers.

### 5.4 The Sections
Four destinations, each with one job, a path back, and the global summary bar pinned.
- **Market Data:** as-is range, AVMs reconciled, comps, actives, trends, DOM. Where "See the comps" leads.
- **Condition:** full condition list with severity/safety/lender tags and inline photos.
- **Repair Plan:** the canonical table and the live knob. Where "See the full plan" leads.
- **Net Proceeds:** full SC closing detail (attorney closing, transfer tax, CL-100, proration at the right ratio, HOA estoppel, recording, concessions, carrying costs, DOM-driven carry) and the bottom line.

### 5.5 Edit and Recompute (live workspace)
After the first reveal the whole tool is live. Two surfaces: a revisitable "your inputs" panel (any value editable in place) and the line-item choices on the Repair Plan table. On any edit, recompute downstream and highlight what moved (instant, not animated, under reduced-motion). Nothing else resets. The progressive "answer one more question to tighten this" prompts appear here as dismissible offers, never blockers.

### 5.6 Export, Print, Share
Each section is an export unit, plus a combined report.
- **Print:** clean paginated report (plans, chosen plan, line items, net), print stylesheet.
- **Share:** read-only link, mortgage figure redacted by default.
- **Export:** PDF and CSV of the plan; per-section or full.
Self-contained rule applies: the exported artifact reads cold for a helper who wasn't there.

---

## Part 6: The Live-Editing Model (cross-cutting)
First pass linear, everything after is live. Intake ends; the seller is never trapped. Editing shows consequence: change the payoff, the floor moves; flip the deck from replace to credit, spend drops, net rises, time-to-sell shifts, and the moved numbers highlight. No "start over," ever.

---

## Part 7: Question Sequencing (cross-cutting)
1. **Intake** front-loads low-effort high-trust items and defers the mortgage ask until the seller is invested.
2. **The live workspace** surfaces at most one "tighten this" suggestion at a time, attached to the recommendation it sharpens, dismissible, never blocking.
3. **The tool always shows an answer now.** Ranges narrow as inputs arrive; they never gate the first answer.

---

## Part 8: The Mortgage Trust Moment (cross-cutting)
Late in intake, after investment. Framed as context, one field. Reason stated inline: "We use this to set your floor, the number you don't want to drop below. It stays private." Plain privacy signal; redacted from shared links. Graceful skip: decline proceeds, floor shows "not set," plans noted as unconstrained. Declining never blocks.

---

## Part 9: Visual Identity and Voice
**Visual (frontend-design principles, not templated defaults):** a calm financial-decision tool for an anxious person. Trustworthy, clear, quietly confident. Boldness spent on the hub and summary bar; everything else quiet. Avoid the generic AI defaults (cream-terracotta-serif, black-acid-accent, broadsheet-hairline). Derive palette and type from the subject: home, ground, stability, clarity. Typography must make numbers legible: a restrained display face, a highly legible data face. Exact palette/type belong to the visual-design pass.
**Voice:** sentence case, plain verbs, active voice. A control says what it does. Consistent vocabulary across hub and sections. Errors and empty states give direction, not mood ("We couldn't find county records for this address. Enter the basics and we'll continue."). Never cheerleads.

---

## Part 10: Accessibility (WCAG 2.2 AA, concrete)
- Contrast 4.5:1 text (1.4.3), 3:1 large/UI (1.4.11).
- Color never the only signal (floor warning, recommended plan, status use text+icon+color) (1.4.1).
- Full keyboard operation incl. popups, plan selection, the knob, nav; visible focus, never obscured (2.1.1, 2.4.7, 2.4.11).
- Content on hover/focus dismissible, hoverable, persistent (1.4.13). Hover never the only path.
- Targets at least 24x24 CSS px (2.5.8).
- Persistent visible labels; specific field-tied errors (3.3.1, 3.3.2). Never re-ask given info (3.3.7).
- Reduced-motion respected for the change-highlight (2.3.3).
- Plain language; financial/SC-legal terms get a plain-language gloss on first use in the popup.
- Scenario comparison available as a real data table; section content uses proper headings/landmarks; exported PDFs tagged.
- No time limits, no session loss (2.2.1).

---

## Part 11: What This Document Is Not
The experience spec. Not the visual-design pass (exact palette, type, components, spacing), not the build-prerequisites checklist (assets you prepare), not the technical handoff (repo, data model, deployment). Those are the companion docs.
