"""
Stage 2 Step 3 -- Change 2 verification: an added (ad-hoc) cost-only item
changes net by exactly its cost and leaves value lift byte-identical.

Run: python backend/tests/test_step3_added_item.py
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
from app.logic.optimizer import build_plans, _items_for_level
from app.logic.custom_plan import build_custom_plan
from app.models import CaptureSubmission, PresenceAnswer, ConditionAnswer

failures = []

def check(label, condition, detail=""):
    tag = "MATCH" if condition else "MISMATCH"
    suffix = "  (" + detail + ")" if detail else ""
    print("  [" + tag + "] " + label + suffix)
    if not condition:
        failures.append(label)
    return condition


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
                         maps_to_condition="aged; functioning but near end of typical service life", maps_to_severity="low"),
        ConditionAnswer(question_id="Q-INSP", component_id="WH-HTR-01", answer="beyond_service_life",
                         maps_to_condition="beyond service life; ~27 yr water heater", maps_to_severity="high"),
        ConditionAnswer(question_id="Q-INSP", component_id="ROOF-01", answer="unknown_age",
                         maps_to_condition="age unknown; no active leak observed", maps_to_severity="medium"),
        ConditionAnswer(question_id="Q-CRAWL-1", component_id="FND-01", answer="unsure",
                         maps_to_condition="crawlspace condition unknown; recommend assessment", maps_to_severity="low"),
        ConditionAnswer(question_id="Q-DECK-1", component_id="DECK-01", answer="yes"),
        ConditionAnswer(question_id="Q-SMOKE-1", component_id="REM-01", answer="no"),
        ConditionAnswer(question_id="Q-ELEC-1", component_id="ELEC-01", answer="no"),
        ConditionAnswer(question_id="Q-INSP", component_id="DET-01", answer="old",
                         maps_to_condition="old; age unknown; test before listing", maps_to_severity="low"),
    ]
    submission = CaptureSubmission(session_id="kingfisher-step3-added-item", has_inspection_report=False,
        photo_tags=[], presence_answers=presence_answers, condition_answers=condition_answers)
    instance = run_capture(submission, ref)
    cond_list = build_condition_list(instance, ref, has_inspection=False)
    repair_rows = build_repair_rows(cond_list)
    enriched = attach_recoup(repair_rows, ref.library)
    floor_result = compute_floor(enriched)
    valuation = {"low": 275000.0, "mid": 305000.0, "high": 335000.0, "avm_avg": None,
                 "confidence": 0.75, "note": "SYNTHETIC sale price for Step 3 added-item test."}
    return ref, prop, seller, enriched, floor_result, valuation


def run():
    ref, prop, seller, enriched, floor_result, valuation = build_fixture()
    closing_const = ref.sc_closing

    print("=" * 70)
    print("STEP 3 CHANGE 2 -- added (ad-hoc) cost-only item")
    print("=" * 70)

    # Use recommended's full displayed item set (floor included, per Change 1's
    # new item_ids contract: caller must include floor explicitly now).
    item_ids = _items_for_level(enriched, floor_result, "recommended")
    print(f"\n  item_ids (floor included): {item_ids}")

    baseline = build_custom_plan(
        enriched_rows=enriched, floor_result=floor_result, valuation=valuation,
        closing_constants=closing_const, seller_inputs=seller,
        item_ids=item_ids, item_cost_overrides={}, commission_rate=None, has_hoa=False,
        added_items=None,
    )

    ADDED_COST = 2000.0
    with_added = build_custom_plan(
        enriched_rows=enriched, floor_result=floor_result, valuation=valuation,
        closing_constants=closing_const, seller_inputs=seller,
        item_ids=item_ids, item_cost_overrides={}, commission_rate=None, has_hoa=False,
        added_items=[{"label": "Detached shed repair (not detected by tool)", "cost": ADDED_COST}],
    )

    print(f"\n  baseline value_lift_capped:   {baseline['value_lift_capped']}")
    print(f"  with_added value_lift_capped: {with_added['value_lift_capped']}")
    check("value_lift_capped byte-identical with an added item",
          baseline["value_lift_capped"] == with_added["value_lift_capped"],
          f"baseline={baseline['value_lift_capped']} with_added={with_added['value_lift_capped']}")

    base_net = baseline["net_proceeds"]["net_proceeds"]
    added_net = with_added["net_proceeds"]["net_proceeds"]
    net_delta = round(added_net - base_net, 2)
    print(f"\n  baseline net:   {base_net}")
    print(f"  with_added net: {added_net}")
    print(f"  delta: {net_delta}  (expected exactly -{ADDED_COST})")
    check("net differs by exactly -cost",
          net_delta == -ADDED_COST,
          f"delta={net_delta} expected=-{ADDED_COST}")

    base_repair = baseline["total_repair_cost_mid"]
    added_repair = with_added["total_repair_cost_mid"]
    repair_delta = round(added_repair - base_repair, 2)
    print(f"\n  baseline total_repair_cost_mid:   {base_repair}")
    print(f"  with_added total_repair_cost_mid: {added_repair}")
    print(f"  delta: {repair_delta}  (expected exactly +{ADDED_COST})")
    check("total_repair_cost_mid differs by exactly +cost",
          repair_delta == ADDED_COST,
          f"delta={repair_delta} expected={ADDED_COST}")

    check("adjusted_sale_price unaffected by added item",
          baseline["adjusted_sale_price"] == with_added["adjusted_sale_price"],
          f"baseline={baseline['adjusted_sale_price']} with_added={with_added['adjusted_sale_price']}")

    check("added_items echoed back on response",
          with_added["added_items"] == [{"label": "Detached shed repair (not detected by tool)", "cost": ADDED_COST}],
          f"got={with_added['added_items']}")
    check("added_items_cost_total correct",
          with_added["added_items_cost_total"] == ADDED_COST,
          f"got={with_added['added_items_cost_total']}")

    # Reconciliation: line items still sum to net (Step 2's discipline, still
    # holding here since the added cost folds into the existing repair_cost line).
    lines = with_added["net_proceeds"]["line_items"]
    line_sum_deductions = round(sum(li["amount"] for li in lines), 2)
    gross = with_added["net_proceeds"]["gross_sale_price"]
    reconciled = round(gross - line_sum_deductions, 2)
    print(f"\n  gross={gross} sum(line deductions)={line_sum_deductions} reconciled={reconciled} net={added_net}")
    check("with_added: line items still sum to net exactly",
          reconciled == added_net,
          f"reconciled={reconciled} net={added_net}")

    print("\n" + "=" * 70)
    if failures:
        print(f"RESULT: {len(failures)} MISMATCH(ES)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("RESULT: ALL CHECKS MATCH")
    print("=" * 70)
    return 0


sys.exit(run())
