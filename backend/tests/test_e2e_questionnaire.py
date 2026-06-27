"""
End-to-end test: raw questionnaire enum data through the full pipeline.

PURPOSE: Catch vocabulary-mismatch bugs that synthetic fixtures miss.
         Every prior test suite used pre-expanded condition text; real
         questionnaire sessions emit short enums ("poor", "failed").
         This test enters the pipeline at the same door real data does —
         a CaptureSubmission with ConditionAnswer objects using un-normalized
         enum values — and asserts the floor items qualify at the end.

CHAIN: CaptureSubmission → run_capture → build_condition_list
       → build_repair_rows → attach_recoup → compute_floor
       (same chain the /compute API runs)

Key components under test:
  FND-01  condition "poor"   maps_to_condition="poor"   (questionnaire enum)
  GAR-01  condition "failed" maps_to_condition="failed"
  DECK-01 condition "failed" maps_to_condition="failed"
  PRCH-01 condition "poor"   maps_to_condition="poor"

All four must emerge with defect_qualifies_floor=True.
Also tests that a seller_confirmed_tag using bare "failed" normalizes correctly.
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.data_loader import ReferenceData
from app.logic.capture import run_capture
from app.logic.condition import build_condition_list
from app.logic.repair_replace import build_repair_rows
from app.logic.recoup import attach_recoup
from app.logic.floor import compute_floor
from app.models import (
    CaptureSubmission,
    PresenceAnswer,
    ConditionAnswer,
    SellerConfirmedTag,
)

REF = ReferenceData()


def _make_submission(extra_confirmed: list = None) -> CaptureSubmission:
    """
    Build a CaptureSubmission that mirrors real questionnaire output.
    All condition values are raw short enums — no pre-expansion.
    """
    return CaptureSubmission(
        session_id="test-e2e-qnr-001",
        has_inspection_report=False,
        photo_tags=[],   # questionnaire-only session — no photos
        presence_answers=[
            # Foundation type = crawlspace → FND-01 present
            PresenceAnswer(question_id="P-CRAWL",    component_id="FND-01",  answer="crawlspace"),
            # Garage present
            PresenceAnswer(question_id="P-GAR",      component_id="GAR-01",  answer="yes"),
            # Deck present
            PresenceAnswer(question_id="P-DECK",     component_id="DECK-01", answer="yes"),
            # Porch present
            PresenceAnswer(question_id="P-PRCH",     component_id="PRCH-01", answer="yes"),
        ],
        condition_answers=[
            # FND-01: seller says crawlspace has standing water (maps_to_condition="poor")
            # This is the real enum the questionnaire frontend sends
            ConditionAnswer(
                question_id="Q-CRAWL-1",
                component_id="FND-01",
                answer="standing_water_now",
                maps_to_condition="poor",    # ← raw enum, must be normalized
                maps_to_severity="medium",
            ),
            # GAR-01: door does not work (maps_to_condition="failed")
            ConditionAnswer(
                question_id="Q-GAR-1",
                component_id="GAR-01",
                answer="does_not_work",
                maps_to_condition="failed",  # ← raw enum, must be normalized
                maps_to_severity="high",
            ),
            # DECK-01: open risers / loose railing (maps_to_condition="failed")
            ConditionAnswer(
                question_id="Q-DECK-3",
                component_id="DECK-01",
                answer="yes",
                maps_to_condition="failed",  # ← raw enum, must be normalized
                maps_to_severity="high",
            ),
            # PRCH-01: railing hazard (maps_to_condition="poor")
            ConditionAnswer(
                question_id="Q-PRCH-1",
                component_id="PRCH-01",
                answer="yes",
                maps_to_condition="poor",    # ← raw enum, must be normalized
                maps_to_severity="medium",
            ),
        ],
        seller_confirmed_tags=extra_confirmed or [],
    )


def _run_full_pipeline(submission: CaptureSubmission):
    instance     = run_capture(submission, REF)
    cond_list    = build_condition_list(instance, REF, has_inspection=False)
    repair_rows  = build_repair_rows(cond_list)
    enriched     = attach_recoup(repair_rows, REF.library)
    floor_result = compute_floor(enriched)
    return instance, cond_list, enriched, floor_result


# ─────────────────────────────────────────────────────────────────────────────
# Core floor-qualification tests
# ─────────────────────────────────────────────────────────────────────────────

class TestE2EQuestionnaireFloorQualification:
    """
    The critical regression test: raw questionnaire enums must produce
    floor-qualified items, not silently fall to Optional.
    """

    def setup_method(self):
        self.instance, self.cond_list, self.enriched, self.floor = \
            _run_full_pipeline(_make_submission())

    def _floor_ids(self):
        return {r["component_id"] for r in self.enriched if r.get("in_floor")}

    def test_fnd01_qualifies_floor(self):
        """FND-01 with maps_to_condition='poor' must reach the Floor."""
        assert "FND-01" in self._floor_ids(), \
            "FND-01 not in floor — vocabulary mismatch not normalized at apply_condition_answers"

    def test_gar01_qualifies_floor(self):
        """GAR-01 with maps_to_condition='failed' must reach the Floor."""
        assert "GAR-01" in self._floor_ids(), \
            "GAR-01 not in floor — vocabulary mismatch not normalized at apply_condition_answers"

    def test_deck01_qualifies_floor(self):
        """DECK-01 with maps_to_condition='failed' must reach the Floor."""
        assert "DECK-01" in self._floor_ids(), \
            "DECK-01 not in floor — vocabulary mismatch not normalized at apply_condition_answers"

    def test_prch01_qualifies_floor(self):
        """PRCH-01 with maps_to_condition='poor' must reach the Floor."""
        assert "PRCH-01" in self._floor_ids(), \
            "PRCH-01 not in floor — vocabulary mismatch not normalized at apply_condition_answers"

    def test_instance_condition_detected_is_expanded(self):
        """
        After run_capture, condition_detected for floor items must be
        expanded text, not the raw enum ('poor'/'failed').
        Raw enums must never reach downstream modules.
        """
        raw_enums = {"poor", "failed", "fair", "good"}
        for cid in ("FND-01", "GAR-01", "DECK-01", "PRCH-01"):
            cond = (self.instance.get(cid, {}).get("condition_detected") or "").strip().lower()
            assert cond not in raw_enums, \
                f"{cid}: condition_detected='{cond}' is a raw enum — must be expanded before leaving capture"

    def test_defect_qualifies_floor_flag_set_on_instance(self):
        """defect_qualifies_floor must be True on the instance dict for all four components."""
        for cid in ("FND-01", "GAR-01", "DECK-01", "PRCH-01"):
            flag = self.instance.get(cid, {}).get("defect_qualifies_floor")
            assert flag is True, \
                f"{cid}: defect_qualifies_floor={flag} on instance — qualify_floor_members failed"

    def test_floor_items_non_selectable(self):
        """
        Floor items in the enriched repair table must have in_floor=True.
        That flag is what the frontend reads to mark items non-selectable.
        """
        for row in self.enriched:
            if row["component_id"] in ("FND-01", "GAR-01", "DECK-01", "PRCH-01"):
                assert row.get("in_floor") is True, \
                    f"{row['component_id']}: in_floor={row.get('in_floor')} — item will appear in Optional"


# ─────────────────────────────────────────────────────────────────────────────
# Seller-confirmed bypass test
# ─────────────────────────────────────────────────────────────────────────────

class TestE2ESellerConfirmedNormalization:
    """
    apply_seller_confirmed is Pass 3 and has highest write priority.
    A bare enum passed as tag.condition must be normalized before it
    overwrites condition_detected.
    """

    def test_seller_confirmed_failed_normalizes(self):
        """
        SellerConfirmedTag(condition='failed') must NOT write the literal
        string 'failed' to condition_detected. It must expand it via
        _CONDITION_ENUM_MAP so downstream keyword matching still works.
        """
        submission = _make_submission(extra_confirmed=[
            SellerConfirmedTag(
                component_id="GAR-01",
                condition="failed",   # ← raw enum override from seller review UI
            )
        ])
        instance, _, enriched, _ = _run_full_pipeline(submission)

        # condition_detected must not be raw "failed"
        cond = (instance.get("GAR-01", {}).get("condition_detected") or "").strip().lower()
        assert cond != "failed", \
            f"apply_seller_confirmed wrote raw enum 'failed' to condition_detected: '{cond}'"

        # GAR-01 must still reach the floor
        floor_ids = {r["component_id"] for r in enriched if r.get("in_floor")}
        assert "GAR-01" in floor_ids, \
            "GAR-01 lost floor qualification after seller_confirmed 'failed' — normalization missing in apply_seller_confirmed"

    def test_seller_confirmed_poor_normalizes(self):
        """
        SellerConfirmedTag(condition='poor') must normalize the bare enum
        to 'poor condition' — never store the raw string.

        Floor assertion: a seller overriding to 'poor' is a downgrade. 'Poor
        condition' contains no FND-01 trigger keywords (moisture/standing water),
        so FND-01 correctly does NOT floor here. This test only asserts
        normalization, not floor qualification.
        """
        submission = _make_submission(extra_confirmed=[
            SellerConfirmedTag(
                component_id="FND-01",
                condition="poor",   # ← raw enum
            )
        ])
        instance, _, enriched, _ = _run_full_pipeline(submission)

        cond = (instance.get("FND-01", {}).get("condition_detected") or "").strip().lower()
        # Must NOT store the raw enum
        assert cond != "poor", \
            f"apply_seller_confirmed wrote raw enum 'poor' to condition_detected: '{cond}'"
        # Must have expanded to normalized form
        assert cond == "poor condition", \
            f"expected 'poor condition' after normalization, got: '{cond}'"


# ─────────────────────────────────────────────────────────────────────────────
# No-false-positive check
# ─────────────────────────────────────────────────────────────────────────────

class TestE2ENoFalsePositives:
    """
    A component with a benign condition enum must NOT qualify for the floor.
    Normalization must not over-expand enums into trigger keywords.
    """

    def test_good_condition_does_not_floor(self):
        """maps_to_condition='good' on a lender-eligible component must not trigger floor."""
        submission = CaptureSubmission(
            session_id="test-e2e-no-fp-001",
            has_inspection_report=False,
            photo_tags=[],
            presence_answers=[
                PresenceAnswer(question_id="P-GAR", component_id="GAR-01", answer="yes"),
            ],
            condition_answers=[
                ConditionAnswer(
                    question_id="Q-GAR-1",
                    component_id="GAR-01",
                    answer="works_normally",
                    maps_to_condition="good",   # benign enum
                    maps_to_severity="low",
                )
            ],
            seller_confirmed_tags=[],
        )
        instance, _, enriched, _ = _run_full_pipeline(submission)

        floor_ids = {r["component_id"] for r in enriched if r.get("in_floor")}
        assert "GAR-01" not in floor_ids, \
            "GAR-01 with 'good' condition falsely qualified for floor — over-expansion in normalization"

    def test_fair_condition_does_not_floor(self):
        """
        A functioning garage door (works_normally) with maps_to_condition='fair'
        must NOT qualify for the floor.

        Note: 'works_but_damaged' is intentionally excluded here because
        _answer_to_condition maps it to 'damaged door; functional but damaged',
        which DOES contain the 'damaged door' trigger keyword — that is correct
        floor behavior. This test uses 'works_normally' which maps to
        'garage door functional', containing no trigger keywords.
        """
        submission = CaptureSubmission(
            session_id="test-e2e-no-fp-002",
            has_inspection_report=False,
            photo_tags=[],
            presence_answers=[
                PresenceAnswer(question_id="P-GAR", component_id="GAR-01", answer="yes"),
            ],
            condition_answers=[
                ConditionAnswer(
                    question_id="Q-GAR-1",
                    component_id="GAR-01",
                    answer="works_normally",
                    maps_to_condition="fair",   # benign enum — must NOT override specific mapping
                    maps_to_severity="low",
                )
            ],
            seller_confirmed_tags=[],
        )
        instance, _, enriched, _ = _run_full_pipeline(submission)

        floor_ids = {r["component_id"] for r in enriched if r.get("in_floor")}
        assert "GAR-01" not in floor_ids, \
            "GAR-01 with 'works_normally' falsely qualified for floor — maps_to_condition='fair' should not override specific mapping"
