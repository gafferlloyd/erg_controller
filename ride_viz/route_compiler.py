#!/usr/bin/env python3
"""
route_compiler.py — parse a .fit or .gpx file into a ride_viz route JSON.

Usage:
    python route_compiler.py <file.fit|file.gpx>

Output:
    routes/<stem>.json
"""

import sys
import json
import math
import argparse
from pathlib import Path

import numpy as np
import requests

SEMICIRCLE_TO_DEG = 180.0 / (2 ** 31)
OSM_OVERPASS_URLS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
]
SCENERY_MIN_OFFSET_M =  8.0   # closer than this = on the road
SCENERY_MAX_OFFSET_M = 80.0
RESAMPLE_INTERVAL_M = 5.0
GRADE_SMOOTH_M = 25.0
LOOKAHEAD_STRIPS = 60


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def parse_fit(path: Path) -> list[dict]:
    import fitparse
    raw = []
    fit = fitparse.FitFile(str(path))
    for rec in fit.get_messages("record"):
        fields = {f.name: f.value for f in rec}
        lat = fields.get("position_lat")
        lon = fields.get("position_long")
        alt = fields.get("enhanced_altitude") or fields.get("altitude")
        dist = fields.get("distance")
        speed = fields.get("enhanced_speed") or fields.get("speed")
        ts = fields.get("timestamp")
        if lat is None or lon is None or alt is None or dist is None:
            continue
        raw.append({
            "lat": lat * SEMICIRCLE_TO_DEG,
            "lon": lon * SEMICIRCLE_TO_DEG,
            "ele_m": float(alt),
            "dist_m": float(dist),
            "speed_mps": float(speed) if speed else 0.0,
            "timestamp": ts.isoformat() if ts else None,
        })
    return raw


def parse_gpx(path: Path) -> list[dict]:
    from lxml import etree
    NS = {"gpx": "http://www.topografix.com/GPX/1/1"}
    tree = etree.parse(str(path))
    root = tree.getroot()
    # Handle namespaced or bare GPX
    ns = root.nsmap.get(None, "")
    prefix = f"{{{ns}}}" if ns else ""
    points = root.findall(f".//{prefix}trkpt")
    raw = []
    cum_dist = 0.0
    prev = None
    for pt in points:
        lat = float(pt.get("lat"))
        lon = float(pt.get("lon"))
        ele_el = pt.find(f"{prefix}ele")
        ele = float(ele_el.text) if ele_el is not None else 0.0
        time_el = pt.find(f"{prefix}time")
        ts = time_el.text if time_el is not None else None
        if prev:
            cum_dist += haversine_m(prev["lat"], prev["lon"], lat, lon)
        raw.append({
            "lat": lat, "lon": lon, "ele_m": ele,
            "dist_m": cum_dist, "speed_mps": 0.0, "timestamp": ts,
        })
        prev = raw[-1]
    return raw


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def bearing_deg(lat1, lon1, lat2, lon2) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlam = math.radians(lon2 - lon1)
    x = math.sin(dlam) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlam)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def rolling_mean(arr, window_samples):
    kernel = np.ones(window_samples) / window_samples
    half = window_samples // 2
    padded = np.pad(arr, (half, half), mode="edge")
    result = np.convolve(padded, kernel, mode="valid")
    return result[:len(arr)]


# ---------------------------------------------------------------------------
# Geometry computation
# ---------------------------------------------------------------------------

def _filter_gps_outliers(raw: list[dict]) -> list[dict]:
    """Remove records whose position is more than 5 km from the median lat/lon."""
    lats = np.array([p["lat"] for p in raw])
    lons = np.array([p["lon"] for p in raw])
    med_lat = float(np.median(lats))
    med_lon = float(np.median(lons))
    cos_lat = math.cos(math.radians(med_lat))
    dy = (lats - med_lat) * 111_320
    dx = (lons - med_lon) * cos_lat * 111_320
    dist_from_median = np.sqrt(dx ** 2 + dy ** 2)
    mask = dist_from_median < 100_000  # 100 km — catches pre-GPS-lock garbage only
    n_removed = len(raw) - int(mask.sum())
    if n_removed:
        print(f"  Removed {n_removed} GPS outlier(s) (>100 km from median position)")
    return [p for p, ok in zip(raw, mask) if ok]


def compute_geometry(raw: list[dict]) -> list[dict]:
    if len(raw) < 2:
        raise ValueError("Not enough GPS points")

    raw = _filter_gps_outliers(raw)

    dists = np.array([p["dist_m"] for p in raw])
    eles  = np.array([p["ele_m"]  for p in raw])
    lats  = np.array([p["lat"]    for p in raw])
    lons  = np.array([p["lon"]    for p in raw])
    speeds = np.array([p["speed_mps"] for p in raw])
    timestamps = [p["timestamp"] for p in raw]

    # Resample to fixed 5m intervals
    total = dists[-1]
    new_dists = np.arange(0, total, RESAMPLE_INTERVAL_M)
    new_eles   = np.interp(new_dists, dists, eles)
    new_lats   = np.interp(new_dists, dists, lats)
    new_lons   = np.interp(new_dists, dists, lons)
    new_speeds = np.interp(new_dists, dists, speeds)

    # Smooth positions over 25m to suppress GPS noise in ribbon geometry
    pos_smooth = max(1, int(25 / RESAMPLE_INTERVAL_M))  # = 5 samples
    new_lats = rolling_mean(new_lats, pos_smooth)
    new_lons = rolling_mean(new_lons, pos_smooth)

    # Interpolate timestamps linearly as seconds
    import datetime
    def ts_to_sec(ts):
        if ts is None:
            return None
        try:
            dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt.timestamp()
        except Exception:
            return None
    raw_secs = np.array([ts_to_sec(t) or 0.0 for t in timestamps])
    new_secs = np.interp(new_dists, dists, raw_secs)

    # Smooth grade
    window = max(1, int(GRADE_SMOOTH_M / RESAMPLE_INTERVAL_M))
    raw_grade = np.gradient(new_eles, RESAMPLE_INTERVAL_M) * 100.0
    grade = rolling_mean(raw_grade, window)

    # Heading: use 50m baseline (10 samples) to suppress GPS point-to-point noise
    HEADING_BASELINE = max(1, int(50 / RESAMPLE_INTERVAL_M))
    headings = np.zeros(len(new_dists))
    for i in range(len(new_dists) - HEADING_BASELINE):
        headings[i] = bearing_deg(
            new_lats[i], new_lons[i],
            new_lats[i + HEADING_BASELINE], new_lons[i + HEADING_BASELINE],
        )
    for i in range(len(new_dists) - HEADING_BASELINE, len(new_dists)):
        headings[i] = headings[len(new_dists) - HEADING_BASELINE - 1]

    # Smooth headings over 100m (wrap-safe: average sin/cos components)
    heading_window = max(1, int(100 / RESAMPLE_INTERVAL_M))
    h_rad = np.radians(headings)
    sin_h = rolling_mean(np.sin(h_rad), heading_window)
    cos_h = rolling_mean(np.cos(h_rad), heading_window)
    headings = np.degrees(np.arctan2(sin_h, cos_h)) % 360

    # Curvature (heading change per metre), smoothed over 100m
    raw_curve = np.diff(headings, prepend=headings[0])
    raw_curve = (raw_curve + 180) % 360 - 180
    curve = rolling_mean(raw_curve / RESAMPLE_INTERVAL_M, heading_window)

    origin_lat = float(new_lats[0])
    origin_lon = float(new_lons[0])
    base_ele   = float(new_eles[0])
    cos_lat    = math.cos(math.radians(origin_lat))

    waypoints = []
    for i in range(len(new_dists)):
        lx = (float(new_lons[i]) - origin_lon) * cos_lat * 111_320
        ly = (float(new_lats[i]) - origin_lat) * 111_320
        waypoints.append({
            "dist_m":      round(float(new_dists[i]), 1),
            "lat":         round(float(new_lats[i]), 6),
            "lon":         round(float(new_lons[i]), 6),
            "ele_m":       round(float(new_eles[i]), 1),
            "grade_pct":   round(float(np.clip(grade[i], -30, 30)), 2),
            "heading_deg": round(float(headings[i]), 1),
            "curve_dpm":   round(float(curve[i]), 6),
            "speed_mps":   round(float(new_speeds[i]), 2),
            "local_x":     round(lx, 1),
            "local_y":     round(ly, 1),
            "local_z":     round(float(new_eles[i]) - base_ele, 2),
        })

    # Attach origin metadata so renderer can convert on the fly if needed
    waypoints[0]["_origin_lat"] = origin_lat
    waypoints[0]["_origin_lon"] = origin_lon
    waypoints[0]["_base_ele"]   = base_ele

    return waypoints


# ---------------------------------------------------------------------------
# OSM scenery
# ---------------------------------------------------------------------------

def fetch_osm_scenery(bbox: dict) -> list[dict]:
    lat_min = bbox["lat_min"] - 0.001
    lat_max = bbox["lat_max"] + 0.001
    lon_min = bbox["lon_min"] - 0.001
    lon_max = bbox["lon_max"] + 0.001
    b = f"{lat_min},{lon_min},{lat_max},{lon_max}"

    # Buildings and individual trees use center-point; forest/wood ways need full
    # polygon geometry so every boundary node becomes a candidate tree position.
    query = f"""
[out:json][timeout:90];
(
  node["natural"="tree"]({b});
  way["building"]({b});
);
out center;
(
  way["natural"="wood"]({b});
  way["landuse"="forest"]({b});
);
out geom;
"""
    print("  Querying Overpass API for OSM scenery...", flush=True)
    resp = None
    for url in OSM_OVERPASS_URLS:
        try:
            resp = requests.post(url, data={"data": query}, timeout=120)
            if resp.ok:
                break
            print(f"  {url} returned {resp.status_code}, trying next...")
        except requests.RequestException as e:
            print(f"  {url} failed ({e}), trying next...")
    if resp is None or not resp.ok:
        raise RuntimeError("All Overpass API mirrors failed")
    elements = resp.json().get("elements", [])
    print(f"  Got {len(elements)} OSM features", flush=True)

    features = []
    for el in elements:
        tags = el.get("tags", {})
        nat = tags.get("natural", "")

        if el["type"] == "node" and nat == "tree":
            features.append({"lat": el["lat"], "lon": el["lon"], "type": "tree"})

        elif el["type"] == "way":
            if "building" in tags:
                c = el.get("center")
                if c:
                    features.append({"lat": c["lat"], "lon": c["lon"], "type": "house"})
            elif nat == "wood" or tags.get("landuse") == "forest":
                # Each polygon boundary node is a potential roadside tree position
                for node in el.get("geometry", []):
                    features.append({"lat": node["lat"], "lon": node["lon"], "type": "tree"})

    return features


def fetch_osm_roads(bbox: dict) -> list[list[tuple]]:
    lat_min = bbox["lat_min"] - 0.001
    lat_max = bbox["lat_max"] + 0.001
    lon_min = bbox["lon_min"] - 0.001
    lon_max = bbox["lon_max"] + 0.001
    b = f"{lat_min},{lon_min},{lat_max},{lon_max}"

    query = f"""
[out:json][timeout:90];
(
  way["highway"~"primary|secondary|tertiary|residential|unclassified|cycleway|track|path"]({b});
);
out geom;
"""
    print("  Querying Overpass API for OSM road centerlines...", flush=True)
    resp = None
    for url in OSM_OVERPASS_URLS:
        try:
            resp = requests.post(url, data={"data": query}, timeout=120)
            if resp.ok:
                break
            print(f"  {url} returned {resp.status_code}, trying next...")
        except requests.RequestException as e:
            print(f"  {url} failed ({e}), trying next...")
    if resp is None or not resp.ok:
        raise RuntimeError("All Overpass API mirrors failed for road data")

    elements = resp.json().get("elements", [])
    print(f"  Got {len(elements)} OSM road ways", flush=True)

    roads = []
    for el in elements:
        geom = el.get("geometry")
        if not geom or len(geom) < 2:
            continue
        roads.append([(pt["lat"], pt["lon"]) for pt in geom])
    return roads


def _nearest_point_on_segment(px, py, ax, ay, bx, by):
    """Return the closest point on segment AB to point P, in local metres."""
    dx, dy = bx - ax, by - ay
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq == 0:
        return ax, ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg_len_sq))
    return ax + t * dx, ay + t * dy


def snap_to_osm_roads(waypoints: list[dict], roads: list[list[tuple]], threshold_m: float = 8.0):
    """Vectorised snap using a 200m grid index to avoid O(n×m) cost."""
    if not roads:
        return

    origin_lat = waypoints[0]["lat"]
    origin_lon = waypoints[0]["lon"]
    cos_lat = math.cos(math.radians(origin_lat))

    # Pre-project all road nodes to local metres and collect segments as numpy arrays
    seg_ax, seg_ay, seg_bx, seg_by = [], [], [], []
    for road in roads:
        pts = [(  (lon - origin_lon) * cos_lat * 111_320,
                  (lat - origin_lat) * 111_320 )
               for lat, lon in road]
        for i in range(len(pts) - 1):
            seg_ax.append(pts[i][0]);   seg_ay.append(pts[i][1])
            seg_bx.append(pts[i+1][0]); seg_by.append(pts[i+1][1])

    if not seg_ax:
        print("  No road segments to snap to")
        return

    SAX = np.array(seg_ax); SAY = np.array(seg_ay)
    SBX = np.array(seg_bx); SBY = np.array(seg_by)
    SDX = SBX - SAX; SDY = SBY - SAY
    seg_len_sq = SDX * SDX + SDY * SDY
    seg_len_sq[seg_len_sq == 0] = 1.0   # degenerate segments

    # Spatial grid: 200m cells
    CELL = 200.0
    all_cx = np.concatenate([SAX, SBX])
    all_cy = np.concatenate([SAY, SBY])
    grid_origin_x = all_cx.min() - CELL
    grid_origin_y = all_cy.min() - CELL

    # For each segment, find which grid cells it touches (just use midpoint)
    mid_ix = ((SAX + SBX) / 2 - grid_origin_x) / CELL
    mid_iy = ((SAY + SBY) / 2 - grid_origin_y) / CELL
    from collections import defaultdict
    cell_to_segs = defaultdict(list)
    for si in range(len(SAX)):
        ci = (int(mid_ix[si]), int(mid_iy[si]))
        cell_to_segs[ci].append(si)
        # Also add to adjacent cells so segments near cell borders are found
        for ddx in (-1, 0, 1):
            for ddy in (-1, 0, 1):
                cell_to_segs[(ci[0]+ddx, ci[1]+ddy)].append(si)

    snapped = 0
    for w in waypoints:
        wx, wy = w["local_x"], w["local_y"]
        ci = (int((wx - grid_origin_x) / CELL), int((wy - grid_origin_y) / CELL))
        candidates = cell_to_segs.get(ci, [])
        if not candidates:
            continue

        ci_arr = np.array(candidates)
        ax = SAX[ci_arr]; ay = SAY[ci_arr]
        bx = SBX[ci_arr]; by = SBY[ci_arr]
        dx = SDX[ci_arr]; dy = SDY[ci_arr]
        lsq = seg_len_sq[ci_arr]

        t = np.clip(((wx - ax) * dx + (wy - ay) * dy) / lsq, 0.0, 1.0)
        sx = ax + t * dx; sy = ay + t * dy
        dists = np.sqrt((sx - wx) ** 2 + (sy - wy) ** 2)
        best = int(np.argmin(dists))
        if dists[best] < threshold_m:
            w["local_x"] = round(float(sx[best]), 1)
            w["local_y"] = round(float(sy[best]), 1)
            w["lon"] = round(origin_lon + float(sx[best]) / (cos_lat * 111_320), 6)
            w["lat"] = round(origin_lat + float(sy[best]) / 111_320, 6)
            snapped += 1

    print(f"  Snapped {snapped}/{len(waypoints)} waypoints to OSM road centerlines")


def fetch_osm_water(bbox: dict) -> list[list[tuple]]:
    lat_min = bbox["lat_min"] - 0.001
    lat_max = bbox["lat_max"] + 0.001
    lon_min = bbox["lon_min"] - 0.001
    lon_max = bbox["lon_max"] + 0.001
    b = f"{lat_min},{lon_min},{lat_max},{lon_max}"

    query = f"""
[out:json][timeout:60];
(
  way["natural"="water"]({b});
  way["landuse"="reservoir"]({b});
);
out geom;
"""
    print("  Querying Overpass API for water bodies...", flush=True)
    resp = None
    for url in OSM_OVERPASS_URLS:
        try:
            resp = requests.post(url, data={"data": query}, timeout=90)
            if resp.ok:
                break
            print(f"  {url} returned {resp.status_code}, trying next...")
        except requests.RequestException as e:
            print(f"  {url} failed ({e}), trying next...")
    if resp is None or not resp.ok:
        print("  Water fetch failed, continuing without water")
        return []
    polygons = []
    for el in resp.json().get("elements", []):
        geom = el.get("geometry", [])
        if len(geom) >= 3:
            polygons.append([(pt["lat"], pt["lon"]) for pt in geom])
    print(f"  Got {len(polygons)} water body polygons", flush=True)
    return polygons


def project_water(polygons: list[list[tuple]], waypoints: list[dict]) -> list[dict]:
    if not polygons:
        return []
    origin_lat = waypoints[0]["lat"]
    origin_lon = waypoints[0]["lon"]
    cos_lat = math.cos(math.radians(origin_lat))
    wlat = np.array([w["lat"] for w in waypoints])
    wlon = np.array([w["lon"] for w in waypoints])

    water_out = []
    for poly in polygons:
        # Keep polygon if any node is within 500m of the route
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
        water_out.append({"points": points})
    return water_out


def fetch_osm_rivers(bbox: dict) -> list[list[tuple]]:
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
    print("  Querying Overpass API for waterways...", flush=True)
    resp = None
    for url in OSM_OVERPASS_URLS:
        try:
            resp = requests.post(url, data={"data": query}, timeout=90)
            if resp.ok:
                break
            print(f"  {url} returned {resp.status_code}, trying next...")
        except requests.RequestException as e:
            print(f"  {url} failed ({e}), trying next...")
    if resp is None or not resp.ok:
        print("  Waterway fetch failed, continuing without rivers")
        return []
    polylines = []
    for el in resp.json().get("elements", []):
        geom = el.get("geometry", [])
        if len(geom) >= 2:
            polylines.append([(pt["lat"], pt["lon"]) for pt in geom])
    print(f"  Got {len(polylines)} waterway polylines", flush=True)
    return polylines


def project_rivers(polylines: list[list[tuple]], waypoints: list[dict]) -> list[dict]:
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


def project_scenery(features: list[dict], waypoints: list[dict]) -> list[dict]:
    wlat = np.array([w["lat"] for w in waypoints])
    wlon = np.array([w["lon"] for w in waypoints])
    wdist = np.array([w["dist_m"] for w in waypoints])
    wheading = np.array([w["heading_deg"] for w in waypoints])
    wlx = np.array([w["local_x"] for w in waypoints])
    wly = np.array([w["local_y"] for w in waypoints])
    wlz = np.array([w["local_z"] for w in waypoints])

    scenery = []
    for feat in features:
        flat, flon = feat["lat"], feat["lon"]

        dlat = wlat - flat
        dlon = (wlon - flon) * np.cos(math.radians(flat))
        dist_sq = dlat**2 + dlon**2
        idx = int(np.argmin(dist_sq))

        offset_m = haversine_m(flat, flon, wlat[idx], wlon[idx])
        if offset_m < SCENERY_MIN_OFFSET_M or offset_m > SCENERY_MAX_OFFSET_M:
            continue

        h_rad = math.radians(wheading[idx])
        hx, hy = math.sin(h_rad), math.cos(h_rad)
        fx = (flon - wlon[idx]) * math.cos(math.radians(wlat[idx])) * 111_320
        fy = (flat - wlat[idx]) * 111_320
        cross = hx * fy - hy * fx
        side = "right" if cross >= 0 else "left"

        # Local 3D position: offset perpendicular to heading from nearest waypoint
        perp_angle = math.radians(wheading[idx] + (90 if side == "right" else -90))
        lx = float(wlx[idx]) + math.cos(perp_angle) * offset_m
        ly = float(wly[idx]) + math.sin(perp_angle) * offset_m

        scenery.append({
            "dist_m":   round(float(wdist[idx]), 1),
            "side":     side,
            "type":     feat["type"],
            "offset_m": round(offset_m, 1),
            "local_x":  round(lx, 1),
            "local_y":  round(ly, 1),
            "local_z":  round(float(wlz[idx]), 2),
        })

    scenery.sort(key=lambda s: s["dist_m"])
    return scenery


def fetch_terrain_grid(bbox: dict, origin_lat: float, origin_lon: float,
                       base_ele: float, step_m: int) -> dict:
    import time
    cos_lat = math.cos(math.radians(origin_lat))

    # Grid extents in local metres, padded by one step on each side
    x_min = (bbox["lon_min"] - origin_lon) * cos_lat * 111_320 - step_m
    x_max = (bbox["lon_max"] - origin_lon) * cos_lat * 111_320 + step_m
    y_min = (bbox["lat_min"] - origin_lat) * 111_320 - step_m
    y_max = (bbox["lat_max"] - origin_lat) * 111_320 + step_m

    nx = max(2, int((x_max - x_min) / step_m) + 1)
    ny = max(2, int((y_max - y_min) / step_m) + 1)
    print(f"  Terrain grid: {nx}×{ny} = {nx*ny} points at {step_m}m resolution", flush=True)

    # Build ordered list of (lat, lon) for each grid point (row-major, S→N, W→E)
    grid_lats = [origin_lat + (y_min + iy * step_m) / 111_320 for iy in range(ny)]
    grid_lons = [origin_lon + (x_min + ix * step_m) / (cos_lat * 111_320) for ix in range(nx)]
    points = [(lat, lon) for lat in grid_lats for lon in grid_lons]

    # Batch fetch from opentopodata.org (100 pts/req, 1 s between requests)
    BATCH = 100
    ELEVATION_URLS = [
        "https://api.opentopodata.org/v1/eudem25m",
        "https://api.opentopodata.org/v1/srtm30m",
    ]
    heights = []
    n_batches = (len(points) + BATCH - 1) // BATCH
    print(f"  Fetching elevations ({n_batches} requests)...", flush=True)

    for bi in range(n_batches):
        batch = points[bi * BATCH: (bi + 1) * BATCH]
        payload = "|".join(f"{lat:.6f},{lon:.6f}" for lat, lon in batch)
        result = None
        for url in ELEVATION_URLS:
            try:
                resp = requests.get(url, params={"locations": payload}, timeout=30)
                if resp.ok:
                    data = resp.json()
                    if data.get("status") == "OK":
                        result = [r["elevation"] or 0.0 for r in data["results"]]
                        break
                    print(f"  {url} returned status {data.get('status')}, trying next...")
            except requests.RequestException as e:
                print(f"  {url} failed ({e}), trying next...")
        if result is None:
            raise RuntimeError("All elevation API endpoints failed")
        heights.extend(result)
        if bi < n_batches - 1:
            time.sleep(1.0)
        if (bi + 1) % 10 == 0:
            print(f"  ... {bi+1}/{n_batches} batches done", flush=True)

    # Convert absolute elevations to local_z (metres above base elevation)
    heights_local = [round(h - base_ele, 2) for h in heights]

    return {
        "nx": nx,
        "ny": ny,
        "origin_x": round(x_min, 1),
        "origin_y": round(y_min, 1),
        "step_m": step_m,
        "heights": heights_local,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Compile a .fit/.gpx file into a ride_viz route JSON")
    parser.add_argument("input", help="Path to .fit or .gpx file")
    parser.add_argument("--no-osm",        action="store_true", help="Skip all OSM and elevation fetches")
    parser.add_argument("--no-snap",       action="store_true", help="Skip OSM road snapping (keeps scenery)")
    parser.add_argument("--no-elevation",  action="store_true", help="Skip terrain elevation fetch")
    parser.add_argument("--elevation-step", type=int, default=200, metavar="M",
                        help="Terrain grid resolution in metres (default 200; use 500 for faster testing)")
    args = parser.parse_args()

    path = Path(args.input).expanduser().resolve()
    if not path.exists():
        sys.exit(f"File not found: {path}")

    print(f"Parsing {path.name}...")
    if path.suffix.lower() == ".fit":
        raw = parse_fit(path)
    elif path.suffix.lower() == ".gpx":
        raw = parse_gpx(path)
    else:
        sys.exit("Unsupported file type — use .fit or .gpx")

    print(f"  {len(raw)} raw GPS records")
    print("Computing geometry...")
    waypoints = compute_geometry(raw)
    print(f"  {len(waypoints)} waypoints at {RESAMPLE_INTERVAL_M}m resolution")

    bbox = {
        "lat_min": min(w["lat"] for w in waypoints),
        "lat_max": max(w["lat"] for w in waypoints),
        "lon_min": min(w["lon"] for w in waypoints),
        "lon_max": max(w["lon"] for w in waypoints),
    }

    scenery = []
    water   = []
    rivers  = []
    if not args.no_osm:
        if not args.no_snap:
            try:
                print("Fetching OSM road centerlines for snapping...")
                roads = fetch_osm_roads(bbox)
                print("Snapping waypoints to OSM roads...")
                snap_to_osm_roads(waypoints, roads)
            except Exception as e:
                print(f"  OSM road snap failed ({e}), continuing without snapping")

        try:
            features = fetch_osm_scenery(bbox)
            print("Projecting scenery onto route...")
            scenery = project_scenery(features, waypoints)
            trees  = sum(1 for s in scenery if s["type"] == "tree")
            houses = sum(1 for s in scenery if s["type"] == "house")
            print(f"  {trees} trees, {houses} houses placed along route")
        except Exception as e:
            print(f"  OSM scenery fetch failed ({e}), continuing without scenery")

        try:
            water_polys = fetch_osm_water(bbox)
            water = project_water(water_polys, waypoints)
            print(f"  {len(water)} water bodies near route")
        except Exception as e:
            print(f"  OSM water fetch failed ({e}), continuing without water")

        try:
            river_lines = fetch_osm_rivers(bbox)
            rivers = project_rivers(river_lines, waypoints)
            print(f"  {len(rivers)} waterway polylines near route")
        except Exception as e:
            print(f"  OSM waterway fetch failed ({e}), continuing without rivers")

    terrain_grid = None
    if not args.no_osm and not args.no_elevation:
        try:
            # Need base_ele — extract from first waypoint before it's popped
            base_ele_val = waypoints[0].get("_base_ele", waypoints[0]["ele_m"])
            print(f"Fetching terrain elevation grid ({args.elevation_step}m step)...")
            terrain_grid = fetch_terrain_grid(
                bbox, origin_lat=waypoints[0]["lat"], origin_lon=waypoints[0]["lon"],
                base_ele=base_ele_val, step_m=args.elevation_step,
            )
            print(f"  Terrain grid: {terrain_grid['nx']}×{terrain_grid['ny']} points")
        except Exception as e:
            print(f"  Terrain elevation fetch failed ({e}), continuing without terrain")

    out_dir = Path(__file__).parent / "routes"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / (path.stem.lower().replace(" ", "_") + ".json")

    w0 = waypoints[0]
    route = {
        "name": path.stem,
        "total_dist_m": waypoints[-1]["dist_m"],
        "origin_lat": w0.pop("_origin_lat"),
        "origin_lon": w0.pop("_origin_lon"),
        "base_ele":   w0.pop("_base_ele"),
        "bbox": bbox,
        "waypoints":    waypoints,
        "scenery":      scenery,
        "water":        water,
        "rivers":       rivers,
        "terrain_grid": terrain_grid,
    }

    with open(out_path, "w") as f:
        json.dump(route, f, separators=(",", ":"))

    size_kb = out_path.stat().st_size // 1024
    print(f"\nWrote {out_path} ({size_kb} KB)")
    print(f"  Total distance: {route['total_dist_m']/1000:.1f} km")
    grid_info = f", Terrain {terrain_grid['nx']}×{terrain_grid['ny']}" if terrain_grid else ""
    print(f"  Waypoints: {len(waypoints)}, Scenery: {len(scenery)}, Water: {len(water)}, Rivers: {len(rivers)}{grid_info}")


if __name__ == "__main__":
    main()
