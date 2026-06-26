"""
Tests for guardrail fixes V4, V5, V6, V7.

Fixture: tests/fixtures/instance_v1v2v3.json  (reused — same components)
Pipeline: condition → repair_replace → recoup → floor → net_proceeds / optimizer

V4 — A2: repair_spend is a direct field on net_for_plan output, not scraped from a label.
V5 — A3: safety_eligible, lender_eligible, essential_when_needed copied onto enriched rows.
V6 — A6/A1: commission_rate change shifts net (gross-based); payoff shifts net dollar-for-dollar.
V7 — A4: Floor item action driven by repairability, not recoup_pct.
"""

import json
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.data_loader import ReferenceData
from app.logic.condition import build_condition_list
from app.logic.repair_replace import build_repair_rows
from app.logic.recoup import attach_recoup, _refined_call
from app.logic.floor import compute_floor
from app.logic.net_proceeds import net_for_plan

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "instance_v1v2v3.json")
REF = ReferenceData()   # REF.library is Dict[str, dict] keyed by component_id

# ── shared helpers ────────────────────────────────────────────────────────────

def load_fixture():
    with open(FIXTURE_PATH) as f:
        data = json.load(f)
    assert "__fixture_guard__" in data, "fixture guard missing — do not remove it"
    return {k: v for k, v in data.items() if not k.startswith("__")}


def run_pipeline(instance):
    cond_list    = build_condition_list(instance, REF, has_inspection=False)
    repair_rows  = build_repair_rows(cond_list)
    enriched     = attach_recoup(repair_rows, REF.library)
    floor_result = compute_floor(enriched)
    return cond_list, repair_rows, enriched, floor_result


CLOSING = {
    "commission": {"default_rate": 0.06},
    "sc_transfer_tax": {"rate_per_500": 1.85, "note": "SC transfer tax"},
    "attorney_closing_fee": {"low": 900, "high": 1100, "note": "attorney"},
    "deed_recording_fee": {"flat": 15, "note": "deed"},
    "cl100_termite_letter": {"low": 75, "high": 125, "note": "CL-100"},
    "hoa_estoppel_transfer": {"low": 200, "high": 400, "note": "HOA"},
}
VALUATION = {"low": 245000, "mid": 260000, "high": 280000}
DOM       = {"estimated_dom": 30}
CARRYING  = {"total": 1200}


def run_net(level="recommended", commission_rate=None, seller_inputs=None):
    _, _, enriched, floor_result = run_pipeline(load_fixture())
    return net_for_plan(
        valuation=VALUATION, plan_level=level,
        floor_result=floor_result, enriched_rows=enriched,
        dom_result=DOM, carrying_cost_result=CARRYING,
        closing_constants=CLOSING,
        seller_inputs=seller_inputs or {},
        commission_rate=commission_rate,
    )


# ── V4 ───────────────────────────────────────────────────────────────────────

class TestV4RepairSpendField:
    """A2: repair_spend is a direct field, not scraped from a display label."""

    def test_field_present(self):
        assert "repair_spend" in run_net(), "repair_spend missing from net_for_plan result"

    def test_field_is_numeric_nonnegative(self):
        val = run_net()["repair_spend"]
        assert isinstance(val, (int, float)) and val >= 0

    def test_field_matches_repair_line_item(self):
        result = run_net()
        repair_line = next(
            (li for li in result.get("line_items", []) if "repair" in li["label"].lower()), None
        )
        if repair_line is not None:
            assert abs(result["repair_spend"] - repair_line["amount"]) < 0.01, (
                f"repair_spend ({result['repair_spend']}) != repair line ({repair_line['amount']})"
            )
        else:
            assert result["repair_spend"] == 0.0

    def test_nonzero_with_floor_items_present(self):
        for level in ("leaner", "recommended", "do_everything"):
            result = run_net(level=level)
            assert result["repair_spend"] > 0, \
                f"repair_spend=0 for '{level}' despite floor items in fixture"

    def test_repair_spend_consistent_across_plans(self):
        """do_everything must have repair_spend >= recommended >= leaner."""
        leaner = run_net("leaner")["repair_spend"]
        rec    = run_net("recommended")["repair_spend"]
        doall  = run_net("do_everything")["repair_spend"]
        assert doall >= rec, f"do_everything ({doall}) < recommended ({rec})"
        assert rec >= leaner, f"recommended ({rec}) < leaner ({leaner})"


# ── V5 ───────────────────────────────────────────────────────────────────────

class TestV5EligibilityFlagsOnEnrichedRows:
    """A3: eligibility flags must be on enriched rows so _floor_reason shows real reasons."""

    def test_all_three_flags_on_every_row(self):
        _, _, enriched, _ = run_pipeline(load_fixture())
        for row in enriched:
            cid = row["component_id"]
            for flag in ("safety_eligible", "lender_eligible", "essential_when_needed"):
                assert flag in row, f"{cid}: missing {flag}"

    def test_gar01_lender_eligible_if_library_marks_it(self):
        _, _, enriched, _ = run_pipeline(load_fixture())
        gar = next((r for r in enriched if r["component_id"] == "GAR-01"), None)
        assert gar is not None, "GAR-01 not in enriched rows"
        lib_row = REF.library.get("GAR-01")  # REF.library is Dict[str,dict]
        if lib_row and lib_row.get("lender_eligible"):
            assert gar["lender_eligible"] is True, \
                "GAR-01 lender_eligible=True in library but not propagated to enriched row"

    def test_fnd01_safety_or_lender_if_library_marks_it(self):
        _, _, enriched, _ = run_pipeline(load_fixture())
        fnd = next((r for r in enriched if r["component_id"] == "FND-01"), None)
        assert fnd is not None, "FND-01 not in enriched rows"
        lib_row = REF.library.get("FND-01")
        if lib_row and (lib_row.get("safety_eligible") or lib_row.get("lender_eligible")):
            assert fnd.get("safety_eligible") or fnd.get("lender_eligible"), \
                "FND-01 eligibility flag in library but not on enriched row"

    def test_floor_reason_not_generic_for_eligible_items(self):
        _, _, enriched, floor_result = run_pipeline(load_fixture())
        for item in floor_result.get("items", []):
            cid = item["component_id"]
            row = next((r for r in enriched if r["component_id"] == cid), None)
            if row is None:
                continue
            has_flag = (
                row.get("safety_eligible")
                or row.get("lender_eligible")
                or row.get("essential_when_needed")
            )
            if has_flag:
                assert item.get("reason", "required") != "required", (
                    f"{cid}: has eligibility flags but floor reason is still generic 'required' "
                    "(V5 fix: flags must propagate into _floor_reason)"
                )


# ── V6 ───────────────────────────────────────────────────────────────────────

class TestV6MoneyMath:
    """A6/A1: commission and payoff must flow correctly through net_proceeds."""

    def test_higher_commission_lowers_net(self):
        net_5 = run_net(commission_rate=0.05)["net_proceeds"]
        net_6 = run_net(commission_rate=0.06)["net_proceeds"]
        assert net_5 > net_6, "Lower commission must yield higher net (A1)"

    def test_commission_delta_magnitude_implies_gross_basis(self):
        # 1% of a ~$260k sale price ≈ $2,600 if applied to gross, not net
        net_5 = run_net(commission_rate=0.05)["net_proceeds"]
        net_6 = run_net(commission_rate=0.06)["net_proceeds"]
        delta = net_5 - net_6
        assert 2000 < delta < 4000, (
            f"1% commission change moved net ${delta:.0f}; expected ~$2,600 "
            "(commission must be applied on gross sale price — A1)"
        )

    def test_payoff_shifts_net_dollar_for_dollar(self):
        net_low  = run_net(seller_inputs={"mortgage_payoff": 100000})["net_proceeds"]
        net_high = run_net(seller_inputs={"mortgage_payoff": 110000})["net_proceeds"]
        delta = net_low - net_high
        assert abs(delta - 10000) < 0.01, (
            f"$10k payoff increase moved net ${delta:.2f}; expected exactly $10,000 (A1)"
        )

    def test_payoff_line_item_present(self):
        result = run_net(seller_inputs={"mortgage_payoff": 120000})
        labels = [li["label"] for li in result.get("line_items", [])]
        assert any("payoff" in lbl.lower() or "mortgage" in lbl.lower() for lbl in labels), \
            "No payoff line item found — A1 requires payoff as its own deduction line"


# ── V7 ───────────────────────────────────────────────────────────────────────

class TestV7FloorActionNoROIGate:
    """
    A4: Floor item action driven by repairability, not recoup_pct.

    Note: _refined_call applies Rule 0 (terminal signals → replace) BEFORE the
    floor branch. We test non-terminal conditions here to isolate the floor branch.
    Terminal-condition items correctly return 'replace' via Rule 0 — that's not V7.
    V7 is specifically: within the floor branch, recoup_pct must not gate the action.
    """

    def _floor_row(self, repairable=True, condition="deteriorated", recoup_pct=50):
        """Build a minimal enriched row for _refined_call testing."""
        return {
            "component_id": "GAR-01",
            "in_floor": True,
            "repairable": repairable,
            "creditable": False,
            "condition_detected": condition,   # non-terminal so Rule 0 doesn't fire
            "severity_detected": "moderate",
            "cost_mid_repair": 500,
            "cost_mid_replace": 1850,
        }

    def test_all_enriched_floor_items_have_repair_or_replace(self):
        _, _, enriched, _ = run_pipeline(load_fixture())
        floor_items = [r for r in enriched if r.get("in_floor")]
        assert floor_items, "No floor items in fixture"
        for row in floor_items:
            cid = row["component_id"]
            bv = row.get("better_value")
            assert bv in ("repair", "replace"), (
                f"{cid}: floor item better_value='{bv}'; must be repair or replace (A4)"
            )

    @pytest.mark.parametrize("recoup_pct", [0, 50, 100, 107, 150, 200])
    def test_repairable_floor_item_is_repair_regardless_of_recoup(self, recoup_pct):
        """
        For a non-terminal, repairable floor item, action must be 'repair'
        at any recoup level — including values below the old 150 gate.
        """
        row = self._floor_row(repairable=True, recoup_pct=recoup_pct)
        result = _refined_call(row, recoup_pct=recoup_pct, source="library", is_defect=True)
        assert result == "repair", (
            f"Repairable floor item with recoup_pct={recoup_pct} returned '{result}'; "
            "expected 'repair' — ROI must not gate floor action (A4, V7)"
        )

    @pytest.mark.parametrize("recoup_pct", [0, 50, 107, 200])
    def test_non_repairable_floor_item_is_replace_regardless_of_recoup(self, recoup_pct):
        row = self._floor_row(repairable=False, recoup_pct=recoup_pct)
        result = _refined_call(row, recoup_pct=recoup_pct, source="library", is_defect=True)
        assert result == "replace", (
            f"Non-repairable floor item with recoup_pct={recoup_pct} returned '{result}'; "
            "expected 'replace' (A4)"
        )
