"""
Tests for the floor-item haircut model and investor-cap lender gate.

Fixes covered:
  A5 — Tier multiplier replaces cost×recoup for Floor/defect-clearing items.
       Multipliers are library-cost-anchored (contractor quote cannot inflate).
  A5 — Investor-cap lender gate: major+lender items with detected severity >=
       component threshold trigger 75%-ARV investor pricing metadata.
       Minor/moderate lender items (GAR-01, HVAC-01 etc.) never trigger cap.
  A5 — Fail-safe: null/empty/unknown severity_detected → rank 0 → cap never fires.

Fixture: tests/fixtures/instance_haircut.json
Tests call recoup.attach_recoup and optimizer._adjusted_sale_price directly.
No UI or capture pipeline involved.
"""

import sys, os, json
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.data_loader import ReferenceData
from app.logic.recoup import attach_recoup, _SEVERITY_RANK
from app.logic.optimizer import _adjusted_sale_price, TIER_MULTIPLIERS, INVESTOR_CAP_RATE

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "instance_haircut.json")
REF = ReferenceData()


def load_fixture():
    with open(FIXTURE_PATH) as f:
        data = json.load(f)
    assert "__fixture_guard__" in data, "fixture guard missing"
    return {k: v for k, v in data.items() if not k.startswith("__")}


def make_row(component_id, severity_detected, in_floor=True, defect_qualifies_floor=True,
             bv="repair", repairable=True, repair_low=None, repair_high=None,
             replace_low=None, replace_high=None):
    """Build a minimal row for recoup/optimizer unit tests."""
    lib = REF.library.get(component_id, {})
    return {
        "component_id":           component_id,
        "display_name":           lib.get("display_name", component_id),
        "condition_detected":     "test condition",
        "severity_detected":      severity_detected,
        "defect_qualifies_floor": defect_qualifies_floor,
        "in_floor":               in_floor,
        "repairable":             repairable if repairable is not None else bool(lib.get("repairable")),
        "creditable":             bool(lib.get("creditable")),
        "repair_low":             repair_low or lib.get("repair_low"),
        "repair_high":            repair_high or lib.get("repair_high"),
        "replace_low":            replace_low or lib.get("replace_low"),
        "replace_high":           replace_high or lib.get("replace_high"),
        "better_value_call":      bv,
        "upgrade_candidate":      False,
    }


def enrich_one(component_id, severity_detected, **kwargs):
    """Enrich a single synthetic row and return the enriched dict."""
    row = make_row(component_id, severity_detected, **kwargs)
    enriched = attach_recoup([row], REF.library)
    return enriched[0]


# ── _SEVERITY_RANK fail-safe ──────────────────────────────────────────────────

class TestSeverityRankFailSafe:
    """Unknown/missing severity must default to rank 0 — below every threshold."""

    @pytest.mark.parametrize("sev", [None, "", "unknown", "inspect", "unclear",
                                     "tbd", "PENDING", "n/a", "???"])
    def test_unrecognized_severity_yields_rank_zero(self, sev):
        key = (sev or "").lower().strip()
        rank = _SEVERITY_RANK.get(key, 0)
        assert rank == 0, (
            f"severity '{sev}' mapped to rank {rank}; expected 0. "
            "Unrecognized severity must default to 0 so investor cap never fires."
        )

    def test_none_severity_on_enriched_row_sets_cap_false(self):
        row = enrich_one("FND-01", severity_detected=None)
        assert row["investor_cap_eligible"] is False, (
            "FND-01 with severity_detected=None must NOT trigger investor cap "
            "(fail-safe: unknown detection → not-firing)"
        )

    def test_empty_severity_on_enriched_row_sets_cap_false(self):
        row = enrich_one("FND-01", severity_detected="")
        assert row["investor_cap_eligible"] is False

    def test_unknown_severity_on_enriched_row_sets_cap_false(self):
        row = enrich_one("FND-01", severity_detected="unknown")
        assert row["investor_cap_eligible"] is False

    def test_known_low_severity_fnd01_does_not_fire(self):
        """FND-01 threshold=medium. low < medium → no cap."""
        row = enrich_one("FND-01", severity_detected="low")
        assert row["investor_cap_eligible"] is False, (
            "FND-01 with low severity must NOT trigger investor cap (below medium threshold)"
        )


# ── investor_cap_eligible computation ────────────────────────────────────────

class TestInvestorCapEligibility:
    """Per-component severity threshold vs detected severity."""

    # FND-01: threshold=medium. medium and high fire; none/low do not.
    @pytest.mark.parametrize("sev,expected", [
        ("high",    True),
        ("medium",  True),
        ("low",     False),
        ("none",    False),
        (None,      False),
        ("unknown", False),
    ])
    def test_fnd01_investor_cap_by_severity(self, sev, expected):
        row = enrich_one("FND-01", severity_detected=sev)
        assert row["investor_cap_eligible"] is expected, (
            f"FND-01 severity='{sev}': expected investor_cap_eligible={expected}, "
            f"got {row['investor_cap_eligible']}. "
            "FND-01 threshold=medium; medium and high should fire, low and below should not."
        )

    # ROOF-01: threshold=high. Only high fires.
    @pytest.mark.parametrize("sev,expected", [
        ("high",    True),
        ("medium",  False),
        ("low",     False),
        (None,      False),
    ])
    def test_roof01_investor_cap_by_severity(self, sev, expected):
        row = enrich_one("ROOF-01", severity_detected=sev)
        assert row["investor_cap_eligible"] is expected, (
            f"ROOF-01 severity='{sev}': expected {expected}, got {row['investor_cap_eligible']}. "
            "Sound roof (medium/low) must NOT trigger investor cap."
        )

    # ELEC-01: threshold=high. Minor cover plate (low) must NOT fire.
    @pytest.mark.parametrize("sev,expected", [
        ("high",    True),    # unsafe panel → cap fires
        ("medium",  False),   # moderate issue → below threshold
        ("low",     False),   # missing cover plate → NO cap
        (None,      False),
    ])
    def test_elec01_investor_cap_by_severity(self, sev, expected):
        row = enrich_one("ELEC-01", severity_detected=sev)
        assert row["investor_cap_eligible"] is expected, (
            f"ELEC-01 severity='{sev}': expected {expected}, got {row['investor_cap_eligible']}. "
            "A missing cover plate (low) must NOT crater the valuation — only unsafe panel (high) should."
        )

    # GAR-01: no threshold in library → NEVER fires regardless of severity
    @pytest.mark.parametrize("sev", ["high", "medium", "low", None, "unknown"])
    def test_gar01_never_fires_investor_cap(self, sev):
        row = enrich_one("GAR-01", severity_detected=sev)
        assert row["investor_cap_eligible"] is False, (
            f"GAR-01 severity='{sev}' triggered investor cap — must never fire. "
            "Garage door is a moderate lender item; it does not collapse buyer pool."
        )

    # HVAC-01: no threshold → NEVER fires
    @pytest.mark.parametrize("sev", ["high", "medium", None])
    def test_hvac01_never_fires_investor_cap(self, sev):
        row = enrich_one("HVAC-01", severity_detected=sev)
        assert row["investor_cap_eligible"] is False, (
            f"HVAC-01 severity='{sev}' triggered investor cap — must never fire."
        )


# ── Tier multiplier math ──────────────────────────────────────────────────────

class TestTierMultiplierRecovery:
    """
    Floor/defect-clearing items use library_cost_mid × tier_multiplier for uplift.
    Discretionary upgrades still use library_cost_mid × recoup_pct.
    Contractor quotes cannot inflate recovery.
    """

    BASE_MID = 300_000.0
    CEILING  = 400_000.0

    def _uplift(self, rows, level="recommended"):
        _, raw, _, _ = _adjusted_sale_price(self.BASE_MID, self.CEILING, rows, level)
        return raw

    def test_moderate_floor_item_recovers_115x_library_cost(self):
        """
        A moderate-tier floor item (GAR-01, lib_repair_mid=$275) must add
        exactly $275 × 1.15 = $316.25 of uplift. Not recoup_pct, not quote cost.
        """
        row = enrich_one("GAR-01", severity_detected="high", in_floor=True,
                         defect_qualifies_floor=True, bv="repair")
        lib_mid = row.get("library_cost_mid_repair")
        assert lib_mid is not None, "library_cost_mid_repair must be on enriched row"
        expected = lib_mid * TIER_MULTIPLIERS["moderate"]  # 1.15
        uplift = self._uplift([row])
        assert abs(uplift - expected) < 0.01, (
            f"GAR-01 moderate uplift: expected {expected:.2f}, got {uplift:.2f}. "
            f"Expected lib_mid ({lib_mid}) × 1.15 = {expected:.2f}."
        )

    def test_major_floor_item_recovers_150x_library_cost(self):
        """
        A major-tier floor item (FND-01, lib_repair_mid=$4,000) must add
        exactly $4,000 × 1.50 = $6,000 of uplift.
        """
        row = enrich_one("FND-01", severity_detected="high", in_floor=True,
                         defect_qualifies_floor=True, bv="repair")
        lib_mid = row.get("library_cost_mid_repair")
        assert lib_mid is not None, "library_cost_mid_repair must be on enriched row"
        expected = lib_mid * TIER_MULTIPLIERS["major"]  # 1.50
        uplift = self._uplift([row])
        assert abs(uplift - expected) < 0.01, (
            f"FND-01 major uplift: expected {expected:.2f}, got {uplift:.2f}. "
            f"Expected lib_mid ({lib_mid}) × 1.50 = {expected:.2f}."
        )

    def test_minor_floor_item_recovers_1x_library_cost(self):
        """
        A minor-tier floor item (OUT-01, missing GFCI) must add exactly 1.0× library cost.
        """
        row = enrich_one("OUT-01", severity_detected="medium", in_floor=True,
                         defect_qualifies_floor=True, bv="repair")
        lib_mid = row.get("library_cost_mid_repair")
        assert lib_mid is not None
        expected = lib_mid * TIER_MULTIPLIERS["minor"]  # 1.0
        uplift = self._uplift([row])
        assert abs(uplift - expected) < 0.01, (
            f"OUT-01 minor uplift: expected {expected:.2f}, got {uplift:.2f}."
        )

    def test_contractor_quote_does_not_inflate_recovery(self):
        """
        If the seller enters a higher contractor quote (cost_mid_repair > library_cost_mid),
        the uplift must NOT increase beyond library_cost_mid × tier_multiplier.
        """
        row = enrich_one("GAR-01", severity_detected="high", in_floor=True,
                         defect_qualifies_floor=True, bv="repair")
        lib_mid = row.get("library_cost_mid_repair")
        expected_uplift = lib_mid * TIER_MULTIPLIERS["moderate"]

        # Simulate a 2× inflated contractor quote on the instance row
        row_inflated = dict(row)
        row_inflated["cost_mid_repair"] = (row.get("cost_mid_repair") or lib_mid) * 2

        uplift_normal   = self._uplift([row])
        uplift_inflated = self._uplift([row_inflated])

        assert abs(uplift_inflated - expected_uplift) < 0.01, (
            f"Inflated quote changed uplift from {uplift_normal:.2f} to {uplift_inflated:.2f}. "
            "Recovery must be anchored to library cost, not contractor quote (A5)."
        )
        assert abs(uplift_normal - uplift_inflated) < 0.01, (
            "Normal vs inflated quote produced different uplifts — library anchor not working."
        )

    def test_discretionary_upgrade_uses_recoup_pct_not_tier_multiplier(self):
        """
        KIT-01 (upgrade, recoup_pct≈102%) must use library_cost_mid × recoup_pct,
        not a tier multiplier. It must NOT be treated as a floor item.
        """
        row = enrich_one("KIT-01", severity_detected="low", in_floor=False,
                         defect_qualifies_floor=False, bv="upgrade")
        lib_mid = row.get("library_cost_mid_repair")
        recoup  = row.get("recoup_pct", 0) / 100.0
        expected = lib_mid * recoup
        uplift = self._uplift([row], level="do_everything")
        assert abs(uplift - expected) < 1.0, (
            f"KIT-01 upgrade: expected {expected:.2f} (lib_mid×recoup_pct), "
            f"got {uplift:.2f}. Discretionary upgrades must not use tier multiplier."
        )

    def test_elec01_low_severity_takes_multiplier_no_investor_cap(self):
        """
        ELEC-01 with low severity (missing cover plate):
        - still gets 1.5× major tier multiplier (component category applies to multiplier)
        - investor_cap_eligible must be False (severity below high threshold)
        """
        row = enrich_one("ELEC-01", severity_detected="low", in_floor=True,
                         defect_qualifies_floor=True, bv="repair")
        lib_mid = row.get("library_cost_mid_repair")
        expected_uplift = lib_mid * TIER_MULTIPLIERS["major"]  # 1.5× still applies

        assert row["investor_cap_eligible"] is False, \
            "ELEC-01 low severity must NOT be investor_cap_eligible"
        uplift = self._uplift([row])
        assert abs(uplift - expected_uplift) < 0.01, (
            f"ELEC-01 low severity uplift: expected {expected_uplift:.2f}, got {uplift:.2f}"
        )


# ── Lender gate in plan output ────────────────────────────────────────────────

class TestLenderGatePlanOutput:
    """
    lender_gate metadata appears in plan output when investor_cap_eligible items
    are in the floor. investor_price = INVESTOR_CAP_RATE × retail_price.
    """

    BASE_MID = 300_000.0
    CEILING  = 400_000.0

    def test_investor_cap_eligible_item_produces_lender_gate(self):
        """FND-01 high severity → lender_gate in plan output."""
        row = enrich_one("FND-01", severity_detected="high", in_floor=True,
                         defect_qualifies_floor=True, bv="repair")
        _, _, _, gate_items = _adjusted_sale_price(
            self.BASE_MID, self.CEILING, [row], "recommended"
        )
        assert gate_items, "Expected lender_gate_items for FND-01 high severity"
        assert gate_items[0]["component_id"] == "FND-01"

    def test_investor_price_is_75_percent_of_retail(self):
        """investor_price = INVESTOR_CAP_RATE (75%) × adjusted_price."""
        row = enrich_one("FND-01", severity_detected="high", in_floor=True,
                         defect_qualifies_floor=True, bv="repair")
        adj_price, _, _, gate_items = _adjusted_sale_price(
            self.BASE_MID, self.CEILING, [row], "recommended"
        )
        assert gate_items, "Expected lender_gate_items"
        # investor_price is computed in build_plans, but we can verify the rate
        investor_price = round(adj_price * INVESTOR_CAP_RATE, -2)
        expected_gap   = round(adj_price - investor_price, 2)
        assert investor_price < adj_price, "Investor price must be < retail price"
        assert abs(investor_price - adj_price * 0.75) < 200, (
            f"investor_price {investor_price} is not ~75% of retail {adj_price}"
        )

    def test_gar01_high_severity_no_lender_gate(self):
        """GAR-01 high severity: no investor cap, no lender_gate_items."""
        row = enrich_one("GAR-01", severity_detected="high", in_floor=True,
                         defect_qualifies_floor=True, bv="replace")
        _, _, _, gate_items = _adjusted_sale_price(
            self.BASE_MID, self.CEILING, [row], "recommended"
        )
        assert not gate_items, (
            "GAR-01 (moderate lender item) must NOT produce lender_gate_items, "
            "even at high severity."
        )

    def test_elec01_low_severity_no_lender_gate(self):
        """ELEC-01 low severity: missing cover plate — no investor cap."""
        row = enrich_one("ELEC-01", severity_detected="low", in_floor=True,
                         defect_qualifies_floor=True, bv="repair")
        _, _, _, gate_items = _adjusted_sale_price(
            self.BASE_MID, self.CEILING, [row], "recommended"
        )
        assert not gate_items, (
            "ELEC-01 low severity (missing cover plate) must NOT produce lender_gate_items."
        )

    def test_elec01_high_severity_produces_lender_gate(self):
        """ELEC-01 high severity: unsafe panel — investor cap fires."""
        row = enrich_one("ELEC-01", severity_detected="high", in_floor=True,
                         defect_qualifies_floor=True, bv="repair")
        _, _, _, gate_items = _adjusted_sale_price(
            self.BASE_MID, self.CEILING, [row], "recommended"
        )
        assert gate_items, "ELEC-01 high severity (unsafe panel) must produce lender_gate_items"

    def test_unknown_severity_no_lender_gate(self):
        """None/unknown severity on investor-cap-eligible component → no gate."""
        for sev in (None, "", "unknown", "inspect"):
            row = enrich_one("FND-01", severity_detected=sev, in_floor=True,
                             defect_qualifies_floor=True, bv="repair")
            _, _, _, gate_items = _adjusted_sale_price(
                self.BASE_MID, self.CEILING, [row], "recommended"
            )
            assert not gate_items, (
                f"FND-01 severity='{sev}' produced lender_gate_items — "
                "unknown/missing severity must NEVER trigger investor cap (fail-safe)."
            )
