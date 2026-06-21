"""
capture.py — submit questionnaire answers and run the capture pipeline.

POST /session/{id}/capture   Accept presence + condition answers, run
                              run_capture, store instance_json, return
                              condition summary.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..db import get_db, TABLE
from ..data_loader import ReferenceData
from ..logic.capture import run_capture
from ..logic.condition import build_condition_list, condition_summary
from ..models import CaptureSubmission

router = APIRouter()

# Reference data loaded once at import time (same instance as main.py if
# imported after app startup, but safe to construct independently here).
_ref: ReferenceData | None = None

def _get_ref() -> ReferenceData:
    global _ref
    if _ref is None:
        _ref = ReferenceData()
    return _ref


@router.post("/{session_id}/capture")
def submit_capture(session_id: str, body: CaptureSubmission):
    """
    Run the capture pipeline for this session.

    Accepts a CaptureSubmission (presence answers, condition answers,
    photo tags). Stores the filled instance in DB and returns a
    condition summary plus the list of floor-flagged components.
    """
    db  = get_db()
    ref = _get_ref()

    # Verify session exists
    row = db.table(TABLE).select("id, property_json, status") \
            .eq("id", session_id).maybe_single().execute()
    if not row.data:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found.")

    # Force session_id consistency
    body.session_id = session_id

    # Run capture pipeline
    instance = run_capture(body, ref)

    # Build condition list for the summary response
    has_insp = body.has_inspection_report
    cond_list = build_condition_list(instance, ref, has_inspection=has_insp)
    summary   = condition_summary(cond_list)

    # Persist: instance_json + raw submission, advance status
    db.table(TABLE).update({
        "instance_json":      instance,
        "capture_submission": body.model_dump(),
        "status":             "capture",
        "compute_result":     None,   # invalidate any cached compute
    }).eq("id", session_id).execute()

    floor_flagged = [
        cid for cid, item in instance.items()
        if item.get("defect_qualifies_floor")
    ]

    return {
        "session_id":      session_id,
        "status":          "capture",
        "condition_summary": summary,
        "floor_flagged":   floor_flagged,
        "present_count":   len([i for i in instance.values() if i.get("present") is True]),
    }
