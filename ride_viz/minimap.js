'use strict';

// OSM tile picture-in-picture minimap
// If the route JSON contains minimap_meta (pre-stitched PNG), uses that for smooth
// full-ride display.  Falls back to live single-tile fetching when not present.

const ZOOM      = 15;   // OSM zoom level — ~1.22km tile at 48°N (fallback mode)
const MAP_SIZE  = 180;  // canvas px
const UPDATE_DIST_M = 50; // redraw only when moved this far

export class Minimap {
  constructor(canvas) {
    this._canvas  = canvas;
    this._ctx     = canvas.getContext('2d');
    this._route   = null;
    this._tile    = null;   // { img, tx, ty, originLat, originLon, degPerPxLat, degPerPxLon }
    this._static  = null;   // { img, origin_lat, origin_lon, deg_per_px_lat, deg_per_px_lon }
    this._lastDist = -9999;
    this._pendingFetch = false;

    canvas.width  = MAP_SIZE;
    canvas.height = MAP_SIZE;
  }

  load(route) {
    this._route    = route;
    this._lastDist = -9999;
    this._tile     = null;
    this._static   = null;
    const meta = route.minimap_meta;
    if (meta) {
      const img = new Image();
      img.crossOrigin = 'anonymous';
      img.onload = () => { this._static = { img, ...meta }; };
      // minimap PNG is served from the same routes/ directory as the JSON
      img.src = `routes/${meta.url}`;
    }
  }

  update(state) {
    if (!this._route) return;
    if (Math.abs(state.dist_m - this._lastDist) < UPDATE_DIST_M) return;
    this._lastDist = state.dist_m;

    const wp = this._waypointAt(state.dist_m);

    // Static stitched image — pan to current position, no tile fetching
    if (this._static) {
      this._drawStatic(wp.lat, wp.lon);
      return;
    }

    // Fallback: live tile fetching
    const { tx, ty } = latLonToTile(wp.lat, wp.lon, ZOOM);
    if (!this._tile || this._tile.tx !== tx || this._tile.ty !== ty) {
      this._fetchTile(tx, ty, wp.lat, wp.lon, state.dist_m);
    } else {
      this._draw(wp.lat, wp.lon);
    }
  }

  _waypointAt(dist) {
    const wps = this._route.waypoints;
    let lo = 0, hi = wps.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (wps[mid].dist_m <= dist) lo = mid; else hi = mid - 1;
    }
    return wps[lo];
  }

  // ---------------------------------------------------------------------------
  // Static stitched-image mode
  // ---------------------------------------------------------------------------

  _drawStatic(lat, lon) {
    const { img, origin_lat, origin_lon, deg_per_px_lat, deg_per_px_lon } = this._static;
    const ctx = this._ctx, S = MAP_SIZE;
    ctx.clearRect(0, 0, S, S);

    // How many metres does the full stitched image span in longitude?
    const imgDegreesLon   = img.width * deg_per_px_lon;
    const groundMetersLon = Math.abs(imgDegreesLon) * Math.cos(lat * Math.PI / 180) * 111320;
    // Scale so ~1.2 km of ground fills the 180 px canvas
    const SHOW_M = 1200;
    const scale  = S / img.width * (groundMetersLon / SHOW_M);

    // Pixel coords of current position within stitched image
    const tpxX = (lon - origin_lon) / deg_per_px_lon;
    const tpxY = (lat - origin_lat) / deg_per_px_lat;

    const imgX = S / 2 - tpxX * scale;
    const imgY = S / 2 - tpxY * scale;
    ctx.drawImage(img, imgX, imgY, img.width * scale, img.height * scale);

    // Position dot
    ctx.beginPath();
    ctx.arc(S / 2, S / 2, 5, 0, Math.PI * 2);
    ctx.fillStyle   = '#ffffff';
    ctx.strokeStyle = '#333';
    ctx.lineWidth   = 1.5;
    ctx.fill();
    ctx.stroke();
  }

  // ---------------------------------------------------------------------------
  // Live single-tile mode (fallback)
  // ---------------------------------------------------------------------------

  _fetchTile(tx, ty, lat, lon, dist) {
    if (this._pendingFetch) return;
    this._pendingFetch = true;

    const url = `https://tile.openstreetmap.org/${ZOOM}/${tx}/${ty}.png`;
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => {
      this._pendingFetch = false;
      const { lat: tLat, lon: tLon } = tileToLatLon(tx, ty, ZOOM);
      const tileSpanLon = 360 / (2 ** ZOOM);
      const tileSpanLat = tileToLatLon(tx, ty+1, ZOOM).lat - tLat;
      this._tile = {
        img, tx, ty,
        originLat: tLat,
        originLon: tLon,
        degPerPxLat: tileSpanLat / 256,
        degPerPxLon: tileSpanLon / 256,
      };
      this._draw(lat, lon);
    };
    img.onerror = () => { this._pendingFetch = false; };
    img.src = url;
  }

  _draw(centerLat, centerLon) {
    if (!this._tile) return;
    const ctx = this._ctx;
    const t   = this._tile;
    const S   = MAP_SIZE;

    ctx.clearRect(0, 0, S, S);

    const tpxX = (centerLon - t.originLon) / t.degPerPxLon;
    const tpxY = (centerLat - t.originLat) / t.degPerPxLat;
    const scaleX = S / 256;
    const scaleY = S / 256;
    const imgX = S / 2 - tpxX * scaleX;
    const imgY = S / 2 - tpxY * scaleY;
    ctx.drawImage(t.img, imgX, imgY, S, S);

    const toCanvas = (lat, lon) => ({
      x: imgX + (lon - t.originLon) / t.degPerPxLon * scaleX,
      y: imgY + (lat - t.originLat) / t.degPerPxLat * scaleY,
    });

    ctx.beginPath();
    ctx.strokeStyle = '#ee4422';
    ctx.lineWidth   = 2;
    const wps = this._route.waypoints;
    let started = false;
    for (let i = 0; i < wps.length; i += 5) {
      const { x, y } = toCanvas(wps[i].lat, wps[i].lon);
      if (x < -10 || x > S + 10 || y < -10 || y > S + 10) { started = false; continue; }
      started ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
      started = true;
    }
    ctx.stroke();

    ctx.beginPath();
    ctx.arc(S / 2, S / 2, 5, 0, Math.PI * 2);
    ctx.fillStyle   = '#ffffff';
    ctx.strokeStyle = '#333';
    ctx.lineWidth   = 1.5;
    ctx.fill();
    ctx.stroke();
  }
}

// ---------------------------------------------------------------------------
// Tile math
// ---------------------------------------------------------------------------

function latLonToTile(lat, lon, zoom) {
  const n = 2 ** zoom;
  const x = Math.floor((lon + 180) / 360 * n);
  const latRad = lat * Math.PI / 180;
  const y = Math.floor((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2 * n);
  return { tx: x, ty: y };
}

function tileToLatLon(tx, ty, zoom) {
  const n = 2 ** zoom;
  const lon = tx / n * 360 - 180;
  const latRad = Math.atan(Math.sinh(Math.PI * (1 - 2 * ty / n)));
  return { lat: latRad * 180 / Math.PI, lon };
}
