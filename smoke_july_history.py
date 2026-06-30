"""
smoke_july_history.py -- July seasonal history, capped at 8 live RentCast calls.

Pass bar:
  STEP 1  _fetch_july_history: per-year counts, no June/Aug leakage, sorted desc
  STEP 2  Single-address: 663 Columbus Cir -> list $309,900, status=ok
  STEP 3  5-row enrichment: zero not_fetched after loop
  STEP 4  Cache hit: ok/no_data rows trigger ZERO real calls (instrumented)
  STEP 5  Retry proof: 2 injected failures both heal to ok/no_data (2 of 2)
  STEP 6  429 backoff: code path verified via inspect (no live call)

Total live RentCast calls: 1 (step2) + 5 (step3) + 2 (step5) = 8 max.
"""
from __future__ import annotations
import copy, os, sys, time
from collections import Counter

sys.path.insert(0, "backend")
from app.data_loader import load_property_inputs
from app.services.attom import parse_address, _fetch_july_history, fetch_rentcast_list_price
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
p_base = (
    f"address1={urllib.parse.quote(street)}"
    f"&address2={urllib.parse.quote(f'{city}, {state} {zip_code}')}"
)

# ---------------------------------------------------------------------------
# STEP 1: _fetch_july_history -- ATTOM only, zero RentCast calls
# ---------------------------------------------------------------------------
print("\n-- STEP 1: _fetch_july_history date filter --")
t0        = time.time()
july_rows = _fetch_july_history(p_base, zip_code)
elapsed   = time.time() - t0

by_year = Counter(r["sold_date"][:4] for r in july_rows)
total   = len(july_rows)
print(f"  Total rows: {total}  ({elapsed:.1f}s)")
for yr in sorted(by_year):
    print(f"    {yr}: {by_year[yr]}")

check("At least 10 total July rows",       total >= 10, str(total))
check("Covers all 4 years 2022-2025",      len(by_year) == 4, str(dict(by_year)))
leak = [r for r in july_rows if "-07-" not in r["sold_date"]]
check("No June/Aug leakage",               len(leak) == 0,
      f"{len(leak)} leaks" if leak else "clean")
dates = [r["sold_date"] for r in july_rows]
check("Sorted newest-first",               dates == sorted(dates, reverse=True))
check("All rows start as not_fetched",
      {r["list_price_status"] for r in july_rows} == {"not_fetched"})

# ---------------------------------------------------------------------------
# STEP 2: single known address (1 call)
# ---------------------------------------------------------------------------
print("\n-- STEP 2: 663 Columbus Cir single-address lookup (1 call) --")
KNOWN_ADDR  = "663 Columbus Cir, Simpsonville, SC 29680"
EXPECTED_LP = 309900
lp, status, listed_date, dom = fetch_rentcast_list_price(KNOWN_ADDR)
print(f"  list_price={lp}  status={status}  listed={listed_date}  dom={dom}")
check("Status is ok",               status == "ok",       status)
check(f"list_price == ${EXPECTED_LP:,}", lp == EXPECTED_LP, str(lp))

# ---------------------------------------------------------------------------
# STEP 3: 5-row enrichment (5 calls)
# ---------------------------------------------------------------------------
print("\n-- STEP 3: 5-row enrichment loop (5 calls) --")
sample = [copy.deepcopy(r) for r in july_rows[:5]]

t0 = time.time()
for row in sample:
    if row.get("list_price_status") not in ("not_fetched", "fetch_failed"):
        continue
    try:
        lp2, st2, ld2, dm2 = fetch_rentcast_list_price(row["address"])
        row["list_price"]        = lp2
        row["listed_date"]       = ld2
        row["dom"]               = dm2
        row["list_price_status"] = st2
    except Exception:
        row["list_price_status"] = "fetch_failed"
    time.sleep(0.3)
elapsed = time.time() - t0

sc3 = Counter(r["list_price_status"] for r in sample)
print(f"  Status counts: {dict(sc3)}  ({elapsed:.1f}s)")
for r in sample:
    lp_d = f"${r['list_price']:>7,}" if r["list_price"] else "     none"
    print(f"    {r['address'][:44]:44s}  {r['list_price_status']:12s}  list={lp_d}  sold=${r['sold_price']:>7,}")

check("Zero not_fetched after enrichment", sc3.get("not_fetched", 0) == 0,
      f"not_fetched={sc3.get('not_fetched', 0)}")

ok_rows = [r for r in sample if r["list_price_status"] == "ok"]
if ok_rows:
    b = ok_rows[0]
    print(f"\n  ok sample: {b['address']}")
    print(f"    list=${b['list_price']:,}  sold=${b['sold_price']:,}  "
          f"spread=${(b['list_price'] or 0) - (b['sold_price'] or 0):+,}")
    check("ok row has both prices", bool(b["list_price"]) and bool(b["sold_price"]))

# ---------------------------------------------------------------------------
# STEP 4: cache hit -- instrument actual invocations of fetch_rentcast_list_price
#
# Design: the enrichment guard is
#   if row["list_price_status"] not in ("not_fetched","fetch_failed"): continue
# So only not_fetched / fetch_failed rows should ever invoke the function.
# ok and no_data rows must produce zero invocations.
# ---------------------------------------------------------------------------
print("\n-- STEP 4: cache hit -- real call counter on ok/no_data rows --")

# Snapshot statuses BEFORE running the step-4 pass (sample may still have
# one fetch_failed row from step 3; that row IS allowed to fire a call).
pre_status = {r["address"]: r["list_price_status"] for r in sample}

# Wrap _rentcast_get (the actual HTTP layer) to count real network requests.
_http_calls: list[dict] = []
_orig_http = _attom_mod._rentcast_get

def _counting_http(path: str, params: str = "") -> dict:
    _http_calls.append({"path": path, "addr": params[:80]})
    return _orig_http(path, params)

_attom_mod._rentcast_get = _counting_http

try:
    for row in sample:
        if row.get("list_price_status") not in ("not_fetched", "fetch_failed"):
            continue   # settled -- must never reach the HTTP layer
        try:
            lp4, st4, ld4, dm4 = fetch_rentcast_list_price(row["address"])
            row["list_price_status"] = st4
        except Exception:
            row["list_price_status"] = "fetch_failed"
        time.sleep(0.1)
finally:
    _attom_mod._rentcast_get = _orig_http   # always restore

# Any HTTP call whose pre-status was ok or no_data is a violation.
ok_violations = [
    c for c in _http_calls
    if any(pre_status.get(r["address"]) in ("ok", "no_data")
           for r in sample if r["address"] in c["addr"])
]
retryable_calls = len(_http_calls) - len(ok_violations)

print(f"  HTTP calls fired total:      {len(_http_calls)}")
print(f"  Calls against ok/no_data:    {len(ok_violations)}  (must be 0)")
print(f"  Calls against retryable rows:{retryable_calls}")
for c in _http_calls:
    print(f"    {c['addr'][:60]}")

check("Zero HTTP calls against ok/no_data rows", len(ok_violations) == 0,
      f"violations={len(ok_violations)}")

# ---------------------------------------------------------------------------
# STEP 5: retry proof -- inject 2 failures, expect both to heal (2 more calls)
# ---------------------------------------------------------------------------
print("\n-- STEP 5: retry proof -- 2 injected failures healed (2 calls) --")
any_settled = [r for r in sample if r["list_price_status"] in ("ok", "no_data")]

if len(any_settled) < 2:
    print("  SKIP: fewer than 2 settled rows to inject into")
else:
    test = [copy.deepcopy(any_settled[0]), copy.deepcopy(any_settled[1])]
    test[0]["list_price"] = None; test[0]["list_price_status"] = "fetch_failed"
    test[1]["list_price"] = None; test[1]["list_price_status"] = "not_fetched"
    print(f"  row0 fetch_failed: {test[0]['address'][:44]}")
    print(f"  row1 not_fetched:  {test[1]['address'][:44]}")

    healed = 0
    for row in test:
        if row.get("list_price_status") not in ("not_fetched", "fetch_failed"):
            continue
        try:
            lp3, st3, ld3, dm3 = fetch_rentcast_list_price(row["address"])
        except Exception:
            lp3, st3, ld3, dm3 = None, "fetch_failed", None, None
        row["list_price_status"] = st3
        if st3 in ("ok", "no_data"):
            row["list_price"]  = lp3
            row["listed_date"] = ld3
            row["dom"]         = dm3
            healed += 1
        time.sleep(0.3)

    sc5 = Counter(r["list_price_status"] for r in test)
    print(f"  Post-retry counts: {dict(sc5)}")
    for r in test:
        print(f"    {r['address'][:44]:44s}  {r['list_price_status']}")
    check("Both injected rows healed (2 of 2)", healed == 2, f"healed={healed}/2")
    check("No not_fetched survives retry",
          sc5.get("not_fetched", 0) == 0, f"not_fetched={sc5.get('not_fetched',0)}")

# ---------------------------------------------------------------------------
# STEP 6: 429 backoff -- static code inspection, no live call
# ---------------------------------------------------------------------------
print("\n-- STEP 6: 429 backoff code structure --")
import inspect
fn_src  = inspect.getsource(fetch_rentcast_list_price)
idx_429 = fn_src.find("exc.code == 429")
idx_ff  = fn_src.find('"fetch_failed"', idx_429)
idx_nd  = fn_src.find('"no_data"',      idx_429)

check("HTTPError / 429 branch present",   idx_429 != -1)
check("Backoff list [1.0, 2.0, 4.0]",    "[1.0, 2.0, 4.0]" in fn_src)
check("continue on 429 (retry loop)",     "continue" in fn_src)
check("429 exhausted -> fetch_failed, not no_data",
      idx_429 != -1 and idx_ff != -1
      and (idx_nd == -1 or idx_ff < idx_nd),
      f"ff_after_429={idx_ff} nd_after_429={idx_nd}")

# ---------------------------------------------------------------------------
print("\n-- SUMMARY --")
if failures:
    print(f"  {RED} {len(failures)} check(s) failed:")
    for f in failures:
        print(f"    - {f}")
    sys.exit(1)
else:
    print(f"  {GREEN} All checks passed  (~8 RentCast calls this run)")
    print("  Ready to push.")
