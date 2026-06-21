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
    """Return session metadata and current status."""
    db = get_db()
    result = db.table(TABLE).select(
        "id, status, address, property_key, listing_month, "
        "commission_rate, has_hoa, seller_inputs, created_at, updated_at"
    ).eq("id", session_id).maybe_single().execute()

    if not result.data:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found.")

    return result.data
