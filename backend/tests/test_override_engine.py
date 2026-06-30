"""
Stage 2 Step 1 -- override engine regression test.

Proves backend/app/logic/net_proceeds.py + optimizer.py reproduce the
documented production net EXACTLY at zero overrides, then exercises a
global override (commission), a reset, and a per-plan override
(repair_cost), asserting isolation between plans.

Fixture: 130 Kingfisher Dr, Simpsonville SC -- same presence/condition
answers as test_kingfisher_chain.py. Sale price is a SYNTHETIC constant
($305,000 mid / $275,000-$335,000 range): the seed's fetched_comps is
intentionally empty until a live ATTOM call populates it, and
valuation.py is untouched by this change, so it is not exercised here.
The override engine's correctness does not depend on the sale price
value -- net = price - deductions, and the override layer only touches
the deductions side.

BASELINE values below were captured from this exact fixture against the
production engine on 2026-06-30, before the override layer was added.
If a future, intentional change to net_proceeds.py legitimately changes
these numbers, update the constants below in the same commit and explain
why in the commit message.

Run: python backend/tests/test_override_engine.py
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.data_loader import ReferenceData, load_property_inputs
from app.logic.capture import run_capture
from app.logic.condition import build_condition_list
from app.logic.repair_replace import build_repair_rows
from app.logic.recoup import attach_recoup
from app.logic.floor import compute_floor
from app.logic.optimizer import build_plans
from app.models import CaptureSubmission, PresenceAnswer, ConditionAnswer

failures = []

def check(label, condition, detail=""):
    tag = "MATCH" if condition else "MISMATCH"
    suffix = "  (" + detail + ")" if detail else ""
    print("  [" + tag + "] " + label + suffix)
    if not condition:
        failures.append(label)
    return condition


BASELINE_NET = {
    "leaner":        131534.24,
    "recommended":   131586.98,
    "do_everything": 131181.43,
}


def build_fixture():
    ref = ReferenceData()
    prop = load_property_inputs("130_kingfisher")
    seller = prop.get("seller_frontdoor_constraints", {})

    presence_answers = [
        PresenceAnswer(question_id="P-DECK", component_id="DECK-01", answer="yes"),
        PresenceAnswer(question_id="P-CRAWL", component_id="FND-01", answer="crawlspace"),
        PresenceAnswer(question_id="P-PORCH", component_id="PRCH-01", answer="no"),
        PresenceAnswer(question_id="P-GARAGE", component_id="GAR-01", answer="no"),
        PresenceAnswer(question_id="P-FIRE", component_id="DET-01", answer="yes"),
        PresenceAnswer(question_id="P-ELEC", component_id="ELEC-01", answer="yes"),
        PresenceAnswer(question_id="P-HVAC-AGE", component_id="HVAC-01", answer="20-25"),
        PresenceAnswer(question_id="P-WH-AGE", component_id="WH-HTR-01", answer="25+"),
        PresenceAnswer(question_id="P-ROOF-AGE", component_id="ROOF-01", answer="unknown"),
    ]
    condition_answers = [
        ConditionAnswer(question_id="Q-INSP", component_id="HVAC-01", answer="aged",
                         maps_to_condition="aged; functioning but near end of typical service life",
                         maps_to_severity="low"),
        ConditionAnswer(question_id="Q-INSP", component_id="WH-HTR-01", answer="beyond_service_life",
                         maps_to_condition="beyond service life; ~27 yr water heater",
                         maps_to_severity="high"),
        ConditionAnswer(question_id="Q-INSP", component_id="ROOF-01", answer="unknown_age",
                         maps_to_condition="age unknown; no active leak observed",
                         maps_to_severity="medium"),
        ConditionAnswer(question_id="Q-CRAWL-1", component_id="FND-01", answer="unsure",
                         maps_to_condition="crawlspace condition unknown; recommend assessment",
                         maps_to_severity="low"),
        ConditionAnswer(question_id="Q-DECK-1", component_id="DECK-01", answer="yes"),
        ConditionAnswer(question_id="Q-SMOKE-1", component_id="REM-01", answer="no"),
        ConditionAnswer(question_id="Q-ELEC-1", component_id="ELEC-01", answer="no"),
        ConditionAnswer(question_id="Q-INSP", component_id="DET-01", answer="old",
                         maps_to_condition="old; age unknown; test before listing",
                         maps_to_severity="low"),
    ]
    submission = CaptureSubmission(
        session_id="kingfisher-override-regression",
        has_inspection_report=False,
        photo_tags=[],
        presence_answers=presence_answers,
        condition_answers=condition_answers,
    )

    instance = run_capture(submission, ref)
    cond_list = build_condition_list(instance, ref, has_inspection=False)
    repair_rows = build_repair_rows(cond_list)
    enriched = attach_recoup(repair_rows, ref.library)
    floor_result = compute_floor(enriched)

    valuation = {
        "low": 275000.0, "mid": 305000.0, "high": 335000.0,
        "avm_avg": None, "confidence": 0.75,
        "note": "SYNTHETIC sale price for override-engine regression test only.",
    }

    return ref, prop, seller, enriched, floor_result, valuation


def run():
    ref, prop, seller, enriched, floor_result, valuation = build_fixture()
    dom_data = ref.dom
    closing_const = ref.sc_closing

    print("=" * 70)
    print("OVERRIDE ENGINE REGRESSION TEST -- 130 Kingfisher Dr (synthetic price)")
    print("=" * 70)

    print("")
    print("--- PASS 1: zero overrides vs. documented baseline ---")
    zero = build_plans(
        enriched_rows=enriched, floor_result=floor_result, valuation=valuation,
        dom_data=dom_data, closing_constants=closing_const, property_inputs=prop,
        seller_inputs=seller, listing_month=6, commission_rate=None, has_hoa=False,
        overrides_by_plan=None,
    )
    for level, expected in BASELINE_NET.items():
        actual = zero[level]["net_proceeds"]["net_proceeds"]
        check(level + ": net_proceeds == baseline", actual == expected,
              "expected=" + str(expected) + " actual=" + str(actual))
        for li in zero[level]["net_proceeds"]["line_items"]:
            if li["key"] in ("mortgage_payoff", "seller_credits", "other_seller_costs"):
                continue
            check(level + ": '" + li["label"] + "' calculated_amount == amount at zero overrides",
                  li["calculated_amount"] == li["amount"])
            check(level + ": '" + li["label"] + "' override_amount is None at zero overrides",
                  li["override_amount"] is None)

    print("")
    print("--- PASS 2: global override -- commission 6% -> 5% ---")
    commission_override = build_plans(
        enriched_rows=enriched, floor_result=floor_result, valuation=valuation,
        dom_data=dom_data, closing_constants=closing_const, property_inputs=prop,
        seller_inputs=seller, listing_month=6, commission_rate=0.05, has_hoa=False,
        overrides_by_plan=None,
    )
    for level in BASELINE_NET:
        base_np = zero[level]["net_proceeds"]
        ov_np   = commission_override[level]["net_proceeds"]
        expected_delta = base_np["gross_sale_price"] * 0.01
        actual_delta = ov_np["net_proceeds"] - base_np["net_proceeds"]
        check(level + ": net moved up by the commission delta",
              abs(actual_delta - expected_delta) < 0.01,
              "expected +" + format(expected_delta, ".2f") + " got +" + format(actual_delta, ".2f"))

    print("")
    print("--- PASS 3: reset -> exact baseline ---")
    reset = build_plans(
        enriched_rows=enriched, floor_result=floor_result, valuation=valuation,
        dom_data=dom_data, closing_constants=closing_const, property_inputs=prop,
        seller_inputs=seller, listing_month=6, commission_rate=None, has_hoa=False,
        overrides_by_plan=None,
    )
    for level, expected in BASELINE_NET.items():
        actual = reset[level]["net_proceeds"]["net_proceeds"]
        check(level + ": net_proceeds == baseline after reset", actual == expected,
              "expected=" + str(expected) + " actual=" + str(actual))

    print("")
    print("--- PASS 4: per-plan override -- leaner.repair_cost (isolation) ---")
    per_plan = build_plans(
        enriched_rows=enriched, floor_result=floor_result, valuation=valuation,
        dom_data=dom_data, closing_constants=closing_const, property_inputs=prop,
        seller_inputs=seller, listing_month=6, commission_rate=None, has_hoa=False,
        overrides_by_plan={"leaner": {"repair_cost": 9999.0}},
    )
    leaner_np = per_plan["leaner"]["net_proceeds"]
    leaner_repair = next(li for li in leaner_np["line_items"] if li["key"] == "repair_cost")
    check("leaner: repair_cost override_amount applied", leaner_repair["override_amount"] == 9999.0)
    check("leaner: repair_cost calculated_amount preserved",
          leaner_repair["calculated_amount"] == zero["leaner"]["net_proceeds"]["repair_spend"])
    for level in ("recommended", "do_everything"):
        check(level + ": untouched by leaner's override (plan isolation)",
              per_plan[level]["net_proceeds"]["net_proceeds"] ==
              zero[level]["net_proceeds"]["net_proceeds"])

    print("")
    print("=" * 70)
    if failures:
        print("RESULT: " + str(len(failures)) + " MISMATCH(ES) -- DO NOT PUSH")
        for f in failures:
            print("  - " + f)
        return 1
    print("RESULT: ALL CHECKS MATCH")
    print("=" * 70)
    return 0


exit_code = run()
sys.exit(exit_code)
