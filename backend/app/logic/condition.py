"""
condition.py — assembles the structured condition list from the filled instance.

Reads the filled instance (output of capture.py) and joins library context.
Output is the per-component condition records used by all downstream modules.
Blindness: reads only the filled instance and the library.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from ..data_loader import ReferenceData


def build_condition_list(
    instance: Dict[str, dict],
    ref: ReferenceData,
    has_inspection: bool = False,
) -> List[dict]:
    """
    Build the structured condition list from the filled instance + library.

    Includes only components confirmed present (present=True).
    For library components typed "always" where presence was never answered,
    marks them as assumed-present at low confidence (0.3) so the seller
    sees them as items to confirm, not silently skip.

    Returns a list of condition records sorted by zone then severity.
    """
    records: List[dict] = []
    sev_rank = {"high": 0, "medium": 1, "low": 2, None: 3}

    for cid, item in instance.items():
        lib = ref.library.get(cid, {})
        if not lib:
            continue

        # Determine effective presence
        present = item.get("present")
        if present is False:
            continue
        if present is None:
            if lib.get("typical_in_home") == "always":
                effective_present = True
                assumed = True
            else:
                continue  # unknown presence for non-universal components; skip
        else:
            effective_present = True
            assumed = False

        if not effective_present:
            continue

        record = {
            # Identity
            "component_id":         cid,
            "display_name":         lib["display_name"],
            "zone":                 lib["zone"],
            # Library context
            "typical_in_home":      lib["typical_in_home"],
            "work_type_default":    lib["work_type_default"],
            "repairable":           lib["repairable"],
            "creditable":           lib["creditable"],
            "recoup_pct":           lib.get("recoup_pct", 50.0),
            "recoup_source":        lib.get("recoup_source", "estimate"),
            "safety_eligible":      lib["safety_eligible"],
            "lender_eligible":      lib["lender_eligible"],
            "essential_when_needed":lib["essential_when_needed"],
            "floor_trigger":        lib["floor_trigger"],
            # Cost ranges from library
            "repair_low":           lib.get("repair_low"),
            "repair_high":          lib.get("repair_high"),
            "replace_low":          lib.get("replace_low"),
            "replace_high":         lib.get("replace_high"),
            # Instance state
            "condition_detected":   item.get("condition_detected"),
            "severity_detected":    item.get("severity_detected"),
            "defect_qualifies_floor": item.get("defect_qualifies_floor", False),
            "chosen_path":          item.get("chosen_path"),
            "source":               item.get("source") or ("assumed" if assumed else None),
            "confidence":           item.get("confidence") or (0.30 if assumed else 0.50),
            "notes":                item.get("notes") or lib["notes"],
            "shared_structure":     item.get("shared_structure"),
            # Age / replacement signal
            "recent_replacement":   item.get("recent_replacement", False),
            "upgrade_candidate":    item.get("upgrade_candidate", False),
            # Flags
            "assumed_present":      assumed,
            "has_inspection":       has_inspection,
        }
        records.append(record)

    # Sort: floor items first, then by severity, zone, name
    records.sort(key=lambda r: (
        0 if r["defect_qualifies_floor"] else 1,
        sev_rank.get(r["severity_detected"], 3),
        r["zone"],
        r["display_name"],
    ))

    return records


def condition_summary(condition_list: List[dict]) -> dict:
    """High-level counts useful for the UI confidence display."""
    total    = len(condition_list)
    floor    = sum(1 for r in condition_list if r["defect_qualifies_floor"])
    high     = sum(1 for r in condition_list if r.get("severity_detected") == "high")
    low_conf = sum(1 for r in condition_list if (r.get("confidence") or 1.0) < 0.6)

    # Positive signals: recently-replaced systems are selling points
    recent = [
        {"component_id": r["component_id"], "display_name": r["display_name"]}
        for r in condition_list
        if r.get("recent_replacement")
    ]

    return {
        "total_present":        total,
        "floor_items":          floor,
        "high_severity":        high,
        "low_confidence_items": low_conf,
        "has_inspection":       any(r.get("has_inspection") for r in condition_list),
        # Positive signals for the seller narrative
        "recent_replacements":  recent,
        "positive_signal_count": len(recent),
    }
