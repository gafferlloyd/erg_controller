'use strict';

// ── W' balance (Skiba 2015 differential model) ────────────────────────────────
// Returns an array of wbal values (joules), one per sample.
// cp:     critical power (watts) — use profile.ftp as proxy
// wprime: total anaerobic capacity (joules)

function calcWbal(sampleArr, cp, wprime) {
  if (!sampleArr.length || !cp || !wprime) return [];
  let wbal = wprime;
  return sampleArr.map(s => {
    const p = s.power ?? 0;
    if (p >= cp) {
      wbal -= (p - cp);
    } else {
      const dcp = cp - p;
      const tau = 546 * Math.exp(-0.01 * dcp) + 316;
      wbal = wprime - (wprime - wbal) * Math.exp(-1 / tau);
    }
    wbal = Math.max(0, Math.min(wprime, wbal));
    return wbal;
  });
}

// ── W'bal chart ───────────────────────────────────────────────────────────────
// Full-session time-compressed overview, drawn on #wbal-canvas.
// Colour zones: green ≥75 %, amber 25–75 %, red <25 %.

function drawWbalChart() {
  const c = getCtx('wbal-canvas');
  if (!c) return;
  const { ctx, w, h } = c;
  fillBg(ctx, w, h);

  const wprime = profile.wprime || 20000;
  const cp     = profile.ftp   || 250;
  const wbalArr = calcWbal(samples, cp, wprime);

  if (!wbalArr.length) {
    ctx.fillStyle = C.label;
    ctx.font = '9px monospace';
    ctx.textAlign = 'left';
    ctx.fillText("W'bal", 4, 12);
    return;
  }

  const PAD = { top: 14, right: 42, bottom: 16, left: 32 };
  const cw = w - PAD.left - PAD.right;
  const ch = h - PAD.top  - PAD.bottom;

  // Zone fills (bottom to top: red, amber, green)
  const zones = [
    { lo: 0,    hi: 0.25, colour: 'rgba(239,83,80,0.15)' },
    { lo: 0.25, hi: 0.75, colour: 'rgba(255,152,0,0.12)' },
    { lo: 0.75, hi: 1.00, colour: 'rgba(102,187,106,0.12)' },
  ];
  for (const z of zones) {
    const y1 = PAD.top + ch * (1 - z.hi);
    const y2 = PAD.top + ch * (1 - z.lo);
    ctx.fillStyle = z.colour;
    ctx.fillRect(PAD.left, y1, cw, y2 - y1);
  }

  // Grid lines at 25 %, 50 %, 75 %, 100 %
  ctx.strokeStyle = C.grid;
  ctx.lineWidth   = 0.5;
  ctx.fillStyle   = C.label;
  ctx.font        = '9px monospace';
  ctx.textAlign   = 'right';
  for (const frac of [0.25, 0.50, 0.75, 1.00]) {
    const y = PAD.top + ch * (1 - frac);
    ctx.beginPath(); ctx.moveTo(PAD.left, y); ctx.lineTo(PAD.left + cw, y); ctx.stroke();
    const kj = (wprime * frac / 1000).toFixed(0);
    ctx.fillText(`${kj}`, PAD.left - 2, y + 3);
  }

  // X-axis time labels
  const n = wbalArr.length;
  ctx.fillStyle = C.label;
  ctx.textAlign = 'center';
  const totalMin = Math.round(n / 60);
  if (totalMin > 0) {
    for (let m = 0; m <= totalMin; m += Math.max(1, Math.round(totalMin / 6))) {
      const x = PAD.left + (m / totalMin) * cw;
      ctx.fillText(`${m}m`, x, h - 3);
    }
  }

  // W'bal polyline — colour by current level
  const xs = wbalArr.map((_, i) => PAD.left + (i / Math.max(n - 1, 1)) * cw);
  const ys = wbalArr.map(v => PAD.top + ch * (1 - v / wprime));

  ctx.strokeStyle = 'rgba(255,255,255,0.8)';
  ctx.lineWidth   = 1.5;
  ctx.lineJoin    = 'round';
  ctx.beginPath();
  xs.forEach((x, i) => i === 0 ? ctx.moveTo(x, ys[i]) : ctx.lineTo(x, ys[i]));
  ctx.stroke();

  // Current value annotation
  const cur = wbalArr[wbalArr.length - 1];
  const pct = cur / wprime;
  const annColour = pct >= 0.75 ? '#66bb6a' : pct >= 0.25 ? '#ff9800' : '#ef5350';
  ctx.fillStyle   = annColour;
  ctx.font        = 'bold 10px monospace';
  ctx.textAlign   = 'left';
  ctx.fillText(`${(cur / 1000).toFixed(1)}kJ`, PAD.left + cw + 3, PAD.top + ch * (1 - pct) + 4);

  // Title
  ctx.fillStyle = C.label;
  ctx.font      = '9px monospace';
  ctx.textAlign = 'left';
  ctx.fillText("W'bal", PAD.left + 2, PAD.top - 2);
}
