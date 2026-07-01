"""
Stage 2 Step 1 -- Custom plan equivalence test.

Proves build_custom_plan(item_ids=<recommended's displayed item set>)
reproduces the real Recommended plan's adjusted_sale_price, value_lift_capped,
plan_roi_pct, and included_items exactly, for the same 130 Kingfisher Dr
fixture used by test_override_engine.py and test_stage1_optimizer_refactor.py.

Net proceeds is compared line-by-line EXCEPT carrying_cost: Custom does not
estimate DOM (parked product decision, see custom_plan.py), so it never
emits a carrying_cost deduction, while Recommended always does when its
DOM-derived carrying total is > 0. This is an approved, documented
divergence -- not a bug -- so instead of asserting raw net equality, this
test asserts the RECONCILIATION identity: custom_net + recommended's
carrying_cost line == recommended_net. That proves the underlying repair/
value-lift engine reproduces Recommended exactly, with the carrying-cost
gap being the sole, accounted-for delta.

This does NOT prove general equivalence for every possible item set -- see
net_proceeds._repair_cost_and_concessions_for_items docstring for the
documented three-way scope asymmetry (upgrade/credit items get unconditional
inclusion in the three standard plans' repair-cost math but not in their
value-lift math). This fixture has zero upgrade/credit items in its
repair_table (verified below), so the asymmetry does not trigger here. If it
ever does on a real property, this test's assertions will fail loudly --
report it, don't force it.

Run: python backend/tests/test_custom_plan_step1.py
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
        session_id="kingfisher-custom-plan-regression",
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
        "note": "SYNTHETIC sale price for custom-plan regression test only.",
    }

    return ref, prop, seller, enriched, floor_result, valuation


def run():
    ref, prop, seller, enriched, floor_result, valuation = build_fixture()
    closing_const = ref.sc_closing
    dom_data = ref.dom

    print("=" * 70)
    print("CUSTOM PLAN EQUIVALENCE TEST -- custom(recommended's items) == recommended")
    print("=" * 70)

    bvs_present = sorted({row.get("better_value") for row in enriched})
    print(f"\n  better_value categories present in this fixture: {bvs_present}")
    check("fixture has no 'upgrade' or 'credit' rows (asymmetry does not trigger here)",
          "upgrade" not in bvs_present and "credit" not in bvs_present,
          f"found: {bvs_present}")

    # Cross-ref: item-3 decision (custom_plan.py) says Custom's concessions can
    # legitimately diverge from Recommended's on properties with low-recoup
    # credit items excluded from included_items. This fixture has none (checked
    # above), so that divergence doesn't apply here and exact equality below is
    # the correct assertion, not a coincidence -- if this fixture ever gains a
    # credit/upgrade row, the check above fails loudly first.

    plans = build_plans(
        enriched_rows=enriched, floor_result=floor_result, valuation=valuation,
        dom_data=dom_data, closing_constants=closing_const, property_inputs=prop,
        seller_inputs=seller, listing_month=6, commission_rate=None, has_hoa=False,
        overrides_by_plan=None,
    )
    recommended = plans["recommended"]

    item_ids = _items_for_level(enriched, floor_result, "recommended")
    print(f"\n  recommended's displayed item set: {item_ids}")

    custom = build_custom_plan(
        enriched_rows=enriched, floor_result=floor_result, valuation=valuation,
        closing_constants=closing_const, seller_inputs=seller,
        item_ids=item_ids, item_cost_overrides={},
        commission_rate=None, has_hoa=False,
    )

    print("\n--- comparing custom(recommended items) vs. recommended ---")
    check("adjusted_sale_price", custom["adjusted_sale_price"] == recommended["adjusted_sale_price"],
          f"custom={custom['adjusted_sale_price']} recommended={recommended['adjusted_sale_price']}")
    check("value_lift_capped", custom["value_lift_capped"] == recommended["value_lift_capped"],
          f"custom={custom['value_lift_capped']} recommended={recommended['value_lift_capped']}")
    check("plan_roi_pct", custom["plan_roi_pct"] == recommended["plan_roi_pct"],
          f"custom={custom['plan_roi_pct']} recommended={recommended['plan_roi_pct']}")
    check("total_repair_cost_mid", custom["total_repair_cost_mid"] == recommended["total_repair_cost_mid"],
          f"custom={custom['total_repair_cost_mid']} recommended={recommended['total_repair_cost_mid']}")
    check("included_items (order + membership)", custom["included_items"] == recommended["included_items"],
          f"custom={custom['included_items']} recommended={recommended['included_items']}")

    custom_lines = {li["key"]: li for li in custom["net_proceeds"]["line_items"]}
    rec_lines    = {li["key"]: li for li in recommended["net_proceeds"]["line_items"]}
    for key, rec_li in rec_lines.items():
        if key == "carrying_cost":
            continue
        cust_li = custom_lines.get(key)
        check(f"line_item[{key}].amount",
              cust_li is not None and cust_li["amount"] == rec_li["amount"],
              f"custom={cust_li['amount'] if cust_li else None} recommended={rec_li['amount']}")

    rec_carrying_li = rec_lines.get("carrying_cost")
    rec_carrying_amt = rec_carrying_li["amount"] if rec_carrying_li else 0.0
    custom_net = custom["net_proceeds"]["net_proceeds"]
    recommended_net = recommended["net_proceeds"]["net_proceeds"]
    print(f"\n  [EXPECTED DIVERGENCE -- DOM parked for Custom]")
    print(f"  recommended carrying_cost line: {rec_carrying_amt}")
    print(f"  custom_net={custom_net}  recommended_net={recommended_net}  "
          f"delta={round(custom_net - recommended_net, 2)}")
    check("custom_net == recommended_net + recommended's carrying_cost (sole accounted-for delta)",
          round(custom_net - recommended_net, 2) == round(rec_carrying_amt, 2),
          f"custom_net-recommended_net={round(custom_net - recommended_net, 2)} "
          f"carrying_cost={round(rec_carrying_amt, 2)}")

    print("\n" + "=" * 70)
    if failures:
        print(f"RESULT: {len(failures)} MISMATCH(ES) -- see net_proceeds.py's documented")
        print("three-way scope asymmetry (upgrade/credit unconditional inclusion) and/or")
        print("the DOM-parked carrying-cost divergence. Reporting, not forcing.")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("RESULT: ALL CHECKS MATCH -- custom(recommended's items) reproduces recommended")
    print("exactly on every dimension except the approved DOM-parked carrying-cost line,")
    print("which reconciles exactly.")
    print("=" * 70)
    return 0


exit_code = run()
sys.exit(exit_code)
