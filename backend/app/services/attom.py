"""
attom.py — ATTOM API integration for real market data.

Fetches:
  - AVM estimate        /propertyapi/v1.0.0/avm/detail
  - Nearby sold props   /propertyapi/v1.0.0/property/basicprofile  (radius up to 1.0 mi)
      fetched_comps:              sales in last 12 months, comparable size
      neighborhood_sales_history: sales in last 5 years

Comp radius strategy:
  Fetch at 1.0 mi (one set of API calls, sorted by distance).
  Try 0.5 mi bucket first — if ≥ MIN_COMPS comparable recent sales, stop there.
  If not, expand to 0.75 mi, then 1.0 mi.  Never widen the time window past 12 mo.

Size filter:
  Comps are filtered to ±40% of subject sqft when subject_sqft is provided.
  Neighborhood history uses ±60% (looser — context only, not valuation input).

ATTOM is a public-records provider.  It does NOT supply active MLS listings.
fetched_active_listings is always returned as an empty list.

API key read from ATTOM_API_KEY env var.  Never hardcoded or committed.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import date, timedelta

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
        return True   # no subject size known; accept all
    lo = subject_sqft * (1 - tolerance)
    hi = subject_sqft * (1 + tolerance)
    return lo <= sqft <= hi


def _extract_entry(p: dict) -> dict | None:
    """
    Extract a normalized comp/history entry from a basicprofile property dict.
    Returns None if the property is missing required fields.
    """
    sale      = p.get("sale", {})
    sale_data = sale.get("saleAmountData", {})
    sale_amt  = float(sale_data.get("saleAmt") or 0)
    sale_date = sale.get("saleTransDate") or sale.get("saleSearchDate") or ""

    if not sale_date or sale_amt < 50_000:
        return None

    bldg = p.get("building", {})
    size = bldg.get("size", {})
    sqft = float(size.get("livingSize") or size.get("universalSize") or 0)
    if sqft <= 0:
        return None

    rooms = bldg.get("rooms", {})
    beds  = int(rooms.get("beds") or 0)
    baths = float(rooms.get("bathsTotal") or 0)
    addr  = p.get("address", {}).get("oneLine", "")
    yr    = p.get("summary", {}).get("yearBuilt")
    ppsf  = round(sale_amt / sqft)
    dist  = float(p.get("location", {}).get("distance") or 0)

    entry: dict = {
        "address":        addr,
        "beds":           beds,
        "baths":          baths,
        "sqft":           int(sqft),
        "built":          yr,
        "sold":           _ym(sale_date),
        "price":          int(sale_amt),
        "ppsf":           ppsf,
        "_sale_date_iso": sale_date,   # full ISO date for date-range filtering
        "_distance_mi":   dist,
    }
    if yr and int(yr) > 2010:
        entry["note"] = "newer build"

    return entry


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
      fetched_comps:              list[comp_dict]   (12-month window, comparable size)
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

    # ── AVM ──────────────────────────────────────────────────────────────
    subject_attom_id = None
    avm_as_of        = ""
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

    # ── Nearby sold properties (one fetch at max radius, sorted by distance) ──
    cutoff_12mo = (date.today() - timedelta(days=365)).isoformat()
    cutoff_5yr  = (date.today() - timedelta(days=1825)).isoformat()

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
        bucket = [
            e for e in candidates
            if e["_sale_date_iso"] >= cutoff_12mo
            and e["_distance_mi"] <= radius
            and _in_size_band(e["sqft"], subject_sqft, 0.20)
        ]
        if len(bucket) >= MIN_COMP_COUNT:
            used_radius = radius
            final_comps = bucket
            break

    # If we never hit MIN_COMP_COUNT even at max radius, use whatever 1.0 mile gave
    if not final_comps:
        used_radius = RADII[-1]
        final_comps = [
            e for e in candidates
            if e["_sale_date_iso"] >= cutoff_12mo
            and _in_size_band(e["sqft"], subject_sqft, 0.20)
        ]

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

    # Sort newest first; strip internal tracking fields; cap counts
    def _clean(entry: dict) -> dict:
        return {k: v for k, v in entry.items() if not k.startswith("_")}

    final_comps.sort(key=lambda x: x["sold"], reverse=True)
    history.sort(key=lambda x: x["sold"], reverse=True)

    result["fetched_comps"]              = [_clean(e) for e in final_comps[:10]]
    result["neighborhood_sales_history"] = [_clean(e) for e in history[:20]]
    result["attom_meta"] = {
        "comp_radius_miles": used_radius,
        "comp_count":        len(result["fetched_comps"]),
        "avm_as_of":         avm_as_of,
    }

    return result
