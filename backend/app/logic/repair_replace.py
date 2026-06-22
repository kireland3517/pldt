"""
repair_replace.py — generates repair/replace options for each present component.

Input:  condition list (from condition.py)
Output: repair plan rows — one per present component, with cost ranges
        and a preliminary better-value call.

Cost ranges come from the library only. No property-specific costs are invented.
If library data is thin, the row is flagged "estimate pending quote."
"""

from __future__ import annotations

from typing import List


def build_repair_rows(condition_list: List[dict]) -> List[dict]:
    """
    For each condition record, generate a repair plan row.

    better_value_call logic (preliminary — recoup.py refines it):
      - If not repairable → replace (or credit if creditable)
      - If repair_high < replace_low * 0.5 → repair (much cheaper)
      - If recoup on replacement is very high (CvV-anchored) → lean replace
      - Otherwise → repair if repairable, else credit if creditable, else leave
    """
    rows: List[dict] = []

    for rec in condition_list:
        rl = rec.get("repair_low")   # may be None for library gaps
        rh = rec.get("repair_high")
        pl = rec.get("replace_low")
        ph = rec.get("replace_high")

        # Flag thin data
        thin_data = (rl is None or pl is None)

        # Preliminary better-value call (refined by recoup.py after ROI is known)
        call = _preliminary_call(rec)

        row = {
            # Identity
            "component_id":   rec["component_id"],
            "display_name":   rec["display_name"],
            "zone":           rec["zone"],
            # Condition
            "condition_detected":      rec["condition_detected"],
            "severity_detected":       rec["severity_detected"],
            "defect_qualifies_floor":  rec["defect_qualifies_floor"],
            "shared_structure":        rec["shared_structure"],
            # Cost ranges (from library)
            "repair_low":     rl,
            "repair_high":    rh,
            "replace_low":    pl,
            "replace_high":   ph,
            "cost_mid_repair":  _mid(rl, rh),
            "cost_mid_replace": _mid(pl, ph),
            # Viability
            "repairable":    rec["repairable"],
            "creditable":    rec["creditable"],
            # Preliminary call (before ROI)
            "better_value":  call,
            # Floor membership
            "in_floor":      rec["defect_qualifies_floor"],
            # Positive signals
            "recent_replacement": rec.get("recent_replacement", False),
            # Confidence / source
            "confidence":    rec["confidence"],
            "source":        rec["source"],
            "notes":         rec["notes"],
            "thin_data":     thin_data,
        }
        rows.append(row)

    return rows


def _mid(low, high) -> float | None:
    if low is None or high is None:
        return None
    return (low + high) / 2


def _preliminary_call(rec: dict) -> str:
    """
    Preliminary better-value call before ROI is known.
    recoup.py overrides this with a ROI-aware recommendation.
    """
    repairable = rec.get("repairable", False)
    creditable = rec.get("creditable", False)
    rl = rec.get("repair_low")
    rh = rec.get("repair_high")
    pl = rec.get("replace_low")
    ph = rec.get("replace_high")

    if not repairable and not creditable:
        return "replace"
    if not repairable and creditable:
        return "credit"

    # If repair is dramatically cheaper than replace
    repair_mid  = _mid(rl, rh)
    replace_mid = _mid(pl, ph)
    if repair_mid is not None and replace_mid is not None:
        if repair_mid < replace_mid * 0.40:
            return "repair"

    # Default: repair if possible
    return "repair" if repairable else "leave"
