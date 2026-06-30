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
import time
from pathlib import Path

BASE           = "https://api.gateway.attomdata.com"
MIN_COMP_COUNT = 5
RADII          = [1.0, 1.5, 2.0]
CONF_RADIUS    = 1.0   # comps beyond this get "extended radius" note

_SEED_DIR = Path(__file__).resolve().parent.parent.parent / "seed"


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
    p0: dict          = {}   # safe default; overwritten if AVM succeeds
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

    # Extract ATTOM rooftop coords (primary for listings center)
    attom_lat: float | None = None
    attom_lon: float | None = None
    try:
        loc       = p0.get("location", {})
        attom_lat = float(loc.get("latitude")  or 0) or None
        attom_lon = float(loc.get("longitude") or 0) or None
    except Exception:
        pass

    # RentCast AVM — second estimate; avm_avg in valuation.py averages all fetched_avms
    rc_data = fetch_rentcast_avm(street, city, state, zip_code)
    if rc_data.get("rc_avm"):
        result["fetched_avms"]["rentcast"] = rc_data["rc_avm"]

    # Coordinate precedence: ATTOM rooftop primary, RentCast AVM response as fallback
    subject_lat = attom_lat or rc_data.get("rc_lat")
    subject_lon = attom_lon or rc_data.get("rc_lon")

    # RentCast active/pending listings (pending tagged; excluded from active count by callers)
    if subject_lat and subject_lon:
        rc_listings, rc_basis = fetch_rentcast_listings(subject_lat, subject_lon, zip_code)
    else:
        rc_listings, rc_basis = [], ""

    # ── Date windows ──────────────────────────────────────────────────────
    today      = date.today().isoformat()
    start_12mo = (date.today() - timedelta(days=365)).isoformat()

    # ── Comp fetch: narrow-to-wide radius, same-zip filter ─────────────
    used_radius              = RADII[-1]
    final_comps: list[dict]  = []
    last_candidates: list[dict] = []

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

    # Flag comps beyond CONF_RADIUS — display only, not a weight trigger
    for e in final_comps:
        if e["distance_mi"] > CONF_RADIUS:
            existing = e.get("note", "")
            e["note"] = (existing + "; extended radius").lstrip("; ") if existing else "extended radius"

    # ── July seasonal history ────────────────────────────────────────────
    july_rows = _fetch_july_history(p_base, zip_code)

    # Enrich each row with RentCast list price; sequential with 0.3s throttle
    for row in july_rows:
        if row.get("list_price_status") not in ("not_fetched", "fetch_failed"):
            continue
        try:
            lp, lp_status, listed_date, dom = fetch_rentcast_list_price(row["address"])
            row["list_price"]        = lp
            row["listed_date"]       = listed_date
            row["dom"]               = dom
            row["list_price_status"] = lp_status
        except Exception:
            row["list_price_status"] = "fetch_failed"
        time.sleep(0.3)

    # ── Active listings: RentCast live feed preferred; manual seed as fallback ──
    if rc_listings:
        final_listings = rc_listings
        listings_basis = rc_basis
    else:
        final_listings, listings_basis = _load_manual_listings(street, city, state)

    # ── Sort, clean, cap, assemble ────────────────────────────────────────
    def _clean(e: dict) -> dict:
        return {k: v for k, v in e.items() if not k.startswith("_")}

    final_comps.sort(key=lambda x: x["sold"], reverse=True)

    result["fetched_comps"]              = [_clean(e) for e in final_comps[:10]]
    result["neighborhood_sales_history"] = july_rows
    result["fetched_active_listings"]    = final_listings

    attom_meta: dict = {
        "comp_radius_miles": used_radius,
        "comp_count":        len(result["fetched_comps"]),
        "avm_as_of":         avm_as_of,
        "history_basis": (
            f"Homes sold in July (closing date) within 1 mile, "
            f"zip {zip_code}, 2022-2025. "
            "List price from RentCast listings where available."
        ),
    }
    if listings_basis:
        attom_meta["active_listings_basis"] = listings_basis
    result["attom_meta"] = attom_meta

    return result

# ── RentCast integration ──────────────────────────────────────────────────────


def _rentcast_get(path: str, params: str = "") -> dict:
    key = os.environ.get("RENTCAST_API_KEY", "")
    if not key:
        raise RuntimeError("RENTCAST_API_KEY not configured")
    url = f"https://api.rentcast.io{path}{'?' + params if params else ''}"
    req = urllib.request.Request(
        url, headers={"X-Api-Key": key, "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def fetch_rentcast_avm(street: str, city: str, state: str, zip_code: str) -> dict:
    """
    Fetch RentCast AVM estimate.
    Returns {"rc_avm": int, "rc_lat": float, "rc_lon": float} or {} on failure/no key.
    Never logs or re-raises the API key.
    """
    if not os.environ.get("RENTCAST_API_KEY"):
        return {}
    try:
        address = urllib.parse.quote(f"{street}, {city}, {state} {zip_code}")
        resp  = _rentcast_get("/v1/avm/value", f"address={address}")
        price = resp.get("price")
        if not price:
            return {}
        out: dict = {"rc_avm": int(price)}
        if resp.get("latitude"):
            out["rc_lat"] = float(resp["latitude"])
        if resp.get("longitude"):
            out["rc_lon"] = float(resp["longitude"])
        return out
    except Exception:
        return {}


def fetch_rentcast_listings(
    lat: float, lon: float, zip_code: str, radius_mi: float = 1.0
) -> tuple[list[dict], str]:
    """
    Fetch active/pending sale listings from RentCast near (lat, lon).
    Filters: zipCode == zip_code, propertyType in {Single Family, Townhouse},
             status in {Active, Pending}.
    Status is lowercased in returned rows to match manual-seed convention.
    Pending rows are included for display but excluded from active-count stats
    by callers via status == "active" check.
    Returns (listings, basis_string).
    """
    if not os.environ.get("RENTCAST_API_KEY"):
        return [], ""
    try:
        params = (
            f"latitude={lat}&longitude={lon}"
            f"&radius={radius_mi}&limit=500"
        )
        resp = _rentcast_get("/v1/listings/sale", params)
        rows = resp if isinstance(resp, list) else resp.get("listings", [])
        ALLOWED_TYPES    = {"Single Family", "Townhouse"}
        ALLOWED_STATUSES = {"Active", "Pending"}
        listings = []
        for row in rows:
            if row.get("zipCode") != zip_code:
                continue
            if row.get("propertyType") not in ALLOWED_TYPES:
                continue
            status = (row.get("status") or "").strip()
            if status not in ALLOWED_STATUSES:
                continue
            sqft  = int(row.get("squareFootage") or 0) or None
            beds  = int(row.get("bedrooms") or 0) or None
            baths = float(row.get("bathrooms") or 0) or None
            dom   = int(row.get("daysOnMarket") or 0) or None
            listings.append({
                "address": row.get("formattedAddress", ""),
                "list_price": int(row.get("price") or 0),
                "sqft":    sqft,
                "beds":    beds,
                "baths":   baths,
                "status":  status.lower(),
                "dom":     dom,
                "source":  "rentcast",
            })
        basis = (
            f"RentCast active listings (aggregated public and listing data); "
            f"fetched {date.today().isoformat()}"
        )
        return listings, basis
    except Exception:
        return [], ""


def _fetch_july_history(p_base: str, zip_code: str) -> list[dict]:
    """
    Fetch SFR sales that CLOSED in July, 2022-2025.
    Padded window Jun 15 - Aug 15 per year (ATTOM filters on record date, not
    closing date), then trims in code to saleTransDate falling in July.
    Filters: SFR, same zip, distance <= 1.0 mi.
    Returns rows with list-price placeholders; caller enriches via RentCast.
    """
    RADIUS = 1.0
    rows: list[dict] = []
    for year in (2022, 2023, 2024, 2025):
        start = f"{year}-06-15"
        end   = f"{year}-08-15"
        raw   = _fetch_snapshot_pages(p_base, RADIUS, start, end)
        for p in raw:
            if p.get("summary", {}).get("proptype") != "SFR":
                continue
            if p.get("address", {}).get("postal1") != zip_code:
                continue
            dist = float((p.get("location") or {}).get("distance") or 0)
            if dist > RADIUS:
                continue
            entry = _extract_snapshot_entry(p)
            if entry is None:
                continue
            # Trim to July closing date (saleTransDate)
            sale_date = entry.get("_sale_date_iso", "")
            if not sale_date.startswith(f"{year}-07"):
                continue
            rows.append({
                "address":           entry["address"],
                "sqft":              entry["sqft"],
                "beds":              entry["beds"],
                "baths":             entry["baths"],
                "year_built":        entry["year_built"],
                "sold_price":        entry["price"],
                "sold_date":         sale_date[:10],
                "ppsf":              entry["ppsf"],
                "distance_mi":       entry["distance_mi"],
                "list_price":        None,
                "listed_date":       None,
                "dom":               None,
                "list_price_status": "not_fetched",
            })
    rows.sort(key=lambda x: x["sold_date"], reverse=True)
    return rows


def fetch_rentcast_list_price(
    address: str,
) -> tuple[int | None, str, str | None, int | None]:
    """
    Look up the list price for a sold home via RentCast /v1/listings/sale.
    Returns (price_or_None, status, listed_date_or_None, dom_or_None).

    Status vocabulary:
      "ok"           -- price found; row is settled, never retried
      "no_data"      -- RentCast returned empty array; settled, never retried
      "fetch_failed" -- call error or 429 exhausted; retried on next compute load

    429 responses get exponential back-off (1 s, 2 s, 4 s) before giving up
    as fetch_failed.  A 429 is NEVER classified as no_data.
    """
    import urllib.error
    if not os.environ.get("RENTCAST_API_KEY"):
        return None, "no_data", None, None
    addr_enc = urllib.parse.quote(address)
    backoff  = [1.0, 2.0, 4.0]
    attempt  = 0
    while True:
        try:
            resp = _rentcast_get("/v1/listings/sale", f"address={addr_enc}")
            rows = resp if isinstance(resp, list) else resp.get("listings", [])
            if not rows:
                return None, "no_data", None, None
            row        = rows[0]
            price      = row.get("price")
            listed_iso = (row.get("listedDate") or "")[:10] or None
            dom_val    = row.get("daysOnMarket")
            if price:
                return (
                    int(price),
                    "ok",
                    listed_iso,
                    int(dom_val) if dom_val is not None else None,
                )
            return None, "no_data", None, None
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < len(backoff):
                time.sleep(backoff[attempt])
                attempt += 1
                continue   # retry with longer wait
            if exc.code == 404:
                return None, "no_data", None, None  # address not in RentCast
            return None, "fetch_failed", None, None
        except Exception:
            return None, "fetch_failed", None, None
