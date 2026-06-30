"""
export.py — export session results.

GET /session/{id}/export        JSON export of the full compute result.
                                PDF generation is a v2 feature.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from ..db import get_db, TABLE

router = APIRouter()


@router.get("/{session_id}/export")
def export_session(session_id: str):
    """
    Return the full compute result as a structured JSON payload.
    Suitable for downstream PDF rendering or report generation.
    """
    db = get_db()

    row = db.table(TABLE).select(
        "id, address, status, listing_month, commission_rate, "
        "has_hoa, seller_inputs, compute_result, created_at"
    ).eq("id", session_id).maybe_single().execute()

    if not row.data:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found.")

    session = row.data
    if not session.get("compute_result"):
        raise HTTPException(
            status_code=422,
            detail="No compute result yet. GET /compute first.",
        )

    return JSONResponse(content={
        "session_id":     session["id"],
        "address":        session["address"],
        "listing_month":  session["listing_month"],
        "commission_rate": session["commission_rate"],
        "has_hoa":        session["has_hoa"],
        "generated_at":   session["created_at"],
        "result":         session["compute_result"],
    })
