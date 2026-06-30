"""
db.py — Supabase client singleton for the Pre-Listing Decision Tool.

Loaded once at startup via FastAPI lifespan or direct import.
All DB access goes through get_db(); never import create_client elsewhere.

Security note (v1): RLS is disabled; this is a single-tenant admin tool.
Add RLS policies + auth before exposing to end users.
"""
from __future__ import annotations

import os
from functools import lru_cache

from supabase import create_client, Client


@lru_cache(maxsize=1)
def get_db() -> Client:
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_KEY", "")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_KEY must be set in environment."
        )
    return create_client(url, key)
