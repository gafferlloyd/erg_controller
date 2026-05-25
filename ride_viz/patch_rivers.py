#!/usr/bin/env python3
"""Patch a compiled route JSON to add OSM waterway river data.

Usage: python3 patch_rivers.py <route.json>
"""

import sys, json, math, requests
import numpy as np
from pathlib import Path

OSM_OVERPASS_URLS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
]


def fetch_osm_rivers(bbox):
    lat_min = bbox["lat_min"] - 0.001
    lat_max = bbox["lat_max"] + 0.001
    lon_min = bbox["lon_min"] - 0.001
    lon_max = bbox["lon_max"] + 0.001
    b = f"{lat_min},{lon_min},{lat_max},{lon_max}"
    query = f"""
[out:json][timeout:60];
(
  way["waterway"~"river|stream|canal"]({b});
);
out geom;
"""
    for url in OSM_OVERPASS_URLS:
        try:
            resp = requests.post(url, data={"data": query}, timeout=90)
            if resp.ok:
                break
            print(f"  {url} returned {resp.status_code}, trying next...")
        except requests.RequestException as e:
            print(f"  {url} failed ({e}), trying next...")
    else:
        print("All Overpass mirrors failed"); return []

    polylines = []
    for el in resp.json().get("elements", []):
        geom = el.get("geometry", [])
        if len(geom) >= 2:
            polylines.append([(pt["lat"], pt["lon"]) for pt in geom])
    print(f"  Got {len(polylines)} waterway polylines")
    return polylines


def project_rivers(polylines, waypoints):
    if not polylines:
        return []
    origin_lat = waypoints[0]["lat"]
    origin_lon = waypoints[0]["lon"]
    cos_lat = math.cos(math.radians(origin_lat))
    wlat = np.array([w["lat"] for w in waypoints])
    wlon = np.array([w["lon"] for w in waypoints])

    rivers_out = []
    for poly in polylines:
        close = False
        for lat, lon in poly:
            dlat = (wlat - lat) * 111_320
            dlon = (wlon - lon) * cos_lat * 111_320
            if float(np.sqrt(dlat**2 + dlon**2).min()) < 500:
                close = True
                break
        if not close:
            continue
        points = [
            {"lx": round((lon - origin_lon) * cos_lat * 111_320, 1),
             "ly": round((lat - origin_lat) * 111_320, 1)}
            for lat, lon in poly
        ]
        rivers_out.append({"points": points})
    return rivers_out


def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "routes/tegernsee_ahornboden_25_0_101_worldcover.json")
    print(f"Loading {path}...")
    with open(path) as f:
        route = json.load(f)

    if route.get("rivers"):
        print(f"Route already has {len(route['rivers'])} river polylines. Use --force to overwrite.")
        if "--force" not in sys.argv:
            return

    print("Fetching OSM waterways...")
    polylines = fetch_osm_rivers(route["bbox"])
    rivers = project_rivers(polylines, route["waypoints"])
    print(f"  {len(rivers)} polylines near route")

    route["rivers"] = rivers
    with open(path, "w") as f:
        json.dump(route, f, separators=(",", ":"))
    size_kb = path.stat().st_size // 1024
    print(f"Patched {path} ({size_kb} KB)")


if __name__ == "__main__":
    main()
