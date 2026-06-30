"""
vision.py -- per-photo AI tagging via Anthropic vision API.

POST /session/{session_id}/photo
GET  /session/{session_id}/questions

BLIND RULE: The vision model receives the photo + component library ONLY.
It never receives the property address, known condition, or answer-key data.
Do not change this without understanding the blind test implications.
"""
from __future__ import annotations

import os
import base64
import json
from fastapi import APIRouter, HTTPException, UploadFile, File, Form

from ..data_loader import ReferenceData

router = APIRouter()

_ref: ReferenceData | None = None

def _get_ref() -> ReferenceData:
    global _ref
    if _ref is None:
        _ref = ReferenceData()
    return _ref


# Zone -> priority component_ids. Full library is always shown; these get
# a "focus here first" section. Mislabeled rooms stay safe because vision
# still sees every component and can tag anything clearly visible.
ZONE_PRIORITY: dict[str, list[str]] = {
    # exterior living spaces
    "exterior_front":  ["SID-01","WIN-01","XDR-01","LAND-01","PWASH-01","GAR-01",
                        "ROOF-01","DRV-01","BELL-01","MBOX-01","XLT-01","OUT-01",
                        "ACCT-01","GUT-01","SCR-01"],
    "exterior_back":   ["SID-01","WIN-01","GUT-01","OUT-01","XLT-01","SCR-01"],
    "deck_porch":      ["DECK-01","PRCH-01","OUT-01","XLT-01","GUT-01"],
    "roof":            ["ROOF-01","GUT-01","ATTIC-01"],
    "yard_lot":        ["LAND-01","DRV-01","GUT-01","MBOX-01","BELL-01"],
    # interior rooms
    "kitchen":         ["KIT-01","FLR-01","PNT-01","ILT-01","IHW-01","IDR-01",
                        "PLMB-01","WIN-01","VENT-01"],
    "primary_bath":    ["BTHP-01","VAN-01","PLMB-01","VENT-01","FLR-01","PNT-01",
                        "IHW-01","WIN-01"],
    "secondary_bath":  ["BTHS-01","VAN-01","PLMB-01","VENT-01","FLR-01","PNT-01",
                        "IHW-01"],
    "living_room":     ["FLR-01","PNT-01","ILT-01","WIN-01","IDR-01","IHW-01"],
    "dining_room":     ["FLR-01","PNT-01","ILT-01","WIN-01","IHW-01"],
    "primary_bedroom": ["FLR-01","PNT-01","ILT-01","WIN-01","IDR-01","IHW-01"],
    "bedroom":         ["FLR-01","PNT-01","ILT-01","WIN-01"],
    # systems / structure
    "mechanical":      ["HVAC-01","WH-HTR-01","ELEC-01","PLMB-01","DUCT-01",
                        "WSHR-01","DET-01"],
    "crawlspace":      ["FND-01"],
    "garage":          ["GAR-01","ELEC-01","FLR-01","OUT-01","DET-01"],
    "attic":           ["ATTIC-01","ELEC-01","ROOF-01","DET-01"],
    "other":           [],
}

ZONE_LABELS: dict[str, str] = {
    "exterior_front":  "Exterior — Front",
    "exterior_back":   "Exterior — Back/Side",
    "deck_porch":      "Deck / Porch / Patio",
    "roof":            "Roof",
    "yard_lot":        "Yard / Lot / Driveway",
    "kitchen":         "Kitchen",
    "primary_bath":    "Primary Bathroom",
    "secondary_bath":  "Secondary Bathroom",
    "living_room":     "Living Room",
    "dining_room":     "Dining Room",
    "primary_bedroom": "Primary Bedroom",
    "bedroom":         "Bedroom",
    "mechanical":      "Mechanical / Utility Room",
    "crawlspace":      "Crawlspace / Foundation",
    "garage":          "Garage",
    "attic":           "Attic",
    "other":           "General",
}

SYSTEM_PROMPT = """You are a property inspection photo tagger for a real estate pre-listing tool.

You receive a photo of a residential property, a room label from the seller,
and a component library with two sections: priority components for this room,
and the full library.

Your task: tag components visible or strongly inferable in the photo.

RULES:
1. Use ONLY component_ids from the library. Never invent IDs.
2. The room label is a focus hint, NOT a constraint. Tag anything you can
   clearly see regardless of zone — water damage on a bathroom ceiling, exposed
   wiring in a living room, etc. are always worth flagging.
3. A mislabeled room is possible. Tag what you actually see.
4. Your assessment is a draft the seller will review. Be honest about uncertainty.
5. Confidence below 0.5 means you are guessing — use "unknown" condition.
6. condition: good | fair | poor | failed | unknown
7. severity: none | low | medium | high
8. You have no knowledge of this property's history or known condition.

Output valid JSON only, no prose, no markdown fences:
{"tags":[{"component_id":"VAN-01","present":true,"condition":"fair","severity":"low","confidence":0.70,"evidence":"Dated vanity fixtures visible, appears functional but aged"}]}"""


def _build_library_text(library: dict, priority_ids: list[str]) -> str:
    header = "component_id | display_name | zone | typical_in_home | floor_trigger"
    priority_set = set(priority_ids)

    priority_rows = [header, "--- PRIORITY FOR THIS ROOM ---"]
    other_rows    = ["--- FULL LIBRARY (tag if clearly visible) ---"]

    for cid, comp in library.items():
        row = (f"{cid} | {comp['display_name']} | {comp['zone']} | "
               f"{comp['typical_in_home']} | {comp.get('floor_trigger','')}")
        if cid in priority_set:
            priority_rows.append(row)
        else:
            other_rows.append(row)

    return "\n".join(priority_rows + other_rows)


@router.post("/{session_id}/photo")
async def tag_photo(
    session_id: str,
    file: UploadFile = File(...),
    room_zone: str = Form("other"),
):
    """
    Tag one photo. Zone is a strong prior from the seller, not a hard filter.
    Blind: model sees photo + library only, never property identity or condition.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured.")

    ref = _get_ref()
    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=422, detail="Empty file.")

    image_b64 = base64.b64encode(image_bytes).decode()
    media_type = file.content_type or "image/jpeg"
    if media_type not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
        media_type = "image/jpeg"

    priority_ids  = ZONE_PRIORITY.get(room_zone, [])
    zone_label    = ZONE_LABELS.get(room_zone, "General")
    library_text  = _build_library_text(ref.library, priority_ids)

    user_text = (
        f"Room labeled by seller: {zone_label}\n\n"
        f"Component library:\n{library_text}\n\n"
        "Tag the components visible in this photo. Output JSON only."
    )

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64",
                     "media_type": media_type, "data": image_b64}},
                    {"type": "text", "text": user_text},
                ],
            }],
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Vision API error: {e}")

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:])

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502,
            detail=f"Vision response not valid JSON: {raw[:300]} | {e}")

    valid_ids = set(ref.library.keys())
    validated, dropped = [], []
    for tag in parsed.get("tags", []):
        cid = tag.get("component_id", "")
        if cid not in valid_ids:
            dropped.append(cid)
            continue
        validated.append({
            "component_id": cid,
            "display_name": ref.library[cid].get("display_name", cid),
            "present":      bool(tag.get("present", True)),
            "condition":    tag.get("condition", "unknown"),
            "severity":     tag.get("severity", "none"),
            "confidence":   float(tag.get("confidence", 0.5)),
            "evidence":     tag.get("evidence", ""),
            "source_photo": file.filename or "upload",
        })

    return {
        "filename": file.filename,
        "room_zone": room_zone,
        "tags": validated,
        "dropped_invalid_ids": dropped,
    }


@router.get("/{session_id}/questions")
def get_questions(session_id: str):
    """Return questionnaire bank. Frontend narrows based on accumulated photo tags."""
    ref = _get_ref()
    return {
        "presence_questions":  ref.questionnaire.get("presence_questions", []),
        "condition_questions": ref.questionnaire.get("questions", []),
        "constraints_intake":  ref.questionnaire.get("constraints_intake", []),
    }
