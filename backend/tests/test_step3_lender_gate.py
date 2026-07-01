"""
Stage 2 Step 3 -- Change 1 verification: dropping a required, major
lender-blocking item fires the lender gate; including it does not.

Uses a variant of the 130 Kingfisher fixture with ROOF-01 bumped to an
active-leak / high-severity condition answer (the stock Kingfisher fixture
has no investor_cap_eligible row at all -- checked components_library.csv:
only ROOF-01/FND-01/ELEC-01 carry an investor_cap_severity_threshold, and
none of Kingfisher's stock answers reach it). This test EMPIRICALLY confirms
investor_cap_eligible=True on the resulting row before relying on it -- see
the first assertion below. If that assertion fails, everything after it is
reporting on a fixture that doesn't actually exercise Change 1, and this
test says so explicitly rather than passing vacuously.

Run: python backend/tests/test_step3_lender_gate.py
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
from app.logic.optimizer import _items_for_level
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
    """Kingfisher fixture, ROOF-01 bumped to active-leak/high severity so it
    becomes investor_cap_eligible (threshold is 'high' per components_library.csv).
    Everything else identical to the stock fixture used by the equivalence test."""
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
        # CHANGED from stock fixture: active leak, high severity (stock fixture
        # used "unknown_age" / medium here, which never reaches ROOF-01's
        # 'high' investor_cap_severity_threshold).
        ConditionAnswer(question_id="Q-INSP", component_id="ROOF-01", answer="active_leak",
                         maps_to_condition="active roof leak observed", maps_to_severity="high"),
        ConditionAnswer(question_id="Q-CRAWL-1", component_id="FND-01", answer="unsure",
                         maps_to_condition="crawlspace condition unknown; recommend assessment", maps_to_severity="low"),
        ConditionAnswer(question_id="Q-DECK-1", component_id="DECK-01", answer="yes"),
        ConditionAnswer(question_id="Q-SMOKE-1", component_id="REM-01", answer="no"),
        ConditionAnswer(question_id="Q-ELEC-1", component_id="ELEC-01", answer="no"),
        ConditionAnswer(question_id="Q-INSP", component_id="DET-01", answer="old",
                         maps_to_condition="old; age unknown; test before listing", maps_to_severity="low"),
    ]
    submission = CaptureSubmission(session_id="kingfisher-step3-lender-gate", has_inspection_report=False,
        photo_tags=[], presence_answers=presence_answers, condition_answers=condition_answers)
    instance = run_capture(submission, ref)
    cond_list = build_condition_list(instance, ref, has_inspection=False)
    repair_rows = build_repair_rows(cond_list)
    enriched = attach_recoup(repair_rows, ref.library)
    floor_result = compute_floor(enriched)
    valuation = {"low": 275000.0, "mid": 305000.0, "high": 335000.0, "avm_avg": None,
                 "confidence": 0.75, "note": "SYNTHETIC sale price for Step 3 lender-gate test."}
    return ref, prop, seller, enriched, floor_result, valuation


def run():
    ref, prop, seller, enriched, floor_result, valuation = build_fixture()
    closing_const = ref.sc_closing

    print("=" * 70)
    print("STEP 3 CHANGE 1 -- lender gate fires when a required item is dropped")
    print("=" * 70)

    roof_row = next((r for r in enriched if r["component_id"] == "ROOF-01"), None)
    print(f"\n  ROOF-01 row: severity_detected={roof_row.get('severity_detected')!r} "
          f"defect_qualifies_floor={roof_row.get('defect_qualifies_floor')!r} "
          f"investor_cap_eligible={roof_row.get('investor_cap_eligible')!r}")

    # EMPIRICAL CHECK -- do not proceed on faith. If this fails, the fixture
    # doesn't exercise Change 1 and the checks below would be testing nothing.
    fixture_valid = check(
        "EMPIRICAL: ROOF-01 is investor_cap_eligible on this fixture",
        roof_row is not None and roof_row.get("investor_cap_eligible") is True,
        f"got investor_cap_eligible={roof_row.get('investor_cap_eligible') if roof_row else 'ROW NOT FOUND'}",
    )
    check("EMPIRICAL: ROOF-01 is a floor item on this fixture",
          roof_row is not None and bool(roof_row.get("defect_qualifies_floor")),
          f"got defect_qualifies_floor={roof_row.get('defect_qualifies_floor') if roof_row else 'ROW NOT FOUND'}")

    if not fixture_valid:
        print("\nABORTING remaining checks -- fixture does not exercise the case under test.")
        print("RESULT: FIXTURE INVALID, not a pass")
        return 1

    all_item_ids = _items_for_level(enriched, floor_result, "do_everything")
    print(f"\n  do_everything's full item set (used as the base 'all required present' case): {all_item_ids}")

    # Case A: ROOF-01 INCLUDED (all required items present). Correction from
    # an earlier draft of this test: lender_gate is NOT None here -- this is
    # the EXISTING, unchanged lender_gate_items path (present since before
    # Change 1), which has always fired when a major lender item IS included,
    # narrating "repairing this unlocks retail pricing." That behavior is
    # untouched by Change 1 -- verified below by checking retail_price equals
    # this plan's own actual adjusted_sale_price (the pre-Change-1 formula)
    # and the item carries "recovery_uplift" (only the included-path shape
    # has that key). "lender_gate is None" would only be true for a property
    # with NO investor-cap-eligible floor item at all -- not this fixture,
    # which was deliberately built to have one.
    plan_included = build_custom_plan(
        enriched_rows=enriched, floor_result=floor_result, valuation=valuation,
        closing_constants=closing_const, seller_inputs=seller,
        item_ids=all_item_ids, item_cost_overrides={}, commission_rate=None, has_hoa=False,
    )
    gate_included = plan_included["lender_gate"]
    print(f"\n  [Case A: ROOF-01 included] lender_gate = {gate_included}")
    check("lender_gate populated when ROOF-01 is included (existing, unchanged path)",
          gate_included is not None, f"got={gate_included}")
    if gate_included is not None:
        check("Case A: retail_price equals this plan's own actual adjusted_sale_price (unchanged formula)",
              gate_included.get("retail_price") == plan_included["adjusted_sale_price"],
              f"retail={gate_included.get('retail_price')} actual={plan_included['adjusted_sale_price']}")
        check("Case A: item carries 'recovery_uplift' (included-path shape, no 'note' field)",
              "recovery_uplift" in (gate_included.get("items") or [{}])[0] and "note" not in gate_included,
              f"items={gate_included.get('items')} note={gate_included.get('note')}")

    # Case B: ROOF-01 EXCLUDED -> expect gate to fire
    item_ids_dropped = [cid for cid in all_item_ids if cid != "ROOF-01"]
    plan_dropped = build_custom_plan(
        enriched_rows=enriched, floor_result=floor_result, valuation=valuation,
        closing_constants=closing_const, seller_inputs=seller,
        item_ids=item_ids_dropped, item_cost_overrides={}, commission_rate=None, has_hoa=False,
    )
    gate = plan_dropped["lender_gate"]
    print(f"\n  [Case B: ROOF-01 dropped] lender_gate = {gate}")

    check("lender_gate is populated when ROOF-01 is dropped (NEW missing-items path)",
          gate is not None, f"got={gate}")
    check("Case B: item does NOT carry 'recovery_uplift' (new missing-path shape has 'note' instead)",
          gate is not None and "recovery_uplift" not in (gate.get("items") or [{}])[0] and "note" in gate,
          f"items={gate.get('items') if gate else None} note={gate.get('note') if gate else None}")
    check("CROSS-CHECK: Case B's hypothetical retail_price equals Case A's actual retail_price "
          "(both represent 'all of do_everything, ROOF-01 included' -- same number, computed two different ways)",
          gate is not None and gate_included is not None and gate["retail_price"] == gate_included["retail_price"],
          f"case_b_retail={gate.get('retail_price') if gate else None} case_a_retail={gate_included.get('retail_price') if gate_included else None}")
    check("Case B's own actual adjusted_sale_price is LOWER than Case A's (ROOF-01's uplift is honestly missing)",
          plan_dropped["adjusted_sale_price"] < plan_included["adjusted_sale_price"],
          f"case_b={plan_dropped['adjusted_sale_price']} case_a={plan_included['adjusted_sale_price']}")

    if gate is not None:
        check("has_major_lender_items is True",
              gate.get("has_major_lender_items") is True, f"got={gate.get('has_major_lender_items')}")
        gate_ids = {i["component_id"] for i in gate.get("items", [])}
        check("gate.items contains ROOF-01",
              "ROOF-01" in gate_ids, f"got item ids={gate_ids}")
        retail = gate.get("retail_price")
        investor = gate.get("investor_price")
        expected_investor = round(retail * 0.75, -2) if retail is not None else None
        check("investor_price == round(retail_price * 0.75, -2)",
              investor == expected_investor,
              f"retail={retail} investor={investor} expected={expected_investor}")
        check("retail_price (hypothetical, if repaired) is HIGHER than the actual dropped-scenario adjusted_sale_price",
              retail is not None and retail > plan_dropped["adjusted_sale_price"],
              f"retail={retail} actual_adjusted_sale_price={plan_dropped['adjusted_sale_price']}")
        print(f"\n  gate.note: {gate.get('note')}")

    # Sanity: line items still sum to net in both scenarios (Step 2 discipline).
    for label, plan in (("Case A (included)", plan_included), ("Case B (dropped)", plan_dropped)):
        lines = plan["net_proceeds"]["line_items"]
        line_sum = round(sum(li["amount"] for li in lines), 2)
        gross = plan["net_proceeds"]["gross_sale_price"]
        net = plan["net_proceeds"]["net_proceeds"]
        reconciled = round(gross - line_sum, 2)
        check(f"{label}: line items sum to net exactly",
              reconciled == net, f"reconciled={reconciled} net={net}")

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
