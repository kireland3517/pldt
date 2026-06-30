"""
Regression test for compute-time floor re-qualification.

THE BUG THIS CATCHES:
  defect_qualifies_floor was frozen into instance_json at capture time.
  Sessions captured before capture.py fixes had raw enums
  ('poor', 'failed') in condition_detected and defect_qualifies_floor=False
  frozen in. The /compute route was reading those frozen values directly,
  so all capture.py fixes only helped NEW sessions, not existing ones.

THE FIX:
  _run_chain in compute.py now calls qualify_floor_members(instance, ref)
  before build_condition_list. This re-derives defect_qualifies_floor from
  condition_detected at compute time, so capture.py improvements apply
  retroactively to all sessions on next recompute.

THIS TEST:
  Builds a pre-frozen instance dict exactly as it appears in a real
  session's instance_json — raw enum condition_detected, stale
  defect_qualifies_floor=False — and runs it through the compute sub-chain
  (qualify_floor_members → build_condition_list → repair_replace → recoup
  → floor). This is the sequence _run_chain executes after valuation.

  It does NOT use run_capture or CaptureSubmission. The frozen instance
  simulates what Supabase holds for a session captured with old code.
  None of the prior test suites used this shape of input.

WHAT THIS DOES NOT TEST:
  compute_as_is_range / valuation — that step needs real comps and is
  orthogonal to floor classification. The tests in test_v1v2v3.py cover
  valuation-adjacent assertions.
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.data_loader import ReferenceData
from app.logic.capture import qualify_floor_members
from app.logic.condition import build_condition_list
from app.logic.repair_replace import build_repair_rows
from app.logic.recoup import attach_recoup
from app.logic.floor import compute_floor

REF = ReferenceData()


def _frozen_instance() -> dict:
    """
    Simulate a real Supabase instance_json captured with OLD code.
    Raw enum condition_detected values, defect_qualifies_floor=False frozen in.
    Matches the exact field values seen in the broken session 437d6cd3.
    """
    instance = REF.new_instance()

    # FND-01: crawlspace with standing water. Old code stored raw enum.
    instance["FND-01"].update({
        "present": True,
        "condition_detected": "poor",       # raw enum — not expanded by old code
        "severity_detected": "high",
        "defect_qualifies_floor": False,    # frozen wrong by old capture code
        "source": "questionnaire",
        "confidence": 0.90,
    })

    # GAR-01: non-functional garage door.
    instance["GAR-01"].update({
        "present": True,
        "condition_detected": "failed",     # raw enum
        "severity_detected": "medium",
        "defect_qualifies_floor": False,
        "source": "questionnaire",
        "confidence": 0.90,
    })

    # DECK-01: open risers / loose railing.
    instance["DECK-01"].update({
        "present": True,
        "condition_detected": "failed",     # raw enum
        "severity_detected": "high",
        "defect_qualifies_floor": False,
        "source": "questionnaire",
        "confidence": 0.90,
    })

    # PRCH-01: loose handrail.
    instance["PRCH-01"].update({
        "present": True,
        "condition_detected": "poor",       # raw enum
        "severity_detected": "high",
        "defect_qualifies_floor": False,
        "source": "questionnaire",
        "confidence": 0.90,
    })

    # ELEC-01: fair condition (no floor trigger)
    instance["ELEC-01"].update({
        "present": True,
        "condition_detected": "fair",       # raw enum, benign
        "severity_detected": "low",
        "defect_qualifies_floor": False,
        "source": "questionnaire",
        "confidence": 0.60,
    })

    return instance


def _run_compute_subchain(instance: dict):
    """
    Run the compute sub-chain that _run_chain executes after valuation.
    This is the exact sequence in compute.py routes/compute.py:_run_chain,
    starting at the qualify_floor_members call added by the architectural fix.
    """
    # This is THE line added by the fix — re-qualify at compute time
    instance = qualify_floor_members(instance, REF)

    cond_list    = build_condition_list(instance, REF, has_inspection=False)
    repair_rows  = build_repair_rows(cond_list)
    enriched     = attach_recoup(repair_rows, REF.library)
    floor_result = compute_floor(enriched)
    return instance, enriched, floor_result


class TestComputeTimeRequalification:
    """
    The compute sub-chain must re-derive in_floor from frozen instance_json,
    ignoring stale defect_qualifies_floor=False values.
    """

    def setup_method(self):
        self.instance, self.enriched, self.floor = \
            _run_compute_subchain(_frozen_instance())

    def _row(self, cid: str) -> dict:
        for r in self.enriched:
            if r["component_id"] == cid:
                return r
        raise AssertionError(f"{cid} not found in enriched repair table")

    def test_fnd01_in_floor_despite_stale_false(self):
        """
        FND-01 frozen with condition='poor' and defect_qualifies_floor=False.
        qualify_floor_members at compute time must re-derive True.
        Mechanism: severity_detected='high' triggers the severity fallback.
        """
        assert self._row("FND-01")["in_floor"] is True, \
            "FND-01 not in floor — compute route is reading stale frozen flag, not re-qualifying"

    def test_gar01_in_floor_despite_stale_false(self):
        """
        GAR-01 frozen with condition='failed' and defect_qualifies_floor=False.
        'failed' expands to 'failed / non-functional' which keyword-matches GAR-01.
        """
        assert self._row("GAR-01")["in_floor"] is True, \
            "GAR-01 not in floor — 'failed' enum not expanding at compute time"

    def test_deck01_in_floor_despite_stale_false(self):
        """
        DECK-01 frozen with condition='failed'. Severity fallback fires
        ('failed' in expanded text AND lender-eligible).
        """
        assert self._row("DECK-01")["in_floor"] is True, \
            "DECK-01 not in floor — compute route is not re-qualifying floor flags"

    def test_prch01_in_floor_despite_stale_false(self):
        """
        PRCH-01 frozen with condition='poor', severity='high'.
        Severity fallback fires (sev='high' AND floor-eligible).
        """
        assert self._row("PRCH-01")["in_floor"] is True, \
            "PRCH-01 not in floor — severity fallback not firing at compute time"

    def test_elec01_not_in_floor_fair_condition(self):
        """
        ELEC-01 with condition='fair' (no trigger keyword, low severity)
        must NOT qualify for floor — normalization must not over-expand.
        """
        row = self._row("ELEC-01")
        assert row.get("in_floor") is not True, \
            "ELEC-01 with 'fair' condition falsely landed in floor"

    def test_all_four_floor_items_non_selectable(self):
        """
        All four items must have in_floor=True — the flag the frontend
        reads to mark items non-selectable and route them to 'Required to sell'.
        """
        floor_ids = {r["component_id"] for r in self.enriched if r.get("in_floor")}
        missing = {"FND-01", "GAR-01", "DECK-01", "PRCH-01"} - floor_ids
        assert not missing, \
            f"Items {missing} not in floor — will appear as Optional with checkboxes"

    def test_instance_flags_rewritten_not_passthrough(self):
        """
        qualify_floor_members must OVERWRITE the stale False values in the
        instance dict, not just pass them through unchanged.
        """
        for cid in ("FND-01", "GAR-01", "DECK-01", "PRCH-01"):
            flag = self.instance[cid]["defect_qualifies_floor"]
            assert flag is True, \
                f"{cid}: qualify_floor_members left stale False in instance — not overwriting"
