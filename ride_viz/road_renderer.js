'use strict';

// Render resolution — scale up with CSS image-rendering: pixelated for 8-bit look
const W_RENDER = 320;
const H_RENDER = 180;

// Road geometry
const SEGMENTS      = 120;    // strips drawn (each = SEG_LEN_M metres of road)
const SEG_LEN_M     = 5;      // metres per strip
const ROAD_BASE_W   = 0.70;   // road width as fraction of W_RENDER at bottom of screen
const FOCAL_SCALE   = W_RENDER / 80;  // pixels per degree of heading diff (80° = screen edge)
const HILL_SCALE    = 0.0025; // horizon shift per % grade

// Strict 16-colour palette
const C = {
  skyTop:     '#3355aa',
  skyBot:     '#5577cc',
  grassA:     '#2d6e1a',
  grassB:     '#357a1f',
  roadA:      '#555555',
  roadB:      '#666666',
  rumbleRed:  '#bb3322',
  rumbleWht:  '#dddddd',
  dash:       '#eeee44',
  treeTrunk:  '#6b3c11',
  treeLeafD:  '#1a5c0a',
  treeLeafL:  '#2a7a18',
  houseWall:  '#ccc098',
  houseRoof:  '#993322',
  houseWin:   '#223355',
  avatarMain: '#ee6611',
  avatarDark: '#220000',
  hudBg:      '#00000088',
  hudText:    '#ffffff',
};

function deltaAngle(a, b) {
  // Returns a - b wrapped to [-180, 180]
  let d = a - b;
  while (d > 180)  d -= 360;
  while (d < -180) d += 360;
  return d;
}

class RoadRenderer {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx    = canvas.getContext('2d');
    // Force internal resolution
    canvas.width  = W_RENDER;
    canvas.height = H_RENDER;
  }

  // state: { dist_m, total_dist_m, grade_pct, speed_mps, waypoints_ahead, scenery_ahead }
  update(state) {
    const ctx = this.ctx;
    const wps    = state.waypoints_ahead || [];
    const scenery = state.scenery_ahead  || [];

    // Smooth grade from next 100m (20 waypoints) to avoid jitter
    let avgGrade = state.grade_pct || 0;
    if (wps.length >= 20) {
      avgGrade = wps.slice(0, 20).reduce((s, w) => s + w.grade_pct, 0) / 20;
    }
    const horizonY = Math.round(H_RENDER * 0.40 - avgGrade * HILL_SCALE * H_RENDER);

    // Build strip geometry (project road using heading-relative angles)
    const strips = this._buildStrips(wps, horizonY);

    this._drawSky(horizonY);
    this._drawGround(strips, horizonY);
    this._drawRoad(strips);
    this._drawScenery(strips, scenery, state.dist_m || 0);
    this._drawAvatar();
    this._drawHUD(state, avgGrade);
  }

  _buildStrips(wps, horizonY) {
    const currentHeading = (wps[0] && wps[0].heading_deg) || 0;
    const strips = [];

    for (let i = 0; i < SEGMENTS; i++) {
      const wp = wps[Math.min(i, wps.length - 1)] || { heading_deg: currentHeading };

      // t=1 → nearest (bottom of screen), t→0 → farthest (horizon)
      const t     = (SEGMENTS - i) / SEGMENTS;
      const tNext = (SEGMENTS - i - 1) / SEGMENTS;

      // Screen Y
      const yBot = Math.round(horizonY + t     * (H_RENDER - horizonY));
      const yTop = Math.round(horizonY + tNext * (H_RENDER - horizonY));

      // Road half-width: linear perspective
      const hw  = Math.round((W_RENDER * ROAD_BASE_W * 0.5) * t);
      const hwN = Math.round((W_RENDER * ROAD_BASE_W * 0.5) * tNext);

      // Centre X: near strips stay centred (we're on the road), far strips
      // shift by the heading difference — (1-t) is 0 at bottom, 1 at horizon.
      const hDiff = deltaAngle(wp.heading_deg, currentHeading);
      const cx    = Math.round(W_RENDER * 0.5 + hDiff * FOCAL_SCALE * (1 - t));

      const distAhead = (SEGMENTS - i) * SEG_LEN_M;

      strips.push({ i, yBot, yTop, cx, hw, hwN, t, distAhead });
    }
    return strips;
  }

  _drawSky(horizonY) {
    const ctx = this.ctx;
    const mid = Math.round(horizonY * 0.5);
    ctx.fillStyle = C.skyTop;
    ctx.fillRect(0, 0, W_RENDER, mid);
    ctx.fillStyle = C.skyBot;
    ctx.fillRect(0, mid, W_RENDER, horizonY - mid);
  }

  _drawGround(strips, horizonY) {
    const ctx = this.ctx;
    // Fill ground below horizon first
    ctx.fillStyle = C.grassA;
    ctx.fillRect(0, horizonY, W_RENDER, H_RENDER - horizonY);

    // Alternating grass bands (perspective stripes for depth)
    const bands = 5;
    for (let b = 0; b < bands; b++) {
      const t0 = b / bands, t1 = (b + 1) / bands;
      const y0 = Math.round(horizonY + t0 * (H_RENDER - horizonY));
      const y1 = Math.round(horizonY + t1 * (H_RENDER - horizonY));
      ctx.fillStyle = b % 2 === 0 ? C.grassA : C.grassB;
      ctx.fillRect(0, y0, W_RENDER, y1 - y0);
    }
  }

  _drawRoad(strips) {
    const ctx = this.ctx;
    for (let i = strips.length - 1; i >= 1; i--) {
      const s  = strips[i];
      const sN = strips[i - 1];   // one strip closer to horizon
      if (s.yBot <= s.yTop) continue;

      const even   = Math.floor(i / 2) % 2 === 0;
      const rumble = Math.floor(i / 3) % 2 === 0;
      const rw     = Math.max(1, Math.round(s.hw * 0.09));

      // Road surface
      ctx.fillStyle = even ? C.roadA : C.roadB;
      ctx.beginPath();
      ctx.moveTo(s.cx  - s.hw,   s.yBot);
      ctx.lineTo(s.cx  + s.hw,   s.yBot);
      ctx.lineTo(sN.cx + sN.hwN, sN.yTop);
      ctx.lineTo(sN.cx - sN.hwN, sN.yTop);
      ctx.closePath();
      ctx.fill();

      // Left rumble strip
      const rc = rumble ? C.rumbleRed : C.rumbleWht;
      ctx.fillStyle = rc;
      ctx.beginPath();
      ctx.moveTo(s.cx  - s.hw,        s.yBot);
      ctx.lineTo(s.cx  - s.hw + rw,   s.yBot);
      ctx.lineTo(sN.cx - sN.hwN + rw, sN.yTop);
      ctx.lineTo(sN.cx - sN.hwN,      sN.yTop);
      ctx.closePath();
      ctx.fill();

      // Right rumble strip
      ctx.beginPath();
      ctx.moveTo(s.cx  + s.hw - rw,   s.yBot);
      ctx.lineTo(s.cx  + s.hw,        s.yBot);
      ctx.lineTo(sN.cx + sN.hwN,      sN.yTop);
      ctx.lineTo(sN.cx + sN.hwN - rw, sN.yTop);
      ctx.closePath();
      ctx.fill();

      // Centre dashes (every 4 strips)
      if (even && i % 4 < 2) {
        const dw = Math.max(1, Math.round(s.hw * 0.03));
        ctx.fillStyle = C.dash;
        ctx.beginPath();
        ctx.moveTo(s.cx  - dw, s.yBot);
        ctx.lineTo(s.cx  + dw, s.yBot);
        ctx.lineTo(sN.cx + dw, sN.yTop);
        ctx.lineTo(sN.cx - dw, sN.yTop);
        ctx.closePath();
        ctx.fill();
      }
    }
  }

  _drawScenery(strips, scenery, currentDist) {
    if (!scenery.length || !strips.length) return;

    // Sort far→near so nearer sprites overdraw distant ones
    const visible = scenery
      .map(sc => ({ ...sc, rel: sc.dist_m - currentDist }))
      .filter(sc => sc.rel > SEG_LEN_M && sc.rel < SEGMENTS * SEG_LEN_M)
      .sort((a, b) => b.rel - a.rel);

    for (const sc of visible) {
      // Find which strip this scenery item falls in
      const stripIdx = Math.min(
        strips.length - 1,
        Math.max(0, Math.round(SEGMENTS - sc.rel / SEG_LEN_M))
      );
      const s = strips[stripIdx];
      if (!s || s.yBot <= s.yTop) continue;

      // X position: off to the side of the road edge
      const offPx = Math.round(sc.offset_m * s.hw * 0.18);
      const x = sc.side === 'right'
        ? s.cx + s.hw + offPx
        : s.cx - s.hw - offPx;

      const baseY = s.yBot;

      if (sc.type === 'tree') {
        this._drawTree(x, baseY, s.t);
      } else {
        this._drawHouse(x, baseY, s.t);
      }
    }
  }

  _drawTree(x, baseY, scale) {
    const ctx = this.ctx;
    const h   = Math.max(3, Math.round(28 * scale));
    const tw  = Math.max(1, Math.round(h * 0.14));
    const th  = Math.round(h * 0.35);
    const lw  = Math.max(2, Math.round(h * 0.55));
    const lh  = Math.round(h * 0.70);

    // Trunk
    ctx.fillStyle = C.treeTrunk;
    ctx.fillRect(Math.round(x - tw / 2), baseY - th, tw, th);

    // Foliage — two rectangular layers (Minecraft block style)
    ctx.fillStyle = C.treeLeafD;
    ctx.fillRect(Math.round(x - lw / 2), baseY - th - lh, lw, Math.round(lh * 0.6));
    ctx.fillStyle = C.treeLeafL;
    const topW = Math.round(lw * 0.65);
    ctx.fillRect(Math.round(x - topW / 2), baseY - th - lh - Math.round(lh * 0.35), topW, Math.round(lh * 0.45));
  }

  _drawHouse(x, baseY, scale) {
    const ctx = this.ctx;
    const w    = Math.max(4, Math.round(24 * scale));
    const wallH = Math.round(w * 0.70);
    const roofH = Math.round(w * 0.40);

    // Wall
    ctx.fillStyle = C.houseWall;
    ctx.fillRect(Math.round(x - w / 2), baseY - wallH, w, wallH);

    // Roof (flat rectangle, slightly wider — Minecraft style, no triangles)
    ctx.fillStyle = C.houseRoof;
    ctx.fillRect(Math.round(x - w / 2 - 1), baseY - wallH - roofH, w + 2, roofH);

    // Windows (only if large enough to be visible)
    if (w >= 8) {
      const winS = Math.max(1, Math.round(w * 0.18));
      ctx.fillStyle = C.houseWin;
      ctx.fillRect(Math.round(x - w * 0.3), baseY - wallH + Math.round(wallH * 0.3), winS, winS);
      ctx.fillRect(Math.round(x + w * 0.1), baseY - wallH + Math.round(wallH * 0.3), winS, winS);
    }
  }

  _drawAvatar() {
    const ctx = this.ctx;
    // Pixel-art cyclist — blocky rectangles only
    const cx  = Math.round(W_RENDER / 2);
    const cy  = Math.round(H_RENDER * 0.82);

    // Wheels (squares, not circles)
    ctx.fillStyle = C.avatarDark;
    ctx.fillRect(cx + 9, cy - 7,  8, 8);   // rear wheel
    ctx.fillRect(cx - 17, cy - 7, 8, 8);   // front wheel

    // Frame
    ctx.fillStyle = C.avatarMain;
    ctx.fillRect(cx - 9,  cy - 11, 18, 5);   // top tube
    ctx.fillRect(cx - 2,  cy - 20, 5,  12);  // seat tube
    ctx.fillRect(cx + 7,  cy - 15, 3,  9);   // fork

    // Torso (leaning forward)
    ctx.fillRect(cx - 3, cy - 26, 7, 10);

    // Head
    ctx.fillStyle = '#ffcc88';
    ctx.fillRect(cx - 2, cy - 33, 6, 7);

    // Helmet
    ctx.fillStyle = '#2244aa';
    ctx.fillRect(cx - 3, cy - 35, 7, 4);
  }

  _drawHUD(state, avgGrade) {
    const ctx   = this.ctx;
    const grade = avgGrade.toFixed(1);
    const speed = ((state.speed_mps || 0) * 3.6).toFixed(0);
    const dist  = ((state.dist_m || 0) / 1000).toFixed(2);
    const total = ((state.total_dist_m || 0) / 1000).toFixed(1);
    const sign  = avgGrade >= 0 ? '+' : '';

    ctx.fillStyle = C.hudBg;
    ctx.fillRect(2, 2, 118, 22);
    ctx.fillStyle = C.hudText;
    ctx.font = '8px monospace';
    ctx.fillText(`${dist}/${total}km  ${speed}km/h`, 5, 12);
    ctx.fillText(`grade: ${sign}${grade}%`, 5, 22);
  }
}
