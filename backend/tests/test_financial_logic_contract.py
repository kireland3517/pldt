"""
Regression tests for the financial logic contract.

Run from repo root:
    python backend/tests/test_financial_logic_contract.py
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.logic.net_proceeds import compute_net_proceeds, net_for_plan


CLOSING_CONSTANTS = {
    "commission": {"default_rate": 0.06},
    "sc_transfer_tax": {"rate_per_500": 1.85, "note": "test transfer tax"},
    "attorney_closing_fee": {"low": 600, "high": 800, "note": "test attorney fee"},
    "deed_recording_fee": {"flat": 30, "note": "test deed fee"},
    "cl100_termite_letter": {"low": 100, "high": 200, "note": "test CL-100"},
    "hoa_estoppel_transfer": {"low": 100, "high": 300, "note": "test HOA fee"},
}


class FinancialLogicContractTests(unittest.TestCase):
    def test_mortgage_payoff_reduces_net_proceeds_dollar_for_dollar(self):
        base = compute_net_proceeds(
            sale_price=300000,
            closing_constants=CLOSING_CONSTANTS,
            seller_inputs={"mortgage_payoff": 0},
            plan_repair_cost_mid=0,
            carrying_cost_total=0,
        )
        with_payoff = compute_net_proceeds(
            sale_price=300000,
            closing_constants=CLOSING_CONSTANTS,
            seller_inputs={"mortgage_payoff": 150000},
            plan_repair_cost_mid=0,
            carrying_cost_total=0,
        )

        self.assertEqual(
            base["net_proceeds"] - with_payoff["net_proceeds"],
            150000,
        )

    def test_seller_credits_reduce_net_proceeds(self):
        base = compute_net_proceeds(
            sale_price=300000,
            closing_constants=CLOSING_CONSTANTS,
            seller_inputs={},
            plan_repair_cost_mid=0,
            carrying_cost_total=0,
        )
        with_credit = compute_net_proceeds(
            sale_price=300000,
            closing_constants=CLOSING_CONSTANTS,
            seller_inputs={"seller_credits": 5000},
            plan_repair_cost_mid=0,
            carrying_cost_total=0,
        )

        self.assertEqual(base["net_proceeds"] - with_credit["net_proceeds"], 5000)

    def test_repair_spend_reduces_net_proceeds(self):
        base = compute_net_proceeds(
            sale_price=300000,
            closing_constants=CLOSING_CONSTANTS,
            seller_inputs={},
            plan_repair_cost_mid=0,
            carrying_cost_total=0,
        )
        with_repairs = compute_net_proceeds(
            sale_price=300000,
            closing_constants=CLOSING_CONSTANTS,
            seller_inputs={},
            plan_repair_cost_mid=12000,
            carrying_cost_total=0,
        )

        self.assertEqual(base["net_proceeds"] - with_repairs["net_proceeds"], 12000)

    def test_recommended_upgrade_spend_is_not_free(self):
        result = net_for_plan(
            valuation={"mid": 300000},
            plan_level="recommended",
            floor_result={"cost_mid": 0},
            enriched_rows=[
                {
                    "component_id": "COS-01",
                    "better_value": "upgrade",
                    "recoup_pct": 80,
                    "cost_mid_repair": 5000,
                    "cost_mid_replace": 0,
                    "defect_qualifies_floor": False,
                }
            ],
            dom_result={"estimated_dom": 30},
            carrying_cost_result={"total": 0},
            closing_constants=CLOSING_CONSTANTS,
            seller_inputs={},
        )

        repair_line = next(
            item for item in result["line_items"]
            if item["label"] == "Pre-listing repairs (plan)"
        )
        self.assertEqual(repair_line["amount"], 5000)

    def test_credit_path_is_closing_concession_not_repair_spend(self):
        result = net_for_plan(
            valuation={"mid": 300000},
            plan_level="recommended",
            floor_result={"cost_mid": 0},
            enriched_rows=[
                {
                    "component_id": "REP-01",
                    "better_value": "credit",
                    "recoup_pct": 0,
                    "cost_mid_repair": 4000,
                    "cost_mid_replace": 0,
                    "defect_qualifies_floor": False,
                }
            ],
            dom_result={"estimated_dom": 30},
            carrying_cost_result={"total": 0},
            closing_constants=CLOSING_CONSTANTS,
            seller_inputs={},
        )

        labels = {item["label"]: item["amount"] for item in result["line_items"]}
        self.assertNotIn("Pre-listing repairs (plan)", labels)
        self.assertEqual(labels["Buyer concessions / credits"], 2000)


if __name__ == "__main__":
    unittest.main()
