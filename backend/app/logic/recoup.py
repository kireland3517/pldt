"""
recoup.py — attaches ROI and refines the better-value call.

Separates defect-clearing from upgrading:
  - Defect-clearing (safety_eligible / lender_eligible / essential_when_needed):
    recoup is modeled against the whole sale. Fixing a lender blocker doesn't
    "add" value above as-is — it removes a discount. Effective recoup = 100%
    of the avoided discount (modeled as: you get the as-is price instead of
    a haircut price). The library's recoup_pct for these items reflects this.
  - Upgrade (everything else): recoup_pct is a fraction of cost returned as
    value at sale. Source from library (CvV-anchored or estimated).

Output: repair rows with recoup_pct, recoup_source, is_defect_clearing,
        effective_recoup_pct, and a refined better_value call.
"""

from __future__ import annotations

from typing import List


# The 5 CvV-anchored values from the library (verify source in README_data_dictionary)
_CVV_ANCHORED = {"GAR-01", "XDR-01", "KIT-01", "DECK-01", "WIN-01"}

# Ordinal severity ranking for investor_cap_eligible comparison.
# Vocabulary matches condition.py (high / medium / low / None).
# severity_detected on each enriched row must be >= the component's
# investor_cap_severity_threshold from the library for the cap to fire.
#
# FAIL-SAFE: any string NOT in this dict — including None, "", "unknown",
# "inspect", "unclear", "pending" — gets the dict default of 0.
# Rank 0 is below every threshold (FND-01 medium=2, ROOF-01/ELEC-01 high=3).
# Unknown or missing severity NEVER triggers the investor cap.
# This is the right default: uncertain detection should route to "get it
# inspected", not to the heaviest pricing hammer in the model.
_SEVERITY_RANK = {
    "none":   0,   # good condition / no defect
    "low":    1,   # minor issue (e.g. ELEC-01 missing cover plate)
    "medium": 2,   # moderate issue (e.g. FND-01 active moisture → FHA gate)
    "high":   3,   # major / serious defect (ROOF-01 active leak, ELEC-01 unsafe panel)
    # Keys NOT in this dict (None, "", "unknown", "inspect", etc.): default 0 → no cap
}


def attach_recoup(repair_rows: List[dict], library: dict) -> List[dict]:
    """
    Attach ROI data and refine better_value call for each repair row.

    library: the full library dict from ReferenceData (keyed by component_id).
    """
    enriched = []
    for row in repair_rows:
        cid  = row["component_id"]
        lib  = library.get(cid, {})

        recoup_pct    = lib.get("recoup_pct",    50.0)
        recoup_source = lib.get("recoup_source", "estimate")
        is_defect     = (
            lib.get("safety_eligible")      or
            lib.get("lender_eligible")       or
            lib.get("essential_when_needed")
        )

        # Effective ROI label shown to seller
        if is_defect:
            effective_recoup_label = "enables sale / removes discount"
        else:
            effective_recoup_label = f"{recoup_pct:.0f}% of cost returns at sale"

        # Refined better_value call
        better_value = _refined_call(row, recoup_pct, recoup_source, is_defect)

        # Library cost anchors — used by optimizer tier-multiplier model.
        # These are the LIBRARY midpoints, independent of any contractor quote
        # the seller may enter in the UI. Recovery is capped to library cost
        # so overpaying a contractor cannot inflate projected sale price.
        def _lib_mid(lo_key, hi_key):
            lo = lib.get(lo_key)
            hi = lib.get(hi_key)
            try:
                lo, hi = float(lo), float(hi)
                return round((lo + hi) / 2, 2)
            except (TypeError, ValueError):
                return None

        # Investor-cap eligibility: fires only when BOTH conditions hold:
        #   1. component has an investor_cap_severity_threshold in the library
        #   2. the DETECTED severity for this instance >= that threshold
        # This prevents a missing cover plate on ELEC-01 (severity=low)
        # from triggering investor pricing. Only unsafe-panel-level defects do.
        # Same for ROOF-01 (active leak = high, sound roof = no cap) and
        # FND-01 (active moisture = medium+, dry crawlspace = no cap).
        # Fail-safe: None/empty/"unknown" → _SEVERITY_RANK default 0 → cap never fires.
        _cap_threshold_str = (lib.get("investor_cap_severity_threshold") or "").strip()
        if _cap_threshold_str and lib.get("lender_eligible"):
            detected_sev = (row.get("severity_detected") or "").lower().strip()
            detected_rank = _SEVERITY_RANK.get(detected_sev, 0)
            threshold_rank = _SEVERITY_RANK.get(_cap_threshold_str, 999)
            _investor_cap_eligible = detected_rank >= threshold_rank
        else:
            _investor_cap_eligible = False

        enriched.append({
            **row,
            "recoup_pct":           recoup_pct,
            "recoup_source":        recoup_source,
            "is_defect_clearing":   bool(is_defect),
            "effective_recoup_label": effective_recoup_label,
            "better_value":         better_value,
            # V5: copy eligibility flags so floor.py _floor_reason can show real reason
            "safety_eligible":      bool(lib.get("safety_eligible")),
            "lender_eligible":      bool(lib.get("lender_eligible")),
            "essential_when_needed": bool(lib.get("essential_when_needed")),
            # Haircut model: library cost anchors + severity tier
            "severity_tier":        lib.get("severity_tier", "") or "",
            "library_cost_mid_repair":   _lib_mid("repair_low",  "repair_high"),
            "library_cost_mid_replace":  _lib_mid("replace_low", "replace_high"),
            # investor_cap_eligible: True only when detected severity >= threshold
            # (e.g. ELEC-01 minor defect = False; ELEC-01 unsafe panel = True)
            "investor_cap_eligible":      _investor_cap_eligible,
            "investor_cap_severity_threshold": _cap_threshold_str,
        })

    return enriched


def _refined_call(row: dict, recoup_pct: float, source: str, is_defect: bool) -> str:
    """
    ROI-aware better_value recommendation.

    Rules:
    0. Terminal failure signals → replace always (repair is not viable when
       the component has failed, is non-functional, or has structural failure).
    1. Floor items (defect, in_floor=True): replace if failed/non-functional,
       otherwise repair unless not repairable. Credit not viable (loan blocks).
    2. Non-floor defects: repair if cheaper and recoup is acceptable.
    3. Upgrades with CvV-anchored high recoup (>=100%): prefer repair or the
       cheaper option; these are the high-ROI moves.
    4. Low-recoup items (<50%): lean toward credit if creditable, else leave.
    """
    in_floor   = row.get("in_floor", False)
    repairable = row.get("repairable", False)
    creditable = row.get("creditable", False)
    repair_mid  = row.get("cost_mid_repair")
    replace_mid = row.get("cost_mid_replace")

    # Rule 0: terminal failure → replace is the only defensible action.
    # "Failed" means the component is beyond repair; repair estimates do not apply.
    _TERMINAL_SIGNALS = (
        "failed",
        "non-functional",
        "structural failure",
        "structural hazard",
        "end-of-life",
        "eol",
        "does not work",
        "beyond service life",
        "beyond typical service life",
    )
    cond_lower = (row.get("condition_detected") or "").lower()

    # Good-condition gate (defense in depth — repair_replace.py should have
    # already excluded these, but guard here too).
    _GOOD_SIGNALS = ("good condition",)
    if any(sig in cond_lower for sig in _GOOD_SIGNALS) and not in_floor:
        return "leave"

    if any(sig in cond_lower for sig in _TERMINAL_SIGNALS):
        return "replace"

    # Floor items must be fixed; credit is not acceptable.
    # Action is driven by condition severity (terminal signals above) and
    # repairability — NOT by ROI. A4: recoup does not govern floor item action.
    if in_floor:
        return "repair" if repairable else "replace"

    # Non-floor: use ROI to guide
    if recoup_pct >= 100 and repairable:
        return "repair"
    if recoup_pct >= 75 and repairable:
        # Repair if it's clearly cheaper than replace
        if repair_mid is not None and replace_mid is not None:
            return "repair" if repair_mid < replace_mid * 0.60 else "replace"
        return "repair"
    if recoup_pct < 50:
        if creditable:
            return "credit"
        return "leave"

    # Mid-range: default to repair or credit
    if repairable:
        return "repair"
    if creditable:
        return "credit"
    return "leave"
