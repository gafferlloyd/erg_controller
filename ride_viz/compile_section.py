#!/usr/bin/env python3
"""
compile_section.py — compile a scenery-rich section (or whole route) from a
source route JSON in routes/.  All remote data is cached in routes/cache/ so
recompiles skip already-fetched data.

Usage:
    python3 compile_section.py [options]

Options:
    --route FILE          Route JSON in routes/  (default: falkenberg_steinsee_22.json)
    --start-km FLOAT      Section start in km  (default: route start)
    --end-km FLOAT        Section end in km    (default: route end)
    --source {osm|terrain|worldcover}  Land cover source (default: osm)
    --elevation-step N    Terrain grid resolution in m (default: 100)
    --no-elevation        Skip terrain fetch entirely
    --lidar-dem NPZ       Blend LiDAR npz into wide Copernicus background grid
"""

import sys
import json
import math
import time
import hashlib
import argparse
from pathlib import Path

import numpy as np
import requests

OSM_OVERPASS_URLS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
]

ROAD_CLEAR_M         = 8.0
TREE_RENDER_M        = 150   # interior trees only placed for polygons within this distance of the road
TREE_OVERHEAD_SKIP_M = 40    # skip interior trees if polygon terrain height exceeds road by this much
CACHE_DIR       = Path(__file__).parent / "routes" / "cache"


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _bbox_hash(bbox, *extras):
    """Short reproducible hash of a bbox dict + optional extra strings."""
    s = (f"{bbox['lat_min']:.3f},{bbox['lat_max']:.3f},"
         f"{bbox['lon_min']:.3f},{bbox['lon_max']:.3f}")
    for e in extras:
        s += f",{e}"
    return hashlib.md5(s.encode()).hexdigest()[:10]


def _load_json_cache(path):
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


def _save_json_cache(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def classify_osm_landcover(tags):
    nat = tags.get("natural", "")
    lu  = tags.get("landuse", "")
    if nat == "wood" or lu == "forest":                  return "forest"
    if lu in ("meadow", "grass") or nat == "grassland":  return "meadow"
    if lu == "farmland":                                 return "farmland"
    if lu == "residential":                              return "residential"
    if lu == "orchard":                                  return "orchard"
    if lu == "vineyard":                                 return "vineyard"
    if nat in ("heath", "scrub"):                        return "heath"
    if nat == "water" or lu == "reservoir":              return "water"
    return None


WORLDCOVER_TO_TYPE = {
    10: "forest",
    20: "heath",
    30: "meadow",
    40: "farmland",
    50: "residential",
    60: None,
    70: None,
    80: "water",
    90: None,
    95: None,
    100: "meadow",
}
WORLDCOVER_URL = (
    "https://esa-worldcover.s3.amazonaws.com/v200/2021/map/"
    "ESA_WorldCover_10m_2021_v200_N{lat:02d}E{lon:03d}_Map.tif"
)


def point_in_polygon(x, y, poly):
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]; xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def terrain_height_local(lx, ly, tg):
    if tg is None:
        return 0.0
    ix = (lx - tg["origin_x"]) / tg.get("step_x_m", tg["step_m"])
    iy = (ly - tg["origin_y"]) / tg.get("step_y_m", tg["step_m"])
    ix0 = max(0, min(tg["nx"] - 2, int(ix)))
    iy0 = max(0, min(tg["ny"] - 2, int(iy)))
    tx, ty = ix - ix0, iy - iy0
    h = tg["heights"]; nx = tg["nx"]
    h00 = h[iy0*nx+ix0];   h10 = h[iy0*nx+ix0+1]
    h01 = h[(iy0+1)*nx+ix0]; h11 = h[(iy0+1)*nx+ix0+1]
    return round(h00*(1-tx)*(1-ty) + h10*tx*(1-ty) + h01*(1-tx)*ty + h11*tx*ty, 2)


def distribute_interior(lc_type, poly_pts, wp_x, wp_y, tg):
    """Place trees (forest) or crops (farmland) inside poly_pts."""
    if not poly_pts or lc_type not in ("forest", "farmland"):
        return []
    xs_arr = np.array([p[0] for p in poly_pts])
    ys_arr = np.array([p[1] for p in poly_pts])
    bx0, bx1 = float(xs_arr.min()), float(xs_arr.max())
    by0, by1 = float(ys_arr.min()), float(ys_arr.max())
    spacing = 6.0  if lc_type == "forest" else 15.0
    jitter  = 1.5  if lc_type == "forest" else 5.0
    seed = int(abs(poly_pts[0][0] * 7 + poly_pts[0][1] * 13)) % (2**31)
    rng  = np.random.default_rng(seed=seed)
    interior = []
    for gx in np.arange(bx0, bx1 + spacing, spacing):
        for gy in np.arange(by0, by1 + spacing, spacing):
            px = gx + (rng.uniform(-jitter, jitter) if jitter else 0.0)
            py = gy + (rng.uniform(-jitter, jitter) if jitter else 0.0)
            if not point_in_polygon(px, py, poly_pts):
                continue
            if wp_x.size > 0 and float(np.sqrt(((wp_x-px)**2+(wp_y-py)**2)).min()) < ROAD_CLEAR_M:
                continue
            interior.append({"lx": round(px,1), "ly": round(py,1),
                              "lz": terrain_height_local(px, py, tg),
                              "v": int(abs(px * 3.7 + py * 5.1)) % 4})
    return interior


def reproject_water_pts(full_route, section_origin_lat, section_origin_lon, section_cos_lat):
    """Convert full-route water polygon nodes to section-local coords."""
    full_orig_lat = full_route["origin_lat"]
    full_orig_lon = full_route["origin_lon"]
    full_cos_lat  = math.cos(math.radians(full_orig_lat))
    pts = []
    for body in full_route.get("water", []):
        for pt in body["points"]:
            lat = full_orig_lat + pt["ly"] / 111_320
            lon = full_orig_lon + pt["lx"] / (full_cos_lat * 111_320)
            lx  = (lon - section_origin_lon) * section_cos_lat * 111_320
            ly  = (lat - section_origin_lat) * 111_320
            pts.append((lx, ly))
    return pts


_ROAD_MASK_M = 13.0

def _road_mask_points(points, wp_x, wp_y):
    """Return only polygon boundary points that lie outside the road corridor."""
    m2 = _ROAD_MASK_M ** 2
    out = []
    for p in points:
        lx = p["lx"] if isinstance(p, dict) else p[0]
        ly = p["ly"] if isinstance(p, dict) else p[1]
        if float(((wp_x - lx) ** 2 + (wp_y - ly) ** 2).min()) > m2:
            out.append(p)
    return out


def _road_crosses_polygon(poly_pts, wp_x, wp_y):
    """Return True if any road waypoint falls inside the polygon OR any edge
    midpoint is within the road mask corridor."""
    if isinstance(poly_pts[0], dict):
        poly = [(p["lx"], p["ly"]) for p in poly_pts]
    else:
        poly = [(p[0], p[1]) for p in poly_pts]
    xs = np.array([p[0] for p in poly])
    ys = np.array([p[1] for p in poly])
    bx0, bx1 = float(xs.min()), float(xs.max())
    by0, by1 = float(ys.min()), float(ys.max())
    candidates = np.where(
        (wp_x >= bx0) & (wp_x <= bx1) & (wp_y >= by0) & (wp_y <= by1)
    )[0]
    for i in candidates:
        if point_in_polygon(float(wp_x[i]), float(wp_y[i]), poly):
            return True
    r2 = _ROAD_MASK_M ** 2
    n = len(poly)
    for k in range(n):
        mx = (poly[k][0] + poly[(k + 1) % n][0]) / 2
        my = (poly[k][1] + poly[(k + 1) % n][1]) / 2
        if float(((wp_x - mx) ** 2 + (wp_y - my) ** 2).min()) < r2:
            return True
    return False


def _centroid_on_road(pts_masked, wp_x, wp_y):
    """Return True if the centroid of the masked polygon is within the road corridor."""
    if isinstance(pts_masked[0], dict):
        xs = [p["lx"] for p in pts_masked]; ys = [p["ly"] for p in pts_masked]
    else:
        xs = [p[0] for p in pts_masked]; ys = [p[1] for p in pts_masked]
    cx = sum(xs) / len(xs); cy = sum(ys) / len(ys)
    return float(((wp_x - cx) ** 2 + (wp_y - cy) ** 2).min()) < _ROAD_MASK_M ** 2


# ---------------------------------------------------------------------------
# Source A — OSM Overpass land cover
# ---------------------------------------------------------------------------

def fetch_osm_landcover(bbox, cache_path=None):
    if cache_path is not None:
        cached = _load_json_cache(cache_path)
        if cached is not None:
            print(f"  Loaded {len(cached)} land cover elements from cache")
            return cached
    lat_min = bbox["lat_min"] - 0.001; lat_max = bbox["lat_max"] + 0.001
    lon_min = bbox["lon_min"] - 0.001; lon_max = bbox["lon_max"] + 0.001
    b = f"{lat_min},{lon_min},{lat_max},{lon_max}"
    query = f"""
[out:json][timeout:120];
(
  way["landuse"~"forest|meadow|farmland|residential|orchard|vineyard|allotments|grass"]({b});
  way["natural"~"wood|grassland|heath|scrub|water"]({b});
  way["landuse"="reservoir"]({b});
);
out geom;
"""
    print("  Querying Overpass API for land cover...", flush=True)
    resp = None
    for url in OSM_OVERPASS_URLS:
        try:
            resp = requests.post(url, data={"data": query}, timeout=150, headers={"Accept": "*/*"})
            if resp.ok:
                break
            print(f"  {url} returned {resp.status_code}, trying next...")
        except requests.RequestException as e:
            print(f"  {url} failed ({e}), trying next...")
    if resp is None or not resp.ok:
        print("  All Overpass mirrors failed — returning empty land cover")
        return []
    elements = resp.json().get("elements", [])
    print(f"  Got {len(elements)} land cover ways", flush=True)
    if cache_path is not None and elements:
        _save_json_cache(cache_path, elements)
    return elements


def fetch_osm_water_areas(bbox, cache_path=None):
    """Fetch natural=water and waterway=riverbank area polygons from Overpass."""
    if cache_path is not None:
        cached = _load_json_cache(cache_path)
        if cached is not None:
            print(f"  Loaded {len(cached)} water elements from cache")
            return cached
    b = (f"{bbox['lat_min']-0.001},{bbox['lon_min']-0.001},"
         f"{bbox['lat_max']+0.001},{bbox['lon_max']+0.001}")
    query = f"""
[out:json][timeout:60];
(
  way["natural"="water"]({b});
  way["waterway"="riverbank"]({b});
  relation["natural"="water"]({b});
);
out geom;
"""
    for url in OSM_OVERPASS_URLS:
        try:
            resp = requests.post(url, data={"data": query}, timeout=90,
                                 headers={"Accept": "*/*"})
            if resp.ok:
                elems = resp.json().get("elements", [])
                if cache_path and elems:
                    _save_json_cache(cache_path, elems)
                print(f"  OSM water: {len(elems)} elements")
                return elems
            print(f"  {url} returned {resp.status_code}")
        except Exception as e:
            print(f"  {url} failed ({e})")
    return []


def build_osm_landcover(elements, origin_lat, origin_lon, cos_lat, wp_x, wp_y, terrain_grid, wp_z=None):
    land_cover = []
    n_trees = n_crops = 0
    for el in elements:
        if el["type"] != "way":
            continue
        tags = el.get("tags", {})
        lc_type = classify_osm_landcover(tags)
        if lc_type is None:
            continue
        geom = el.get("geometry", [])
        if len(geom) < 3:
            continue
        poly_local = [(round((pt["lon"]-origin_lon)*cos_lat*111_320, 1),
                       round((pt["lat"]-origin_lat)*111_320, 1)) for pt in geom]
        if wp_x.size > 0:
            close = any(float(np.sqrt(((wp_x-lx)**2+(wp_y-ly)**2)).min()) < 800
                        for lx, ly in poly_local)
            if not close:
                continue
        if _road_crosses_polygon(poly_local, wp_x, wp_y):
            continue
        cx_lc = sum(p[0] for p in poly_local) / len(poly_local)
        cy_lc = sum(p[1] for p in poly_local) / len(poly_local)
        near = (wp_x.size == 0 or
                float(((wp_x - cx_lc)**2 + (wp_y - cy_lc)**2).min()) <= TREE_RENDER_M**2)
        if near and wp_z is not None and terrain_grid is not None:
            th = terrain_height_local(cx_lc, cy_lc, terrain_grid)
            rz = float(wp_z[int(np.argmin((wp_x - cx_lc)**2 + (wp_y - cy_lc)**2))])
            if th - rz > TREE_OVERHEAD_SKIP_M:
                near = False
        interior = distribute_interior(lc_type, poly_local, wp_x, wp_y, terrain_grid) if near else []
        n_trees += len(interior) if lc_type == "forest" else 0
        n_crops += len(interior) if lc_type == "farmland" else 0
        pts_masked = _road_mask_points(
            [{"lx": lx, "ly": ly} for lx, ly in poly_local], wp_x, wp_y)
        if len(pts_masked) < 3:
            continue
        if _centroid_on_road(pts_masked, wp_x, wp_y):
            continue
        land_cover.append({"type": lc_type, "points": pts_masked, "interior": interior})
    type_counts = {}
    for lc in land_cover:
        type_counts[lc["type"]] = type_counts.get(lc["type"], 0) + 1
    print(f"  {len(land_cover)} OSM polygons: {type_counts}")
    print(f"  {n_trees} interior trees, {n_crops} interior crops")
    return land_cover


# ---------------------------------------------------------------------------
# Source B — Terrain-derived
# ---------------------------------------------------------------------------

def build_terrain_landcover(terrain_grid, wp_x, wp_y, water_pts, wp_z=None):
    """Classify terrain_grid cells by elevation + slope gradient."""
    if terrain_grid is None:
        print("  No terrain grid — terrain source requires elevation data")
        return []

    tg = terrain_grid
    nx, ny, step = tg["nx"], tg["ny"], tg["step_m"]
    h = np.array(tg["heights"], dtype=float).reshape(ny, nx)

    gx = np.zeros_like(h); gy = np.zeros_like(h)
    gx[:, 1:-1] = (h[:, 2:] - h[:, :-2]) / (2 * step)
    gx[:,  0]   = (h[:,  1] - h[:,  0])   / step
    gx[:, -1]   = (h[:, -1] - h[:, -2])   / step
    gy[1:-1, :] = (h[2:, :] - h[:-2, :]) / (2 * step)
    gy[0,   :]  = (h[1,  :] - h[0,  :])  / step
    gy[-1,  :]  = (h[-1, :] - h[-2, :])  / step
    gradient = np.sqrt(gx**2 + gy**2)

    if water_pts:
        wlx = np.array([p[0] for p in water_pts])
        wly = np.array([p[1] for p in water_pts])
    else:
        wlx = wly = np.array([])

    land_cover = []
    n_trees = n_crops = n_cells = 0

    for iy in range(ny):
        for ix in range(nx):
            lx = tg["origin_x"] + ix * step
            ly = tg["origin_y"] + iy * step
            elev = float(h[iy, ix])
            grad = float(gradient[iy, ix])

            if wlx.size > 0 and float(np.sqrt(((wlx-lx)**2+(wly-ly)**2)).min()) < 60:
                continue

            if grad >= 0.08:
                lc_type = "forest"
            elif elev < -5 or (grad < 0.03 and elev < 20):
                lc_type = "farmland"
            else:
                lc_type = "meadow"

            half = step / 2.0
            poly_pts = [(lx-half, ly-half), (lx+half, ly-half),
                        (lx+half, ly+half), (lx-half, ly+half)]

            if _road_crosses_polygon(poly_pts, wp_x, wp_y):
                continue
            near = (wp_x.size == 0 or
                    float(((wp_x - lx)**2 + (wp_y - ly)**2).min()) <= TREE_RENDER_M**2)
            if near and wp_z is not None:
                rz = float(wp_z[int(np.argmin((wp_x - lx)**2 + (wp_y - ly)**2))])
                if h[iy, ix] - rz > TREE_OVERHEAD_SKIP_M:
                    near = False
            interior = distribute_interior(lc_type, poly_pts, wp_x, wp_y, terrain_grid) if near else []
            n_trees += len(interior) if lc_type == "forest" else 0
            n_crops += len(interior) if lc_type == "farmland" else 0

            pts_masked = _road_mask_points(
                [{"lx": x, "ly": y} for x, y in poly_pts], wp_x, wp_y)
            if len(pts_masked) < 3:
                continue
            if _centroid_on_road(pts_masked, wp_x, wp_y):
                continue
            land_cover.append({"type": lc_type, "points": pts_masked, "interior": interior})
            n_cells += 1

    type_counts = {}
    for lc in land_cover:
        type_counts[lc["type"]] = type_counts.get(lc["type"], 0) + 1
    print(f"  {n_cells} terrain cells classified: {type_counts}")
    print(f"  {n_trees} interior trees, {n_crops} interior crops")
    return land_cover


# ---------------------------------------------------------------------------
# Source C — ESA WorldCover 2021
# ---------------------------------------------------------------------------

def fetch_worldcover_landcover(bbox, origin_lat, origin_lon, cos_lat, wp_x, wp_y, terrain_grid, wp_z=None):
    """Read ESA WorldCover 2021 (10m) from AWS S3 COG via range-request.
    Requires: pip install rasterio"""
    try:
        import rasterio
        from rasterio.windows import from_bounds
    except ImportError:
        raise RuntimeError("rasterio required for --source worldcover: pip install rasterio")

    tile_lat = (int(bbox["lat_min"]) // 3) * 3
    tile_lon = (int(bbox["lon_min"]) // 3) * 3
    tile_url = "/vsicurl/" + WORLDCOVER_URL.format(lat=tile_lat, lon=tile_lon)

    print(f"  Reading ESA WorldCover tile N{tile_lat:02d}E{tile_lon:03d}...", flush=True)
    with rasterio.open(tile_url) as ds:
        win = from_bounds(bbox["lon_min"], bbox["lat_min"],
                          bbox["lon_max"], bbox["lat_max"],
                          transform=ds.transform)
        data = ds.read(1, window=win).astype(int)
        win_tf = ds.window_transform(win)

    unique = np.unique(data[data > 0])
    print(f"  Raster {data.shape[1]}×{data.shape[0]}, classes: {unique}", flush=True)

    STEP = 10
    land_cover = []
    n_trees = n_crops = 0
    px_w_m = abs(win_tf.a) * STEP * cos_lat * 111_320
    px_h_m = abs(win_tf.e) * STEP * 111_320

    for row in range(0, data.shape[0], STEP):
        for col in range(0, data.shape[1], STEP):
            cls = int(data[row, col])
            lc_type = WORLDCOVER_TO_TYPE.get(cls)
            if lc_type is None:
                continue

            lon = win_tf.c + (col + STEP / 2) * win_tf.a
            lat = win_tf.f + (row + STEP / 2) * win_tf.e
            lx  = (lon - origin_lon) * cos_lat * 111_320
            ly  = (lat - origin_lat) * 111_320

            half_w, half_h = px_w_m / 2, px_h_m / 2
            poly_pts = [(lx-half_w, ly-half_h), (lx+half_w, ly-half_h),
                        (lx+half_w, ly+half_h), (lx-half_w, ly+half_h)]

            if _road_crosses_polygon(poly_pts, wp_x, wp_y):
                continue
            near = (wp_x.size == 0 or
                    float(((wp_x - lx)**2 + (wp_y - ly)**2).min()) <= TREE_RENDER_M**2)
            if near and wp_z is not None and terrain_grid is not None:
                th = terrain_height_local(lx, ly, terrain_grid)
                rz = float(wp_z[int(np.argmin((wp_x - lx)**2 + (wp_y - ly)**2))])
                if th - rz > TREE_OVERHEAD_SKIP_M:
                    near = False
            interior = distribute_interior(lc_type, poly_pts, wp_x, wp_y, terrain_grid) if near else []
            n_trees += len(interior) if lc_type == "forest" else 0
            n_crops += len(interior) if lc_type == "farmland" else 0

            pts_masked = _road_mask_points(
                [{"lx": x, "ly": y} for x, y in poly_pts], wp_x, wp_y)
            if len(pts_masked) < 3:
                continue
            if _centroid_on_road(pts_masked, wp_x, wp_y):
                continue
            land_cover.append({"type": lc_type, "points": pts_masked, "interior": interior})

    type_counts = {}
    for lc in land_cover:
        type_counts[lc["type"]] = type_counts.get(lc["type"], 0) + 1
    print(f"  {len(land_cover)} WorldCover cells: {type_counts}")
    print(f"  {n_trees} interior trees, {n_crops} interior crops")
    return land_cover


# ---------------------------------------------------------------------------
# Terrain elevation fetch (shared)
# ---------------------------------------------------------------------------

def fetch_terrain_grid(bbox, origin_lat, origin_lon, base_ele, step_m):
    cos_lat = math.cos(math.radians(origin_lat))
    x_min = (bbox["lon_min"] - origin_lon) * cos_lat * 111_320 - step_m
    x_max = (bbox["lon_max"] - origin_lon) * cos_lat * 111_320 + step_m
    y_min = (bbox["lat_min"] - origin_lat) * 111_320 - step_m
    y_max = (bbox["lat_max"] - origin_lat) * 111_320 + step_m
    nx = max(2, int((x_max - x_min) / step_m) + 1)
    ny = max(2, int((y_max - y_min) / step_m) + 1)
    print(f"  Terrain grid: {nx}×{ny} = {nx*ny} points at {step_m}m resolution", flush=True)

    grid_lats = [origin_lat + (y_min + iy * step_m) / 111_320 for iy in range(ny)]
    grid_lons = [origin_lon + (x_min + ix * step_m) / (cos_lat * 111_320) for ix in range(nx)]
    points = [(lat, lon) for lat in grid_lats for lon in grid_lons]

    BATCH = 100
    ELEVATION_URLS = [
        "https://api.opentopodata.org/v1/eudem25m",
        "https://api.opentopodata.org/v1/srtm30m",
    ]
    heights = []; n_batches = (len(points) + BATCH - 1) // BATCH
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
            except requests.RequestException as e:
                print(f"  {url} failed ({e}), trying next...")
        if result is None:
            raise RuntimeError("All elevation API endpoints failed")
        heights.extend(result)
        if bi < n_batches - 1:
            time.sleep(1.0)
        if (bi + 1) % 10 == 0:
            print(f"  ... {bi+1}/{n_batches} batches done", flush=True)

    return {
        "nx": nx, "ny": ny,
        "origin_x": round(x_min, 1), "origin_y": round(y_min, 1),
        "step_m": step_m,
        "heights": [round(h - base_ele, 2) for h in heights],
    }


TERRAIN_BUFFER_DEG       = 0.009  # ~1 km (use cached terrain; widen to 0.027 once APIs back up)
VISTA_TERRAIN_BUFFER_DEG = 0.072  # ~8 km — captures distant mountain ranges
VISTA_TERRAIN_STEP_M     = 500    # coarse resolution for distant ridges only


def blend_lidar_into_copernicus(lidar, cop):
    """Replace Copernicus cells with bilinearly-interpolated LiDAR values where
    LiDAR coverage exists."""
    h = list(cop["heights"])
    sx_c = cop.get("step_x_m", cop["step_m"])
    sy_c = cop.get("step_y_m", cop["step_m"])
    sx_l = lidar.get("step_x_m", lidar["step_m"])
    sy_l = lidar.get("step_y_m", lidar["step_m"])
    nx_l = lidar["nx"]
    for iy in range(cop["ny"]):
        for ix in range(cop["nx"]):
            cx = cop["origin_x"] + ix * sx_c
            cy = cop["origin_y"] + iy * sy_c
            fx = (cx - lidar["origin_x"]) / sx_l
            fy = (cy - lidar["origin_y"]) / sy_l
            if 0 <= fx < lidar["nx"] - 1 and 0 <= fy < lidar["ny"] - 1:
                x0, y0 = int(fx), int(fy)
                dx, dy = fx - x0, fy - y0
                lh = (lidar["heights"][y0 * nx_l + x0]           * (1 - dx) * (1 - dy) +
                      lidar["heights"][y0 * nx_l + x0 + 1]       * dx       * (1 - dy) +
                      lidar["heights"][(y0 + 1) * nx_l + x0]     * (1 - dx) * dy       +
                      lidar["heights"][(y0 + 1) * nx_l + x0 + 1] * dx       * dy)
                h[iy * cop["nx"] + ix] = round(lh, 2)
    return {**cop, "heights": h}


# ---------------------------------------------------------------------------
# Minimap tile stitching
# ---------------------------------------------------------------------------

def stitch_minimap(bbox, waypoints, origin_lat, origin_lon, cos_lat, out_dir, name):
    """Fetch OSM tiles at zoom 13 covering bbox+1km, stitch to a single PNG
    with route overlay.  Tiles are cached in CACHE_DIR/tiles/ to avoid re-downloads."""
    import io
    from PIL import Image, ImageDraw
    ZOOM = 13
    BUF  = TERRAIN_BUFFER_DEG

    lat0 = bbox["lat_min"] - BUF
    lat1 = bbox["lat_max"] + BUF
    lon0 = bbox["lon_min"] - BUF / cos_lat
    lon1 = bbox["lon_max"] + BUF / cos_lat

    def ll_to_tile(lat, lon):
        n = 2 ** ZOOM
        tx = int((lon + 180) / 360 * n)
        lr = math.radians(lat)
        ty = int((1 - math.log(math.tan(lr) + 1 / math.cos(lr)) / math.pi) / 2 * n)
        return tx, ty

    def tile_to_ll(tx, ty):
        n = 2 ** ZOOM
        lon = tx / n * 360 - 180
        lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * ty / n))))
        return lat, lon

    tx0, ty1 = ll_to_tile(lat0, lon0)
    tx1, ty0 = ll_to_tile(lat1, lon1)
    nx_t = tx1 - tx0 + 1
    ny_t = ty1 - ty0 + 1
    print(f"  Minimap: stitching {nx_t}×{ny_t} tiles at zoom {ZOOM}...", flush=True)

    tile_cache = CACHE_DIR / "tiles"
    tile_cache.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": "RideViz/1.0 (gafferlloyd@gmail.com route visualiser)"}

    canvas = Image.new("RGB", (nx_t * 256, ny_t * 256))
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            tile_file = tile_cache / f"{ZOOM}_{tx}_{ty}.png"
            try:
                if tile_file.exists():
                    tile_img = Image.open(tile_file).convert("RGB")
                else:
                    url = f"https://tile.openstreetmap.org/{ZOOM}/{tx}/{ty}.png"
                    r = requests.get(url, headers=headers, timeout=15)
                    if r.ok:
                        tile_file.write_bytes(r.content)
                        tile_img = Image.open(io.BytesIO(r.content)).convert("RGB")
                    else:
                        print(f"    tile {tx},{ty} → {r.status_code}", flush=True)
                        continue
                canvas.paste(tile_img, ((tx - tx0) * 256, (ty - ty0) * 256))
            except Exception as e:
                print(f"    tile {tx},{ty} failed: {e}", flush=True)

    orig_lat, orig_lon = tile_to_ll(tx0, ty0)
    _, next_lon = tile_to_ll(tx0 + 1, ty0)
    next_lat, _ = tile_to_ll(tx0, ty0 + 1)
    deg_per_px_lon = (next_lon - orig_lon) / 256
    deg_per_px_lat = (next_lat - orig_lat) / 256

    def ll_to_px(lat, lon):
        return ((lon - orig_lon) / deg_per_px_lon,
                (lat - orig_lat) / deg_per_px_lat)

    draw = ImageDraw.Draw(canvas)
    pts_px = [ll_to_px(w["lat"], w["lon"]) for w in waypoints[::5]]
    draw.line(pts_px, fill=(238, 68, 34), width=3)

    out_path = Path(out_dir) / f"{name}_minimap.png"
    canvas.save(str(out_path), optimize=True)
    print(f"  Minimap saved: {out_path.name} ({canvas.width}×{canvas.height} px)", flush=True)

    return {
        "url": f"{name}_minimap.png",
        "origin_lat": orig_lat,
        "origin_lon": orig_lon,
        "deg_per_px_lat": deg_per_px_lat,
        "deg_per_px_lon": deg_per_px_lon,
        "px_w": canvas.width,
        "px_h": canvas.height,
    }


# ---------------------------------------------------------------------------
# OSM buildings (Overpass + OSM XML fallback, 100m road filter, cached)
# ---------------------------------------------------------------------------

def fetch_osm_buildings(bbox, origin_lat, origin_lon, cos_lat, wp_x, wp_y, terrain_grid,
                        cache_path=None):
    """Fetch OSM building centres within 100m of route.
    Tries Overpass; falls back to OSM XML API; reads/writes cache_path."""
    lat_min = bbox["lat_min"] - 0.002; lat_max = bbox["lat_max"] + 0.002
    lon_min = bbox["lon_min"] - 0.002; lon_max = bbox["lon_max"] + 0.002

    elements = None

    # 1. Cache
    if cache_path is not None:
        cached = _load_json_cache(cache_path)
        if cached is not None and len(cached) > 0:
            print(f"  Loaded {len(cached)} cached elements", flush=True)
            elements = cached

    # 2. Overpass
    if elements is None:
        b = f"{lat_min},{lon_min},{lat_max},{lon_max}"
        query = f"""
[out:json][timeout:90];
(
  way["building"]({b});
  node["amenity"="place_of_worship"]["religion"="christian"]({b});
  way["amenity"="place_of_worship"]["religion"="christian"]({b});
);
out center;
"""
        print("  Querying Overpass API for buildings...", flush=True)
        for url in OSM_OVERPASS_URLS:
            try:
                resp = requests.post(url, data={"data": query}, timeout=120,
                                     headers={"Accept": "*/*"})
                if resp.ok:
                    got = resp.json().get("elements", [])
                    if got:
                        elements = got
                        break
                    else:
                        print(f"  {url} returned empty result, trying next...")
                else:
                    print(f"  {url} returned {resp.status_code}, trying next...")
            except requests.RequestException as e:
                print(f"  {url} failed ({e}), trying next...")

    # 3. OSM XML API fallback
    if elements is None:
        print("  Overpass unavailable — trying OSM XML API...", flush=True)
        xml_url = (f"https://api.openstreetmap.org/api/0.6/map"
                   f"?bbox={lon_min},{lat_min},{lon_max},{lat_max}")
        try:
            import xml.etree.ElementTree as ET
            resp = requests.get(xml_url, timeout=120,
                                headers={"User-Agent": "RideViz/1.0"})
            if resp.ok:
                root = ET.fromstring(resp.content)
                nodes = {nd.get("id"): (float(nd.get("lat")), float(nd.get("lon")))
                         for nd in root.findall("node")}
                elements = []
                for way in root.findall("way"):
                    tags = {t.get("k"): t.get("v") for t in way.findall("tag")}
                    building = tags.get("building", "")
                    amenity  = tags.get("amenity", "")
                    religion = tags.get("religion", "")
                    if not (building and building != "no") and not (
                            amenity == "place_of_worship" and religion == "christian"):
                        continue
                    nd_refs = [nd.get("ref") for nd in way.findall("nd")]
                    coords  = [nodes[r] for r in nd_refs if r in nodes]
                    if not coords:
                        continue
                    clat = sum(c[0] for c in coords) / len(coords)
                    clon = sum(c[1] for c in coords) / len(coords)
                    elements.append({"type": "way", "tags": tags,
                                     "center": {"lat": clat, "lon": clon}})
                print(f"  OSM XML API: {len(elements)} building ways", flush=True)
            else:
                print(f"  OSM XML API returned {resp.status_code}")
        except Exception as e:
            print(f"  OSM XML API failed ({e})")

    if elements is None:
        print("  Cache is empty and all sources failed — no buildings")
        return []

    if cache_path is not None and elements:
        _save_json_cache(cache_path, elements)

    # Process raw elements into local-coord result
    ROAD_NEAR_M = 100   # only include buildings within this distance of the route
    result = []
    for el in elements:
        tags = el.get("tags", {})
        if el["type"] == "node":
            lat, lon = el["lat"], el["lon"]
        elif el["type"] == "way":
            c = el.get("center")
            if not c:
                continue
            lat, lon = c["lat"], c["lon"]
        else:
            continue
        lx = (lon - origin_lon) * cos_lat * 111_320
        ly = (lat - origin_lat) * 111_320
        if wp_x.size > 0 and float(np.sqrt(((wp_x - lx)**2 + (wp_y - ly)**2)).min()) > ROAD_NEAR_M:
            continue
        building = tags.get("building", "")
        amenity  = tags.get("amenity", "")
        religion = tags.get("religion", "")
        if building == "church" or (amenity == "place_of_worship" and religion == "christian"):
            obj_type = "church"
        elif building and building != "no":
            obj_type = "house"
        else:
            continue
        # Use minimum terrain height in 20m radius to find ground level
        # (Copernicus DSM can sample building rooftops)
        lz = terrain_height_local(lx, ly, terrain_grid)
        for dlx in range(-10, 15, 5):
            for dly in range(-10, 15, 5):
                lz = min(lz, terrain_height_local(lx + dlx, ly + dly, terrain_grid))
        result.append({
            "type":    obj_type,
            "local_x": round(lx, 1),
            "local_y": round(ly, 1),
            "local_z": round(lz, 2),
        })
    n_houses  = sum(1 for r in result if r["type"] == "house")
    n_churches = sum(1 for r in result if r["type"] == "church")
    print(f"  {n_houses} buildings, {n_churches} churches found")
    return result


# ---------------------------------------------------------------------------
# Road-terrain conformance
# ---------------------------------------------------------------------------

def conform_terrain_to_road(terrain_grid, wp_x, wp_y, wp_z):
    """Correct EUDEM canopy-height bias near the road surface."""
    CANOPY_H = 6.0
    tg = terrain_grid
    nx, ny, step = tg["nx"], tg["ny"], tg["step_m"]
    sigma = step * 0.25
    threshold = 3.0 * sigma
    h = list(tg["heights"])
    ox, oy = tg["origin_x"], tg["origin_y"]

    for iy in range(ny):
        for ix in range(nx):
            lx = ox + ix * step
            ly = oy + iy * step
            dists_sq = (wp_x - lx) ** 2 + (wp_y - ly) ** 2
            j = int(np.argmin(dists_sq))
            d = math.sqrt(float(dists_sq[j]))
            if d > threshold:
                continue
            road_z = float(wp_z[j])
            idx = iy * nx + ix
            excess = h[idx] - road_z
            if excess <= 0 or excess > CANOPY_H:
                continue
            w = math.exp(-d ** 2 / (2 * sigma ** 2))
            h_new = h[idx] * (1 - w) + road_z * w
            h[idx] = round(min(h_new, road_z), 2)

    tg["heights"] = h
    return tg


# ---------------------------------------------------------------------------
# Road junction detection
# ---------------------------------------------------------------------------

JUNCTION_SNAP_M   = 18.0
JUNCTION_MIN_ANGLE = 25
JUNCTION_MAX_ANGLE = 155

def fetch_osm_roads_section(bbox, cache_path=None):
    """Fetch OSM road polylines for the section bbox."""
    if cache_path is not None:
        cached = _load_json_cache(cache_path)
        if cached is not None:
            print(f"  Loaded {len(cached)} road ways from cache")
            return cached
    lat_min = bbox["lat_min"] - 0.001; lat_max = bbox["lat_max"] + 0.001
    lon_min = bbox["lon_min"] - 0.001; lon_max = bbox["lon_max"] + 0.001
    b = f"{lat_min},{lon_min},{lat_max},{lon_max}"
    query = f"""
[out:json][timeout:90];
(
  way["highway"~"primary|secondary|tertiary|residential|unclassified|cycleway|track|path"]({b});
);
out geom;
"""
    print("  Querying Overpass API for road network...", flush=True)
    resp = None
    for url in OSM_OVERPASS_URLS:
        try:
            resp = requests.post(url, data={"data": query}, timeout=120,
                                 headers={"Accept": "*/*"})
            if resp.ok:
                break
            print(f"  {url} returned {resp.status_code}, trying next...")
        except requests.RequestException as e:
            print(f"  {url} failed ({e}), trying next...")
    if resp is None or not resp.ok:
        print("  Road fetch failed — skipping junctions")
        return []
    elements = resp.json().get("elements", [])
    print(f"  Got {len(elements)} road ways")
    roads = []
    for el in elements:
        geom = el.get("geometry")
        if geom and len(geom) >= 2:
            roads.append([(pt["lat"], pt["lon"]) for pt in geom])
    if cache_path is not None and roads:
        _save_json_cache(cache_path, roads)
    return roads


def detect_junctions(roads, wps, origin_lat, origin_lon, cos_lat):
    """Find road intersections along the route and return junction stub descriptors."""
    if not roads or not wps:
        return []

    wp_x = np.array([w["local_x"] for w in wps])
    wp_y = np.array([w["local_y"] for w in wps])
    wp_hdg = np.array([w["heading_deg"] for w in wps])

    candidates = []
    for road in roads:
        pts_local = [
            ((lon - origin_lon) * cos_lat * 111_320,
             (lat - origin_lat) * 111_320)
            for lat, lon in road
        ]
        for i in range(len(pts_local) - 1):
            ax, ay = pts_local[i]
            bx, by = pts_local[i + 1]
            seg_dx, seg_dy = bx - ax, by - ay
            seg_len = math.sqrt(seg_dx**2 + seg_dy**2)
            if seg_len < 1.0:
                continue
            mx, my = (ax + bx) / 2, (ay + by) / 2
            dists = np.sqrt((wp_x - mx)**2 + (wp_y - my)**2)
            j = int(np.argmin(dists))
            d = float(dists[j])
            if d > JUNCTION_SNAP_M * 2:
                continue
            t = max(0, min(1, ((wp_x[j]-ax)*seg_dx + (wp_y[j]-ay)*seg_dy) / (seg_len**2)))
            snap_x = ax + t * seg_dx
            snap_y = ay + t * seg_dy
            snap_d = math.sqrt((wp_x[j]-snap_x)**2 + (wp_y[j]-snap_y)**2)
            if snap_d > JUNCTION_SNAP_M:
                continue
            seg_hdg = (math.degrees(math.atan2(seg_dx, seg_dy)) + 360) % 360
            route_hdg = float(wp_hdg[j])
            diff = abs((seg_hdg - route_hdg + 180) % 360 - 180)
            if diff < JUNCTION_MIN_ANGLE or diff > JUNCTION_MAX_ANGLE:
                continue
            candidates.append((snap_d, j, seg_hdg))

    if not candidates:
        return []

    candidates.sort(key=lambda c: c[0])
    junctions = []
    for snap_d, j, seg_hdg in candidates:
        wp = wps[j]
        duplicate = False
        for jn in junctions:
            dx = jn["local_x"] - wp["local_x"]
            dy = jn["local_y"] - wp["local_y"]
            if math.sqrt(dx**2 + dy**2) < 30:
                existing_hdgs = [s["heading_deg"] for s in jn["stubs"]]
                new_hdg = round(seg_hdg, 1)
                opp_hdg = round((seg_hdg + 180) % 360, 1)
                if not any(abs((h - new_hdg + 180) % 360 - 180) < 20 for h in existing_hdgs):
                    jn["stubs"].append({"heading_deg": new_hdg})
                    jn["stubs"].append({"heading_deg": opp_hdg})
                duplicate = True
                break
        if not duplicate:
            junctions.append({
                "dist_m":  round(wp["dist_m"], 1),
                "local_x": wp["local_x"],
                "local_y": wp["local_y"],
                "local_z": wp["local_z"],
                "stubs": [
                    {"heading_deg": round(seg_hdg, 1)},
                    {"heading_deg": round((seg_hdg + 180) % 360, 1)},
                ],
            })

    print(f"  {len(junctions)} road junctions detected")
    return junctions


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--route", default="falkenberg_steinsee_22.json",
                        help="Route JSON filename in routes/")
    parser.add_argument("--start-km", type=float, default=None,
                        help="Section start in km (default: route start)")
    parser.add_argument("--end-km", type=float, default=None,
                        help="Section end in km (default: route end)")
    parser.add_argument("--source", choices=["osm", "terrain", "worldcover"], default="osm",
                        help="Data source for land cover (default: osm)")
    parser.add_argument("--elevation-step", type=int, default=100, metavar="M",
                        help="Terrain grid resolution in m (default: 100)")
    parser.add_argument("--no-elevation", action="store_true")
    parser.add_argument("--lidar-dem", metavar="NPZ",
                        help="Blend LiDAR npz into wide Copernicus background")
    args = parser.parse_args()

    src = Path(__file__).parent / "routes" / args.route
    if not src.exists():
        sys.exit(f"Source route not found: {src}")

    route_stem = src.stem

    print(f"Loading {src.name}  (source={args.source})...")
    with open(src) as f:
        full = json.load(f)

    all_wps = full["waypoints"]
    total_dist_m = all_wps[-1]["dist_m"]

    start_m = int((args.start_km or 0) * 1000)
    end_m   = int((args.end_km * 1000) if args.end_km is not None else total_dist_m + 1)

    wps = [w for w in all_wps if start_m <= w["dist_m"] <= end_m]
    if not wps:
        sys.exit(f"No waypoints found in km{start_m//1000}–{end_m//1000} window")

    start_km_label = int(start_m / 1000)
    end_km_label   = int(round(wps[-1]["dist_m"] / 1000))
    print(f"  {len(wps)} waypoints in km{start_km_label}–{end_km_label} window")

    origin_lat  = wps[0]["lat"]
    origin_lon  = wps[0]["lon"]
    base_ele    = wps[0]["ele_m"]
    cos_lat     = math.cos(math.radians(origin_lat))
    dist_offset = wps[0]["dist_m"]

    for w in wps:
        w["dist_m"]  = round(w["dist_m"] - dist_offset, 1)
        w["local_x"] = round((w["lon"] - origin_lon) * cos_lat * 111_320, 1)
        w["local_y"] = round((w["lat"] - origin_lat) * 111_320, 1)
        w["local_z"] = round(w["ele_m"] - base_ele, 2)

    bbox = {
        "lat_min": min(w["lat"] for w in wps),
        "lat_max": max(w["lat"] for w in wps),
        "lon_min": min(w["lon"] for w in wps),
        "lon_max": max(w["lon"] for w in wps),
    }

    wp_x = np.array([w["local_x"] for w in wps])
    wp_y = np.array([w["local_y"] for w in wps])
    wp_z = np.array([w["local_z"] for w in wps])

    water_pts_local = reproject_water_pts(full, origin_lat, origin_lon, cos_lat)
    print(f"  {len(water_pts_local)} water polygon nodes available for water-proximity check")

    # -------------------------------------------------------------------
    # Terrain (+1km buffer, cached)
    # -------------------------------------------------------------------
    terrain_grid = None
    buf = TERRAIN_BUFFER_DEG
    wide_bbox = {
        "lat_min": bbox["lat_min"] - buf,
        "lat_max": bbox["lat_max"] + buf,
        "lon_min": bbox["lon_min"] - buf / cos_lat,
        "lon_max": bbox["lon_max"] + buf / cos_lat,
    }

    if args.lidar_dem:
        print(f"Loading LiDAR DEM from {args.lidar_dem}…")
        ld = np.load(args.lidar_dem)
        # Reproject from geographic coords so any section origin works correctly.
        # lons[i] = longitude of column i, lats[j] = latitude of row j (north→south).
        lons_1d = ld['lons']    # shape (nx,)
        lats_1d = ld['lats']    # shape (ny,), typically north-first (descending lat)
        elev2d  = ld['elev2d']  # shape (ny, nx)
        # Flip to south-first so row 0 = lowest local_y (ascending latitude)
        if lats_1d[0] > lats_1d[-1]:
            lats_1d = lats_1d[::-1]
            elev2d  = elev2d[::-1, :]
        nx_l = len(lons_1d)
        ny_l = len(lats_1d)
        step_x_m = float((lons_1d[-1] - lons_1d[0]) / (nx_l - 1)) * cos_lat * 111_320
        step_y_m = float((lats_1d[-1] - lats_1d[0]) / (ny_l - 1)) * 111_320
        origin_x_l = float((lons_1d[0] - origin_lon) * cos_lat * 111_320)
        origin_y_l = float((lats_1d[0] - origin_lat) * 111_320)
        heights_l  = (elev2d - base_ele).flatten().round(2).tolist()
        lidar_grid = dict(
            nx=nx_l, ny=ny_l,
            origin_x=round(origin_x_l, 1),
            origin_y=round(origin_y_l, 1),
            step_m=round((step_x_m + step_y_m) / 2, 1),
            step_x_m=round(step_x_m, 2),
            step_y_m=round(step_y_m, 2),
            heights=heights_l,
        )
        print(f"  {lidar_grid['nx']}×{lidar_grid['ny']} pts  "
              f"step_x={step_x_m:.1f} m  step_y={step_y_m:.1f} m  "
              f"ele {ld['elev2d'].min():.0f}–{ld['elev2d'].max():.0f} m")

        cop_cache = CACHE_DIR / f"terrain_cop_{_bbox_hash(wide_bbox)}_100m.json"
        try:
            print("Fetching wide-area Copernicus terrain (100 m step, +1 km buffer)...")
            cop_grid = _load_json_cache(cop_cache)
            if cop_grid is not None:
                print(f"  Loaded from cache: {cop_grid['nx']}×{cop_grid['ny']}", flush=True)
            else:
                cop_grid = fetch_terrain_grid(
                    wide_bbox, origin_lat=origin_lat, origin_lon=origin_lon,
                    base_ele=base_ele, step_m=100)
                _save_json_cache(cop_cache, cop_grid)
            terrain_grid = blend_lidar_into_copernicus(lidar_grid, cop_grid)
            print(f"  Merged terrain: {terrain_grid['nx']}×{terrain_grid['ny']} "
                  f"(Copernicus+LiDAR blend)", flush=True)
        except Exception as e:
            print(f"  Wide terrain fetch failed ({e}), using LiDAR only")
            terrain_grid = lidar_grid

    elif not args.no_elevation:
        step_m = args.elevation_step
        terrain_cache = CACHE_DIR / f"terrain_{_bbox_hash(wide_bbox)}_{step_m}m.json"
        try:
            print(f"Fetching terrain elevation grid ({step_m}m step, +1 km buffer)...")
            terrain_grid = _load_json_cache(terrain_cache)
            if terrain_grid is not None:
                print(f"  Loaded from cache: {terrain_grid['nx']}×{terrain_grid['ny']}", flush=True)
            else:
                terrain_grid = fetch_terrain_grid(
                    wide_bbox, origin_lat=origin_lat, origin_lon=origin_lon,
                    base_ele=base_ele, step_m=step_m)
                _save_json_cache(terrain_cache, terrain_grid)
                print(f"  Terrain grid: {terrain_grid['nx']}×{terrain_grid['ny']} points")
        except Exception as e:
            print(f"  Terrain fetch failed ({e}), continuing without terrain")

    if terrain_grid is not None and not args.lidar_dem:
        terrain_grid = conform_terrain_to_road(terrain_grid, wp_x, wp_y, wp_z)
        print("  Terrain conformed (canopy correction only)")

    # -------------------------------------------------------------------
    # Wide vista terrain (500 m step, +8 km buffer) — distant mountain ranges
    # -------------------------------------------------------------------
    vista_terrain = None
    try:
        vista_bbox = {
            "lat_min": bbox["lat_min"] - VISTA_TERRAIN_BUFFER_DEG,
            "lat_max": bbox["lat_max"] + VISTA_TERRAIN_BUFFER_DEG,
            "lon_min": bbox["lon_min"] - VISTA_TERRAIN_BUFFER_DEG / cos_lat,
            "lon_max": bbox["lon_max"] + VISTA_TERRAIN_BUFFER_DEG / cos_lat,
        }
        vista_cache = CACHE_DIR / f"terrain_{_bbox_hash(vista_bbox)}_{VISTA_TERRAIN_STEP_M}m.json"
        vista_terrain = _load_json_cache(vista_cache)
        if vista_terrain is not None:
            print(f"Loaded vista terrain from cache: "
                  f"{vista_terrain['nx']}×{vista_terrain['ny']}", flush=True)
        else:
            print("Fetching wide vista terrain (500 m step, +8 km buffer)...", flush=True)
            vista_terrain = fetch_terrain_grid(
                vista_bbox, origin_lat=origin_lat, origin_lon=origin_lon,
                base_ele=base_ele, step_m=VISTA_TERRAIN_STEP_M)
            _save_json_cache(vista_cache, vista_terrain)
            print(f"  Vista terrain: {vista_terrain['nx']}×{vista_terrain['ny']} points")
    except Exception as e:
        print(f"  Vista terrain fetch failed ({e}), continuing without")

    # -------------------------------------------------------------------
    # Land cover
    # -------------------------------------------------------------------
    print(f"\nBuilding land cover — source: {args.source}")
    roads = []
    source_suffix = {"osm": "", "terrain": "_terrain", "worldcover": "_worldcover"}[args.source]

    if args.source == "osm":
        lc_cache = CACHE_DIR / f"landcover_osm_{_bbox_hash(bbox)}.json"
        elements = fetch_osm_landcover(bbox, cache_path=lc_cache)
        land_cover = build_osm_landcover(
            elements, origin_lat, origin_lon, cos_lat, wp_x, wp_y, terrain_grid, wp_z=wp_z)
        roads_cache = CACHE_DIR / f"roads_{_bbox_hash(bbox)}.json"
        roads = fetch_osm_roads_section(bbox, cache_path=roads_cache)

    elif args.source == "terrain":
        land_cover = build_terrain_landcover(terrain_grid, wp_x, wp_y, water_pts_local, wp_z=wp_z)

    elif args.source == "worldcover":
        try:
            land_cover = fetch_worldcover_landcover(
                bbox, origin_lat, origin_lon, cos_lat, wp_x, wp_y, terrain_grid, wp_z=wp_z)
        except RuntimeError as e:
            sys.exit(f"WorldCover source failed: {e}")
        # Supplement with OSM water areas (rivers/lakes mapped as OSM polygons)
        water_cache = CACHE_DIR / f"water_{_bbox_hash(bbox)}.json"
        osm_water = fetch_osm_water_areas(bbox, cache_path=water_cache)
        for el in osm_water:
            geom = el.get("geometry", [])
            if el.get("type") == "relation":
                for m in el.get("members", []):
                    if m.get("role") == "outer" and m.get("geometry"):
                        geom = m["geometry"]
                        break
            if len(geom) < 3:
                continue
            poly_local = [(round((pt["lon"] - origin_lon) * cos_lat * 111_320, 1),
                           round((pt["lat"] - origin_lat) * 111_320, 1)) for pt in geom]
            if wp_x.size > 0 and not any(
                    float(np.sqrt(((wp_x - lx) ** 2 + (wp_y - ly) ** 2)).min()) < 800
                    for lx, ly in poly_local):
                continue
            pts_masked = _road_mask_points(
                [{"lx": x, "ly": y} for x, y in poly_local], wp_x, wp_y)
            if len(pts_masked) < 3:
                continue
            if _centroid_on_road(pts_masked, wp_x, wp_y):
                continue
            land_cover.append({"type": "water", "points": pts_masked, "interior": []})
        water_count = sum(1 for lc in land_cover if lc["type"] == "water")
        print(f"  {water_count} water polygons after OSM merge")

    lidar_suffix = "_lidar" if args.lidar_dem else ""
    out_name = (f"{route_stem}_{start_km_label}_{end_km_label}"
                f"{source_suffix}{lidar_suffix}.json")

    junctions = []
    if args.source == "osm" and roads:
        junctions = detect_junctions(roads, wps, origin_lat, origin_lon, cos_lat)

    print("Fetching buildings...")
    bld_cache = CACHE_DIR / f"buildings_{_bbox_hash(bbox)}.json"
    scenery = []
    try:
        scenery = fetch_osm_buildings(
            bbox, origin_lat, origin_lon, cos_lat, wp_x, wp_y, terrain_grid,
            cache_path=bld_cache)
    except Exception as e:
        print(f"  Buildings fetch failed ({e})")

    out_dir  = Path(__file__).parent / "routes"
    out_path = out_dir / out_name

    print("Stitching minimap...")
    minimap_meta = None
    try:
        minimap_meta = stitch_minimap(
            bbox, wps, origin_lat, origin_lon, cos_lat, out_dir, out_path.stem)
    except Exception as e:
        print(f"  Minimap stitch failed ({e})")

    route = {
        "name":         out_path.stem,
        "total_dist_m": wps[-1]["dist_m"],
        "origin_lat":   origin_lat,
        "origin_lon":   origin_lon,
        "base_ele":     base_ele,
        "bbox":         bbox,
        "waypoints":    wps,
        "scenery":      scenery,
        "water":        [],
        "terrain_grid":       terrain_grid,
        "vista_terrain_grid": vista_terrain,
        "land_cover":         land_cover,
        "junctions":    junctions,
        "minimap_meta": minimap_meta,
    }

    with open(out_path, "w") as f:
        json.dump(route, f, separators=(",", ":"))

    size_kb = out_path.stat().st_size // 1024
    print(f"\nWrote {out_path} ({size_kb} KB)")
    print(f"  Distance: {route['total_dist_m']/1000:.1f} km, "
          f"Waypoints: {len(wps)}, Land cover: {len(land_cover)} polygons")

    # Update routes/index.json
    index_path = out_dir / "index.json"
    try:
        with open(index_path) as f:
            index = json.load(f)
    except Exception:
        index = []
    if out_name not in index:
        index.append(out_name)
        with open(index_path, "w") as f:
            json.dump(index, f)
        print(f"  Added {out_name} to routes/index.json")


if __name__ == "__main__":
    main()
