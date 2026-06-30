"""
smoke_full_run.py -- pre-push 22-address live run.

Three passes:
  PASS 1  Full fetch_attom_data for 130 Kingfisher (all ~22 July rows enriched).
          Report ok / no_data / fetch_failed counts.
  PASS 2  Retry pass: re-run fetch_rentcast_list_price on any fetch_failed rows.
          Report how many healed (fetch_failed -> ok/no_data).
  PASS 3  Cache check: wrap _rentcast_get with counter, re-run retry pass.
          Expect zero HTTP calls (no fetch_failed rows remain, nothing to retry).

Do NOT push until these three numbers are confirmed green.
"""
from __future__ import annotations
import copy, os, sys, time
from collections import Counter

sys.path.insert(0, "backend")
from app.data_loader import load_property_inputs
from app.services.attom import fetch_attom_data, parse_address, fetch_rentcast_list_price
import app.services.attom as _attom_mod
import urllib.parse

GREEN = "\033[32mPASS\033[0m"
RED   = "\033[31mFAIL\033[0m"
failures: list[str] = []

def check(label: str, condition: bool, detail: str = "") -> bool:
    tag    = GREEN if condition else RED
    suffix = f"  ({detail})" if detail else ""
    print(f"  [{tag}] {label}{suffix}")
    if not condition:
        failures.append(label)
    return condition

if not os.environ.get("ATTOM_API_KEY"):
    print("ERROR: ATTOM_API_KEY not set"); sys.exit(1)
if not os.environ.get("RENTCAST_API_KEY"):
    print("ERROR: RENTCAST_API_KEY not set"); sys.exit(1)

prop = load_property_inputs("130_kingfisher")
street, city, state, zip_code = parse_address(prop["address"])
sqft = float(prop.get("public_county_facts", {}).get("sqft", 0))
beds = int(prop.get("public_county_facts", {}).get("beds", 0))

# =============================================================================
# PASS 1: full fetch_attom_data -- all July rows enriched live
# =============================================================================
print("\n=== PASS 1: full fetch_attom_data (live, all July rows) ===")
t0   = time.time()
data = fetch_attom_data(street, city, state, zip_code, sqft, beds)
elapsed = time.time() - t0

hist = data.get("neighborhood_sales_history", [])
sc1  = Counter(r.get("list_price_status") for r in hist)
total = len(hist)

print(f"\n  Total July rows:  {total}")
print(f"  ok:               {sc1.get('ok', 0)}")
print(f"  no_data:          {sc1.get('no_data', 0)}")
print(f"  fetch_failed:     {sc1.get('fetch_failed', 0)}")
print(f"  not_fetched:      {sc1.get('not_fetched', 0)}  (must be 0)")
print(f"  Elapsed:          {elapsed:.1f}s")
print(f"\n  Per-row detail:")
for r in hist:
    lp_d = f"${r['list_price']:>8,}" if r.get("list_price") else "      none"
    print(f"    {r['address'][:46]:46s}  {r.get('list_price_status','?'):12s}  "
          f"list={lp_d}  sold=${r.get('sold_price',0):>8,}")

print(f"\n  history_basis: {data.get('attom_meta',{}).get('history_basis','MISSING')}")

check("PASS 1: zero not_fetched", sc1.get("not_fetched", 0) == 0,
      f"not_fetched={sc1.get('not_fetched',0)}")
check("PASS 1: total rows >= 10", total >= 10, str(total))

# =============================================================================
# PASS 2: retry fetch_failed rows
# =============================================================================
print("\n=== PASS 2: retry fetch_failed rows ===")
history2 = copy.deepcopy(hist)
to_retry = [i for i, r in enumerate(history2)
            if r.get("list_price_status") in ("not_fetched", "fetch_failed")]
print(f"  Rows to retry: {len(to_retry)}")

healed = 0
for i in to_retry:
    addr = history2[i]["address"]
    try:
        lp, st, ld, dm = fetch_rentcast_list_price(addr)
    except Exception:
        lp, st, ld, dm = None, "fetch_failed", None, None
    history2[i]["list_price_status"] = st
    if st in ("ok", "no_data"):
        history2[i]["list_price"]  = lp
        history2[i]["listed_date"] = ld
        history2[i]["dom"]         = dm
        healed += 1
        print(f"    HEALED  [{st:7s}]  {addr[:46]}  list=${lp}")
    else:
        print(f"    STILL FAILED [{st}]  {addr[:46]}")
    time.sleep(0.3)

sc2 = Counter(r.get("list_price_status") for r in history2)
print(f"\n  After retry:")
print(f"    ok:           {sc2.get('ok', 0)}")
print(f"    no_data:      {sc2.get('no_data', 0)}")
print(f"    fetch_failed: {sc2.get('fetch_failed', 0)}")
print(f"    healed:       {healed}/{len(to_retry)}")

check("PASS 2: zero not_fetched after retry",
      sc2.get("not_fetched", 0) == 0,
      f"not_fetched={sc2.get('not_fetched', 0)}")

# =============================================================================
# PASS 3: cache check -- no fetch_failed remain, zero HTTP calls should fire
# =============================================================================
print("\n=== PASS 3: third load -- expect zero new RentCast calls ===")
http_calls3: list[str] = []
_orig_http  = _attom_mod._rentcast_get

def _counting_http(path: str, params: str = "") -> dict:
    http_calls3.append(params[:60])
    return _orig_http(path, params)

_attom_mod._rentcast_get = _counting_http
try:
    history3     = copy.deepcopy(history2)
    still_retry  = [i for i, r in enumerate(history3)
                    if r.get("list_price_status") in ("not_fetched", "fetch_failed")]
    print(f"  Rows still retryable after pass 2: {len(still_retry)}")
    for i in still_retry:
        try:
            lp3, st3, ld3, dm3 = fetch_rentcast_list_price(history3[i]["address"])
            history3[i]["list_price_status"] = st3
        except Exception:
            history3[i]["list_price_status"] = "fetch_failed"
        time.sleep(0.1)
finally:
    _attom_mod._rentcast_get = _orig_http

print(f"  HTTP calls fired in pass 3: {len(http_calls3)}")
for c in http_calls3:
    print(f"    {c}")

check("PASS 3: zero HTTP calls (fully cached)", len(http_calls3) == 0,
      f"calls={len(http_calls3)}")

# =============================================================================
print("\n=== SUMMARY ===")
print(f"  PASS 1  ok={sc1.get('ok',0)}  no_data={sc1.get('no_data',0)}  "
      f"fetch_failed={sc1.get('fetch_failed',0)}  not_fetched={sc1.get('not_fetched',0)}")
print(f"  PASS 2  healed={healed}/{len(to_retry)}  "
      f"remaining_fetch_failed={sc2.get('fetch_failed',0)}")
print(f"  PASS 3  http_calls={len(http_calls3)}")

if failures:
    print(f"\n  {RED} {len(failures)} check(s) failed:")
    for f in failures:
        print(f"    - {f}")
    sys.exit(1)
else:
    print(f"\n  {GREEN} All checks passed")
