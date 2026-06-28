"""
attom.py — ATTOM API integration for real market data.

Fetches:
  - AVM estimate        /propertyapi/v1.0.0/avm/detail
  - Nearby sold props   /propertyapi/v1.0.0/sale/snapshot
      fetched_comps:              sales in last 12 months, comparable size
      neighborhood_sales_history: sales in last 5 years

Active listings:
  ATTOM is a public-records provider — no MLS data.
  fetched_active_listings is populated only from manually-verified seed files.
  For any address without a seed file it is always an empty list.

API key read from ATTOM_API_KEY env var.  Never hardcoded or committed.
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

BASE     = "https://api.gateway.attomdata.com"
MIN_COMP_COUNT = 3            # minimum comps; widen radius before aging comps
RADII    = [1.0, 2.0, 3.0, 5.0]        # step through these until MIN_COMP_COUNT is met
CONF_RADIUS = 2.0                        # comps beyond this mile get flagged lower-confidence


def _get(path: str, params: str = "") -> dict:
    key = os.environ.get("ATTOM_API_KEY", "")
    if not key:
        raise RuntimeError("ATTOM_API_KEY not configured")
    url = f"{BASE}{path}{'?' + params if params else ''}"
    req = urllib.request.Request(
        url, headers={"apikey": key, "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def parse_address(one_line: str) -> tuple[str, str, str, str]:
    parts    = [p.strip() for p in one_line.split(",")]
    street   = parts[0] if len(parts) > 0 else ""
    city     = parts[1] if len(parts) > 1 else ""
    sc_zip   = parts[2].split() if len(parts) > 2 else []
    state    = sc_zip[0] if sc_zip else ""
    zip_code = sc_zip[1] if len(sc_zip) > 1 else ""
    return street, city, state, zip_code


def _ym(date_str: str) -> str:
    return date_str[:7] if date_str else ""


def _in_size_band(sqft: float, subject_sqft: float, tolerance: float) -> bool:
    if subject_sqft <= 0:
        return True
    lo = subject_sqft * (1 - tolerance)
    hi = subject_sqft * (1 + tolerance)
    return lo <= sqft <= hi


def _normalize_addr(addr: str) -> str:
    return re.sub(r"[^A-Z0-9 ]", "", addr.upper()).strip()


def _extract_snapshot_entry(p: dict) -> dict | None:
    """
    Field map (case-sensitive, from raw ATTOM JSON):
      price        -> sale.amount.saleamt
      sale date    -> sale.saleTransDate
      sqft         -> building.size.universalsize
      address      -> address.oneLine
      zip          -> address.postal1
      beds         -> building.rooms.beds
      baths        -> building.rooms.bathstotal
      year_built   -> summary.yearbuilt
      prop type    -> summary.proptype
      distance_mi  -> location.distance

    is_newer_build: explicit boolean, True when year_built > 2010.
    note:           display text only; NOT a weight trigger in valuation.py.
    """
    sale      = p.get("sale", {})
    sale_amt  = float((sale.get("amount") or {}).get("saleamt") or 0)
    sale_date = sale.get("saleTransDate") or ""
    if not sale_date or sale_amt < 50_000:
        return None

    bldg = p.get("building", {})
    size = bldg.get("size", {})
    sqft = float(size.get("universalsize") or 0)
    if sqft <= 0:
        return None

    rooms      = bldg.get("rooms", {})
    beds       = int(rooms.get("beds") or 0)
    baths      = float(rooms.get("bathstotal") or 0)
    addr_block = p.get("address", {})
    addr       = addr_block.get("oneLine", "")
    zip_code   = addr_block.get("postal1", "") or ""
    yr         = p.get("summary", {}).get("yearbuilt")
    ppsf       = round(sale_amt / sqft)
    dist       = float((p.get("location") or {}).get("distance") or 0)

    is_newer   = bool(yr and int(yr) > 2010)

    entry: dict = {
        "address":        addr,
        "zip":            zip_code,
        "beds":           beds,
        "baths":          baths,
        "sqft":           int(sqft),
        "year_built":     yr,
        "sold":           _ym(sale_date),
        "price":          int(sale_amt),
        "ppsf":           ppsf,
        "distance_mi":    dist,
        "is_newer_build": is_newer,
        "_sale_date_iso": sale_date,   # internal only; stripped by _clean
    }
    if is_newer:
        entry["note"] = "newer build"
    return entry


def _fetch_snapshot_pages(
    params_base: str,
    radius: float,
    start_date: str,
    end_date: str,
) -> list[dict]:
    rows: list[dict] = []
    for page in range(1, 31):
        params = (
            f"{params_base}"
            f"&radius={radius}"
            f"&startsalesearchdate={start_date}"
            f"&endsalesearchdate={end_date}"
            f"&pagesize=50"
            f"&page={page}"
        )
        try:
            resp  = _get("/propertyapi/v1.0.0/sale/snapshot", params)
            batch = resp.get("property", [])
            if not batch:
                break
            rows.extend(batch)
        except Exception:
            break
    return rows


def _load_manual_listings(street: str, city: str, state: str) -> tuple[list[dict], str]:
    """
    Load manually-verified active/pending listings for a known subject address.
    Returns ([], "") for non-matching addresses or any file error.
    """
    subject_norm    = _normalize_addr(f"{street} {city} {state}")
    kingfisher_norm = _normalize_addr("130 Kingfisher Dr Simpsonville SC")
    if subject_norm != kingfisher_norm:
        return [], ""

    seed_file = _SEED_DIR / "manual_active_listings_kingfisher.json"
    try:
        data = json.loads(seed_file.read_text(encoding="utf-8"))
    except Exception:
        return [], ""

    basis = data.get("basis", "")
    valid = [
        row for row in data.get("listings", [])
        if row.get("source") == "manual" and row.get("verified_on")
    ]
    return valid, basis


def fetch_attom_data(
    street: str,
    city: str,
    state: str,
    zip_code: str,
    subject_sqft: float = 0,
    subject_beds: int = 0,
) -> dict:
    """
    Returns dict with keys:
      fetched_avms, fetched_comps, neighborhood_sales_history,
      fetched_active_listings, attom_meta

    Comp and history filters applied (in order):
      1. SFR only
      2. Same postal code as subject (zip_code) — keeps comps in-submarket
      3. Beds within 1 of subject_beds (skipped if subject_beds == 0)
      4. Size band: ±40% for comps, ±60% for history
    """
    addr1  = street
    addr2  = f"{city}, {state} {zip_code}"
    p_base = (
        f"address1={urllib.parse.quote(addr1)}"
        f"&address2={urllib.parse.quote(addr2)}"
    )

    result: dict = {
        "fetched_avms":               {},
        "fetched_comps":              [],
        "neighborhood_sales_history": [],
        "fetched_active_listings":    [],
        "attom_meta":                 {},
    }

    # ── AVM ──────────────────────────────────────────────────────────────
    subject_attom_id  = None
    subject_addr_norm = _normalize_addr(f"{street} {city} {state} {zip_code}")
    avm_as_of         = ""
    try:
        avm_resp = _get("/propertyapi/v1.0.0/avm/detail", p_base)
        props    = avm_resp.get("property", [])
        if props:
            p0               = props[0]
            subject_attom_id = p0.get("identifier", {}).get("attomId")
            avm_block        = p0.get("avm", {})
            amt              = avm_block.get("amount", {})
            avm_as_of        = avm_block.get("eventDate", "")
            if amt.get("value"):
                result["fetched_avms"]["attom"] = int(amt["value"])
    except Exception:
        pass

    # ── Date windows ──────────────────────────────────────────────────────
    today      = date.today().isoformat()
    start_12mo = (date.today() - timedelta(days=365)).isoformat()
    start_5yr  = (date.today() - timedelta(days=1825)).isoformat()

    # Fetch up to 100 closest SFR properties within 2.0 miles (our max radius).
    # Properties are sorted by distance, so pages 1-10 give the closest 100.
    nearby: list[dict] = []
    for page in range(1, 16):
        try:
            resp  = _get(
                "/propertyapi/v1.0.0/property/basicprofile",
                f"{p_base}&radius=5.0&page={page}&pageSize=10",
            )
            batch = resp.get("property", [])
            if not batch:
                break
            nearby.extend(batch)
        except Exception:
            break

    # Build candidate list from all nearby properties
    candidates: list[dict] = []
    for p in nearby:
        if p.get("identifier", {}).get("attomId") == subject_attom_id:
            continue
        if p.get("summary", {}).get("propType") != "SFR":
            continue

        entry = _extract_entry(p)
        if entry:
            candidates.append(entry)

    # ── Step radius for comps (12-month window, comparable size) ─────────
    used_radius  = RADII[-1]   # default to widest
    final_comps: list[dict] = []

    for radius in RADII:
        rows = _fetch_snapshot_pages(p_base, radius, start_12mo, today)

        candidates: list[dict] = []
        for p in rows:
            # Skip subject property itself
            if subject_attom_id and p.get("identifier", {}).get("attomId") == subject_attom_id:
                continue
            addr_norm = _normalize_addr(p.get("address", {}).get("oneLine", ""))
            if addr_norm and addr_norm == subject_addr_norm:
                continue
            # SFR only
            if p.get("summary", {}).get("proptype") != "SFR":
                continue
            # Same zip — keeps comps in the same submarket
            if p.get("address", {}).get("postal1") != zip_code:
                continue
            entry = _extract_snapshot_entry(p)
            if entry is None:
                continue
            if not _in_size_band(entry["sqft"], subject_sqft, 0.40):
                continue
            # Beds filter: within 1 of subject
            if subject_beds > 0 and entry["beds"] > 0:
                if abs(entry["beds"] - subject_beds) > 1:
                    continue
            candidates.append(entry)

        last_candidates = candidates
        if len(candidates) >= MIN_COMP_COUNT:
            used_radius = radius
            final_comps = candidates
            break

    if not final_comps:
        used_radius = RADII[-1]
        final_comps = last_candidates

    # Flag comps beyond CONF_RADIUS as lower-confidence
    for e in final_comps:
        if e["_distance_mi"] > CONF_RADIUS:
            e["note"] = ((e.get("note") or "") + "; extended radius").lstrip("; ")

    # ── Neighborhood history (5-year, looser size band, full 1.0 mi) ─────
    comp_addresses = {e["address"] for e in final_comps}
    history: list[dict] = [
        e for e in candidates
        if e["_sale_date_iso"] >= cutoff_5yr
        and _in_size_band(e["sqft"], subject_sqft, 0.60)
        and e["address"] not in comp_addresses
    ]

    # ── 5-year history (same-zip filter applied) ──────────────────────
    hist_rows     = _fetch_snapshot_pages(p_base, used_radius, start_5yr, today)
    comp_addr_set = {_normalize_addr(e["address"]) for e in final_comps}

    history: list[dict] = []
    for p in hist_rows:
        if subject_attom_id and p.get("identifier", {}).get("attomId") == subject_attom_id:
            continue
        addr_norm = _normalize_addr(p.get("address", {}).get("oneLine", ""))
        if addr_norm and addr_norm == subject_addr_norm:
            continue
        if p.get("summary", {}).get("proptype") != "SFR":
            continue
        # Same zip filter on history too
        if p.get("address", {}).get("postal1") != zip_code:
            continue
        entry = _extract_snapshot_entry(p)
        if entry and _in_size_band(entry["sqft"], subject_sqft, 0.60):
            if addr_norm not in comp_addr_set:
                history.append(entry)

    # ── Manual active listings ────────────────────────────────────────────
    manual_listings, listings_basis = _load_manual_listings(street, city, state)

    # ── Sort, clean, cap, assemble ────────────────────────────────────────
    def _clean(e: dict) -> dict:
        return {k: v for k, v in e.items() if not k.startswith("_")}

    final_comps.sort(key=lambda x: x["sold"], reverse=True)
    history.sort(key=lambda x: x["sold"], reverse=True)

    result["fetched_comps"]              = [_clean(e) for e in final_comps[:10]]
    result["neighborhood_sales_history"] = [_clean(e) for e in history[:20]]
    result["fetched_active_listings"]    = manual_listings

    attom_meta: dict = {
        "comp_radius_miles": used_radius,
        "comp_count":        len(result["fetched_comps"]),
        "avm_as_of":         avm_as_of,
    }
    if listings_basis:
        attom_meta["active_listings_basis"] = listings_basis
    result["attom_meta"] = attom_meta

    return result
