"""
Data loader for the Pre-Listing Decision Tool.

BLIND RULE — enforced here:
  Loads ONLY from reference/ and seed/.
  NEVER loads from validation/.
  The running tool must be genuinely blind to any specific property's condition.
  Condition enters only through the capture pipeline (photos + questionnaire).

Path layout (relative to project root = PLDT/):
  reference/   components_library.csv, instance_schema.csv, *.json
  seed/        property_inputs_*.json
  validation/  QUARANTINED — not referenced here at all
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, List, Optional

# Project root: two levels up from backend/app/data_loader.py
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
REFERENCE_DIR = PROJECT_ROOT / "reference"
SEED_DIR      = PROJECT_ROOT / "seed"
# VALIDATION_DIR is intentionally absent. Do not add it.


# ---------------------------------------------------------------------------
# Library loader
# ---------------------------------------------------------------------------

def load_library() -> Dict[str, dict]:
    """
    Load components_library.csv into a dict keyed by component_id.
    This is the universal common-house catalog — no house-specific facts.
    """
    path = REFERENCE_DIR / "components_library.csv"
    library: Dict[str, dict] = {}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cid = row["component_id"].strip()
            # Normalize booleans
            for col in ("repairable", "creditable",
                        "safety_eligible", "lender_eligible", "essential_when_needed"):
                row[col] = row[col].strip().lower() == "true"
            # Normalize numerics
            for col in ("repair_low", "repair_high",
                        "replace_low", "replace_high", "recoup_pct"):
                row[col] = float(row[col])
            library[cid] = dict(row)
    return library


# ---------------------------------------------------------------------------
# Instance schema
# ---------------------------------------------------------------------------

def load_instance_schema_columns() -> List[str]:
    """Return the column names of the blank instance schema (headers only)."""
    path = REFERENCE_DIR / "instance_schema.csv"
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        return next(reader)


def blank_instance(library: Dict[str, dict]) -> Dict[str, dict]:
    """
    Create a blank per-property instance: one entry per library component,
    all fields None.  The capture pipeline fills this; nothing else may.
    """
    return {
        cid: {
            "component_id": cid,
            "present": None,
            "condition_detected": None,
            "severity_detected": None,
            "defect_qualifies_floor": None,
            "chosen_path": None,
            "source": None,
            "confidence": None,
            "notes": None,
            "shared_structure": None,   # set when two components share one structure
            "recent_replacement": None,   # True if seller confirms replacement within ~5 years
        }
        for cid in library
    }


# ---------------------------------------------------------------------------
# Reference JSON files
# ---------------------------------------------------------------------------

def load_sc_closing_constants() -> dict:
    path = REFERENCE_DIR / "sc_closing_constants.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_dom_seasonality() -> dict:
    path = REFERENCE_DIR / "dom_seasonality.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_questionnaire_bank() -> dict:
    path = REFERENCE_DIR / "questionnaire_bank.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Seed loader (front-door property inputs only)
# ---------------------------------------------------------------------------

def load_property_inputs(address_key: str) -> dict:
    """
    Load front-door inputs for a property: address, public county facts,
    fetched AVMs/comps, and seller constraints.

    NOT condition. NOT as-is range. NOT chosen paths.
    Those are produced by the capture and compute pipelines.

    address_key examples: "130_kingfisher"
    """
    filename = f"property_inputs_{address_key}.json"
    path = SEED_DIR / filename
    if not path.exists():
        raise FileNotFoundError(
            f"No seed file for '{address_key}' at {path}. "
            "Create one or check the address key."
        )
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    # Sanity check: seed file must not contain pre-computed condition
    for forbidden in ("condition", "flagged_components", "as_is_range", "chosen_paths"):
        if forbidden in data:
            raise ValueError(
                f"Seed file '{filename}' contains '{forbidden}'. "
                "Condition and computed values must not be pre-seeded. "
                "Move them to validation/answer_key_*.json."
            )
    return data


# ---------------------------------------------------------------------------
# Assembled reference bundle (loaded once at startup)
# ---------------------------------------------------------------------------

class ReferenceData:
    """
    Loaded once at startup.  Holds all general reference data.
    Never holds property-specific condition or computed results.
    """

    def __init__(self) -> None:
        self.library: Dict[str, dict] = load_library()
        self.instance_schema_columns: List[str] = load_instance_schema_columns()
        self.sc_closing: dict = load_sc_closing_constants()
        self.dom: dict = load_dom_seasonality()
        self.questionnaire: dict = load_questionnaire_bank()

        # Build lookup structures used by logic modules
        self._floor_eligible: Dict[str, dict] = {
            cid: comp
            for cid, comp in self.library.items()
            if comp["safety_eligible"] or comp["lender_eligible"] or comp["essential_when_needed"]
        }
        self._presence_questions: List[dict] = self.questionnaire.get("presence_questions", [])
        self._condition_questions: List[dict] = self.questionnaire.get("questions", [])
        self._constraints_questions: List[dict] = self.questionnaire.get("constraints_intake", [])

    def new_instance(self) -> Dict[str, dict]:
        """Return a fresh blank instance for a new session. Always starts empty."""
        return blank_instance(self.library)

    def is_floor_eligible(self, component_id: str) -> bool:
        return component_id in self._floor_eligible

    def get_floor_trigger(self, component_id: str) -> Optional[str]:
        comp = self.library.get(component_id)
        if not comp:
            return None
        trigger = comp.get("floor_trigger", "")
        if trigger.startswith("none"):
            return None
        return trigger

    def component(self, component_id: str) -> Optional[dict]:
        return self.library.get(component_id)

    @property
    def presence_questions(self) -> List[dict]:
        return self._presence_questions

    @property
    def condition_questions(self) -> List[dict]:
        return self._condition_questions

    @property
    def constraints_questions(self) -> List[dict]:
        return self._constraints_questions
