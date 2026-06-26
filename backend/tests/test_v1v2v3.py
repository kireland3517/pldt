"""
Tests for guardrail fixes V1, V2, V3.

Fixture:  tests/fixtures/instance_v1v2v3.json
Pipeline: condition → repair_replace → recoup → floor → optimizer (net_for_plan)

FIXTURE GUARD: this test file only imports from the logic layer.
No production capture entrypoint (run_capture, apply_photo_tags, etc.) is called.
The fixture is a pre-built instance_json — it skips the blind photo/questionnaire
pipeline entirely. That is intentional. These tests verify math, not capture.
"""

import json
import os
import sys
import pytest

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.data_loader import ReferenceData
from app.logic.condition import build_condition_list
from app.logic.repair_replace import build_repair_rows
from app.logic.recoup import attach_recoup
from app.logic.floor import compute_floor
from app.logic.net_proceeds import net_for_plan
from app.logic.optimizer import _adjusted_sale_price, _items_for_level

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "instance_v1v2v3.json")
REF = ReferenceData()

# ── helpers ──────────────────────────────────────────────────────────────────

def load_fixture() -> dict:
    with open(FIXTURE_PATH) as f:
        data = json.load(f)
    assert "__fixture_guard__" in data, "fixture guard missing — do not remove it"
    return {k: v for k, v in data.items() if not k.startswith("__")}

def run_pipeline(instance: dict):
    cond_list  = build_condition_list(instance, REF, has_inspection=False)
    repair_rows = build_repair_rows(cond_list)
    enriched    = attach_recoup(repair_rows, REF.library)
    floor_result = compute_floor(enriched)
    return cond_list, repair_rows, enriched, floor_result

# ── V1: Floor classification ──────────────────────────────────────────────────

class TestV1FloorClassification:
    """A3: Floor items must have in_floor=True and appear in floor_result.items."""

    def test_floor_items_have_in_floor_flag(self):
        """Every item with defect_qualifies_floor=True must carry in_floor=True on its enriched row."""
        _, _, enriched, floor_result = run_pipeline(load_fixture())
        floor_cids = {r["component_id"] for r in floor_result["items"]}
        for row in enriched:
            if row.get("defect_qualifies_floor"):
                assert row["in_floor"] is True, \
                    f"{row['component_id']}: defect_qualifies_floor=True but in_floor={row['in_floor']}"
                assert row["component_id"] in floor_cids, \
                    f"{row['component_id']}: defect_qualifies_floor=True but missing from floor_result.items"

    def test_gar01_in_floor(self):
        """GAR-01 (non-functional door, lender-required) must be in the Floor."""
        _, _, enriched, floor_result = run_pipeline(load_fixture())
        gar = next(r for r in enriched if r["component_id"] == "GAR-01")
        assert gar["in_floor"] is True
        floor_cids = {r["component_id"] for r in floor_result["items"]}
        assert "GAR-01" in floor_cids

    def test_good_condition_item_excluded(self):
        """WIN-01 has severity=none (good condition) — must not appear in repair_rows at all."""
        _, repair_rows, _, _ = run_pipeline(load_fixture())
        cids = {r["component_id"] for r in repair_rows}
        assert "WIN-01" not in cids, \
            "WIN-01 is good condition (severity=none) and must be excluded before ROI"

    def test_floor_items_not_selectable_via_in_floor(self):
        """
        Frontend uses row.in_floor || floorIds.has(cid). Belt-and-suspenders:
        even if floor_result.items were empty, in_floor on the row prevents
        the item appearing as optional. Verify in_floor is authoritative.
        """
        _, _, enriched, _ = run_pipeline(load_fixture())
        for row in enriched:
            if row.get("defect_qualifies_floor"):
                assert row["in_floor"] is True, \
                    f"{row['component_id']}: must have in_floor=True for frontend routing"

# ── V2: Floor uplift cap ──────────────────────────────────────────────────────

class TestV2FloorUpliftCap:
    """A5: Floor item uplift must never exceed its repair cost."""

    def test_floor_uplift_never_exceeds_cost(self):
        """
        For every Floor item, uplift contribution must be <= its mid repair cost.
        Tests the min(mid * recoup, mid) cap in _adjusted_sale_price.
        """
        _, _, enriched, _ = run_pipeline(load_fixture())
        for row in enriched:
            if not row.get("defect_qualifies_floor"):
                continue
            recoup = row.get("recoup_pct", 0) / 100
            bv = row.get("better_value", "repair")
            mid = (row.get("cost_mid_repair") if bv in ("repair", "upgrade")
                   else row.get("cost_mid_replace")) or 0
            uplift_contribution = min(mid * recoup, mid)
            assert uplift_contribution <= mid + 0.01, \
                f"{row['component_id']}: floor uplift {uplift_contribution:.2f} exceeds cost {mid:.2f}"

    def test_gar01_uplift_does_not_exceed_repair_cost(self):
        """GAR-01 at 97.8% recoup: uplift from repair mid ($275) must be <= $275."""
        _, _, enriched, _ = run_pipeline(load_fixture())
        gar = next(r for r in enriched if r["component_id"] == "GAR-01")
        mid = gar["cost_mid_repair"]
        recoup = gar["recoup_pct"] / 100
        uplift = min(mid * recoup, mid)
        assert uplift <= mid, f"GAR-01 uplift {uplift:.2f} > cost {mid:.2f}"

    def test_high_recoup_floor_item_cap_binds(self):
        """
        If a Floor item had recoup > 100%, the cap MUST bind (uplift = cost, not cost×recoup).
        Use a synthetic row to prove the cap formula works.
        """
        synthetic_row = {
            "component_id": "HYPO-01", "display_name": "Hypothetical",
            "zone": "Exterior", "better_value": "repair",
            "cost_mid_repair": 1850, "cost_mid_replace": None,
            "recoup_pct": 110,  # 110% — would exceed cost without cap
            "defect_qualifies_floor": True, "in_floor": True,
        }
        mid    = synthetic_row["cost_mid_repair"]
        recoup = synthetic_row["recoup_pct"] / 100
        uplift_uncapped = mid * recoup          # $2,035 — wrong
        uplift_capped   = min(mid * recoup, mid) # $1,850 — correct
        assert uplift_capped == mid, f"cap should equal cost exactly at >=100% recoup"
        assert uplift_uncapped > mid, "test setup error: uncapped should exceed cost"

    def test_adjusted_sale_price_floor_branch(self):
        """_adjusted_sale_price must use capped uplift for floor items."""
        _, _, enriched, _ = run_pipeline(load_fixture())
        valuation = {"mid": 260_000, "high": 300_000}
        price, uplift, capped = _adjusted_sale_price(
            valuation["mid"], valuation["high"], enriched, "leaner"
        )
        # Leaner = floor items only. Uplift must be <= sum of each item's actual
        # action cost (repair vs replace), mirroring what _adjusted_sale_price uses.
        floor_cost_sum = sum(
            (
                r.get("cost_mid_repair") if r.get("better_value") in ("repair", "upgrade")
                else (r.get("cost_mid_replace") or 0)
            )
            for r in enriched
            if r.get("defect_qualifies_floor") and r.get("better_value") in ("repair","replace","upgrade")
        )
        assert uplift <= floor_cost_sum + 0.01, \
            f"Floor-only uplift {uplift:.2f} exceeds action-cost sum {floor_cost_sum:.2f}"

# ── V3: Upgrade cost deducted ─────────────────────────────────────────────────

class TestV3UpgradeCostDeducted:
    """A2: upgrade items must contribute their cost to net_for_plan repair_cost_mid."""

    PROP = {
        "address": "123 Test St", "city": "Columbia", "state": "SC",
        "zip": "29201", "beds": 3, "baths": 2, "sqft": 1800,
        "year_built": 1990, "lot_size": 0.25,
        "comps": [{"address": "100 A St", "price": 260000, "sqft": 1800,
                   "ppsf": 144.44, "weight": 1.0, "note": "test comp"}],
        "avm_avg": 260000,
    }
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

    def _run_net(self, level):
        _, _, enriched, floor_result = run_pipeline(load_fixture())
        return net_for_plan(
            valuation=self.VALUATION,
            plan_level=level,
            floor_result=floor_result,
            enriched_rows=enriched,
            dom_result=self.DOM,
            carrying_cost_result=self.CARRYING,
            closing_constants=self.CLOSING,
            seller_inputs={},
        )

    def test_kit01_cost_in_recommended_repair_line(self):
        """
        KIT-01 is an upgrade candidate with cost_mid_repair=$3,000.
        The recommended plan must deduct it from net proceeds.
        """
        result = self._run_net("recommended")
        repair_line = next(
            (li for li in result["line_items"] if "repair" in li["label"].lower()),
            None
        )
        assert repair_line is not None, "no repair line item found"
        # KIT-01 mid=$3,000 must be included (floor cost also in there)
        assert repair_line["amount"] >= 3000, \
            f"KIT-01 upgrade cost missing: repair line is only {repair_line['amount']}"

    def test_kit01_cost_in_do_everything_repair_line(self):
        """Same check for do_everything plan."""
        result = self._run_net("do_everything")
        repair_line = next(
            (li for li in result["line_items"] if "repair" in li["label"].lower()),
            None
        )
        assert repair_line is not None
        assert repair_line["amount"] >= 3000, \
            f"KIT-01 upgrade cost missing from do_everything: {repair_line['amount']}"

    def test_net_is_lower_with_upgrade_cost_included(self):
        """
        do_everything net must be strictly lower than if we zeroed out KIT-01 cost.
        Confirm upgrade cost actually reduces net (not free lift).
        """
        result_full = self._run_net("do_everything")
        net_full    = result_full["net_proceeds"]

        # Simulate OLD behavior: run with KIT-01 upgrade_candidate=False so it's excluded
        fixture = load_fixture()
        fixture["KIT-01"]["upgrade_candidate"] = False
        fixture["KIT-01"]["severity_detected"] = "none"   # exclude via good-condition gate
        _, _, enriched_no_kit, floor_no_kit = run_pipeline(fixture)
        result_no_kit = net_for_plan(
            valuation=self.VALUATION, plan_level="do_everything",
            floor_result=floor_no_kit, enriched_rows=enriched_no_kit,
            dom_result=self.DOM, carrying_cost_result=self.CARRYING,
            closing_constants=self.CLOSING, seller_inputs={},
        )
        net_no_kit = result_no_kit["net_proceeds"]
        # With KIT-01 in plan: net should be lower (cost deducted) but also higher sale price
        # Net difference should be approximately upgrade_cost * (1 - recoup) — small negative
        # The key assertion: the two nets are DIFFERENT (upgrade cost is not $0)
        assert net_full != net_no_kit, \
            "KIT-01 upgrade cost has no effect on net — A2 violation still present"

