"""Inject hats_geocoded.csv into map_template.html -> index.html (self-contained)."""
import csv
import json

rows = [
    {"name": r["name"], "suburb": r["suburb"], "region": r["region"], "hats": int(r["hats"]),
     "new": r["new"] == "True", "lat": float(r["lat"]), "lng": float(r["lng"])}
    for r in csv.DictReader(open("hats_geocoded.csv", encoding="utf-8"))
]
html = open("map_template.html", encoding="utf-8").read()
html = html.replace("/*DATA*/[]", json.dumps(rows, ensure_ascii=False))
open("index.html", "w", encoding="utf-8").write(html)
print(f"index.html: {len(rows)} restaurants")
