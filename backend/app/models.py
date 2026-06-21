"""
Pydantic schemas for the Pre-Listing Decision Tool.
These describe what flows through the API — not the reference data files themselves.
"""
from __future__ import annotations
from typing import Optional, List, Literal, Dict, Any
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Library layer (loaded from reference/components_library.csv at startup)
# ---------------------------------------------------------------------------

class LibraryComponent(BaseModel):
    component_id: str
    display_name: str
    zone: str
    typical_in_home: Literal["always", "common", "sometimes"]
    work_type_default: Literal["major", "minor", "clean"]
    repair_low: float
    repair_high: float
    replace_low: float
    replace_high: float
    repairable: bool
    creditable: bool
    recoup_pct: float
    recoup_source: str          # "CvV-anchored" or "estimate"
    safety_eligible: bool
    lender_eligible: bool
    essential_when_needed: bool
    floor_trigger: str          # "none (discretionary)" or a condition phrase
    notes: str


# ---------------------------------------------------------------------------
# Instance layer (per-session, starts BLANK, filled by capture pipeline)
# ---------------------------------------------------------------------------

class InstanceItem(BaseModel):
    component_id: str
    present: Optional[bool] = None
    condition_detected: Optional[str] = None
    severity_detected: Optional[Literal["low", "medium", "high"]] = None
    defect_qualifies_floor: Optional[bool] = None
    chosen_path: Optional[Literal["repair", "replace", "credit", "leave"]] = None
    source: Optional[Literal["photo", "questionnaire", "inspection"]] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    notes: Optional[str] = None
    # Shared-structure flag: set when two components share one physical structure
    # (e.g. DECK-01 and PRCH-01 sharing stairs). floor.py sums cost once.
    shared_structure: Optional[str] = None  # component_id of the "owner" component


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

class SessionCreate(BaseModel):
    address: str

class SessionStatus(BaseModel):
    session_id: str
    status: Literal["intake", "active", "complete"]
    property_id: str


# ---------------------------------------------------------------------------
# Capture inputs (what the capture pipeline accepts)
# ---------------------------------------------------------------------------

class PresenceAnswer(BaseModel):
    question_id: str
    component_id: str | List[str]
    answer: str                 # "yes"/"no" or option value


class ConditionAnswer(BaseModel):
    question_id: str
    component_id: str
    answer: str
    maps_to_condition: Optional[str] = None   # normalized condition string
    maps_to_severity: Optional[Literal["low", "medium", "high"]] = None


class PhotoTag(BaseModel):
    """A single vision-model tag from one uploaded photo."""
    component_id: str
    tag: str                    # e.g. "deck_present", "open_risers_visible"
    confidence: float = Field(ge=0.0, le=1.0)
    source_photo: str           # filename or upload ID


class CaptureSubmission(BaseModel):
    session_id: str
    has_inspection_report: bool = False
    photo_tags: List[PhotoTag] = []
    presence_answers: List[PresenceAnswer] = []
    condition_answers: List[ConditionAnswer] = []


# ---------------------------------------------------------------------------
# Compute outputs
# ---------------------------------------------------------------------------

class FloorItem(BaseModel):
    component_id: str
    display_name: str
    reason: str                 # plain-language: "safety hazard", "lender required", "essential"
    chosen_path: Literal["repair", "replace"]
    cost_low: float
    cost_high: float
    shared_structure: Optional[str] = None


class RepairLineItem(BaseModel):
    component_id: str
    display_name: str
    zone: str
    repair_low: float
    repair_high: float
    replace_low: float
    replace_high: float
    repairable: bool
    creditable: bool
    recoup_pct: float
    recoup_source: str
    better_value: Literal["repair", "replace", "credit", "leave"]
    in_floor: bool
    notes: str


class Plan(BaseModel):
    key: str                    # "recommended", "leaner", "do_everything"
    label: str
    tradeoff: str               # one-line why
    floor_spend_low: float
    floor_spend_high: float
    discretionary_spend_low: float
    discretionary_spend_high: float
    total_spend_low: float
    total_spend_high: float
    estimated_sale_price: float
    net_low: float
    net_high: float
    estimated_dom: int
    confidence: float
    discretionary_items: List[str]  # component_ids included


class ComputeResponse(BaseModel):
    session_id: str
    as_is_range: Dict[str, float]       # {"low": ..., "high": ..., "avm_avg": ...}
    floor: List[FloorItem]
    repair_table: List[RepairLineItem]
    plans: List[Plan]
    confidence_overall: float
    open_questions: List[str]           # what would tighten the estimate


class ReverseGoalRequest(BaseModel):
    session_id: str
    target_net: float


class ReverseGoalResponse(BaseModel):
    session_id: str
    target_net: float
    achievable: bool
    plan: Optional[Plan] = None
    dropped_items: List[str] = []       # component_ids that were excluded
    message: str


# ---------------------------------------------------------------------------
# Editable inputs (seller constraints, live knob)
# ---------------------------------------------------------------------------

class InputUpsert(BaseModel):
    key: str
    value: Any


class ChosenPathUpdate(BaseModel):
    component_id: str
    chosen_path: Literal["repair", "replace", "credit", "leave"]
