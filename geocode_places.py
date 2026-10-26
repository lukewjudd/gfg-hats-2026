"""Geocode hats.csv with Google Places Text Search (New) -> hats_geocoded.csv.

Reads PLACES_API_KEY from .env. Compares each result with the free OSM geocode
(cache from geocode.py, if present) and writes review.csv listing anything that
needs a human cross-check. overrides.csv (name,lat,lng[,note]) always wins.
"""
import csv
import difflib
import json
import math
import os
import re
import urllib.request

KEY = next(l.split("=", 1)[1].strip().strip('"\'') for l in open(".env") if l.startswith("PLACES_API_KEY="))
URL = "https://places.googleapis.com/v1/places:searchText"
FIELDS = "places.id,places.displayName,places.formattedAddress,places.location,places.primaryType,places.businessStatus,places.googleMapsUri"
SUBURB_FIX = {"CBD": "Sydney", "Rushcutters Bar": "Rushcutters Bay"}
ACT = {"Canberra", "Pialligo", "Acton", "Ainslie"}

cache = json.load(open("places_cache.json")) if os.path.exists("places_cache.json") else {}


def search(query):
    if query not in cache:
        body = json.dumps({
            "textQuery": query, "regionCode": "AU", "pageSize": 3,
            "locationBias": {"rectangle": {"low": {"latitude": -37.6, "longitude": 140.9},
                                           "high": {"latitude": -28.1, "longitude": 153.7}}},
        }).encode()
        req = urllib.request.Request(URL, data=body, headers={
            "Content-Type": "application/json", "X-Goog-Api-Key": KEY, "X-Goog-FieldMask": FIELDS})
        with urllib.request.urlopen(req, timeout=30) as r:
            cache[query] = json.load(r).get("places", [])
        json.dump(cache, open("places_cache.json", "w"), indent=1)
    return cache[query]


def norm(s):
    s = s.lower().replace("’", "'")
    s = re.sub(r"^the |restaurant|dining( room)?|& bar|[^a-z0-9 ]", " ", s)
    return " ".join(s.split())


def name_score(a, b):
    a, b = norm(a), norm(b)
    short, long_ = sorted((a, b), key=len)
    if short and re.search(rf"\b{re.escape(short)}\b", long_):
        return 1.0
    return round(difflib.SequenceMatcher(None, a, b).ratio(), 2)


def metres(a, b):
    dlat = math.radians(b[0] - a[0])
    dlng = math.radians(b[1] - a[1]) * math.cos(math.radians(a[0]))
    return round(6371000 * math.hypot(dlat, dlng))


osm = {}
if os.path.exists("hats_geocoded_osm.csv"):
    osm = {r["name"]: (float(r["lat"]), float(r["lng"])) for r in csv.DictReader(open("hats_geocoded_osm.csv", encoding="utf-8"))}

overrides = {}
if os.path.exists("overrides.csv"):
    overrides = {r["name"]: r for r in csv.DictReader(open("overrides.csv", encoding="utf-8")) if r.get("lat")}

out, review = [], []
for row in csv.DictReader(open("hats.csv", encoding="utf-8")):
    name = row["name"]
    suburb = SUBURB_FIX.get(row["suburb"], row["suburb"])
    state = "ACT" if suburb in ACT else "NSW"
    rec = {**row, "suburb": suburb}

    if name in overrides:
        o = overrides[name]
        out.append({**rec, "lat": o["lat"], "lng": o["lng"], "source": "manual",
                    "matched_name": name, "address": o.get("note", ""), "maps_url": ""})
        continue

    places = search(f"{name}, {suburb} {state}")
    if not places:
        review.append({"name": name, "suburb": suburb, "issue": "no Google result"})
        continue
    p = places[0]
    gname = p["displayName"]["text"]
    lat, lng = p["location"]["latitude"], p["location"]["longitude"]
    score = name_score(name, gname)
    issues = []
    if score < 0.75:
        issues.append(f"name mismatch ({score})")
    if suburb.lower() not in p["formattedAddress"].lower() and suburb != "Sydney":
        issues.append("suburb not in address")
    if p.get("businessStatus", "OPERATIONAL") != "OPERATIONAL":
        issues.append(p["businessStatus"].lower())
    if name in osm and (d := metres(osm[name], (lat, lng))) > 300:
        issues.append(f"OSM disagrees by {d}m")
    if issues:
        review.append({"name": name, "suburb": suburb, "issue": "; ".join(issues),
                       "google_name": gname, "google_address": p["formattedAddress"], "maps_url": p.get("googleMapsUri", "")})
    out.append({**rec, "lat": round(lat, 6), "lng": round(lng, 6), "source": "google",
                "matched_name": gname, "address": p["formattedAddress"], "maps_url": p.get("googleMapsUri", "")})

with open("hats_geocoded.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=out[0].keys())
    w.writeheader()
    w.writerows(out)
with open("review.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["name", "suburb", "issue", "google_name", "google_address", "maps_url"])
    w.writeheader()
    w.writerows(review)
print(f"{len(out)} geocoded, {len(review)} to review -> review.csv")
