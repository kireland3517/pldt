"""
compute.py — run the full logic chain and expose results.

GET  /session/{id}/compute          Run chain (cached); return full result.
PATCH /session/{id}/inputs          Update seller inputs; invalidate cache.
POST  /session/{id}/reverse         Reverse-goal: find plan that hits target net.
"""
from __future__ import annotations

import json
import os
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
from ..logic.capture import qualify_floor_members

router = APIRouter()

_ref: ReferenceData | None = None

def _get_ref() -> ReferenceData:
    global _ref
    if _ref is None:
        _ref = ReferenceData()
    return _ref


def _ensure_attom_fetched(session: dict, db, session_id: str) -> dict:
    """
    Fetch real market data from ATTOM once per session.
    Caches result in property_json with attom_fetched=True flag.
    Silently skips if ATTOM_API_KEY is not set or the API call fails,
    so the seed data (or empty arrays) serve as the fallback.
    """
    prop = session.get("property_json") or {}
    if prop.get("attom_fetched"):
        return session  # already fetched for this session

    if not os.environ.get("ATTOM_API_KEY"):
        return session  # key not configured; use seed data

    addr = prop.get("address", "")
    if not addr:
        return session

    try:
        from ..services.attom import fetch_attom_data, parse_address
        street, city, state, zip_code = parse_address(addr)
        subject_sqft = float(prop.get("public_county_facts", {}).get("sqft", 0))
        attom_data   = fetch_attom_data(street, city, state, zip_code, subject_sqft)
        updated_prop = {**prop, **attom_data, "attom_fetched": True}
        # Clear compute_result alongside the property_json update so the
        # next compute() call picks up real ATTOM data instead of serving
        # the stale cached result.  No manual ?refresh=true needed.
        db.table(TABLE).update({
            "property_json":  updated_prop,
            "compute_result": None,
        }).eq("id", session_id).execute()
        return {**session, "property_json": updated_prop, "compute_result": None}
    except Exception:
        return session  # ATTOM failed; fall through to seed data


def _run_chain(session: dict, ref: ReferenceData) -> dict:
    """
    Execute the full logic chain for a session row.
    Returns the compute result dict (also stored as compute_result in DB).
    Blindness: reads property_json and instance_json from session; never
    reads validation/.
    """
    # Re-load base property data fresh from seed at compute time so that
    # seed updates (county facts, seller constraints, etc.) flow through
    # to all existing sessions without recreating them.
    property_key = session.get("property_key")
    if property_key:
        try:
            prop = load_property_inputs(property_key)
        except (FileNotFoundError, ValueError):
            prop = session.get("property_json") or {}
    else:
        prop = session.get("property_json") or {}

    # Overlay ATTOM market data cached in session's property_json.
    # _ensure_attom_fetched() stores real comps, AVMs, and history there
    # on the first compute.  Subsequent computes read from cache.
    session_prop = session.get("property_json") or {}
    if session_prop.get("attom_fetched"):
        prop = {
            **prop,
            "fetched_avms":               session_prop.get("fetched_avms") or {},
            "fetched_comps":              session_prop.get("fetched_comps") or [],
            "fetched_active_listings":    session_prop.get("fetched_active_listings") or [],
            "neighborhood_sales_history": session_prop.get("neighborhood_sales_history") or [],
            "attom_meta":                 session_prop.get("attom_meta") or {},
        }
    elif session_prop.get("fetched_comps"):
        # Session has comps without full attom_fetched flag — prefer them over empty seed arrays
        prop["fetched_comps"] = session_prop["fetched_comps"]
        if session_prop.get("fetched_avms"):
            prop["fetched_avms"] = session_prop["fetched_avms"]
        if session_prop.get("neighborhood_sales_history"):
            prop["neighborhood_sales_history"] = session_prop["neighborhood_sales_history"]

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
    try:
        val = compute_as_is_range(prop)
    except ValueError as exc:
        attom_key_set = bool(os.environ.get("ATTOM_API_KEY"))
        detail = f"Valuation failed: {exc}. "
        if not attom_key_set:
            detail += "ATTOM_API_KEY is not set — add it to the Railway backend environment variables to enable live market data."
        else:
            detail += "ATTOM market data fetch may have failed. Try the 'Refresh market data' button, or wait a moment and reload."
        raise HTTPException(status_code=422, detail=detail)

    # Re-evaluate floor qualification at compute time.
    # defect_qualifies_floor was frozen into instance_json at capture time.
    # Re-running qualify_floor_members here makes capture.py logic fixes
    # (keyword expansion, severity fallback) apply to all sessions, including
    # those captured before the fix was deployed. This is a read-and-derive
    # step: it does not mutate the DB row, only the local instance dict.
    instance = qualify_floor_members(instance, ref)

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

    # active_listings and sales_history_5yr are display-only.
    # They are sourced from property_inputs but NEVER passed into
    # compute_as_is_range(). The valuation regression uses only
    # fetched_comps, which is unchanged.
    return {
        "valuation":          val,
        "condition_summary":  summary,
        "floor":              floor_result,
        "repair_table":       enriched,
        "plans":              plans,
        "active_listings":    prop.get("fetched_active_listings") or [],
        "sales_history_5yr":  prop.get("neighborhood_sales_history") or [],
        "attom_meta":         prop.get("attom_meta") or {},
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
    prop    = session.get("property_json") or {}

    # Serve cached result only when ATTOM data is already in this session.
    # If attom_fetched is absent, skip the cache so _ensure_attom_fetched
    # can run and replace stale/fake seed data on first compute.
    attom_ready = bool(prop.get("attom_fetched"))
    if session.get("compute_result") and not refresh and attom_ready:
        return {
            "session_id":      session_id,
            "address":         session.get("address", ""),
            "cached":          True,
            "commission_rate": session.get("commission_rate", 0.06),
            "seller_inputs":   session.get("seller_inputs") or {},
            **session["compute_result"],
        }

    # Fetch real ATTOM market data on first compute; clears cached result
    # so this recompute always uses the fresh ATTOM data.
    session = _ensure_attom_fetched(session, db, session_id)

    result = _run_chain(session, ref)

    # Cache result and advance status
    db.table(TABLE).update({
        "compute_result": result,
        "status": "compute",
    }).eq("id", session_id).execute()

    return {
        "session_id":      session_id,
        "address":         session.get("address", ""),
        "cached":          False,
        "commission_rate": session.get("commission_rate", 0.06),
        "seller_inputs":   session.get("seller_inputs") or {},
        **result,
    }


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

    row = db.table(TABLE).select("*").eq("id", session_id).maybe_single().execute()
    if not row.data:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found.")

    session = row.data
    patch: dict = {"compute_result": None}   # always invalidate cache on input change

    if body.commission_rate is not None:
        patch["commission_rate"] = body.commission_rate
    if body.has_hoa is not None:
        patch["has_hoa"] = body.has_hoa
    if body.listing_month is not None:
        patch["listing_month"] = body.listing_month
    if body.seller_inputs is not None:
        existing = session.get("seller_inputs") or {}
        patch["seller_inputs"] = {**existing, **body.seller_inputs}

    db.table(TABLE).update(patch).eq("id", session_id).execute()
    return {"ok": True, "session_id": session_id}


@router.post("/{session_id}/refetch-market-data")
def refetch_market_data(session_id: str):
    """
    Clear cached ATTOM data so the next compute() call re-fetches fresh
    market data from ATTOM.  Never touches instance_json (tags/conditions).
    """
    db = get_db()

    row = db.table(TABLE).select("*").eq("id", session_id).maybe_single().execute()
    if not row.data:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found.")

    prop = row.data.get("property_json") or {}
    attom_keys = {
        "attom_fetched", "fetched_avms", "fetched_comps",
        "fetched_active_listings", "neighborhood_sales_history", "attom_meta",
    }
    cleaned_prop = {k: v for k, v in prop.items() if k not in attom_keys}

    db.table(TABLE).update({
        "property_json":  cleaned_prop,
        "compute_result": None,
    }).eq("id", session_id).execute()

    return {
        "ok":        True,
        "session_id": session_id,
        "message":   "Market data cleared. Re-run compute to fetch fresh ATTOM data.",
    }
