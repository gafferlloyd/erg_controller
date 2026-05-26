#!/usr/bin/env python3
"""Patch a compiled route JSON to add OSM waterway and cliff data.

Usage: python3 patch_rivers.py <route.json> [--force]
"""

import sys, json, math, requests
import numpy as np
from pathlib import Path

OSM_OVERPASS_URLS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
]


def overpass_query(query):
    import subprocess, time
    # Try requests first
    for url in OSM_OVERPASS_URLS:
        try:
            resp = requests.post(url, data={"data": query}, timeout=60)
            if resp.ok:
                els = resp.json().get("elements", [])
                # Reject if only a count sentinel with 0 (Swiss server covers only CH)
                if els and els[0].get("type") == "count" and els[0].get("tags", {}).get("total") == "0":
                    continue
                return els
            print(f"  {url} returned {resp.status_code}, trying next...")
        except requests.RequestException as e:
            print(f"  {url} failed ({e}), trying next...")
        time.sleep(2)
    # Last resort: curl (works even when requests hits rate limits)
    print("  Trying curl fallback...")
    url = OSM_OVERPASS_URLS[0]
    try:
        result = subprocess.run(
            ["curl", "-s", "--max-time", "60", url, "--data-urlencode", f"data={query}"],
            capture_output=True, text=True, timeout=65,
        )
        if result.returncode == 0 and result.stdout.strip():
            els = json.loads(result.stdout).get("elements", [])
            if els:
                return els
    except Exception as e:
        print(f"  curl failed: {e}")
    print("  All Overpass methods failed")
    return None


def bbox_str(bbox):
    return (f"{bbox['lat_min']-0.001},{bbox['lon_min']-0.001},"
            f"{bbox['lat_max']+0.001},{bbox['lon_max']+0.001}")


def project_polylines(polylines, waypoints, proximity_m=500):
    if not polylines:
        return []
    origin_lat = waypoints[0]["lat"]
    origin_lon = waypoints[0]["lon"]
    cos_lat = math.cos(math.radians(origin_lat))
    wlat = np.array([w["lat"] for w in waypoints])
    wlon = np.array([w["lon"] for w in waypoints])
    out = []
    for poly in polylines:
        close = any(
            float(np.sqrt(((wlat - lat) * 111_320)**2 + ((wlon - lon) * cos_lat * 111_320)**2).min()) < proximity_m
            for lat, lon in poly
        )
        if not close:
            continue
        out.append({"points": [
            {"lx": round((lon - origin_lon) * cos_lat * 111_320, 1),
             "ly": round((lat - origin_lat) * 111_320, 1)}
            for lat, lon in poly
        ]})
    return out


def fetch_rivers(bbox):
    b = bbox_str(bbox)
    els = overpass_query(f'[out:json][timeout:60];(way["waterway"~"river|stream|canal"]({b}););out geom;')
    if els is None:
        return None
    polys = [[(pt["lat"], pt["lon"]) for pt in el.get("geometry", [])]
             for el in els if len(el.get("geometry", [])) >= 2]
    print(f"  Got {len(polys)} waterway polylines")
    return polys


def fetch_cliffs(bbox):
    b = bbox_str(bbox)
    els = overpass_query(f'[out:json][timeout:60];(way["natural"="cliff"]({b}););out geom;')
    if els is None:
        return None
    polys = [[(pt["lat"], pt["lon"]) for pt in el.get("geometry", [])]
             for el in els if len(el.get("geometry", [])) >= 2]
    print(f"  Got {len(polys)} cliff polylines")
    return polys


def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else
                "routes/tegernsee_ahornboden_25_0_101_worldcover.json")
    force = "--force" in sys.argv
    print(f"Loading {path}...")
    with open(path) as f:
        route = json.load(f)

    wps = route["waypoints"]
    bbox = route["bbox"]
    changed = False

    for key, fetcher, label in [
        ("rivers", fetch_rivers, "waterways"),
        ("cliffs", fetch_cliffs, "cliffs"),
    ]:
        if route.get(key) and not force:
            print(f"{key.capitalize()}: already {len(route[key])} polylines (use --force to refresh)")
            continue
        print(f"Fetching OSM {label}...")
        raw = fetcher(bbox)
        if raw is None:
            print(f"  API failed — keeping existing {key} data unchanged")
            continue
        projected = project_polylines(raw, wps)
        print(f"  {len(projected)} near route")
        if not projected and route.get(key):
            print(f"  API returned 0 results but route already has {len(route[key])} — keeping existing")
            continue
        route[key] = projected
        changed = True

    if changed:
        with open(path, "w") as f:
            json.dump(route, f, separators=(",", ":"))
        print(f"Patched {path} ({path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
