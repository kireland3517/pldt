"""
capture.py — the only path by which condition enters the instance layer.

BLIND RULE: this module starts from a BLANK instance and fills it from
photo tags and questionnaire answers only. It never reads validation/.
It never loads a pre-built condition list.

Two-pass fill:
  Pass 1 — Photo tags (Tier 2 vision): set component PRESENCE and
            visible condition where photos show it.
  Pass 2 — Questionnaire:
      a. Presence questions: confirm / fill presence for components
         photos couldn't resolve (e.g. crawlspace type, HVAC age).
      b. Condition questions: assess components confirmed present,
         filling gaps photos can't see.

Shared-staircase dedup rule (DECK-01 / PRCH-01):
  If DECK-01 and PRCH-01 are both present and Q-PRCH-1 detects a
  railing/riser hazard, the defect is recorded on PRCH-01 with
  shared_structure="DECK-01". floor.py reads this flag and counts
  the staircase cost once (under DECK-01).

ELEC-01 partial-detection contract:
  Q-ELEC-1 asks about visible wiring issues (panel, attic, cover plates).
  Hidden junction boxes are not seller-visible without an inspection.
  A "no" answer means "nothing visible," not "no electrical issues."
  Confidence for ELEC-01 is capped at 0.6 without an inspection report.
  This is expected behavior in the blind test, not a defect.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from ..data_loader import ReferenceData
from ..models import CaptureSubmission, PhotoTag, PresenceAnswer, ConditionAnswer


# ---------------------------------------------------------------------------
# Confidence constants
# ---------------------------------------------------------------------------

CONF_PHOTO_HIGH   = 0.85   # vision model saw it clearly
CONF_PHOTO_MED    = 0.65   # vision model partial / uncertain tag
CONF_Q_DIRECT     = 0.90   # seller answered a direct condition question
CONF_Q_INFERRED   = 0.70   # condition inferred from a non-specific answer
CONF_NO_INPUT     = 0.40   # component present but no condition info given
CONF_ELEC_MAX_BLIND = 0.60  # ELEC-01 without inspection (hidden boxes unknown)

# How much inspection presence boosts confidence across the board
INSPECTION_CONFIDENCE_BOOST = 0.10


# ---------------------------------------------------------------------------
# Severity helpers
# ---------------------------------------------------------------------------

_SEVERITY_WORDS = {
    "high":   {"standing", "active", "structural", "missing", "non-functional",
               "open", "exposed", "hazard", "heavy", "non_functional"},
    "medium": {"past", "moisture", "dated", "aged", "worn", "minor",
               "functional", "partial"},
    "low":    {"cosmetic", "clean", "service", "cheap", "optional"},
}

def _infer_severity(condition_text: str) -> str:
    words = set(re.sub(r"[^a-z_\s]", "", condition_text.lower()).split())
    for level in ("high", "medium", "low"):
        if words & _SEVERITY_WORDS[level]:
            return level
    return "medium"


# ---------------------------------------------------------------------------
# Floor-trigger matcher
# ---------------------------------------------------------------------------

_TRIGGER_KEYWORDS: Dict[str, List[str]] = {
    # component_id -> keywords that, if found in condition_detected, confirm the trigger
    "ROOF-01":   ["leak", "active leak", "end-of-life", "eol", "failed"],
    "FND-01":    ["standing water", "standing_water", "active water", "moisture",
                  "efflorescence", "structural movement"],
    "GUT-01":    ["water intrusion", "intrusion", "drainage causing"],
    "WIN-01":    ["safety glazing", "stairwell", "door glass", "wet area"],
    "DECK-01":   ["open riser", "loose railing", "rot", "structural hazard",
                  "open risers", "loose railing", "deteriorated tread"],
    "PRCH-01":   ["loose handrail", "missing handrail", "open riser",
                  "open risers", "deteriorated tread", "railing"],
    "HVAC-01":   ["non-functional", "non_functional", "not operating", "failed"],
    "WH-HTR-01": ["non-functional", "leaking", "failed", "beyond service life", "beyond typical service life"],
    "ELEC-01":   ["open junction", "exposed wiring", "missing cover",
                  "unsafe panel", "open box"],
    "PLMB-01":   ["active leak", "non-functional supply", "leaking"],
    "DET-01":    ["missing", "beyond service life", "old", "non-functional"],
    "DUCT-01":   ["heavy contamination", "smoke residue", "contamination"],
    "OUT-01":    ["missing cover", "missing covers", "shock hazard"],
    "REM-01":    ["heavy smoke", "heavy cigarette", "smoke odor", "smoke staining",
                  "heavy cigarette/smoke"],
    "GAR-01":    ["non-functional", "non_functional", "damaged door",
                  "does not work", "does_not_work"],
}

def defect_matches_floor_trigger(component_id: str, condition_detected: str) -> bool:
    """
    Return True if condition_detected contains keywords matching the
    floor_trigger for this component.
    Eligibility flags alone are not enough — a detected defect is required.

    Negation guard: if the sentence containing the keyword starts with "no ",
    "not ", "none", or contains "no <keyword>" or "not <keyword>", skip it.
    This prevents "no active leak observed" from matching the "leak" keyword.
    """
    if not condition_detected:
        return False
    cond_lower = condition_detected.lower()
    keywords = _TRIGGER_KEYWORDS.get(component_id, [])
    for kw in keywords:
        if kw not in cond_lower:
            continue
        # Negation check: look at the 20-char window before the keyword
        idx = cond_lower.find(kw)
        window = cond_lower[max(0, idx - 20): idx]
        if any(neg in window for neg in ("no ", "not ", "none", "without ")):
            continue   # "no active leak" — skip
        return True
    return False


# ---------------------------------------------------------------------------
# Pass 1: Photo tag processing
# ---------------------------------------------------------------------------

# Vision tag format: "<component_id>_<condition_tag>" or "<component_id>_present"
# Condition tags that indicate a defect condition (not just presence)
_VISION_CONDITION_TAGS: Dict[str, Tuple[str, str]] = {
    # tag suffix -> (condition_detected, severity)
    "open_risers_visible":    ("open risers visible",           "high"),
    "loose_railing_visible":  ("loose railing visible",         "high"),
    "deck_rot_visible":       ("deck rot visible",              "high"),
    "standing_water_visible": ("standing water visible",        "high"),
    "moisture_staining":      ("moisture staining visible",     "medium"),
    "smoke_staining_visible": ("heavy smoke staining visible",  "high"),
    "smoke_odor_noted":       ("heavy smoke odor noted",        "high"),
    "dated_fixtures":         ("dated fixtures",                "low"),
    "missing_covers":         ("missing cover plates",          "high"),
    "exposed_wiring":         ("exposed wiring visible",        "high"),
    "non_functional":         ("non-functional",                "high"),
    "damaged":                ("damaged",                       "medium"),
    "missing":                ("missing",                       "high"),
    "cracked":                ("cracked",                       "medium"),
    "weathered":              ("weathered",                     "low"),
    "aged":                   ("aged",                          "low"),
}

def apply_photo_tags(
    instance: Dict[str, dict],
    photo_tags: List[PhotoTag],
    ref: ReferenceData,
) -> Dict[str, dict]:
    """
    Pass 1: apply vision-model photo tags to the instance.
    Tags set PRESENCE and visible CONDITION; they never set cost or severity directly.
    """
    for tag in photo_tags:
        cid = tag.component_id
        if cid not in instance:
            continue  # unknown component; skip

        item = instance[cid]

        # A tag whose name is just "<cid>_present" sets presence only
        if tag.tag.endswith("_present") or tag.tag == "present":
            if item["present"] is None:
                item["present"] = True
                item["source"] = "photo"
                item["confidence"] = max(item["confidence"] or 0, tag.confidence)
            continue

        # Condition tags
        tag_suffix = tag.tag.replace(f"{cid}_", "").strip()
        if tag_suffix in _VISION_CONDITION_TAGS:
            cond_text, severity = _VISION_CONDITION_TAGS[tag_suffix]
            item["present"] = True
            # Take the more severe condition if multiple tags arrive
            if item["condition_detected"] is None:
                item["condition_detected"] = cond_text
                item["severity_detected"]  = severity
            else:
                existing_sev = item["severity_detected"] or "low"
                if _sev_rank(severity) > _sev_rank(existing_sev):
                    item["condition_detected"] = cond_text
                    item["severity_detected"]  = severity
            item["source"] = "photo"
            item["confidence"] = max(item["confidence"] or 0, tag.confidence)

    return instance


def _sev_rank(s: str) -> int:
    return {"low": 0, "medium": 1, "high": 2}.get(s, 0)


# ---------------------------------------------------------------------------
# Pass 2a: Presence questions
# ---------------------------------------------------------------------------

# Map presence question answers to instance state changes
_FOUNDATION_TYPE_MAP = {
    "crawlspace": ("present", True),
    "basement":   ("present", True),
    "slab":       ("present", False),   # FND-01 not applicable on slab
}

def apply_presence_answers(
    instance: Dict[str, dict],
    answers: List[PresenceAnswer],
    ref: ReferenceData,
) -> Dict[str, dict]:
    """
    Pass 2a: presence questions establish which library components this house has.
    """
    for ans in answers:
        maps_to = ans.component_id  # may be a list (e.g. ["BTHP-01", "BTHS-01"])
        cids = maps_to if isinstance(maps_to, list) else [maps_to]

        for cid in cids:
            if cid not in instance:
                continue
            item = instance[cid]

            # Foundation type special case
            if ans.question_id == "P-CRAWL":
                pres, val = _FOUNDATION_TYPE_MAP.get(ans.answer, ("present", True))
                item["present"] = val
                item["source"]  = item["source"] or "questionnaire"
                item["confidence"] = item["confidence"] or CONF_Q_DIRECT
                continue

            # Age-band questions: set condition text so downstream can use it.
            # PRECEDENCE: seller answer is the ground truth for system age.
            # Build year is only a fallback when the seller answers "unknown".
            # A recently-replaced system must NOT be treated as old.
            if ans.question_id in ("P-HVAC-AGE", "P-WH-AGE", "P-ROOF-AGE"):
                item["present"] = True
                item["source"]  = item["source"] or "questionnaire"
                age_band = ans.answer  # e.g. "0-5", "6-10", "15+", "unknown"
                # Seller answer REPLACES any prior build-year inference
                item["condition_detected"] = f"age band: {age_band}"
                item["confidence"] = item["confidence"] or CONF_Q_DIRECT
                # Flag recent replacements as a positive selling point
                _RECENT_BANDS = {"0-5", "0_5", "new", "recent", "1", "2", "3", "4", "5"}
                if str(age_band).lower() in _RECENT_BANDS:
                    item["recent_replacement"] = True
                    item["condition_detected"] = f"recently replaced (age band: {age_band})"
                continue

            # Bath count: P-BATHS maps to BTHP-01 and BTHS-01
            if ans.question_id == "P-BATHS":
                n = int(ans.answer.replace("+", "")) if ans.answer != "3+" else 3
                if cid == "BTHP-01":
                    item["present"] = n >= 1
                elif cid == "BTHS-01":
                    item["present"] = n >= 2
                item["source"]     = item["source"] or "questionnaire"
                item["confidence"] = item["confidence"] or CONF_Q_DIRECT
                continue

            # ELEC-01 access question: presence is always true (it's a system);
            # "cannot access" lowers confidence
            if ans.question_id == "P-ELEC":
                item["present"] = True
                if ans.answer == "no_cannot_access":
                    item["confidence"] = min(item["confidence"] or CONF_ELEC_MAX_BLIND,
                                             CONF_ELEC_MAX_BLIND)
                    item["notes"] = (item["notes"] or "") + \
                        " Panel/attic not accessible; ELEC-01 confidence capped."
                item["source"] = item["source"] or "questionnaire"
                continue

            # Generic yes/no presence
            item["present"] = (ans.answer.lower() == "yes")
            item["source"]  = item["source"] or "questionnaire"
            item["confidence"] = item["confidence"] or CONF_Q_DIRECT

    return instance


# ---------------------------------------------------------------------------
# Pass 2b: Condition questions
# ---------------------------------------------------------------------------

def apply_condition_answers(
    instance: Dict[str, dict],
    answers: List[ConditionAnswer],
    ref: ReferenceData,
    has_inspection: bool,
) -> Dict[str, dict]:
    """
    Pass 2b: condition questions fill in what photos can't resolve.
    Only fires for components confirmed present in pass 2a.
    """
    conf_base = CONF_Q_DIRECT
    if has_inspection:
        conf_base = min(conf_base + INSPECTION_CONFIDENCE_BOOST, 1.0)

    for ans in answers:
        maps_to = ans.component_id
        cids = maps_to if isinstance(maps_to, list) else [maps_to]

        for cid in cids:
            if cid not in instance:
                continue
            item = instance[cid]

            # Skip if component not present (shouldn't happen, but guard it)
            if not item["present"]:
                continue

            # Use the normalized condition from the answer if provided;
            # otherwise derive it from the raw answer value.
            cond = ans.maps_to_condition or _answer_to_condition(ans.question_id, ans.answer)
            sev  = ans.maps_to_severity  or _infer_severity(cond)

            if item["condition_detected"] is None:
                item["condition_detected"] = cond
                item["severity_detected"]  = sev
            else:
                # Merge: take higher severity; append condition text if different
                if _sev_rank(sev) > _sev_rank(item["severity_detected"] or "low"):
                    item["severity_detected"] = sev
                if cond.lower() not in (item["condition_detected"] or "").lower():
                    item["condition_detected"] = (item["condition_detected"] or "") + "; " + cond

            item["source"]     = item["source"] or "questionnaire"
            item["confidence"] = max(item["confidence"] or 0, conf_base)

            # --- ELEC-01 confidence cap (hidden boxes unknown without inspection) ---
            if cid == "ELEC-01" and not has_inspection:
                item["confidence"] = min(item["confidence"], CONF_ELEC_MAX_BLIND)
                note = "Partial detection: hidden junction boxes not seller-visible without inspection."
                if note not in (item["notes"] or ""):
                    item["notes"] = ((item["notes"] or "") + " " + note).strip()

    return instance


def _answer_to_condition(question_id: str, answer: str) -> str:
    """Map a question-answer pair to a plain-text condition string."""
    _map: Dict[str, Dict[str, str]] = {
        "Q-DECK-1": {
            "yes":  "deck structure sound",
            "no":   "deck structure unsound; structural failure",
        },
        "Q-DECK-2": {
            "yes":  "deck boards soft or rotten; lean replace",
            "no":   "deck boards mostly sound",
        },
        "Q-DECK-3": {
            "yes":  "open risers; loose railing",
            "no":   "railings and risers acceptable",
        },
        "Q-GAR-1": {
            "works_normally":    "garage door functional",
            "does_not_work":     "non-functional door",
            "works_but_damaged": "damaged door; functional but damaged",
        },
        "Q-CRAWL-1": {
            "standing_water_now": "standing water in crawlspace; active water",
            "past_moisture_only": "past moisture; no standing water currently",
            "unsure":             "crawlspace condition unknown; recommend assessment",
        },
        "Q-KIT-1": {
            "yes": "cabinet boxes solid; refresh is viable",
            "no":  "cabinet boxes compromised; consider replace",
        },
        "Q-VAN-1": {
            "yes": "vanity original and dated; replace defensible",
            "no":  "vanity adequate; refresh only",
        },
        "Q-SMOKE-1": {
            "yes": "heavy cigarette/smoke odor or staining detected",
            "no":  "no heavy smoke odor",
        },
        "Q-ELEC-1": {
            "yes": "exposed wiring or missing covers visible",
            "no":  "no visible electrical issues",
        },
        "Q-PRCH-1": {
            "yes": "loose or missing handrail; open risers on porch/deck stairs",
            "no":  "porch stairs and railings acceptable",
        },
    }
    return _map.get(question_id, {}).get(answer, f"{question_id}={answer}")


# ---------------------------------------------------------------------------
# Shared-staircase dedup (DECK-01 / PRCH-01)
# ---------------------------------------------------------------------------

def resolve_shared_stairs(instance: Dict[str, dict]) -> Dict[str, dict]:
    """
    If DECK-01 and PRCH-01 are both present and both have a railing/riser
    defect, they may share one physical staircase. Mark PRCH-01 as
    shared_structure="DECK-01" so floor.py counts the cost once.

    We only do this when BOTH components have a railing/riser defect detected
    and BOTH are present — not merely because both are present.
    """
    deck = instance.get("DECK-01", {})
    prch = instance.get("PRCH-01", {})

    deck_present = deck.get("present") is True
    prch_present = prch.get("present") is True

    if not (deck_present and prch_present):
        return instance

    deck_railing = defect_matches_floor_trigger("DECK-01", deck.get("condition_detected") or "")
    prch_railing = defect_matches_floor_trigger("PRCH-01", prch.get("condition_detected") or "")

    if deck_railing and prch_railing:
        # One staircase. DECK-01 is the owner; PRCH-01 defers.
        instance["PRCH-01"]["shared_structure"] = "DECK-01"
        existing = instance["PRCH-01"].get("notes") or ""
        if "shared staircase" not in existing:
            instance["PRCH-01"]["notes"] = (
                existing + " Shared staircase with DECK-01; cost counted once."
            ).strip()

    return instance


# ---------------------------------------------------------------------------
# Floor qualification pass (sets defect_qualifies_floor)
# ---------------------------------------------------------------------------

def qualify_floor_members(
    instance: Dict[str, dict],
    ref: ReferenceData,
) -> Dict[str, dict]:
    """
    For each present component with a detected defect, decide whether it
    enters the mandatory Floor.

    Rule (from floor.py spec):
      floor_member = present
                     AND condition_detected is not None
                     AND (safety_eligible OR lender_eligible OR essential_when_needed)
                     AND defect_matches(floor_trigger)

    Eligibility alone is NOT enough (the GUT-01 case: lender_eligible=True
    but no drainage-intrusion defect -> stays discretionary).
    """
    for cid, item in instance.items():
        if not item["present"]:
            item["defect_qualifies_floor"] = False
            continue

        if not item["condition_detected"]:
            item["defect_qualifies_floor"] = False
            continue

        if not ref.is_floor_eligible(cid):
            item["defect_qualifies_floor"] = False
            continue

        item["defect_qualifies_floor"] = defect_matches_floor_trigger(
            cid, item["condition_detected"]
        )

    return instance


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_capture(
    submission: CaptureSubmission,
    ref: ReferenceData,
    existing_instance: Optional[Dict[str, dict]] = None,
) -> Dict[str, dict]:
    """
    Run the full capture pipeline for a session.

    Starts from a blank instance (or an existing partial one for resumable
    sessions). Applies photo tags then questionnaire answers. Sets
    defect_qualifies_floor on every component.

    Returns the filled instance dict.
    """
    instance = existing_instance if existing_instance is not None else ref.new_instance()

    has_inspection = submission.has_inspection_report

    # Pass 1: photo tags
    instance = apply_photo_tags(instance, submission.photo_tags, ref)

    # Pass 2a: presence questions
    instance = apply_presence_answers(instance, submission.presence_answers, ref)

    # Pass 2b: condition questions (only for present components)
    instance = apply_condition_answers(
        instance, submission.condition_answers, ref, has_inspection
    )

    # Shared-staircase dedup
    instance = resolve_shared_stairs(instance)

    # Floor qualification
    instance = qualify_floor_members(instance, ref)

    return instance
