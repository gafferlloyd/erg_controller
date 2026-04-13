'use strict';

// ── HR vs Power scatter plot ───────────────────────────────────────────────────
// Draws each session sample as a dot: Power on X-axis, HR on Y-axis.
// Dots fade from muted (oldest) to bright red (newest).
// Depends on globals from: chart.js (getCtx, fillBg, C, HR_ZONES, niceTicks)
//                          session.js (samples)
//                          profile.js (profile)

function drawHRPower() {
  const c = getCtx('hr-power-canvas');
  if (!c) return;
  const { ctx, w, h } = c;

  fillBg(ctx, w, h);

  const valid = samples.filter(s => s.hr > 0 && s.power != null && s.power > 0);

  if (!valid.length) {
    ctx.fillStyle = C.label;
    ctx.font      = '10px monospace';
    ctx.textAlign = 'center';
    ctx.fillText('No data yet', w / 2, h / 2);
    return;
  }

  const PAD = { top: 12, right: 8, bottom: 22, left: 36 };
  const cw  = w - PAD.left - PAD.right;
  const ch  = h - PAD.top  - PAD.bottom;

  const pVals = valid.map(s => s.power);
  const hVals = valid.map(s => s.hr);
  const pMin  = Math.max(0,  Math.min(...pVals) - 20);
  const pMax  = Math.max(pMin + 50, Math.max(...pVals) + 20);
  const hMin  = Math.max(30, Math.min(...hVals) - 10);
  const hMax  = Math.max(hMin + 20, Math.max(...hVals) + 10);

  function xOf(p) { return PAD.left + (p - pMin) / (pMax - pMin) * cw; }
  function yOf(v) { return PAD.top  + ch - (v - hMin) / (hMax - hMin) * ch; }

  // HR zone horizontal bands
  const hrr = profile.maxHR - profile.restHR;
  for (const z of HR_ZONES) {
    const loHR = profile.restHR + z.lo / 100 * hrr;
    const hiHR = profile.restHR + z.hi / 100 * hrr;
    const y1   = yOf(Math.min(hMax, hiHR));
    const y2   = yOf(Math.max(hMin, loHR));
    if (y2 > y1) {
      ctx.fillStyle = z.colour;
      ctx.fillRect(PAD.left, y1, cw, y2 - y1);
    }
  }

  // Grid lines
  ctx.strokeStyle = C.grid;
  ctx.lineWidth   = 0.5;
  ctx.fillStyle   = C.label;
  ctx.font        = '9px monospace';

  ctx.textAlign = 'right';
  for (const t of niceTicks(hMin, hMax, 4)) {
    const y = yOf(t);
    ctx.beginPath(); ctx.moveTo(PAD.left, y); ctx.lineTo(PAD.left + cw, y); ctx.stroke();
    ctx.fillText(`${t}`, PAD.left - 2, y + 3);
  }
  ctx.textAlign = 'center';
  for (const t of niceTicks(pMin, pMax, 4)) {
    const x = xOf(t);
    ctx.beginPath(); ctx.moveTo(x, PAD.top); ctx.lineTo(x, PAD.top + ch); ctx.stroke();
    ctx.fillText(`${t}`, x, h - 4);
  }

  // Scatter dots — older = faint, newer = bright
  const n = valid.length;
  valid.forEach((s, i) => {
    const alpha = (0.2 + (i / Math.max(n - 1, 1)) * 0.8).toFixed(2);
    ctx.fillStyle = `rgba(239,83,80,${alpha})`;
    ctx.beginPath();
    ctx.arc(xOf(s.power), yOf(s.hr), 2.5, 0, Math.PI * 2);
    ctx.fill();
  });

  // Axis label
  ctx.fillStyle = C.label;
  ctx.font      = '9px monospace';
  ctx.textAlign = 'center';
  ctx.fillText('Power (W)', PAD.left + cw / 2, h - 4);
}
