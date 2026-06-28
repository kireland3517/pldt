"""
Blind chain test against 130 Kingfisher Dr, Simpsonville SC.

Runs: valuation -> capture -> condition -> repair_replace ->
      recoup -> floor -> dom -> net_proceeds -> optimizer

Uses ONLY:
  - seed/property_inputs_130_kingfisher.json   (front-door inputs)
  - reference/*.csv / *.json                  (library data)

Never reads validation/answer_key_130_kingfisher.json.

Run: python backend/tests/test_kingfisher_chain.py
"""

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.data_loader import ReferenceData, load_property_inputs
from app.logic.valuation import compute_as_is_range
from app.logic.capture import run_capture
from app.logic.condition import build_condition_list, condition_summary
from app.logic.repair_replace import build_repair_rows
from app.logic.recoup import attach_recoup
from app.logic.floor import compute_floor
from app.logic.dom import estimate_dom, estimate_carrying_cost
from app.logic.optimizer import build_plans
from app.models import (
    CaptureSubmission, PhotoTag, PresenceAnswer, ConditionAnswer,
)


def run():
    print("\n" + "="*60)
    print("BLIND CHAIN TEST — 130 Kingfisher Dr, Simpsonville SC")
    print("="*60)

    # ── 1. Load reference data ──────────────────────────────────
    ref = ReferenceData()
    dom_data      = ref.dom          # dom_seasonality.json
    closing_const = ref.sc_closing   # sc_closing_constants.json
    print(f"\n[1] Library loaded: {len(ref.library)} components")

    # ── 2. Load seed (front-door inputs only) ───────────────────
    prop   = load_property_inputs("130_kingfisher")
    sqft   = prop["public_county_facts"]["sqft"]
    seller = prop.get("seller_frontdoor_constraints", {})
    payoff = seller.get("mortgage_payoff", 0)
    print(f"[2] Seed loaded: {prop['address']} | {sqft} sqft")
    print(f"    Comps: {len(prop.get('fetched_comps', []))}  Payoff: ${payoff:,}")

    # ── 3. Valuation (OLS from comps — never reads answer key) ──
    print("\n[3] VALUATION")
    val = compute_as_is_range(prop)
    print(f"    AVM avg   : ${val['avm_avg']:,.0f}  (reference only, not blended)")
    print(f"    PPSF pred : ${val['ppsf_predicted']:.2f}/sqft at {sqft} sqft")
    print(f"    Range     : ${val['low']:,.0f} – ${val['high']:,.0f}")
    print(f"    Mid       : ${val['mid']:,.0f}")
    print(f"    Confidence: {val['confidence']:.2f}")
    if val.get("note"):
        print(f"    Note      : {val['note']}")

    # ── 4. Capture ───────────────────────────────────────────────
    # Simulate what a seller at 130 Kingfisher would answer.
    # We do NOT read these from the answer key.
    #
    # Property profile:
    #   1999 build, crawlspace, deck (no porch), no garage noted,
    #   HVAC ~25yr (functioning but aging), WH ~27yr (beyond service life),
    #   roof age unknown, no smoke/odor, no visible electrical issues.

    presence_answers = [
        # Generic yes/no answers (question_id used for routing in capture.py)
        PresenceAnswer(question_id="P-DECK",    component_id="DECK-01",   answer="yes"),
        PresenceAnswer(question_id="P-CRAWL",   component_id="FND-01",    answer="crawlspace"),
        PresenceAnswer(question_id="P-PORCH",   component_id="PRCH-01",   answer="no"),
        PresenceAnswer(question_id="P-GARAGE",  component_id="GAR-01",    answer="no"),
        PresenceAnswer(question_id="P-FIRE",    component_id="DET-01",    answer="yes"),
        PresenceAnswer(question_id="P-ELEC",    component_id="ELEC-01",   answer="yes"),
        # Age-band questions
        PresenceAnswer(question_id="P-HVAC-AGE",  component_id="HVAC-01",   answer="20-25"),
        PresenceAnswer(question_id="P-WH-AGE",    component_id="WH-HTR-01", answer="25+"),
        PresenceAnswer(question_id="P-ROOF-AGE",  component_id="ROOF-01",   answer="unknown"),
    ]

    condition_answers = [
        # HVAC: functioning but aging (~25yr unit)
        ConditionAnswer(
            question_id="Q-INSP",
            component_id="HVAC-01",
            answer="aged",
            maps_to_condition="aged; functioning but near end of typical service life",
            maps_to_severity="low",
        ),
        # Water heater: beyond service life (~27yr)
        ConditionAnswer(
            question_id="Q-INSP",
            component_id="WH-HTR-01",
            answer="beyond_service_life",
            maps_to_condition="beyond service life; ~27 yr water heater",
            maps_to_severity="high",
        ),
        # Roof: age unknown; no active leak (seller can't trigger floor without "leak")
        ConditionAnswer(
            question_id="Q-INSP",
            component_id="ROOF-01",
            answer="unknown_age",
            maps_to_condition="age unknown; no active leak observed",
            maps_to_severity="medium",
        ),
        # Crawlspace: no standing water (FND-01 not floor-triggered)
        ConditionAnswer(
            question_id="Q-CRAWL-1",
            component_id="FND-01",
            answer="unsure",
            maps_to_condition="crawlspace condition unknown; recommend assessment",
            maps_to_severity="low",
        ),
        # Deck: no visible structural issue
        ConditionAnswer(
            question_id="Q-DECK-1",
            component_id="DECK-01",
            answer="yes",   # deck structure sound
        ),
        # No smoke / odor
        ConditionAnswer(
            question_id="Q-SMOKE-1",
            component_id="REM-01",
            answer="no",    # no heavy smoke odor
        ),
        # ELEC-01: no visible issues
        ConditionAnswer(
            question_id="Q-ELEC-1",
            component_id="ELEC-01",
            answer="no",    # no visible electrical issues
        ),
        # Smoke detectors: age unknown
        ConditionAnswer(
            question_id="Q-INSP",
            component_id="DET-01",
            answer="old",
            maps_to_condition="old; age unknown; test before listing",
            maps_to_severity="low",
        ),
    ]

    submission = CaptureSubmission(
        session_id="kingfisher-blind-test",
        has_inspection_report=False,
        photo_tags=[],
        presence_answers=presence_answers,
        condition_answers=condition_answers,
    )

    instance = run_capture(submission, ref)
    floor_flagged = [k for k, v in instance.items() if v.get("defect_qualifies_floor")]
    not_present   = [k for k, v in instance.items() if v.get("present") is False]
    present       = [k for k, v in instance.items() if v.get("present") is True]
    print(f"\n[4] Capture complete.")
    print(f"    Present    : {present}")
    print(f"    Not present: {not_present}")
    print(f"    Floor-flagged: {floor_flagged}")

    # ── 5. Condition list ────────────────────────────────────────
    cond_list = build_condition_list(instance, ref, has_inspection=False)
    summary   = condition_summary(cond_list)
    print(f"\n[5] Condition: {summary['total_present']} present, "
          f"{summary['floor_items']} floor items, "
          f"{summary['high_severity']} high severity, "
          f"{summary['low_confidence_items']} low-confidence")

    # ── 6-7. Repair rows + Recoup ────────────────────────────────
    repair_rows = build_repair_rows(cond_list)
    enriched    = attach_recoup(repair_rows, ref.library)
    print(f"\n[6-7] Repair rows ({len(enriched)}) with ROI:")
    for r in enriched:
        fl   = "FLOOR" if r.get("in_floor") else "     "
        bv   = r.get("better_value", "?")
        rp   = r.get("recoup_pct")
        cond = (r.get("condition_detected") or "no defect")[:35]
        print(f"    {fl} {r['component_id']:12s} bv={bv:8s} recoup={rp}%  [{cond}]")

    # ── 8. Floor ─────────────────────────────────────────────────
    floor_result = compute_floor(enriched)
    print(f"\n[8] FLOOR — {floor_result['item_count']} item(s)")
    print(f"    Cost: ${floor_result['cost_low']:,.0f} – ${floor_result['cost_high']:,.0f}  "
          f"(mid ${floor_result['cost_mid']:,.0f})")
    for item in floor_result["items"]:
        contrib = "" if item["cost_contributing"] else " [shared/deduped $0]"
        print(f"      {item['component_id']:12s} {item['display_name'][:28]:28s} "
              f"reason={item['reason']}{contrib}")

    # ── 9. DOM (June listing) ────────────────────────────────────
    dom_leaner = estimate_dom(dom_data, "leaner",        listing_month=6)
    dom_rec    = estimate_dom(dom_data, "recommended",   listing_month=6)
    dom_all    = estimate_dom(dom_data, "do_everything", listing_month=6)
    print(f"\n[9] DOM (June)  leaner={dom_leaner['estimated_dom']}d  "
          f"recommended={dom_rec['estimated_dom']}d  "
          f"do_everything={dom_all['estimated_dom']}d")
    carry = estimate_carrying_cost(dom_leaner, prop, seller)
    print(f"    Carrying (leaner): ${carry['total']:,.0f}  "
          f"({carry['months']} months × ${carry['monthly']:,.0f}/mo)")

    # ── 10. NET PROCEEDS — all three plans ───────────────────────
    print(f"\n[10] NET PROCEEDS")
    plans = build_plans(
        enriched_rows=enriched,
        floor_result=floor_result,
        valuation=val,
        dom_data=dom_data,
        closing_constants=closing_const,
        property_inputs=prop,
        seller_inputs=seller,
        listing_month=6,
        commission_rate=None,   # default 6%
        has_hoa=False,
    )

    for level in ("leaner", "recommended", "do_everything"):
        p  = plans[level]
        np = p["net_proceeds"]
        print(f"\n    [{level}]")
        print(f"      Adjusted sale price : ${p['adjusted_sale_price']:>10,.0f}")
        print(f"      Total deductions    : ${np['total_deductions']:>10,.0f}")
        print(f"      NET PROCEEDS        : ${np['net_proceeds']:>10,.0f}")
        print(f"      DOM                 : {p['dom']['estimated_dom']} days")
        print(f"      Repairs seller does : {p['item_count']} items")
        print(f"      Line items:")
        for li in np["line_items"]:
            print(f"        {li['label']:<38s}: -${li['amount']:>9,.0f}")

    print(f"\n    Scorecard:")
    for row in plans["scorecard"]["plans"]:
        print(f"      #{row['net_proceeds_rank']}  {row['plan']:20s}  "
              f"net=${row['net_proceeds']:,.0f}  dom={row['dom_days']}d")

    print("\n" + "="*60)
    print("BLIND CHECK COMPLETE")
    print(f"Valuation range: ${val['low']:,.0f} – ${val['high']:,.0f}  mid=${val['mid']:,.0f}")
    print("Compare against answer key ONLY after verifying logic is sound.")
    print("="*60 + "\n")


if __name__ == "__main__":
    run()
