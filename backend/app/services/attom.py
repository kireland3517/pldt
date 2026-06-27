"""
attom.py — ATTOM API integration for real market data.

Fetches:
  - AVM estimate        /propertyapi/v1.0.0/avm/detail
  - Nearby sold props   /propertyapi/v1.0.0/sale/snapshot
      fetched_comps:              sales in last 12 months, comparable size
      neighborhood_sales_history: sales in last 5 years

Comp radius strategy:
  Step through RADII narrowest-first. At each radius, fetch all pages with the
  12-month date window passed server-side (startsalesearchdate / endsalesearchdate).
  Stop at the first radius that yields MIN_COMP_COUNT comparable sales.
  Never widen the time window past 12 months.

Size filter:
  Comps: ±40% of subject sqft. History: ±60% (looser — context only, not valuation).

ATTOM is a public-records provider.  It does NOT supply active MLS listings.
fetched_active_listings is always returned as an empty list.

API key read from ATTOM_API_KEY env var.  Never hardcoded or committed.
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from datetime import date, timedelta

BASE           = "https://api.gateway.attomdata.com"
MIN_COMP_COUNT = 3
RADII          = [1.0, 2.0, 3.0, 5.0]
CONF_RADIUS    = 2.0


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
    """
    Parse "130 Kingfisher Dr, Simpsonville, SC 29680"
    -> (street, city, state, zip_code)
    """
    parts    = [p.strip() for p in one_line.split(",")]
    street   = parts[0] if len(parts) > 0 else ""
    city     = parts[1] if len(parts) > 1 else ""
    sc_zip   = parts[2].split() if len(parts) > 2 else []
    state    = sc_zip[0] if sc_zip else ""
    zip_code = sc_zip[1] if len(sc_zip) > 1 else ""
    return street, city, state, zip_code


def _ym(date_str: str) -> str:
    """'2024-09-13' -> '2024-09'"""
    return date_str[:7] if date_str else ""


def _in_size_band(sqft: float, subject_sqft: float, tolerance: float) -> bool:
    """True if sqft is within ±tolerance fraction of subject_sqft."""
    if subject_sqft <= 0:
        return True
    lo = subject_sqft * (1 - tolerance)
    hi = subject_sqft * (1 + tolerance)
    return lo <= sqft <= hi


def _normalize_addr(addr: str) -> str:
    """Uppercase, strip punctuation — for fallback self-exclusion comparison."""
    return re.sub(r"[^A-Z0-9 ]", "", addr.upper()).strip()


def _extract_snapshot_entry(p: dict) -> dict | None:
    """
    Extract a normalized comp/history entry from a sale/snapshot property dict.

    Field map (case-sensitive, from raw ATTOM JSON):
      price      -> sale.amount.saleamt
      sale date  -> sale.saleTransDate
      sqft       -> building.size.universalsize
      address    -> address.oneLine
      beds       -> building.rooms.beds
      baths      -> building.rooms.bathstotal
      year built -> summary.yearbuilt
      prop type  -> summary.proptype
      distance   -> location.distance
      attomId    -> identifier.attomId
    """
    sale     = p.get("sale", {})
    sale_amt = float((sale.get("amount") or {}).get("saleamt") or 0)
    sale_date = sale.get("saleTransDate") or ""

    if not sale_date or sale_amt < 50_000:
        return None

    bldg = p.get("building", {})
    size = bldg.get("size", {})
    sqft = float(size.get("universalsize") or 0)
    if sqft <= 0:
        return None

    rooms = bldg.get("rooms", {})
    beds  = int(rooms.get("beds") or 0)
    baths = float(rooms.get("bathstotal") or 0)
    addr  = p.get("address", {}).get("oneLine", "")
    yr    = p.get("summary", {}).get("yearbuilt")
    ppsf  = round(sale_amt / sqft)
    dist  = float((p.get("location") or {}).get("distance") or 0)

    entry: dict = {
        "address":        addr,
        "beds":           beds,
        "baths":          baths,
        "sqft":           int(sqft),
        "built":          yr,
        "sold":           _ym(sale_date),
        "price":          int(sale_amt),
        "ppsf":           ppsf,
        "_sale_date_iso": sale_date,
        "_distance_mi":   dist,
    }
    if yr and int(yr) > 2010:
        entry["note"] = "newer build"

    return entry


def _fetch_snapshot_pages(
    params_base: str,
    radius: float,
    start_date: str,
    end_date: str,
) -> list[dict]:
    """Paginate sale/snapshot at a given radius and date window."""
    rows: list[dict] = []
    for page in range(1, 31):   # max 30 pages × 50 = 1 500 rows
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


def fetch_attom_data(
    street: str,
    city: str,
    state: str,
    zip_code: str,
    subject_sqft: float = 0,
) -> dict:
    """
    Returns dict with keys matching property_inputs schema:

      fetched_avms:               {"attom": <int>}
      fetched_comps:              list[comp_dict]   (12-month, comparable size)
      neighborhood_sales_history: list[hist_dict]   (5-year window)
      fetched_active_listings:    []                (always empty — no MLS data)
      attom_meta:                 {comp_radius_miles, comp_count, avm_as_of}

    comp_dict keys: address, beds, baths, sqft, built, sold (YYYY-MM),
                    price, ppsf, note (optional)
    hist_dict keys: address, sold (YYYY-MM), price, sqft, ppsf, beds, baths
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

    # ── AVM (still on avm/detail — basicprofile field shape; unaffected) ──
    subject_attom_id   = None
    subject_addr_norm  = _normalize_addr(f"{street} {city} {state} {zip_code}")
    avm_as_of          = ""
    try:
        avm_resp         = _get("/propertyapi/v1.0.0/avm/detail", p_base)
        props            = avm_resp.get("property", [])
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

    # ── Comp fetch: narrow-to-wide radius, date window server-side ────────
    used_radius            = RADII[-1]
    final_comps: list[dict] = []
    last_candidates: list[dict] = []

    for radius in RADII:
        rows = _fetch_snapshot_pages(p_base, radius, start_12mo, today)

        candidates: list[dict] = []
        for p in rows:
            # Self-exclude: attomId first, fallback to normalized address
            if subject_attom_id and p.get("identifier", {}).get("attomId") == subject_attom_id:
                continue
            addr_norm = _normalize_addr(p.get("address", {}).get("oneLine", ""))
            if addr_norm and addr_norm == subject_addr_norm:
                continue
            # SFR only
            if p.get("summary", {}).get("proptype") != "SFR":
                continue

            entry = _extract_snapshot_entry(p)
            if entry and _in_size_band(entry["sqft"], subject_sqft, 0.40):
                candidates.append(entry)

        last_candidates = candidates
        if len(candidates) >= MIN_COMP_COUNT:
            used_radius = radius
            final_comps = candidates
            break

    # Fallback: use whatever the widest radius returned
    if not final_comps:
        used_radius = RADII[-1]
        final_comps = last_candidates

    # Flag comps beyond CONF_RADIUS as lower-confidence
    for e in final_comps:
        if e["_distance_mi"] > CONF_RADIUS:
            e["note"] = ((e.get("note") or "") + "; extended radius").lstrip("; ")

    # ── 5-year history: separate call at used_radius ──────────────────────
    hist_rows      = _fetch_snapshot_pages(p_base, used_radius, start_5yr, today)
    comp_addr_set  = {_normalize_addr(e["address"]) for e in final_comps}

    history: list[dict] = []
    for p in hist_rows:
        if subject_attom_id and p.get("identifier", {}).g