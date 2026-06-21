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

        enriched.append({
            **row,
            "recoup_pct":           recoup_pct,
            "recoup_source":        recoup_source,
            "is_defect_clearing":   bool(is_defect),
            "effective_recoup_label": effective_recoup_label,
            "better_value":         better_value,
        })

    return enriched


def _refined_call(row: dict, recoup_pct: float, source: str, is_defect: bool) -> str:
    """
    ROI-aware better_value recommendation.

    Rules:
    1. Floor items (defect, in_floor=True): use repair unless repair is not
       possible, then replace. Credit is not viable for lender/safety items
       (loan can't close until fixed).
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

    # Floor items must be fixed; credit is not acceptable
    if in_floor:
        if repairable:
            # Prefer repair unless replace is only marginally more and recoup is high
            if (repair_mid is not None and replace_mid is not None
                    and replace_mid < repair_mid * 1.5 and recoup_pct >= 150):
                return "replace"
            return "repair"
        return "replace"

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
