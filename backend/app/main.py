"""
Pre-Listing Decision Tool — FastAPI entry point.

BLIND RULE: reference data is loaded from reference/ and seed/ only.
validation/ is never referenced. See data_loader.py.
"""

from __future__ import annotations

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from .data_loader import ReferenceData

load_dotenv()

app = FastAPI(
    title="Pre-Listing Decision Tool",
    version="0.1.0",
    description="Turns pre-listing dollars into expected net-proceeds changes.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load reference data once at startup. Never loads validation/.
ref = ReferenceData()


@app.get("/health")
def health():
    return {
        "status": "ok",
        "library_components": len(ref.library),
        "floor_eligible_components": len(
            [c for c in ref.library.values()
             if c["safety_eligible"] or c["lender_eligible"] or c["essential_when_needed"]]
        ),
    }


# ---------------------------------------------------------------------------
# Routes are registered here as modules are built.
# ---------------------------------------------------------------------------

# TODO Step 4: from .routes import sessions, capture, compute, export
# app.include_router(sessions.router, prefix="/session", tags=["session"])
# app.include_router(capture.router, prefix="/session", tags=["capture"])
# app.include_router(compute.router, prefix="/session", tags=["compute"])
# app.include_router(export.router, prefix="/session", tags=["export"])
