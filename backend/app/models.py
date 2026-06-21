"""
Pydantic schemas for the Pre-Listing Decision Tool.
"""
from __future__ import annotations
from typing import Optional, List, Literal, Dict, Any
from pydantic import BaseModel, Field


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
    recoup_source: str
    safety_eligible: bool
    lender_eligible: bool
    essential_when_needed: bool
    floor_trigger: str
    notes: str


class InstanceItem(BaseModel):
    component_id: str
    present: Optional[bool] = None
    condition_detected: Optional[str] = None
    severity_detected: Optional[Literal["low", "medium", "high"]] = None
    defect_qualifies_floor: Optional[bool] = None
    chosen_path: Optional[Literal["repair", "replace", "credit", "leave"]] = None
    source: Optional[Literal["photo", "questionnaire", "inspection", "seller_confirmed"]] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    notes: Optional[str] = None
    shared_structure: Optional[str] = None
    recent_replacement: Optional[bool] = None


class SessionCreate(BaseModel):
    address: str

class SessionStatus(BaseModel):
    session_id: str
    status: Literal["intake", "active", "complete"]
    property_id: str


class PresenceAnswer(BaseModel):
    question_id: str
    component_id: str | List[str]
    answer: str


class ConditionAnswer(BaseModel):
    question_id: str
    component_id: str
    answer: str
    maps_to_condition: Optional[str] = None
    maps_to_severity: Optional[Literal["low", "medium", "high"]] = None


class PhotoTag(BaseModel):
    component_id: str
    tag: str
    confidence: float = Field(ge=0.0, le=1.0)
    source_photo: str


class SellerConfirmedTag(BaseModel):
    """
    A seller correction to a vision-tagged component.

    Pass 3 in run_capture: overwrites ONLY the fields explicitly set here.
    None means "seller did not touch this field — leave whatever vision/
    questionnaire set." An empty SellerConfirmedTag only sets source and
    confidence; it does not blank out correctly-populated fields.

    Confidence is always set to 1.0 for seller-confirmed fields.
    """
    component_id: str
    present:    Optional[bool] = None   # None = not edited by seller
    condition:  Optional[str] = None    # None = not edited
    severity:   Optional[str] = None    # None = not edited
    seller_note: Optional[str] = None   # appended to notes, never replaces


class CaptureSubmission(BaseModel):
    session_id: str
    has_inspection_report: bool = False
    photo_tags: List[PhotoTag] = []
    presence_answers: List[PresenceAnswer] = []
    condition_answers: List[ConditionAnswer] = []
    seller_confirmed_tags: List[SellerConfirmedTag] = []   # Pass 3 — always wins


class FloorItem(BaseModel):
    component_id: str
    display_name: str
    reason: str
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
    key: str
    label: str
    tradeoff: str
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
    discretionary_items: List[str]


class ComputeResponse(BaseModel):
    session_id: str
    as_is_range: Dict[str, float]
    floor: List[FloorItem]
    repair_table: List[RepairLineItem]
    plans: List[Plan]
    confidence_overall: float
    open_questions: List[str]


class ReverseGoalRequest(BaseModel):
    session_id: str
    target_net: float


class ReverseGoalResponse(BaseModel):
    session_id: str
    target_net: float
    achievable: bool
    plan: Optional[Plan] = None
    dropped_items: List[str] = []
    message: str


class InputUpsert(BaseModel):
    key: str
    value: Any


class ChosenPathUpdate(BaseModel):
    component_id: str
    chosen_path: Literal["repair", "replace", "credit", "leave"]
