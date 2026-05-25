#!/usr/bin/env python3
"""
terrain_contour_extract.py  —  OSM tile → 3D terrain surface

Pipeline
  1.  Download OpenTopoMap tiles for the route bbox
  2.  Stitch tiles → geo-referenced image
  3.  HSV colour-filter → extract brown contour pixels
  4.  Assign elevation to contour pixels via OpenTopoData grid (cached)
  5.  IDW-interpolate to a regular surface grid
  6.  Plotly 3D: IDW surface + raw elevation grid + .fit GPS track
  LiDAR (optional, independent):
  7.  Download Copernicus DEM GLO-30 (~30 m) for bbox, store as local GeoTIFF + npz

All fetched/computed data cached in terrain_data/; re-runs use cached files.

Usage
  python3 terrain_contour_extract.py --all
  python3 terrain_contour_extract.py --download [--zoom 14] [--route stelvio]
  python3 terrain_contour_extract.py --extract  [--zoom 14]
  python3 terrain_contour_extract.py --elev
  python3 terrain_contour_extract.py --interp
  python3 terrain_contour_extract.py --lidar
  python3 terrain_contour_extract.py --plot
"""

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import requests
from PIL import Image

# ─── Route configurations ────────────────────────────────────────────────────

ROUTES = {
    'falkenberg': dict(
        lat_min=48.032, lat_max=48.056,
        lon_min=11.877, lon_max=11.927,
        origin_lat=48.0334, origin_lon=11.885332,
        base_ele=519.6,
        route_json='routes/falkenberg_24_34_worldcover.json',
    ),
    'stelvio': dict(
        lat_min=46.500, lat_max=46.575,
        lon_min=10.420, lon_max=10.560,
        origin_lat=46.540, origin_lon=10.481,
        base_ele=900.0,
        route_json=None,
    ),
}

DATA_DIR = Path('terrain_data')
TILE_DIR = DATA_DIR / 'tiles'
HEADERS  = {'User-Agent': 'ride_viz terrain investigation (personal research)'}

# ─── Slippy tile helpers ──────────────────────────────────────────────────────

def latlon_to_tile(lat, lon, z):
    """Return (x, y) slippy tile index for a given lat/lon at zoom z."""
    n = 2 ** z
    x = int((lon + 180) / 360 * n)
    lat_r = math.radians(lat)
    y = int((1 - math.log(math.tan(lat_r) + 1 / math.cos(lat_r)) / math.pi) / 2 * n)
    return x, y


def tile_nw_corner(x, y, z):
    """Return (lat, lon) of the NW corner of tile (x, y) at zoom z."""
    n = 2 ** z
    lon = x / n * 360 - 180
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lat, lon


# ─── Stage 1: Download + stitch tiles ────────────────────────────────────────

def download_tiles(cfg, zoom):
    TILE_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # NW corner of bbox: lat_max, lon_min → smallest tile y
    x_min, y_min = latlon_to_tile(cfg['lat_max'], cfg['lon_min'], zoom)
    # SE corner of bbox: lat_min, lon_max → largest tile y
    x_max, y_max = latlon_to_tile(cfg['lat_min'], cfg['lon_max'], zoom)

    tiles = [(x, y) for y in range(y_min, y_max + 1) for x in range(x_min, x_max + 1)]
    print(f"  {len(tiles)} tiles at z{zoom}  ({x_min}–{x_max}, {y_min}–{y_max})")

    downloaded = 0
    for x, y in tiles:
        path = TILE_DIR / f'z{zoom}_{x}_{y}.png'
        if path.exists():
            continue
        url = f'https://tile.opentopomap.org/{zoom}/{x}/{y}.png'
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            path.write_bytes(r.content)
            downloaded += 1
            time.sleep(1.0)
        except Exception as e:
            print(f"    Warning: tile {zoom}/{x}/{y} → {e}")
    print(f"  Downloaded {downloaded} new tiles ({len(tiles) - downloaded} already cached)")

    meta = dict(
        zoom=zoom,
        x_min=x_min, x_max=x_max,
        y_min=y_min, y_max=y_max,
        nw_lat=tile_nw_corner(x_min,     y_min,     zoom)[0],
        nw_lon=tile_nw_corner(x_min,     y_min,     zoom)[1],
        se_lat=tile_nw_corner(x_max + 1, y_max + 1, zoom)[0],
        se_lon=tile_nw_corner(x_max + 1, y_max + 1, zoom)[1],
    )
    (DATA_DIR / f'z{zoom}_meta.json').write_text(json.dumps(meta, indent=2))
    return meta


def stitch_tiles(zoom):
    out_path  = DATA_DIR / f'z{zoom}_stitched.png'
    meta_path = DATA_DIR / f'z{zoom}_meta.json'

    if out_path.exists():
        print(f"  {out_path.name} already cached")
        return json.loads(meta_path.read_text())

    meta = json.loads(meta_path.read_text())
    nx   = meta['x_max'] - meta['x_min'] + 1
    ny   = meta['y_max'] - meta['y_min'] + 1
    canvas = Image.new('RGB', (nx * 256, ny * 256))

    for yi in range(ny):
        for xi in range(nx):
            path = TILE_DIR / f"z{zoom}_{meta['x_min']+xi}_{meta['y_min']+yi}.png"
            if path.exists():
                canvas.paste(Image.open(path).convert('RGB'), (xi * 256, yi * 256))
            else:
                print(f"    Missing tile {path.name}")

    canvas.save(out_path)
    print(f"  Stitched {nx}×{ny} tiles → {out_path.name} ({canvas.width}×{canvas.height} px)")
    return meta


# ─── Stage 2: HSV colour-filter → contour pixel coords ───────────────────────

def _rgb_to_hsv(rgb):
    """Convert (H, W, 3) uint8 array to (H, S, V) float arrays.
    H ∈ [0,360), S and V ∈ [0,100].
    """
    r, g, b = rgb[:, :, 0] / 255., rgb[:, :, 1] / 255., rgb[:, :, 2] / 255.
    cmax  = np.maximum(np.maximum(r, g), b)
    cmin  = np.minimum(np.minimum(r, g), b)
    delta = cmax - cmin

    h = np.zeros_like(cmax)
    mr = (cmax == r) & (delta > 0)
    mg = (cmax == g) & (delta > 0)
    mb = (cmax == b) & (delta > 0)
    h[mr] = 60 * (((g[mr] - b[mr]) / delta[mr]) % 6)
    h[mg] = 60 * ((b[mg] - r[mg]) / delta[mg] + 2)
    h[mb] = 60 * ((r[mb] - g[mb]) / delta[mb] + 4)

    s = np.where(cmax > 0, delta / cmax * 100, 0.0)
    v = cmax * 100
    return h, s, v


def extract_contours(zoom):
    pts_path  = DATA_DIR / 'contour_pts.npy'
    mask_path = DATA_DIR / f'z{zoom}_contour_mask.png'
    meta_path = DATA_DIR / f'z{zoom}_meta.json'

    if pts_path.exists():
        pts = np.load(pts_path)
        print(f"  contour_pts.npy already cached ({len(pts):,} pts)")
        return pts

    meta = json.loads(meta_path.read_text())
    img  = np.array(Image.open(DATA_DIR / f'z{zoom}_stitched.png').convert('RGB'))
    H, W = img.shape[:2]

    hue, sat, val = _rgb_to_hsv(img)

    # Brown/tan contour lines on OpenTopoMap
    # (inspect z{zoom}_contour_mask.png and widen/narrow if needed)
    mask = (
        (hue >  6) & (hue < 42) &
        (sat > 16) & (sat < 68) &
        (val > 40) & (val < 88)
    )

    Image.fromarray((mask * 255).astype(np.uint8)).save(mask_path)
    print(f"  Contour mask: {mask.sum():,} / {H*W:,} pixels → {mask_path.name}")

    # Convert mask pixels → (lat, lon) via bilinear affine
    rows, cols = np.where(mask)
    lat_arr = meta['nw_lat'] + rows * (meta['se_lat'] - meta['nw_lat']) / H
    lon_arr = meta['nw_lon'] + cols * (meta['se_lon'] - meta['nw_lon']) / W

    # Subsample: every 5th point (keeps ~2k–10k pts depending on tile count)
    lat_arr = lat_arr[::5]
    lon_arr = lon_arr[::5]
    pts = np.column_stack([lat_arr, lon_arr]).astype(np.float32)
    np.save(pts_path, pts)
    print(f"  Saved {len(pts):,} contour sample points → contour_pts.npy")
    return pts


# ─── Stage 3: OpenTopoData elevation reference grid ──────────────────────────

def fetch_elevation_grid(cfg):
    out_path = DATA_DIR / 'elev_grid.npz'
    if out_path.exists():
        print("  elev_grid.npz already cached")
        return

    cos_lat   = math.cos(math.radians(cfg['origin_lat']))
    step_lat  = 50.0 / 111_320
    step_lon  = 50.0 / (111_320 * cos_lat)

    lats = np.arange(cfg['lat_min'], cfg['lat_max'] + step_lat * 0.5, step_lat)
    lons = np.arange(cfg['lon_min'], cfg['lon_max'] + step_lon * 0.5, step_lon)
    glon, glat = np.meshgrid(lons, lats)
    pts_flat   = list(zip(glat.ravel().tolist(), glon.ravel().tolist()))
    n_pts      = len(pts_flat)

    elevs = []
    batch = 100
    url   = 'https://api.opentopodata.org/v1/eudem25m'
    n_bat = math.ceil(n_pts / batch)
    print(f"  Querying {n_pts} pts in {n_bat} batches (50 m grid)…")

    for i in range(0, n_pts, batch):
        chunk   = pts_flat[i:i + batch]
        loc_str = '|'.join(f'{la:.6f},{lo:.6f}' for la, lo in chunk)
        ok = False
        for attempt in range(3):
            try:
                r = requests.post(url, data={'locations': loc_str}, timeout=45)
                r.raise_for_status()
                elevs.extend(res['elevation'] or 0.0 for res in r.json()['results'])
                ok = True
                break
            except Exception as e:
                print(f"    Batch {i//batch+1}/{n_bat} attempt {attempt+1} failed: {e}")
                time.sleep(2)
        if not ok:
            elevs.extend([cfg['base_ele']] * len(chunk))
        time.sleep(1.1)

    elev2d = np.array(elevs).reshape(glat.shape)
    lx2d   = (glon - cfg['origin_lon']) * cos_lat * 111_320
    ly2d   = (glat - cfg['origin_lat']) * 111_320

    np.savez(out_path, lx2d=lx2d, ly2d=ly2d, elev2d=elev2d,
             lons=lons, lats=lats)
    print(f"  Saved {elev2d.size} pts  ele {elev2d.min():.0f}–{elev2d.max():.0f} m → elev_grid.npz")


# ─── Stage 4: Label contour pixels → (lx, ly, lz) ───────────────────────────

def label_contours(cfg, pts):
    """Bilinear-interpolate elevation from reference grid for every contour pt."""
    d      = np.load(DATA_DIR / 'elev_grid.npz')
    lx2d   = d['lx2d']
    ly2d   = d['ly2d']
    elev2d = d['elev2d']
    ny, nx = lx2d.shape

    cos_lat = math.cos(math.radians(cfg['origin_lat']))
    lx_c    = (pts[:, 1] - cfg['origin_lon']) * cos_lat * 111_320
    ly_c    = (pts[:, 0] - cfg['origin_lat']) * 111_320

    # Grid is regular — derive spacing from corner values
    x0  = float(lx2d[0, 0]);  dx = (float(lx2d[0, -1]) - x0) / max(nx - 1, 1)
    y0  = float(ly2d[0, 0]);  dy = (float(ly2d[-1, 0]) - y0)  / max(ny - 1, 1)

    ix  = (lx_c - x0) / dx
    iy  = (ly_c - y0) / dy
    ix0 = np.clip(np.floor(ix).astype(int), 0, nx - 2)
    iy0 = np.clip(np.floor(iy).astype(int), 0, ny - 2)
    tx  = np.clip(ix - ix0, 0, 1)
    ty  = np.clip(iy - iy0, 0, 1)

    ele = (elev2d[iy0,   ix0  ] * (1 - tx) * (1 - ty) +
           elev2d[iy0,   ix0+1] * tx       * (1 - ty) +
           elev2d[iy0+1, ix0  ] * (1 - tx) * ty       +
           elev2d[iy0+1, ix0+1] * tx       * ty)

    valid = (ix >= 0) & (ix <= nx - 1) & (iy >= 0) & (iy <= ny - 1)
    return lx_c[valid], ly_c[valid], (ele[valid] - cfg['base_ele'])


# ─── Stage 5: IDW interpolation ───────────────────────────────────────────────

def idw_surface(lx, ly, lz, cfg, step_m=50.0):
    out_path = DATA_DIR / 'surface.npz'
    if out_path.exists():
        print("  surface.npz already cached")
        return

    cos_lat = math.cos(math.radians(cfg['origin_lat']))
    xi = np.arange((cfg['lon_min'] - cfg['origin_lon']) * cos_lat * 111_320,
                   (cfg['lon_max'] - cfg['origin_lon']) * cos_lat * 111_320,
                   step_m)
    yi = np.arange((cfg['lat_min'] - cfg['origin_lat']) * 111_320,
                   (cfg['lat_max'] - cfg['origin_lat']) * 111_320,
                   step_m)

    pts  = np.column_stack([lx, ly])
    vals = lz

    rng = np.random.default_rng(42)
    max_src = 3000
    if len(pts) > max_src:
        idx  = rng.choice(len(pts), max_src, replace=False)
        pts  = pts[idx];  vals = vals[idx]

    print(f"  IDW: {len(pts)} source pts  grid {len(xi)}×{len(yi)} …")

    zgrid   = np.empty((len(yi), len(xi)))
    chunk   = 8   # rows per chunk — limits peak RAM to ~chunk*len(xi)*N*8 bytes
    for i0 in range(0, len(yi), chunk):
        i1  = min(i0 + chunk, len(yi))
        gx, gy = np.meshgrid(xi, yi[i0:i1])
        dx  = gx[..., None] - pts[:, 0]
        dy  = gy[..., None] - pts[:, 1]
        d2  = np.maximum(dx * dx + dy * dy, 1.0)
        w   = 1.0 / d2
        zgrid[i0:i1] = (w * vals).sum(-1) / w.sum(-1)

    np.savez(out_path, xi=xi, yi=yi, zgrid=zgrid)
    print(f"  IDW surface {zgrid.shape}  z {zgrid.min():.1f}–{zgrid.max():.1f} m → surface.npz")


# ─── Stage LiDAR: Copernicus DEM GLO-30 download ─────────────────────────────

def _copernicus_tile_url(lat_deg, lon_deg):
    """Return the Copernicus DEM GLO-30 AWS COG URL for the 1°×1° tile
    containing (lat_deg, lon_deg).  lat_deg and lon_deg are the SW corner."""
    ns  = 'N' if lat_deg >= 0 else 'S'
    ew  = 'E' if lon_deg >= 0 else 'W'
    lat = abs(int(lat_deg))
    lon = abs(int(lon_deg))
    code = f'Copernicus_DSM_COG_10_{ns}{lat:02d}_00_{ew}{lon:03d}_00_DEM'
    return (
        f'https://copernicus-dem-30m.s3.amazonaws.com/{code}/{code}.tif'
    )


def download_lidar(cfg):
    """Window-read Copernicus DEM GLO-30 (~30 m) for the route bbox.
    Saves terrain_data/lidar_{route}.tif  and  terrain_data/lidar_{route}.npz.
    Handles the case where the bbox spans up to 2×2 degree tiles.
    """
    import rasterio
    from rasterio.windows import from_bounds
    from rasterio.merge import merge as rio_merge
    from rasterio.transform import from_origin
    import tempfile

    route_key = next(k for k, v in ROUTES.items() if v is cfg)
    tif_path   = DATA_DIR / f'lidar_{route_key}.tif'
    npz_path   = DATA_DIR / f'lidar_{route_key}.npz'

    if npz_path.exists():
        print(f'  lidar_{route_key}.npz already cached')
        return

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    lat_min, lat_max = cfg['lat_min'], cfg['lat_max']
    lon_min, lon_max = cfg['lon_min'], cfg['lon_max']
    cos_lat   = math.cos(math.radians(cfg['origin_lat']))

    # Identify all degree-tiles needed (SW corners of 1°×1° cells)
    lat_floors = range(int(math.floor(lat_min)), int(math.floor(lat_max)) + 1)
    lon_floors = range(int(math.floor(lon_min)), int(math.floor(lon_max)) + 1)

    tile_urls = [
        _copernicus_tile_url(la, lo)
        for la in lat_floors for lo in lon_floors
    ]
    print(f'  Fetching {len(tile_urls)} Copernicus GLO-30 tile(s) for {route_key}…')

    # Open each remote COG and window-read the bbox
    tile_arrays = []   # list of (data, transform, nodata)
    res = None         # arcsec resolution (degrees per pixel)
    for url in tile_urls:
        vsi_url = '/vsicurl/' + url
        try:
            with rasterio.open(vsi_url) as src:
                if res is None:
                    res = src.res   # (dy, dx) in degrees
                win  = from_bounds(lon_min, lat_min, lon_max, lat_max, src.transform)
                data = src.read(1, window=win).astype(np.float32)
                win_tf = src.window_transform(win)
                tile_arrays.append((data, win_tf, src.nodata))
                print(f'    {url.split("/")[-1]}: {data.shape}  '
                      f'ele {data.min():.0f}–{data.max():.0f} m')
        except Exception as e:
            print(f'    Warning: could not read {url}: {e}')

    if not tile_arrays:
        print('  LiDAR download failed — no tiles read.')
        return

    # If multiple tiles, mosaic by simple paste onto output grid
    if len(tile_arrays) == 1:
        data, win_tf, nodata = tile_arrays[0]
    else:
        # Build a combined grid covering the full bbox at the same resolution
        dy, dx = res
        nx = round((lon_max - lon_min) / dx)
        ny = round((lat_max - lat_min) / dy)
        data = np.full((ny, nx), np.nan, dtype=np.float32)
        origin_tf = from_origin(lon_min, lat_max, dx, dy)
        for arr, tf, nd in tile_arrays:
            col0 = round((tf.c - lon_min) / dx)
            row0 = round((lat_max - tf.f) / dy)
            r1, r2 = max(row0, 0), min(row0 + arr.shape[0], ny)
            c1, c2 = max(col0, 0), min(col0 + arr.shape[1], nx)
            sr1 = r1 - row0;  sr2 = sr1 + (r2 - r1)
            sc1 = c1 - col0;  sc2 = sc1 + (c2 - c1)
            mask = arr[sr1:sr2, sc1:sc2]
            if nd is not None:
                mask = np.where(mask == nd, np.nan, mask)
            data[r1:r2, c1:c2] = mask
        win_tf = origin_tf
        nodata = None

    # Replace nodata with NaN
    if nodata is not None:
        data = np.where(data == nodata, np.nan, data)

    # Save GeoTIFF
    from rasterio.crs import CRS
    with rasterio.open(
        tif_path, 'w',
        driver='GTiff', height=data.shape[0], width=data.shape[1],
        count=1, dtype='float32', crs=CRS.from_epsg(4326),
        transform=win_tf,
    ) as dst:
        dst.write(data, 1)
    print(f'  Saved GeoTIFF → {tif_path}  ({data.shape[0]}×{data.shape[1]} px)')

    # Build (lx2d, ly2d, elev2d) arrays in local metres (same convention as elev_grid)
    dy_deg, dx_deg = abs(win_tf.e), abs(win_tf.a)
    lons = win_tf.c + (np.arange(data.shape[1]) + 0.5) * dx_deg
    lats = win_tf.f - (np.arange(data.shape[0]) + 0.5) * dy_deg   # top-down
    glon, glat = np.meshgrid(lons, lats)

    lx2d = (glon - cfg['origin_lon']) * cos_lat * 111_320
    ly2d = (glat - cfg['origin_lat']) * 111_320

    np.savez(npz_path, lx2d=lx2d, ly2d=ly2d, elev2d=data, lons=lons, lats=lats)
    print(f'  Saved npz → {npz_path}  '
          f'ele {np.nanmin(data):.0f}–{np.nanmax(data):.0f} m  '
          f'({data.shape[0]}×{data.shape[1]} pts)')


# ─── Stage LiDAR-OSM: OSM tile draped on LiDAR surface ───────────────────────

def lidar_osm_surface(cfg):
    import plotly.graph_objects as go

    route_key = next(k for k, v in ROUTES.items() if v is cfg)
    npz_path  = DATA_DIR / f'lidar_{route_key}.npz'
    meta_path = DATA_DIR / 'z15_meta.json'
    tile_path = DATA_DIR / 'z15_stitched.png'

    if not npz_path.exists():
        print(f'  {npz_path.name} not found — run --lidar first'); return
    if not meta_path.exists() or not tile_path.exists():
        print('  z15 tile not found — run --download --zoom 15 first'); return

    ld      = np.load(npz_path)
    lx2d    = ld['lx2d']       # (ny, nx)
    ly2d    = ld['ly2d']
    elev2d  = ld['elev2d']
    lons    = ld['lons']        # (nx,) col centres
    lats    = ld['lats']        # (ny,) row centres — row 0 northernmost

    meta     = json.loads(meta_path.read_text())
    tile_img = Image.open(tile_path).convert('RGB')
    tw, th   = tile_img.size                        # 1280 × 1024
    tile_arr = np.array(tile_img)                   # (th, tw, 3)

    # Map each LiDAR pixel centre (lat, lon) → nearest tile pixel
    col_i = np.clip(
        ((lons - meta['nw_lon']) / (meta['se_lon'] - meta['nw_lon']) * tw).astype(int),
        0, tw - 1)                                  # (nx,)
    row_i = np.clip(
        ((meta['nw_lat'] - lats) / (meta['nw_lat'] - meta['se_lat']) * th).astype(int),
        0, th - 1)                                  # (ny,) — nw_lat > lats → positive

    # Broadcasting: row_i[:,None] picks rows, col_i[None,:] picks columns
    rgb = tile_arr[row_i[:, None], col_i[None, :], :]   # (ny, nx, 3)

    # Quantize to ≤256 colours so plotly's colorscale trick works
    rgb_img     = Image.fromarray(rgb.astype(np.uint8))
    palette_img = rgb_img.quantize(colors=256)
    idx         = np.array(palette_img)               # (ny, nx) int
    pal         = palette_img.getpalette()             # [R,G,B, ...] 256*3 ints

    colorscale = [
        [i / 255, f'#{pal[i*3]:02x}{pal[i*3+1]:02x}{pal[i*3+2]:02x}']
        for i in range(256)
    ]

    lx1d   = lx2d[0, :]
    ly1d   = ly2d[:, 0]
    z_rel  = elev2d - cfg['base_ele']

    fig = go.Figure()
    fig.add_trace(go.Surface(
        x=lx1d, y=ly1d, z=z_rel,
        surfacecolor=idx.astype(float),
        cmin=0, cmax=255,
        colorscale=colorscale,
        showscale=False,
        name='OSM tile on LiDAR',
        hovertemplate='E: %{x:.0f} m<br>N: %{y:.0f} m<br>z: %{z:.0f} m<extra></extra>',
    ))

    if cfg.get('route_json') and Path(cfg['route_json']).exists():
        wps   = json.loads(Path(cfg['route_json']).read_text())['waypoints']
        wp_lx = [w['local_x'] for w in wps]
        wp_ly = [w['local_y'] for w in wps]
        wp_lz = [w['local_z'] + 5 for w in wps]
        fig.add_trace(go.Scatter3d(
            x=wp_lx, y=wp_ly, z=wp_lz,
            mode='lines', line=dict(color='red', width=4),
            name='.fit GPS track',
        ))

    fig.update_layout(
        title='OSM tile draped on Copernicus LiDAR 30 m surface — ' + route_key,
        scene=dict(
            xaxis_title='East (m)', yaxis_title='North (m)',
            zaxis_title='Elev above base (m)',
            aspectmode='data',
        ),
    )

    out = DATA_DIR / 'lidar_osm_surface.html'
    fig.write_html(str(out))
    print(f'  → {out}')


# ─── Stage 6: Plotly 3D output ────────────────────────────────────────────────

def plot_surface(cfg):
    import plotly.graph_objects as go

    surf = np.load(DATA_DIR / 'surface.npz')
    xi, yi, zgrid = surf['xi'], surf['yi'], surf['zgrid']

    elev  = np.load(DATA_DIR / 'elev_grid.npz')
    lx2d  = elev['lx2d'];  ly2d = elev['ly2d'];  elev2d = elev['elev2d']
    zraw  = elev2d - cfg['base_ele']

    fig = go.Figure()

    # IDW surface derived from tile contour pixels
    fig.add_trace(go.Surface(
        x=xi, y=yi, z=zgrid,
        colorscale='earth', opacity=0.92,
        name='Tile contour IDW surface',
        contours=dict(z=dict(show=True, size=10, color='saddlebrown', width=1)),
        showscale=True,
    ))

    # Raw OpenTopoData 50 m grid (toggle in legend for comparison)
    fig.add_trace(go.Surface(
        x=lx2d[0, :], y=ly2d[:, 0], z=zraw,
        colorscale='earth', opacity=0.92,
        name='Raw 50 m elevation grid',
        visible='legendonly',
        showscale=False,
    ))

    # Copernicus DEM LiDAR surface (toggle)
    route_key = next(k for k, v in ROUTES.items() if v is cfg)
    lidar_path = DATA_DIR / f'lidar_{route_key}.npz'
    if lidar_path.exists():
        ld = np.load(lidar_path)
        zlidar = ld['elev2d'] - cfg['base_ele']
        fig.add_trace(go.Surface(
            x=ld['lx2d'][0, :], y=ld['ly2d'][:, 0], z=zlidar,
            colorscale='earth', opacity=0.92,
            name='Copernicus DEM 30 m',
            visible='legendonly',
            showscale=False,
        ))

    # .fit GPS track from route JSON waypoints
    if cfg.get('route_json'):
        wps   = json.loads(Path(cfg['route_json']).read_text())['waypoints']
        wp_lx = np.array([w['local_x'] for w in wps])
        wp_ly = np.array([w['local_y'] for w in wps])
        wp_lz = np.array([w['local_z'] for w in wps])
        fig.add_trace(go.Scatter3d(
            x=wp_lx, y=wp_ly, z=wp_lz + 3,
            mode='lines',
            line=dict(color='red', width=4),
            name='.fit GPS track',
        ))

    fig.update_layout(
        title='OSM tile → terrain surface  (contour IDW vs raw elevation grid)',
        scene=dict(
            xaxis_title='East (m)',
            yaxis_title='North (m)',
            zaxis_title='Elev above base (m)',
            aspectmode='data',
        ),
        legend=dict(x=0.01, y=0.99),
    )

    out = Path('terrain_contour.html')
    fig.write_html(str(out))
    print(f"  → {out}  (open in browser)")


# ─── Entry point ─────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--route',    default='falkenberg', choices=list(ROUTES))
    ap.add_argument('--zoom',     type=int, default=14, help='Tile zoom level (14=overview, 15=better)')
    ap.add_argument('--all',      action='store_true', help='Run all stages')
    ap.add_argument('--download', action='store_true')
    ap.add_argument('--extract',  action='store_true')
    ap.add_argument('--elev',     action='store_true')
    ap.add_argument('--interp',   action='store_true')
    ap.add_argument('--lidar',     action='store_true', help='Download Copernicus DEM GLO-30 (~30 m)')
    ap.add_argument('--lidar-osm', action='store_true', help='OSM tile draped on LiDAR surface (plotly)')
    ap.add_argument('--plot',      action='store_true')
    args = ap.parse_args()

    cfg = ROUTES[args.route]
    do  = lambda flag: args.all or getattr(args, flag)

    if do('download'):
        print(f'\n── Download z{args.zoom} tiles ({args.route}) ──')
        download_tiles(cfg, args.zoom)
        stitch_tiles(args.zoom)

    if do('extract'):
        print(f'\n── Extract contours from z{args.zoom} ──')
        extract_contours(args.zoom)

    if do('elev'):
        print('\n── Elevation reference grid ──')
        fetch_elevation_grid(cfg)

    if do('interp'):
        print('\n── Label + IDW interpolation ──')
        pts = np.load(DATA_DIR / 'contour_pts.npy')
        print(f'  Labelling {len(pts):,} contour pts…')
        lx, ly, lz = label_contours(cfg, pts)
        print(f'  {len(lx):,} valid pts  lz {lz.min():.1f}–{lz.max():.1f} m')
        idw_surface(lx, ly, lz, cfg)

    if do('lidar'):
        print(f'\n── Copernicus DEM GLO-30 ({args.route}) ──')
        download_lidar(cfg)

    if args.lidar_osm:
        print(f'\n── OSM tile on LiDAR surface ({args.route}) ──')
        lidar_osm_surface(cfg)

    if do('plot'):
        print('\n── Plot ──')
        plot_surface(cfg)

    if not any([args.all, args.download, args.extract, args.elev,
                args.interp, args.lidar, args.lidar_osm, args.plot]):
        ap.print_help()


if __name__ == '__main__':
    main()
