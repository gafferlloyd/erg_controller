'use strict';

const LOOKAHEAD_COUNT = 80;  // waypoints ahead to send to renderer

class RidePlayer {
  constructor(renderer, ui) {
    this.renderer = renderer;
    this.ui       = ui;
    this.route    = null;

    this.playing    = false;
    this.speedMult  = 1;
    this.distM      = 0;
    this.lastTime   = null;
    this._rafId     = null;
  }

  load(route) {
    this.route  = route;
    this.distM  = 0;
    this.playing = false;
    this.lastTime = null;
    this.ui.onLoad(route);
    this._render();
  }

  play()  { if (!this.route) return; this.playing = true;  this.lastTime = null; this._tick(); }
  pause() { this.playing = false; if (this._rafId) { cancelAnimationFrame(this._rafId); this._rafId = null; } }
  toggle() { this.playing ? this.pause() : this.play(); }

  setSpeedMult(m) { this.speedMult = m; }

  seekFraction(f) {
    if (!this.route) return;
    this.distM = f * this.route.total_dist_m;
    this._render();
  }

  _tick() {
    this._rafId = requestAnimationFrame((now) => {
      if (!this.playing) return;

      if (this.lastTime !== null) {
        const dt = (now - this.lastTime) / 1000;  // seconds
        const speed = this._currentSpeed() * this.speedMult;
        this.distM = Math.min(
          this.route.total_dist_m,
          this.distM + speed * dt
        );
      }
      this.lastTime = now;

      this._render();
      this.ui.onProgress(this.distM, this.route.total_dist_m);

      if (this.distM >= this.route.total_dist_m) {
        this.pause();
        this.ui.onFinish();
        return;
      }
      this._tick();
    });
  }

  _currentSpeed() {
    if (!this.route) return 5;
    const wp = this._interpolateWaypoint(this.distM);
    return Math.max(wp.speed_mps, 2.0);   // at least 2 m/s (7 km/h) to keep moving
  }

  // Binary search for waypoint index at given dist_m
  _wpIndex(dist) {
    const wps = this.route.waypoints;
    let lo = 0, hi = wps.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (wps[mid].dist_m <= dist) lo = mid; else hi = mid - 1;
    }
    return lo;
  }

  _interpolateWaypoint(dist) {
    const wps = this.route.waypoints;
    const i = this._wpIndex(dist);
    if (i >= wps.length - 1) return wps[wps.length - 1];
    const a = wps[i], b = wps[i + 1];
    const t = (b.dist_m - a.dist_m) > 0
      ? (dist - a.dist_m) / (b.dist_m - a.dist_m)
      : 0;
    return {
      dist_m:      dist,
      lat:         a.lat      + t * (b.lat      - a.lat),
      lon:         a.lon      + t * (b.lon      - a.lon),
      ele_m:       a.ele_m    + t * (b.ele_m    - a.ele_m),
      grade_pct:   a.grade_pct + t * (b.grade_pct - a.grade_pct),
      heading_deg: a.heading_deg + t * (b.heading_deg - a.heading_deg),
      curve_dpm:   a.curve_dpm  + t * (b.curve_dpm  - a.curve_dpm),
      speed_mps:   a.speed_mps  + t * (b.speed_mps  - a.speed_mps),
    };
  }

  _lookahead(dist) {
    const wps = this.route.waypoints;
    const startIdx = this._wpIndex(dist);
    return wps.slice(startIdx, startIdx + LOOKAHEAD_COUNT);
  }

  _sceneryAhead(dist) {
    const sc = this.route.scenery;
    if (!sc || !sc.length) return [];
    // Binary search for first scenery item >= dist
    let lo = 0, hi = sc.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (sc[mid].dist_m < dist) lo = mid + 1; else hi = mid;
    }
    const horizon = dist + LOOKAHEAD_COUNT * 5;   // 5m per strip
    const out = [];
    for (let i = lo; i < sc.length && sc[i].dist_m <= horizon; i++) {
      out.push(sc[i]);
    }
    return out;
  }

  _render() {
    if (!this.route) return;
    const wp = this._interpolateWaypoint(this.distM);
    const state = {
      dist_m:         this.distM,
      total_dist_m:   this.route.total_dist_m,
      grade_pct:      wp.grade_pct,
      heading_deg:    wp.heading_deg,
      speed_mps:      wp.speed_mps * this.speedMult,
      waypoints_ahead: this._lookahead(this.distM),
      scenery_ahead:   this._sceneryAhead(this.distM),
    };
    this.renderer.update(state);
  }
}
