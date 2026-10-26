"""Geocode hats.csv -> hats_geocoded.csv using free OSM geocoders (no API key).

Order of attempts per restaurant:
  1. Photon (komoot) POI search "name, suburb", biased to NSW/ACT
  2. Nominatim POI search "name, suburb, Australia"
No fallback: anything unmatched goes to needs_coords.csv for manual lat/lngs.
Responses are cached in cache.json so reruns are cheap. Add manual fixes to
overrides.csv (name,lat,lng) and they win over everything else.
"""
import csv
import difflib
import json
import os
import re
import time
import urllib.parse
import urllib.request

UA = "gfg-hats-map/1.0 (personal project)"
BBOX = (140.9, -37.6, 153.7, -28.1)  # NSW + ACT, lon/lat
SUBURB_FIX = {"CBD": "Sydney", "Rushcutters Bar": "Rushcutters Bay"}
FOOD = {"restaurant", "bar", "cafe", "pub", "fast_food", "biergarten", "food_court", "winery", "hotel"}

cache = json.load(open("cache.json")) if os.path.exists("cache.json") else {}
_last = {"t": 0.0}


def get(url):
    if url in cache:
        return cache[url]
    wait = 1.1 - (time.time() - _last["t"])  # Nominatim policy: max 1 req/s
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
            break
        except OSError as e:  # URLError, timeouts, SSL handshake failures
            if attempt == 3:
                raise
            print(f"  retrying after {e}", flush=True)
            time.sleep(5 * (attempt + 1))
    _last["t"] = time.time()
    cache[url] = data
    json.dump(cache, open("cache.json", "w"))
    return data


def norm(s):
    s = s.lower().replace("’", "'")
    s = re.sub(r"^the |restaurant|dining( room)?|& bar| bar$|[^a-z0-9 ]", " ", s)
    return " ".join(s.split())


def similar(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0
    short, long_ = sorted((a, b), key=len)
    # whole-word containment, and the shorter name must be most of the longer one
    if re.search(rf"\b{re.escape(short)}\b", long_) and len(short) / len(long_) >= 0.4:
        return 1
    return difflib.SequenceMatcher(None, a, b).ratio()


def in_bbox(lat, lng):
    return BBOX[1] <= lat <= BBOX[3] and BBOX[0] <= lng <= BBOX[2]


def photon(name, suburb):
    q = urllib.parse.urlencode({"q": f"{name}, {suburb}", "limit": 8, "lat": -33.87, "lon": 151.2,
                                "bbox": ",".join(map(str, BBOX))})
    best = None
    for f in get(f"https://photon.komoot.io/api/?{q}").get("features", []):
        p = f["properties"]
        lng, lat = f["geometry"]["coordinates"]
        if p.get("osm_key") not in ("amenity", "tourism", "shop", "craft", "leisure") or not in_bbox(lat, lng):
            continue
        score = similar(name, p.get("name", ""))
        if score < 0.85:  # name must match on its own; bonuses only break ties
            continue
        place = " ".join(str(p.get(k, "")) for k in ("city", "district", "locality", "suburb", "name"))
        if suburb.lower() in place.lower():
            score += 0.15
        if p.get("osm_value") in FOOD:
            score += 0.1
        if score >= 0.85 and (best is None or score > best[0]):
            best = (score, lat, lng, p.get("name"), "photon")
    return best


def nominatim(query, require_name=None):
    q = urllib.parse.urlencode({"q": query, "format": "jsonv2", "limit": 5, "countrycodes": "au"})
    for r in get(f"https://nominatim.openstreetmap.org/search?{q}"):
        lat, lng = float(r["lat"]), float(r["lon"])
        if not in_bbox(lat, lng):
            continue
        if require_name:
            if r.get("category") not in ("amenity", "tourism", "shop", "leisure", "craft"):
                continue
            if similar(require_name, r.get("name", "")) < 0.85:
                continue
        return (1, lat, lng, r.get("name") or r.get("display_name"), "nominatim")
    return None


# geocoder matches checked by hand and known to be the wrong place
REJECT = {"Golden Century", "Fontana", "South End", "Megalong Restaurant", "Grill Americano", "Arthur", "Pizza’Mare"}

overrides = {}
if os.path.exists("overrides.csv"):
    for r in csv.DictReader(open("overrides.csv", encoding="utf-8")):
        overrides[r["name"]] = r

out, missing = [], []
for row in csv.DictReader(open("hats.csv", encoding="utf-8")):
    name = row["name"]
    suburb = SUBURB_FIX.get(row["suburb"], row["suburb"])
    state = "ACT" if suburb in ("Canberra", "Pialligo", "Acton", "Ainslie") else "NSW"
    if name in overrides:
        o = overrides[name]
        hit = (1, float(o["lat"]), float(o["lng"]), o.get("note", ""), "manual")
    elif name in REJECT:
        hit = None
    else:
        hit = photon(name, suburb) or nominatim(f"{name}, {suburb}, {state}, Australia", require_name=name)
    if not hit:
        print(f"MISS      {name} ({suburb})", flush=True)
        missing.append({"name": name, "suburb": suburb, "lat": "", "lng": "", "note": ""})
        continue
    _, lat, lng, matched, source = hit
    print(f"{source:9} {name} ({suburb}) -> {matched}", flush=True)
    out.append({**row, "suburb": suburb, "lat": round(lat, 6), "lng": round(lng, 6),
                "source": source, "matched_name": matched})

with open("hats_geocoded.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=out[0].keys())
    w.writeheader()
    w.writerows(out)
with open("needs_coords.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["name", "suburb", "lat", "lng", "note"])
    w.writeheader()
    w.writerows(missing)
print(f"\n{len(out)} geocoded, {len(missing)} missing -> needs_coords.csv")
