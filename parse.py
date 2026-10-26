"""Parse the pasted Good Food Guide hats list into hats.csv."""
import csv
import re

HATS = {"One": 1, "Two": 2, "Three": 3}

# corrections to the guide's own listing
REGION_FIX = {"Mu Omakase": "Regional NSW and ACT"}  # listed under Sydney but it's in Canberra

rows = []
hats = region = None
for line in open("hats_raw.txt", encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    m = re.match(r"^(One|Two|Three) hats? — (.+)$", line)
    if m:
        hats, region = HATS[m[1]], m[2]
        continue
    is_new = line.endswith(" NEW")
    if is_new:
        line = line[: -len(" NEW")]
    name, suburb = line.rsplit(", ", 1)
    rows.append({"name": name, "suburb": suburb, "hats": hats, "region": REGION_FIX.get(name, region), "new": is_new})

with open("hats.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=rows[0].keys())
    w.writeheader()
    w.writerows(rows)
print(f"{len(rows)} restaurants")
