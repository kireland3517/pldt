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
from fastapi import APIRouter, HTTPException, UploadFile, File

from ..data_loader import ReferenceData

router = APIRouter()

_ref: ReferenceData | None = None

def _get_ref() -> ReferenceData:
    global _ref
    if _ref is None:
        _ref = ReferenceData()
    return _ref


def _build_library_text(library: dict) -> str:
    lines = ["component_id | display_name | zone | typical_in_home | floor_trigger"]
    for cid, comp in library.items():
        lines.append(
            f"{cid} | {comp['display_name']} | {comp['zone']} | "
            f"{comp['typical_in_home']} | {comp.get('floor_trigger', '')}"
        )
    return "\n".join(lines)


SYSTEM_PROMPT = """You are a property inspection photo tagger for a real estate pre-listing tool.

You receive a photo of a residential property and a component library.
Your task: identify which components from the library are visible or strongly inferable,
and assess their condition.

RULES:
1. Use ONLY component_ids from the provided library table. Never invent IDs.
2. Only include components you can actually see or confidently infer.
3. If you cannot determine condition, set confidence low (below 0.5) and condition "unknown".
4. You have no knowledge of this property's history or known condition. Tag only what you see.
5. condition must be one of: good, fair, poor, failed, unknown
6. severity must be one of: none, low, medium, high

Output valid JSON only, no prose, no markdown fences:
{"tags":[{"component_id":"DECK-01","present":true,"condition":"fair","severity":"low","confidence":0.85,"evidence":"Weathered boards visible, railing appears stable"}]}"""


@router.post("/{session_id}/photo")
async def tag_photo(session_id: str, file: UploadFile = File(...)):
    """Tag one photo. Returns component tags mapped to library IDs. Blind: model sees photo + library only."""
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

    library_text = _build_library_text(ref.library)
    user_text = f"Component library:\n{library_text}\n\nTag the components visible in this photo. Output JSON only."

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
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
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
        raise HTTPException(status_code=502, detail=f"Vision response not valid JSON: {raw[:300]} | {e}")

    valid_ids = set(ref.library.keys())
    validated, dropped = [], []
    for tag in parsed.get("tags", []):
        cid = tag.get("component_id", "")
        if cid not in valid_ids:
            dropped.append(cid)
            continue
        validated.append({
            "component_id": cid,
            "present":      bool(tag.get("present", True)),
            "condition":    tag.get("condition", "unknown"),
            "severity":     tag.get("severity", "none"),
            "confidence":   float(tag.get("confidence", 0.5)),
            "evidence":     tag.get("evidence", ""),
            "source_photo": file.filename or "upload",
        })

    return {"filename": file.filename, "tags": validated, "dropped_invalid_ids": dropped}


@router.get("/{session_id}/questions")
def get_questions(session_id: str):
    """Return questionnaire bank. Frontend narrows based on accumulated photo tags."""
    ref = _get_ref()
    return {
        "presence_questions":  ref.questionnaire.get("presence_questions", []),
        "condition_questions": ref.questionnaire.get("questions", []),
        "constraints_intake":  ref.questionnaire.get("constraints_intake", []),
    }
