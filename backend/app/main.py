"""
Pre-Listing Decision Tool -- FastAPI entry point.

BLIND RULE: reference data is loaded from reference/ and seed/ only.
validation/ is never referenced. See data_loader.py.
"""
from __future__ import annotations

import os
import traceback
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

from .data_loader import ReferenceData
from .routes import sessions, capture, compute, export, vision, pdf_gen, pdf_gen_large

load_dotenv()

app = FastAPI(
    title="Pre-Listing Decision Tool",
    version="0.3.0",
    description="Turns pre-listing dollars into expected net-proceeds changes.",
)

_allowed_origins = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "*").split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Ensure 500 responses still pass through CORSMiddleware."""
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


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


app.include_router(sessions.router,    prefix="/session",  tags=["session"])
app.include_router(capture.router,     prefix="/session",  tags=["capture"])
app.include_router(compute.router,     prefix="/session",  tags=["compute"])
app.include_router(export.router,      prefix="/session",  tags=["export"])
app.include_router(vision.router,      prefix="/session",  tags=["vision"])
app.include_router(pdf_gen.router,     prefix="/session",  tags=["pdf"])
app.include_router(pdf_gen_large.router, prefix="/session", tags=["pdf"])
