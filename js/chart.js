'use strict';

// ── Chart data store ──────────────────────────────────────────────────────────
// One point per second, pushed by ui.js via pushChartPoint().
// { hr, power, np, cadence, target } — any may be null.
const chartData = [];

const ROLLING_SECS = 120;

// ── Layout constants (fractions of canvas height) ─────────────────────────────
const BAND = {
  power:   { top: 0.00, bot: 0.45 },
  hr:      { top: 0.47, bot: 0.78 },
  cadence: { top: 0.80, bot: 1.00 },
};

// ── Colours ───────────────────────────────────────────────────────────────────
const C = {
  power:   '#4fc3f7',
  np:      '#ff9800',
  hr:      '#ef5350',
  cadence: '#66bb6a',
  target:  'rgba(255,235,59,0.7)',
  grid:    'rgba(255,255,255,0.08)',
  label:   'rgba(255,255,255,0.45)',
  bg:      '#1a1a2e',
};

// HR zone %HRR thresholds → colour
const HR_ZONES = [
  { lo: 0,  hi: 50, colour: 'rgba(66,165,245,0.12)' },  // Z1 blue
  { lo: 50, hi: 60, colour: 'rgba(102,187,106,0.12)' }, // Z2 green
  { lo: 60, hi: 70, colour: 'rgba(255,238,88,0.12)' },  // Z3 yellow
  { lo: 70, hi: 80, colour: 'rgba(255,152,0,0.12)' },   // Z4 orange
  { lo: 80, hi: 101,colour: 'rgba(239,83,80,0.15)' },   // Z5 red
];

// ── RAF state ─────────────────────────────────────────────────────────────────
let _rafId      = null;
let _dirtyChart = false;

function pushChartPoint(hr, power, np, cadence, target) {
  chartData.push({ hr, power, np, cadence, target });
  _dirtyChart = true;
}

function startChartLoop() {
  if (_rafId) return;
  function frame() {
    if (_dirtyChart) {
      _dirtyChart = false;
      drawOverview();
      drawRolling();
    }
    _rafId = requestAnimationFrame(frame);
  }
  _rafId = requestAnimationFrame(frame);
}

function stopChartLoop() {
  if (_rafId) cancelAnimationFrame(_rafId);
  _rafId = null;
}

function clearChartData() {
  chartData.length = 0;
  _dirtyChart = true;
}

// ── Canvas helpers ────────────────────────────────────────────────────────────

function getCtx(id) {
  const canvas = document.getElementById(id);
  if (!canvas) return null;
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  if (canvas.width !== Math.round(rect.width * dpr) || canvas.height !== Math.round(rect.height * dpr)) {
    canvas.width  = Math.round(rect.width  * dpr);
    canvas.height = Math.round(rect.height * dpr);
    ctx.scale(dpr, dpr);
  }
  return { ctx, w: rect.width, h: rect.height };
}

// Fill canvas background
function fillBg(ctx, w, h) {
  ctx.fillStyle = C.bg;
  ctx.fillRect(0, 0, w, h);
}

// Pixel Y for a value within a band, given data min/max.
function valToY(v, vMin, vMax, band, h) {
  const range = vMax - vMin || 1;
  const frac  = 1 - (v - vMin) / range;   // 0=top, 1=bottom
  const top   = band.top * h;
  const bot   = band.bot * h;
  return top + frac * (bot - top);
}

// Draw horizontal grid lines and axis label inside a band.
function drawBandGrid(ctx, w, h, band, ticks, fmt, colour) {
  ctx.strokeStyle = C.grid;
  ctx.lineWidth   = 0.5;
  ctx.fillStyle   = C.label;
  ctx.font        = '9px monospace';
  ctx.textAlign   = 'left';

  const top = band.top * h;
  const bot = band.bot * h;
  for (const tick of ticks) {
    const y = valToY(tick, ticks[0], ticks[ticks.length - 1], band, h);
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
    ctx.fillText(fmt(tick), 2, Math.max(top + 9, Math.min(bot - 2, y - 2)));
  }
}

// Separator line between bands
function drawBandSeparator(ctx, w, h, frac) {
  ctx.strokeStyle = 'rgba(255,255,255,0.15)';
  ctx.lineWidth   = 1;
  ctx.beginPath();
  ctx.moveTo(0, frac * h);
  ctx.lineTo(w, frac * h);
  ctx.stroke();
}

// Draw a polyline from data arrays; xs/ys are pixel coords arrays.
function drawLine(ctx, xs, ys, colour, lineWidth) {
  if (xs.length < 2) return;
  ctx.strokeStyle = colour;
  ctx.lineWidth   = lineWidth;
  ctx.lineJoin    = 'round';
  ctx.beginPath();
  let started = false;
  for (let i = 0; i < xs.length; i++) {
    if (ys[i] === null) { started = false; continue; }
    if (!started) { ctx.moveTo(xs[i], ys[i]); started = true; }
    else           ctx.lineTo(xs[i], ys[i]);
  }
  ctx.stroke();
}

// ── HR zone background in HR band ────────────────────────────────────────────

function drawHRZoneBands(ctx, w, h, hrMin, hrMax) {
  const restHR = profile.restHR;
  const maxHR  = profile.maxHR;
  const hrr    = maxHR - restHR;

  for (const z of HR_ZONES) {
    const loHR = restHR + z.lo / 100 * hrr;
    const hiHR = restHR + z.hi / 100 * hrr;
    const y1   = valToY(Math.min(hrMax, hiHR), hrMin, hrMax, BAND.hr, h);
    const y2   = valToY(Math.max(hrMin, loHR), hrMin, hrMax, BAND.hr, h);
    if (y2 > y1) {
      ctx.fillStyle = z.colour;
      ctx.fillRect(0, y1, w, y2 - y1);
    }
  }
}

// ── Shared range calculators ──────────────────────────────────────────────────

function powerRange(data) {
  const vals = data.flatMap(d => [d.power, d.np]).filter(v => v != null);
  if (!vals.length) return { min: 0, max: 300 };
  const lo = Math.max(0, Math.min(...vals) - 20);
  const hi = Math.max(lo + 50, Math.max(...vals) + 20);
  return { min: lo, max: hi };
}

function hrRange(data) {
  const vals = data.map(d => d.hr).filter(v => v != null);
  if (!vals.length) return { min: 50, max: 180 };
  const lo = Math.max(30, Math.min(...vals) - 10);
  const hi = Math.max(lo + 20, Math.max(...vals) + 10);
  return { min: lo, max: hi };
}

function cadenceRange(data) {
  const vals = data.map(d => d.cadence).filter(v => v != null);
  if (!vals.length) return { min: 60, max: 110 };
  const lo = Math.max(0, Math.min(...vals) - 5);
  const hi = Math.max(lo + 20, Math.max(...vals) + 5);
  return { min: lo, max: hi };
}

// ── Overview chart (full session, compressed) ─────────────────────────────────

function drawOverview() {
  const c = getCtx('overview-canvas');
  if (!c) return;
  const { ctx, w, h } = c;
  fillBg(ctx, w, h);

  const data = chartData;
  if (!data.length) return;

  const pRange = powerRange(data);
  const hRange = hrRange(data);
  const cRange = cadenceRange(data);

  drawHRZoneBands(ctx, w, h, hRange.min, hRange.max);
  drawBandSeparator(ctx, w, h, BAND.hr.top);
  drawBandSeparator(ctx, w, h, BAND.cadence.top);

  // Map each data point to an x pixel
  const xs = data.map((_, i) => (i / Math.max(data.length - 1, 1)) * w);

  const pyPower   = data.map(d => d.power   != null ? valToY(d.power,   pRange.min, pRange.max, BAND.power,   h) : null);
  const pyNP      = data.map(d => d.np       != null ? valToY(d.np,      pRange.min, pRange.max, BAND.power,   h) : null);
  const pyHR      = data.map(d => d.hr       != null ? valToY(d.hr,      hRange.min, hRange.max, BAND.hr,      h) : null);
  const pyCadence = data.map(d => d.cadence  != null ? valToY(d.cadence, cRange.min, cRange.max, BAND.cadence, h) : null);
  const pyTarget  = data.map(d => d.target   != null ? valToY(d.target,  pRange.min, pRange.max, BAND.power,   h) : null);

  // Dashed target line
  ctx.setLineDash([4, 4]);
  drawLine(ctx, xs, pyTarget, C.target, 1);
  ctx.setLineDash([]);

  drawLine(ctx, xs, pyPower,   C.power,   1);
  drawLine(ctx, xs, pyNP,      C.np,      1.5);
  drawLine(ctx, xs, pyHR,      C.hr,      1);
  drawLine(ctx, xs, pyCadence, C.cadence, 1);

  // Time axis labels
  ctx.fillStyle = C.label;
  ctx.font      = '9px monospace';
  ctx.textAlign = 'center';
  const totalMin = Math.round(data.length / 60);
  if (totalMin > 0) {
    for (let m = 0; m <= totalMin; m += Math.max(1, Math.round(totalMin / 8))) {
      const x = (m / totalMin) * w;
      ctx.fillText(`${m}m`, x, h - 2);
    }
  }
}

// ── Rolling chart (last 120 s) ────────────────────────────────────────────────

function drawRolling() {
  const c = getCtx('rolling-canvas');
  if (!c) return;
  const { ctx, w, h } = c;
  fillBg(ctx, w, h);

  const data = chartData.slice(-ROLLING_SECS);
  if (!data.length) return;

  const pRange = powerRange(data);
  const hRange = hrRange(data);
  const cRange = cadenceRange(data);

  drawHRZoneBands(ctx, w, h, hRange.min, hRange.max);
  drawBandSeparator(ctx, w, h, BAND.hr.top);
  drawBandSeparator(ctx, w, h, BAND.cadence.top);

  // Fixed-width: each second is (w / ROLLING_SECS) pixels; right-aligned.
  const step = w / ROLLING_SECS;
  const offset = (ROLLING_SECS - data.length) * step;
  const xs = data.map((_, i) => offset + i * step);

  const pyPower   = data.map(d => d.power   != null ? valToY(d.power,   pRange.min, pRange.max, BAND.power,   h) : null);
  const pyNP      = data.map(d => d.np       != null ? valToY(d.np,      pRange.min, pRange.max, BAND.power,   h) : null);
  const pyHR      = data.map(d => d.hr       != null ? valToY(d.hr,      hRange.min, hRange.max, BAND.hr,      h) : null);
  const pyCadence = data.map(d => d.cadence  != null ? valToY(d.cadence, cRange.min, cRange.max, BAND.cadence, h) : null);
  const pyTarget  = data.map(d => d.target   != null ? valToY(d.target,  pRange.min, pRange.max, BAND.power,   h) : null);

  // Grid ticks for power band
  const pTicks = niceTicks(pRange.min, pRange.max, 4);
  drawBandGrid(ctx, w, h, BAND.power, pTicks, v => `${v}W`, C.grid);

  const hTicks = niceTicks(hRange.min, hRange.max, 3);
  drawBandGrid(ctx, w, h, BAND.hr, hTicks, v => `${v}`, C.grid);

  // Dashed target line
  ctx.setLineDash([4, 4]);
  drawLine(ctx, xs, pyTarget, C.target, 1.5);
  ctx.setLineDash([]);

  drawLine(ctx, xs, pyPower,   C.power,   1.5);
  drawLine(ctx, xs, pyNP,      C.np,      2);
  drawLine(ctx, xs, pyHR,      C.hr,      1.5);
  drawLine(ctx, xs, pyCadence, C.cadence, 1.5);

  // "Now" marker
  ctx.strokeStyle = 'rgba(255,255,255,0.25)';
  ctx.lineWidth   = 1;
  ctx.beginPath();
  ctx.moveTo(w - 1, 0);
  ctx.lineTo(w - 1, h);
  ctx.stroke();

  // Legend (top-right)
  const legend = [['Power', C.power], ['NP', C.np], ['HR', C.hr], ['Cad', C.cadence]];
  ctx.font      = '9px monospace';
  ctx.textAlign = 'right';
  legend.forEach(([lbl, col], i) => {
    ctx.fillStyle = col;
    ctx.fillText(lbl, w - 2, 12 + i * 12);
  });
}

// ── Power curve chart ─────────────────────────────────────────────────────────
// Log-scale x-axis (duration), linear y-axis (watts).
// mmpData / npData: [{dur, power}] from session.js calcMMP / calcNPCurve.

function drawPowerCurve() {
  const c = getCtx('power-curve-canvas');
  if (!c) return;
  const { ctx, w, h } = c;
  fillBg(ctx, w, h);

  const mmpData = calcMMP(samples);
  const npData  = calcNPCurve(samples);

  if (!mmpData.length) {
    ctx.fillStyle = C.label;
    ctx.font = '10px monospace';
    ctx.textAlign = 'center';
    ctx.fillText('No data yet', w / 2, h / 2);
    return;
  }

  const PAD = { top: 12, right: 8, bottom: 22, left: 36 };
  const cw  = w - PAD.left - PAD.right;
  const ch  = h - PAD.top  - PAD.bottom;

  // X: log scale over duration range
  const durMin = MMP_DURATIONS[0];
  const durMax = mmpData[mmpData.length - 1].dur;
  const logMin = Math.log10(durMin);
  const logMax = Math.log10(durMax);

  function xOf(dur) {
    return PAD.left + (Math.log10(dur) - logMin) / (logMax - logMin) * cw;
  }

  // Y: linear power range
  const allPowers = [...mmpData.map(d => d.power), ...npData.map(d => d.power)];
  const pMax = Math.max(...allPowers);
  const pMin = Math.max(0, Math.min(...allPowers) - 20);

  function yOf(p) {
    return PAD.top + ch - (p - pMin) / (pMax - pMin || 1) * ch;
  }

  // Y-axis grid lines
  const pTicks = niceTicks(pMin, pMax, 4);
  ctx.strokeStyle = C.grid;
  ctx.lineWidth   = 0.5;
  ctx.fillStyle   = C.label;
  ctx.font        = '9px monospace';
  ctx.textAlign   = 'right';
  for (const t of pTicks) {
    const y = yOf(t);
    ctx.beginPath(); ctx.moveTo(PAD.left, y); ctx.lineTo(w - PAD.right, y); ctx.stroke();
    ctx.fillText(`${t}`, PAD.left - 2, y + 3);
  }

  // X-axis duration labels
  const xLabels = [
    [1, '1s'], [5, '5s'], [10, '10s'], [30, '30s'],
    [60, '1m'], [120, '2m'], [300, '5m'], [600, '10m'],
    [1200, '20m'], [2400, '40m'], [3600, '1h'],
  ];
  ctx.fillStyle = C.label;
  ctx.textAlign = 'center';
  ctx.font      = '9px monospace';
  for (const [dur, lbl] of xLabels) {
    if (dur < durMin || dur > durMax) continue;
    const x = xOf(dur);
    ctx.beginPath(); ctx.moveTo(x, PAD.top); ctx.lineTo(x, PAD.top + ch); ctx.stroke();
    ctx.fillText(lbl, x, h - 4);
  }

  // MMP line
  ctx.strokeStyle = C.power;
  ctx.lineWidth   = 2;
  ctx.lineJoin    = 'round';
  ctx.beginPath();
  mmpData.forEach((d, i) => {
    const x = xOf(d.dur);
    const y = yOf(d.power);
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.stroke();

  // NP line (dashed, orange)
  if (npData.length >= 2) {
    ctx.strokeStyle = C.np;
    ctx.lineWidth   = 1.5;
    ctx.setLineDash([5, 3]);
    ctx.beginPath();
    npData.forEach((d, i) => {
      const x = xOf(d.dur);
      const y = yOf(d.power);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // FTP reference line
  if (profile.ftp) {
    const y = yOf(profile.ftp);
    if (y >= PAD.top && y <= PAD.top + ch) {
      ctx.strokeStyle = 'rgba(255,235,59,0.4)';
      ctx.lineWidth   = 1;
      ctx.setLineDash([3, 5]);
      ctx.beginPath(); ctx.moveTo(PAD.left, y); ctx.lineTo(w - PAD.right, y); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = 'rgba(255,235,59,0.6)';
      ctx.textAlign = 'left';
      ctx.fillText('FTP', PAD.left + 2, y - 2);
    }
  }

  // Legend
  ctx.font = '9px monospace';
  ctx.textAlign = 'left';
  ctx.fillStyle = C.power; ctx.fillText('MMP', PAD.left + 2, PAD.top + 10);
  ctx.fillStyle = C.np;    ctx.fillText('NP',  PAD.left + 2, PAD.top + 20);
}

// ── Utility: nice tick values ─────────────────────────────────────────────────

function niceTicks(lo, hi, n) {
  const range = hi - lo;
  const step  = Math.pow(10, Math.floor(Math.log10(range / n)));
  const nice  = [1, 2, 5, 10].map(f => f * step).find(s => range / s <= n + 1) || step;
  const start = Math.ceil(lo / nice) * nice;
  const ticks = [];
  for (let v = start; v <= hi + 0.001; v += nice) ticks.push(Math.round(v));
  return ticks;
}
