"""
compute.py — run the full logic chain and expose results.

GET  /session/{id}/compute          Run chain (cached); return full result.
PATCH /session/{id}/inputs          Update seller inputs; invalidate cache.
POST  /session/{id}/reverse         Reverse-goal: find plan that hits target net.
"""
from __future__ import annotations

import json
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db import get_db, TABLE
from ..data_loader import ReferenceData, load_property_inputs
from ..logic.valuation import compute_as_is_range
from ..logic.condition import build_condition_list, condition_summary
from ..logic.repair_replace import build_repair_rows
from ..logic.recoup import attach_recoup
from ..logic.floor import compute_floor
from ..logic.dom import estimate_dom, estimate_carrying_cost
from ..logic.optimizer import build_plans

router = APIRouter()

_ref: ReferenceData | None = None

def _get_ref() -> ReferenceData:
    global _ref
    if _ref is None:
        _ref = ReferenceData()
    return _ref


def _run_chain(session: dict, ref: ReferenceData) -> dict:
    """
    Execute the full logic chain for a session row.
    Returns the compute result dict (also stored as compute_result in DB).
    Blindness: reads property_json and instance_json from session; never
    reads validation/.
    """
    prop         = session["property_json"]
    instance     = session["instance_json"]
    listing_month = session.get("listing_month", 6)
    seller_inputs = session.get("seller_inputs") or {}
    commission_rate = session.get("commission_rate") or 0.06
    has_hoa      = session.get("has_hoa", False)

    if not prop:
        raise HTTPException(status_code=422, detail="Session has no property_json. Re-create session.")
    if not instance:
        raise HTTPException(status_code=422, detail="Session has no capture data. POST to /capture first.")

    # Valuation
    val = compute_as_is_range(prop)

    # Condition list
    cond_list = build_condition_list(instance, ref, has_inspection=False)
    summary   = condition_summary(cond_list)

    # Repair rows + recoup
    repair_rows = build_repair_rows(cond_list)
    enriched    = attach_recoup(repair_rows, ref.library)

    # Floor
    floor_result = compute_floor(enriched)

    # Plans (optimizer)
    plans = build_plans(
        enriched_rows=enriched,
        floor_result=floor_result,
        valuation=val,
        dom_data=ref.dom,
        closing_constants=ref.sc_closing,
        property_inputs=prop,
        seller_inputs=seller_inputs,
        listing_month=listing_month,
        commission_rate=commission_rate,
        has_hoa=has_hoa,
    )

    return {
        "valuation":         val,
        "condition_summary": summary,
        "floor":             floor_result,
        "repair_table":      enriched,
        "plans":             plans,
    }


@router.get("/{session_id}/compute")
def compute(session_id: str, refresh: bool = False):
    """
    Run the full chain and return results.
    Results are cached in DB; pass ?refresh=true to force recompute.
    """
    db  = get_db()
    ref = _get_ref()

    row = db.table(TABLE).select("*").eq("id", session_id).maybe_single().execute()
    if not row.data:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found.")

    session = row.data

    # Return cached result unless refresh requested or cache is empty
    if session.get("compute_result") and not refresh:
        return {"session_id": session_id, "cached": True, **session["compute_result"]}

    result = _run_chain(session, ref)

    # Cache result and advance status
    db.table(TABLE).update({
        "compute_result": result,
        "status": "compute",
    }).eq("id", session_id).execute()

    return {"session_id": session_id, "cached": False, **result}


class InputsUpdate(BaseModel):
    commission_rate: Optional[float] = None
    has_hoa: Optional[bool] = None
    listing_month: Optional[int] = None
    seller_inputs: Optional[dict] = None    # merged into existing seller_inputs


@router.patch("/{session_id}/inputs")
def update_inputs(session_id: str, body: InputsUpdate):
    """
    Update seller inputs or listing params. Invalidates compute cache so
    next GET /compute reflects the change.
    """
    db = get_db()

    row = db.table(TABLE).select(
        "id, seller_inputs, commission_rate, has_hoa, listing_month"
    ).eq("id", session_id).maybe_single().execute()
    if not row.data:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found.")

    patch: dict = {"compute_result": None}   # always invalidate cache

    if body.commission_rate is not None:
        patch["commission_rate"] = body.commission_rate
    if body.has_hoa is not None:
        patch["has_hoa"] = body.has_hoa
    if body.listing_month is not None:
        patch["listing_month"] = body.listing_month
    if body.seller_inputs is not None:
        existing = row.data.get("seller_inputs") or {}
        patch["seller_inputs"] = {**existing, **body.seller_inputs}

    db.table(TABLE).update(patch).eq("id", session_id).execute()
    return {"session_id": session_id, "updated": list(patch.keys())}


class ReverseRequest(BaseModel):
    target_net: float


@router.post("/{session_id}/reverse")
def reverse_goal(session_id: str, body: ReverseRequest):
    """
    Given a target net proceeds, find the cheapest plan that meets it.
    Runs chain if not cached. Returns the matching plan or 'not achievable'.
    """
    db  = get_db()
    ref = _get_ref()

    row = db.table(TABLE).select("*").eq("id", session_id).maybe_single().execute()
    if not row.data:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found.")

    session = row.data
    result  = session.get("compute_result") or _run_chain(session, ref)
    plans   = result["plans"]

    # Walk from leaner -> recommended -> do_everything; pick first that beats target
    for level in ("leaner", "recommended", "do_everything"):
        p  = plans.get(level, {})
        np = p.get("net_proceeds", {}).get("net_proceeds", 0)
        if np >= body.target_net:
            return {
                "session_id":  session_id,
                "target_net":  body.target_net,
                "achievable":  True,
                "plan":        level,
                "net_proceeds": np,
                "dom":         p.get("dom", {}).get("estimated_dom"),
                "message":     f"'{level}' plan reaches ${np:,.0f} net, meeting your ${body.target_net:,.0f} target.",
            }

    # None of the plans hit target
    best_plan  = plans.get("leaner", {})
    best_net   = best_plan.get("net_proceeds", {}).get("net_proceeds", 0)
    return {
        "session_id":  session_id,
        "target_net":  body.target_net,
        "achievable":  False,
        "plan":        None,
        "net_proceeds": best_net,
        "message":     (
            f"Target ${body.target_net:,.0f} is not achievable with any plan. "
            f"Best available is ${best_net:,.0f} (leaner plan). "
            "Consider adjusting payoff, commission rate, or target."
        ),
    }
