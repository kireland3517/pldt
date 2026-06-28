# Questionnaire Bank: Provenance and Design

The questionnaire was rebuilt against two recognized standards so it is general and blind, not shaped by any one property. This document records where the questions come from and how the engine should use them.

## Why standards-based
The earlier bank leaned toward one property's specifics and lacked depth. The fix was not to invent more questions but to anchor coverage to standards a seller and an inspector already use:

- **SC Residential Property Condition Disclosure Statement (SCR230 / "seller disclosure").** State-required form an owner completes before a contract. Covers eight areas: water supply and sewage; roof and structural; plumbing/electrical/HVAC; wood-destroying insects; appliances; environmental/hazardous (mold, asbestos, lead, radon, meth, etc.); HOA/restrictions; rental/lease. These are already written as questions a seller answers about their own home, which is exactly the blind-capture need.
- **InterNACHI International Standards of Practice (3.1-3.10).** Defines what a general home inspection covers: 3.1 Roof, 3.2 Exterior, 3.3 Basement/Foundation/Crawlspace/Structure, 3.4 Heating, 3.5 Cooling, 3.6 Plumbing, 3.7 Electrical, 3.8 Fireplace, 3.9 Attic/Insulation/Ventilation, 3.10 Doors/Windows/Interior.

The disclosure form supplies the seller-knowledge layer (things only the owner knows). InterNACHI supplies the systematic component coverage (so nothing major is skipped). Together they are the general backbone; component-specific condition questions layer on top.

## Four sections, in order
1. **Presence** - which library components this home has (InterNACHI-mapped). Photos pre-fill where visible; questions confirm and fill the rest.
2. **Condition** - assess present components, with branching. InterNACHI-mapped. Datedness and subtle defects (the things vision misses) are asked of the seller directly.
3. **Disclosure** - SC SCR230 seller-knowledge items vision and inspection can't see (environmental hazards, known past problems, HOA).
4. **Constraints** - front-door financial inputs (payoff split into primary/secondary/liens, pay-up-front, timeline, optional credits/other costs).

## Two design rules baked in
- **The "inspect" resolution.** Honoring InterNACHI's own limit (an inspection identifies visible material defects, not hidden scope or cost), any scope-unknown item the seller answers "unsure / cannot access" resolves to an **inspect** action: shown as "get this checked before deciding," excluded from plan cost totals, never given a fabricated cost. This covers crawlspace moisture, electrical behind walls, fireplace/flue, foundation cracks.
- **Floor candidates are staged, not written.** A condition answer that implies a safety/lender defect produces a Floor *candidate*. It only enters the mandatory Floor after explicit seller confirmation. The branch targets (floor_candidate_*) feed the confirmation gate, not a direct write.

## Honest limits (state these, don't paper over)
- Hidden defects a seller can't see (junction boxes inside walls, moisture behind finishes, smoke residue in ducts) surface only if a question asks, and even then the answer is "unsure -> inspect" as often as not. The questionnaire narrows uncertainty; it does not replace an inspection. Confidence is lower for any component assessed without one.
- Datedness (kitchen, bath, flooring) is a seller value-judgment, not a defect, and is asked as such.

## Maps-to integrity
Every question carries a `maps_to` of one or more component_ids from components_library.csv (or a `_closing_*` key for closing-cost inputs like HOA). The seller never sees these IDs; they are the join the engine uses to write the instance.
