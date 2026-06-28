"""
Comp-selection + weighting smoke check.
Run from the repo root:  python smoke_comp.py
"""
import os, sys, math
sys.path.insert(0, "backend")
os.environ.setdefault("ATTOM_API_KEY", "8ad7547af2471a319f3e831802ff91d9")

from app.services.attom import fetch_attom_data
from app.logic.valuation import compute_as_is_range, _comp_weights

SUBJECT_SQFT = 2019
SUBJECT_BEDS = 3
SUBJECT_ZIP  = "29680"

def section(t): print(f"\n{'='*60}\n{t}\n{'='*60}")

section("1. Fetch comps")
r = fetch_attom_data("130 Kingfisher Dr", "Simpsonville", "SC", SUBJECT_ZIP,
                     SUBJECT_SQFT, SUBJECT_BEDS)

comps = r["fetched_comps"]
meta  = r["attom_meta"]
avms  = r["fetched_avms"]

print(f"used_radius : {meta['comp_radius_miles']} mi")
print(f"comp_count  : {meta['comp_count']}")
print(f"avm         : {avms}")

section("2. Per-comp detail")
ws = _comp_weights(comps, SUBJECT_SQFT)

BW_SQFT = max(150.0, 0.10 * SUBJECT_SQFT)
BW_DIST = 0.75

header = (f"{'#':>2}  {'address':<36} {'zip':>5} {'dist':>5} {'sqft':>5} {'beds':>4} "
          f"{'price':>9} {'newer':>5} {'note':<18} {'weight':>7}")
print(header)
print("-" * len(header))

fails = []
for i, (c, w) in enumerate(zip(comps, ws)):
    dist  = c.get("distance_mi")
    beds  = c.get("beds")
    newer = c.get("is_newer_build", False)
    note  = c.get("note", "")
    zip_c = c.get("zip", "")

    # All comps must be same zip
    if zip_c != SUBJECT_ZIP:
        fails.append(f"comp {i+1} zip={zip_c} != subject {SUBJECT_ZIP}: {c.get('address','')}")

    if dist is None:
        fails.append(f"comp {i+1} missing distance_mi")

    if beds is not None and abs(beds - SUBJECT_BEDS) > 1:
        fails.append(f"comp {i+1} beds={beds} >1 away from subject {SUBJECT_BEDS}")

    if dist is not None and dist > meta["comp_radius_miles"] + 0.01:
        fails.append(f"comp {i+1} dist={dist:.2f} > radius {meta['comp_radius_miles']}")

    # "extended radius" only note must not trigger newer_penalty
    if note and "extended radius" in note and not newer:
        sqft_diff  = float(c["sqft"]) - SUBJECT_SQFT
        size_w     = math.exp(-0.5 * (sqft_diff / BW_SQFT) ** 2)
        dist_w     = math.exp(-0.5 * ((dist or 0) / BW_DIST) ** 2)
        expected_w = size_w * dist_w
        if abs(expected_w - w) > 0.001:
            fails.append(f"comp {i+1} 'extended radius' newer_penalty wrong: "
                         f"weight={w:.4f} expected~{expected_w:.4f}")

    addr_s = (c.get("address") or "")[:36]
    print(f"{i+1:>2}  {addr_s:<36} {zip_c:>5} {(dist or 0):>5.2f} {c['sqft']:>5} "
          f"{(beds or 0):>4} ${c['price']:>8,} {str(newer):>5} {note:<18} {w:>7.4f}")

section("3. Valuation result")
prop = {
    "public_county_facts": {"sqft": SUBJECT_SQFT, "beds": SUBJECT_BEDS},
    "fetched_avms": avms,
    "fetched_comps": comps,
}
try:
    val     = compute_as_is_range(prop)
    avm_avg = val["avm_avg"]
    mid     = val["mid"]
    print(f"low         : ${val['low']:,.0f}")
    print(f"mid         : ${mid:,.0f}")
    print(f"high        : ${val['high']:,.0f}")
    if avm_avg:
        div = abs(mid - avm_avg) / avm_avg
        print(f"avm_avg     : ${avm_avg:,.0f}")
        print(f"divergence  : {div:.1%}  {'<-- STILL HIGH (>8%)' if div > 0.08 else 'OK'}")
        if div > 0.08 and meta["comp_radius_miles"] <= 1.0:
            fails.append(f"divergence {div:.1%} >8% with local comps — stopping here for review")
    print(f"confidence  : {val['confidence']}")
    print(f"note        : {val['note']}")
except Exception as e:
    fails.append(f"valuation failed: {e}")
    print(f"ERROR: {e}")

section("4. Pass/Fail")
if fails:
    for f in fails:
        print(f"FAIL: {f}")
    sys.exit(1)
else:
    print("All checks passed.")
