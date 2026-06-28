"""
floor.py — computes the mandatory Floor from the enriched repair rows.

Rule: a component is in the Floor when:
  - present=True
  - defect_qualifies_floor=True  (set by capture.py using floor_trigger matching)

This module collects those rows, resolves shared_structure dedup, and
returns the Floor item list with costs.

Shared-staircase note (v1 known simplification):
  shared_structure is set by capture.py when BOTH DECK-01 and PRCH-01 have
  a railing/riser defect. In v1 this is used as a proxy for "one staircase
  serving both." The actual sharing depends on the house's physical layout
  (a layout question would be the correct test). Do not treat v1 dedup
  as authoritative for non-standard configurations.

Cost counting rule when shared_structure is set:
  The "owner" component (e.g. DECK-01) carries the staircase cost in full.
  The "dependent" component (e.g. PRCH-01 with shared_structure="DECK-01")
  contributes $0 to the Floor cost total — it's already counted under the owner.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple


def compute_floor(enriched_rows: List[dict]) -> dict:
    """
    Collect Floor items and compute total Floor cost.

    Returns:
    {
        "items":      List[FloorItemDict],
        "cost_low":   float,
        "cost_high":  float,
        "cost_mid":   float,
        "item_count": int,        # physical items (not counting shared dedup)
    }
    """
    floor_rows = [r for r in enriched_rows if r.get("in_floor") or r.get("defect_qualifies_floor")]

    # Resolve shared_structure: components that are owned by another in the Floor
    # should not add their cost to the total.
    owner_ids = {r["component_id"] for r in floor_rows}
    items: List[dict] = []
    cost_low  = 0.0
    cost_high = 0.0

    for row in floor_rows:
        shared = row.get("shared_structure")
        cost_contributing = True

        if shared and shared in owner_ids:
            # This component's physical structure is counted under the owner.
            cost_contributing = False

        # Choose cost basis: repair preferred for Floor items if repairable,
        # replace otherwise.
        better_value = row.get("better_value", "repair")
        if better_value in ("repair",):
            item_low  = row.get("repair_low")  or row.get("replace_low")  or 0
            item_high = row.get("repair_high") or row.get("replace_high") or 0
            path_used = "repair"
        else:
            item_low  = row.get("replace_low")  or row.get("repair_low")  or 0
            item_high = row.get("replace_high") or row.get("repair_high") or 0
            path_used = "replace"

        if cost_contributing:
            cost_low  += item_low
            cost_high += item_high

        reason = _floor_reason(row)

        items.append({
            "component_id":      row["component_id"],
            "display_name":      row["display_name"],
            "zone":              row["zone"],
            "reason":            reason,
            "path_used":         path_used,
            "cost_low":          item_low,
            "cost_high":         item_high,
            "cost_mid":          (item_low + item_high) / 2,
            "cost_contributing": cost_contributing,
            "shared_structure":  row.get("shared_structure"),
            "condition_detected": row.get("condition_detected"),
            "confidence":        row.get("confidence", 0.7),
            "recoup_pct":        row.get("recoup_pct", 100.0),
            "notes":             row.get("notes", ""),
        })

    return {
        "items":      items,
        "cost_low":   cost_low,
        "cost_high":  cost_high,
        "cost_mid":   (cost_low + cost_high) / 2,
        "item_count": len(items),
    }


def _floor_reason(row: dict) -> str:
    """Plain-language reason for Floor membership."""
    reasons = []
    if row.get("safety_eligible"):
        reasons.append("safety hazard")
    if row.get("lender_eligible"):
        reasons.append("lender required")
    if row.get("essential_when_needed"):
        reasons.append("essential remediation")
    return "; ".join(reasons) if reasons else "required"
