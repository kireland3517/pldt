"""
sessions.py — create and inspect sessions.

POST /session          Create a new session for a property.
GET  /session/{id}     Get session status and metadata.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from ..db import get_db, TABLE
from ..data_loader import load_property_inputs, resolve_address_to_key

router = APIRouter()


class SessionCreateRequest(BaseModel):
    address: str
    property_key: Optional[str] = None   # omit to auto-resolve from address
    listing_month: Optional[int] = None  # 1-12; defaults to current month
    commission_rate: Optional[float] = 0.06
    has_hoa: Optional[bool] = False
    seller_inputs: Optional[dict] = {}


@router.post("")
def create_session(body: SessionCreateRequest):
    """
    Create a new session. Loads property_json from the seed file.
    property_key is optional — if omitted, it is resolved from the address
    by scanning the seed directory for a matching file.
    Returns {session_id, status}.
    """
    db = get_db()

    # Resolve seed key: explicit wins, otherwise derive from address
    try:
        key = body.property_key or resolve_address_to_key(body.address)
        prop = load_property_inputs(key)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    import datetime
    month = body.listing_month or datetime.datetime.now().month

    row = {
        "address":        body.address,
        "property_key":   key,
        "status":         "intake",
        "listing_month":  month,
        "property_json":  prop,
        "seller_inputs":  body.seller_inputs or {},
        "commission_rate": body.commission_rate,
        "has_hoa":        body.has_hoa,
    }

    result = db.table(TABLE).insert(row).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create session.")

    session = result.data[0]
    return {
        "session_id": session["id"],
        "status":     session["status"],
        "address":    session["address"],
        "listing_month": session["listing_month"],
    }


@router.get("/{session_id}")
def get_session(session_id: str):
    """Return session metadata and current status.
    Includes photo_tags extracted from capture_submission so the frontend
    can resume the photo review step without re-tagging."""
    db = get_db()
    result = db.table(TABLE).select(
        "id, status, address, property_key, listing_month, "
        "commission_rate, has_hoa, seller_inputs, created_at, updated_at, "
        "capture_submission"
    ).eq("id", session_id).maybe_single().execute()

    if not result.data:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found.")

    data = dict(result.data)
    capture_sub   = data.pop("capture_submission", None) or {}
    seller_inputs = data.get("seller_inputs") or {}
    # Prefer submitted photo_tags; fall back to draft saved during photo step
    data["photo_tags"] = (
        capture_sub.get("photo_tags", [])
        or seller_inputs.get("_photo_tags_draft", [])
    )
    return data


@router.get("")
def list_sessions(limit: int = 20):
    """
    Return recent sessions ordered by most recent first.
    Includes address, created_at, status, and net proceeds from cached compute result.
    No auth required (single-tenant tool; add RLS when multi-user).
    """
    db = get_db()
    result = db.table(TABLE).select(
        "id, address, status, created_at, compute_result"
    ).order("created_at", desc=True).limit(limit).execute()

    sessions = []
    for row in (result.data or []):
        cr = row.get("compute_result") or {}
        # Pull net from recommended plan, fall back to leaner
        net = None
        plans = cr.get("plans", {})
        for level in ("recommended", "leaner", "do_everything"):
            p = plans.get(level, {})
            np = p.get("net_proceeds", {}).get("net_proceeds")
            if np is not None:
                net = np
                break

        sessions.append({
            "id":         row["id"],
            "address":    row["address"],
            "created_at": row["created_at"],
            "status":     row["status"],
            "net":        net,
            # status=="compute" means capture is done; session is openable even
            # if compute_result cache is NULL (it will recompute on open).
            "has_results": bool(cr) or row["status"] == "compute",
        })

    return {"sessions": sessions}
