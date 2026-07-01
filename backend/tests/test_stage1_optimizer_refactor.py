"""
Stage 1 optimizer refactor — proof harness.

Proves that refactoring optimizer.py / net_proceeds.py to expose explicit
included-item-id functions (in addition to the existing level-based ones)
does not change any output for the three standard plans.

Usage:
    python test_stage1_optimizer_refactor.py --capture   # BEFORE the refactor
    python test_stage1_optimizer_refactor.py --verify     # AFTER the refactor (default)

--capture runs build_plans() against the fixture (zero overrides AND a
sample per-plan override) and writes every relevant field, per plan, to
_stage1_baseline.json next to this file.

--verify re-runs the same fixture through the (now refactored) build_plans()
and asserts every captured field is exactly equal to the baseline. Any
mismatch fails loudly and prints which field, which plan, which pass.

Fixture is the same 130 Kingfisher Dr fixture used in
backend/tests/test_override_engine.py (same presence/condition answers),
reused here rather than re-invented so both harnesses stay comparable.
"""
import argparse
import json
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

BASELINE_PATH = Path(__file__).resolve().parent / "_stage1_baseline.json"

# Fields captured per plan, per pass. Whole sub-dicts for dom/net_proceeds
# so line_items, calculated_amount/override_amount/amount are all covered.
PLAN_FIELDS = [
    "adjusted_sale_price",
    "as_is_price",
    "improved_listing_ceiling",
    "value_lift_capped",
    "value_lift_cap_binding",
    "total_repair_cost_mid",
    "plan_roi_pct",
    "dom",
    "net_proceeds",
    "included_items",
    "item_count",
    "lender_gate",
]

LEVELS = ("leaner", "recommended", "do_everything")


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
        session_id="kingfisher-stage1-regression",
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
        "note": "SYNTHETIC sale price for Stage 1 regression test only.",
    }

    return ref, prop, seller, enriched, floor_result, valuation


def run_pass(enriched, floor_result, valuation, dom_data, closing_const, prop, seller,
             overrides_by_plan):
    plans = build_plans(
        enriched_rows=enriched, floor_result=floor_result, valuation=valuation,
        dom_data=dom_data, closing_constants=closing_const, property_inputs=prop,
        seller_inputs=seller, listing_month=6, commission_rate=None, has_hoa=False,
        overrides_by_plan=overrides_by_plan,
    )
    out = {}
    for level in LEVELS:
        out[level] = {f: plans[level][f] for f in PLAN_FIELDS}
    return out


def capture():
    ref, prop, seller, enriched, floor_result, valuation = build_fixture()
    dom_data = ref.dom
    closing_const = ref.sc_closing

    zero = run_pass(enriched, floor_result, valuation, dom_data, closing_const,
                     prop, seller, overrides_by_plan=None)
    with_override = run_pass(enriched, floor_result, valuation, dom_data, closing_const,
                              prop, seller,
                              overrides_by_plan={"leaner": {"repair_cost": 9999.0}})

    baseline = {"zero_overrides": zero, "sample_override": with_override}
    BASELINE_PATH.write_text(json.dumps(baseline, indent=2, sort_keys=True))
    print(f"Captured baseline -> {BASELINE_PATH}")
    for level in LEVELS:
        print(f"  {level}: net_proceeds={zero[level]['net_proceeds']['net_proceeds']}")


def _diff(label, expected, actual, failures):
    if expected == actual:
        print(f"  [MATCH] {label}")
    else:
        print(f"  [MISMATCH] {label}")
        print(f"      expected: {json.dumps(expected, sort_keys=True)}")
        print(f"      actual:   {json.dumps(actual, sort_keys=True)}")
        failures.append(label)


def verify():
    if not BASELINE_PATH.exists():
        print(f"No baseline found at {BASELINE_PATH}. Run --capture first (before the refactor).")
        return 1

    baseline = json.loads(BASELINE_PATH.read_text())
    ref, prop, seller, enriched, floor_result, valuation = build_fixture()
    dom_data = ref.dom
    closing_const = ref.sc_closing

    zero = run_pass(enriched, floor_result, valuation, dom_data, closing_const,
                     prop, seller, overrides_by_plan=None)
    with_override = run_pass(enriched, floor_result, valuation, dom_data, closing_const,
                              prop, seller,
                              overrides_by_plan={"leaner": {"repair_cost": 9999.0}})

    failures = []
    print("=" * 70)
    print("STAGE 1 OPTIMIZER REFACTOR — PROOF OF INERTNESS")
    print("=" * 70)

    print("\n--- PASS 1: zero overrides ---")
    for level in LEVELS:
        for field in PLAN_FIELDS:
            _diff(f"{level}.{field} (zero overrides)",
                  baseline["zero_overrides"][level][field],
                  zero[level][field], failures)

    print("\n--- PASS 2: sample per-plan override (leaner.repair_cost=9999) ---")
    for level in LEVELS:
        for field in PLAN_FIELDS:
            _diff(f"{level}.{field} (sample override)",
                  baseline["sample_override"][level][field],
                  with_override[level][field], failures)

    print("\n" + "=" * 70)
    if failures:
        print(f"RESULT: {len(failures)} MISMATCH(ES) — DO NOT PUSH, DO NOT PROCEED TO STAGE 2")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("RESULT: ALL CHECKS MATCH — all three plans byte-identical, zero overrides and sample override")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()

    if args.capture:
        sys.exit(capture())
    else:
        sys.exit(verify())
