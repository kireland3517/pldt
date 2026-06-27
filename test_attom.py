#!/usr/bin/env python3
"""
Run this locally to capture ATTOM response shapes.
Usage:
  $env:ATTOM_API_KEY = "your_key"
  python test_attom.py

Paste the full output back so the field mappings can be confirmed.
"""
import json, os, sys, urllib.request, urllib.parse

KEY = os.environ.get("ATTOM_API_KEY")
if not KEY:
    sys.exit("Set ATTOM_API_KEY env var first.")

BASE    = "https://api.gateway.attomdata.com"
STREET  = "130 Kingfisher Dr"
CITY    = "Simpsonville"
STATE   = "SC"
ZIP_    = "29680"
ADDR2   = f"{CITY}, {STATE} {ZIP_}"
ATTOM_ID = 50578769   # from AVM response

def get(path, params=""):
    url = f"{BASE}{path}{'?' + params if params else ''}"
    req = urllib.request.Request(url, headers={
        "apikey": KEY, "Accept": "application/json"
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"__error__": str(e)}

def sep(title):
    print("\n" + "="*60)
    print(title)
    print("="*60)

# ------------------------------------------------------------------
# 1. AVM (already confirmed working — quick re-check)
# ------------------------------------------------------------------
sep("1. AVM")
avm = get("/propertyapi/v1.0.0/avm/detail",
          f"address1={urllib.parse.quote(STREET)}&address2={urllib.parse.quote(ADDR2)}")
code = avm.get("status", {}).get("code", avm.get("__error__"))
print(f"status: {code}  |  avm.value: {avm.get('property',[{}])[0].get('avm',{}).get('amount',{}).get('value','N/A')}")

# ------------------------------------------------------------------
# 2. SalesComparables — try by attomId (minimal params)
# ------------------------------------------------------------------
sep("2a. SalesComparables by attomId (minimal)")
comps_id = get(f"/property/v2/SalesComparables/Id/{ATTOM_ID}",
               "miles=1&pageSize=20")
print(json.dumps(comps_id, indent=2))

# ------------------------------------------------------------------
# 2b. SalesComparables by address — minimal params only
# ------------------------------------------------------------------
sep("2b. SalesComparables by address (minimal params)")
addr_path = f"/{urllib.parse.quote(STREET)}/{urllib.parse.quote(CITY)}/{STATE}/{ZIP_}"
comps_addr = get(f"/property/v2/SalesComparables/Address{addr_path}",
                 "miles=1&pageSize=20")
print(json.dumps(comps_addr, indent=2))

# ------------------------------------------------------------------
# 2c. SalesComparables by address — v1 path
# ------------------------------------------------------------------
sep("2c. SalesComparables v1 endpoint")
comps_v1 = get("/propertyapi/v1.0.0/salescomparables/address",
               f"address1={urllib.parse.quote(STREET)}&address2={urllib.parse.quote(ADDR2)}&miles=1&minsaleamt=50000&maxsaleamt=500000&saleDateRange=12")
print(json.dumps(comps_v1, indent=2))

# ------------------------------------------------------------------
# 3. Property search by radius — for neighborhood sales history
# ------------------------------------------------------------------
sep("3. Radius search — neighborhood sold properties")
# Try /propertyapi/v1.0.0/property/basicprofile with geoId from AVM
radius_geo = get("/propertyapi/v1.0.0/property/basicprofile",
                 f"address1={urllib.parse.quote(STREET)}&address2={urllib.parse.quote(ADDR2)}&radius=0.5")
print(json.dumps(radius_geo, indent=2))

# ------------------------------------------------------------------
# 4. Sale history for a specific property (via salehistory endpoint)
# ------------------------------------------------------------------
sep("4. Sale history — /propertyapi/v1.0.0/saleshistory/detail")
sale_hist = get("/propertyapi/v1.0.0/saleshistory/detail",
                f"address1={urllib.parse.quote(STREET)}&address2={urllib.parse.quote(ADDR2)}")
print(json.dumps(sale_hist, indent=2))

# ------------------------------------------------------------------
# 5. Property search (try getting nearby sales via SB geoId)
#    SB geoId from AVM: 7f7913bdedff01e10b3c320a6c1ff0bf (one of many subdivisions)
# ------------------------------------------------------------------
sep("5. Sales in subdivision by geoId")
geo_id = "7f7913bdedff01e10b3c320a6c1ff0bf"  # first SB from AVM
geo_sales = get("/propertyapi/v1.0.0/saleshistory/snapshot",
                f"geoIdV4=SB{geo_id}&startcalendardate=2020-01-01&endcalendardate=2025-12-31&pageSize=25")
print(json.dumps(geo_sales, indent=2))
