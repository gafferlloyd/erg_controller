'use strict';

// ══════════════════════════════════════════════════════
//  HR & Power time-series chart  (600 pts @ 1 s = 10 min)
// ══════════════════════════════════════════════════════
const HIST = 600;
const chartHR  = new Array(HIST).fill(null);
const chartPwr = new Array(HIST).fill(null);
const chartTgt = new Array(HIST).fill(null);
let   chartTimer = null;

function sampleChart() {
  const targetHR = parseInt(document.getElementById('target-hr').value);
  chartHR.push(lastHR);     chartHR.shift();
  chartPwr.push(lastPower); chartPwr.shift();
  chartTgt.push(targetHR);  chartTgt.shift();
  drawChart();
}

function drawChart() {
  const canvas = document.getElementById('chart');
  const W = canvas.offsetWidth, H = 220;
  if (canvas.width !== W || canvas.height !== H) { canvas.width = W; canvas.height = H; }
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#131920';
  ctx.fillRect(0, 0, W, H);

  const PAD = { t: 12, b: 28, l: 38, r: 52 };
  const cW = W - PAD.l - PAD.r, cH = H - PAD.t - PAD.b;

  const hrVals  = chartHR.filter(v => v !== null);
  const pwrVals = chartPwr.filter(v => v !== null);
  const tgtVals = chartTgt.filter(v => v !== null);

  const hrMin  = hrVals.length  ? Math.min(...hrVals, ...tgtVals) - 10   : 60;
  const hrMax  = hrVals.length  ? Math.max(...hrVals, ...tgtVals) + 10   : 200;
  const pwrMin = pwrVals.length ? Math.max(0, Math.min(...pwrVals) - 20) : 0;
  const pwrMax = pwrVals.length ? Math.max(...pwrVals) + 20              : 300;

  const hrY = v => PAD.t + cH * (1 - (v - hrMin)  / (hrMax  - hrMin));
  const pwY = v => PAD.t + cH * (1 - (v - pwrMin) / (pwrMax - pwrMin));
  const xOf = i => PAD.l + (i / (HIST - 1)) * cW;

  // Grid
  ctx.strokeStyle = '#1a2233'; ctx.lineWidth = 0.5;
  for (let i = 0; i <= 4; i++) {
    const y = PAD.t + (i / 4) * cH;
    ctx.beginPath(); ctx.moveTo(PAD.l, y); ctx.lineTo(PAD.l + cW, y); ctx.stroke();
  }

  // Left axis — HR (red)
  ctx.fillStyle = '#ff3355'; ctx.font = '9px Share Tech Mono'; ctx.textAlign = 'right';
  for (let i = 0; i <= 4; i++) {
    const val = hrMin + (i / 4) * (hrMax - hrMin);
    ctx.fillText(Math.round(val), PAD.l - 4, PAD.t + cH * (1 - i / 4) + 3);
  }

  // Right axis — Power (amber)
  ctx.fillStyle = '#ffaa00'; ctx.textAlign = 'left';
  for (let i = 0; i <= 4; i++) {
    const val = pwrMin + (i / 4) * (pwrMax - pwrMin);
    ctx.fillText(Math.round(val) + 'W', PAD.l + cW + 4, PAD.t + cH * (1 - i / 4) + 3);
  }

  // Target HR dashed line
  const tgt = parseInt(document.getElementById('target-hr').value);
  if (!isNaN(tgt)) {
    ctx.strokeStyle = 'rgba(255,51,85,.35)'; ctx.lineWidth = 1; ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(PAD.l, hrY(tgt)); ctx.lineTo(PAD.l + cW, hrY(tgt)); ctx.stroke();
    ctx.setLineDash([]);
  }

  function drawLine(data, color, yFn) {
    ctx.beginPath();
    let started = false;
    data.forEach((v, i) => {
      if (v === null) { started = false; return; }
      const x = xOf(i), y = yFn(v);
      if (!started) { ctx.moveTo(x, y); started = true; } else { ctx.lineTo(x, y); }
    });
    ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.stroke();
  }

  drawLine(chartPwr, 'rgba(255,170,0,.8)', pwY);
  drawLine(chartHR,  'rgba(255,51,85,.9)', hrY);

  // Legend
  ctx.font = '9px Share Tech Mono'; ctx.textAlign = 'left';
  ctx.fillStyle = '#ff3355';           ctx.fillText('HR',     PAD.l + 4,  PAD.t + 12);
  ctx.fillStyle = '#ffaa00';           ctx.fillText('Power',  PAD.l + 28, PAD.t + 12);
  ctx.fillStyle = 'rgba(255,51,85,.5)'; ctx.fillText('Target', PAD.l + 74, PAD.t + 12);

  // X axis time labels
  ctx.fillStyle = '#3d5068'; ctx.textAlign = 'center'; ctx.font = '8px Share Tech Mono';
  ['−10m', '−7.5m', '−5m', '−2.5m', 'now'].forEach((lbl, i) => {
    ctx.fillText(lbl, PAD.l + (i / 4) * cW, H - 8);
  });
}

// ══════════════════════════════════════════════════════
//  HR vs Power Characteristic scatter
// ══════════════════════════════════════════════════════
function drawCharacteristic() {
  const canvas = document.getElementById('char-canvas');
  const W = canvas.offsetWidth;
  const H = 180;
  if (!W) return;
  if (canvas.width !== W || canvas.height !== H) { canvas.width = W; canvas.height = H; }
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#131920';
  ctx.fillRect(0, 0, W, H);

  document.getElementById('char-count').textContent =
    `${hrCharStored.length} stored · ${hrCharSession.length} session`;

  if (hrCharStored.length === 0 && !(servoActive && lastHR !== null)) {
    ctx.fillStyle = '#3d5068'; ctx.font = '10px Share Tech Mono'; ctx.textAlign = 'center';
    ctx.fillText('Characteristic builds during non-warmup servo sessions', W / 2, H / 2);
    return;
  }

  const PAD = { t: 14, b: 26, l: 46, r: 16 };
  const cW = W - PAD.l - PAD.r, cH = H - PAD.t - PAD.b;

  // Axis ranges — include stored points and live operating point
  const xVals = hrCharStored.map(p => p.hr);
  const yVals = hrCharStored.map(p => p.power);
  if (servoActive && lastHR !== null) {
    xVals.push(lastHR);
    if (lastPower !== null) yVals.push(lastPower);
  }

  const xMin = xVals.length ? Math.max(profile.restHR - 5, Math.min(...xVals) - 5)  : profile.restHR;
  const xMax = xVals.length ? Math.min(profile.maxHR  + 5, Math.max(...xVals) + 10) : profile.maxHR;
  const yMin = yVals.length ? Math.max(0, Math.min(...yVals) - 20)                   : 0;
  const yMax = yVals.length ? Math.max(...yVals) + 30                                : 300;

  const xOf = hr  => PAD.l + (hr  - xMin) / (xMax - xMin) * cW;
  const yOf = pwr => PAD.t + (1 - (pwr - yMin) / (yMax - yMin)) * cH;

  // Grid
  ctx.strokeStyle = '#1a2233'; ctx.lineWidth = 0.5;
  for (let i = 0; i <= 4; i++) {
    const y = PAD.t + (i / 4) * cH;
    ctx.beginPath(); ctx.moveTo(PAD.l, y); ctx.lineTo(PAD.l + cW, y); ctx.stroke();
  }

  // Y axis (Power, amber)
  ctx.fillStyle = '#ffaa00'; ctx.font = '8px Share Tech Mono'; ctx.textAlign = 'right';
  for (let i = 0; i <= 4; i++) {
    const val = yMin + (i / 4) * (yMax - yMin);
    ctx.fillText(Math.round(val) + 'W', PAD.l - 3, PAD.t + cH * (1 - i / 4) + 3);
  }

  // X axis (HR, red)
  ctx.fillStyle = '#ff3355'; ctx.textAlign = 'center';
  for (let i = 0; i <= 4; i++) {
    const val = xMin + (i / 4) * (xMax - xMin);
    ctx.fillText(Math.round(val), PAD.l + (i / 4) * cW, H - 8);
  }

  // Regression line (dashed cyan) from all stored data
  const fit = fitChar(hrCharStored.length >= 4 ? hrCharStored : []);
  if (fit) {
    ctx.strokeStyle = 'rgba(0,212,255,.5)'; ctx.lineWidth = 1.5; ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(xOf(xMin), yOf(fit.a * xMin + fit.b));
    ctx.lineTo(xOf(xMax), yOf(fit.a * xMax + fit.b));
    ctx.stroke(); ctx.setLineDash([]);
  }

  // Stored points — dim purple (excluding session points to avoid double-draw)
  const storedOnly = hrCharStored.slice(0, hrCharStored.length - hrCharSession.length);
  for (const {hr, power} of storedOnly) {
    ctx.fillStyle = 'rgba(170,102,255,0.3)';
    ctx.beginPath(); ctx.arc(xOf(hr), yOf(power), 2.5, 0, Math.PI * 2); ctx.fill();
  }

  // Session points — bright amber
  for (const {hr, power} of hrCharSession) {
    ctx.fillStyle = 'rgba(255,170,0,0.85)';
    ctx.beginPath(); ctx.arc(xOf(hr), yOf(power), 3, 0, Math.PI * 2); ctx.fill();
  }

  // Current operating point — green dot
  if (servoActive && lastHR !== null) {
    const pwr = lastPower !== null ? lastPower : ergSetpoint;
    ctx.fillStyle = '#00e87a';
    ctx.beginPath(); ctx.arc(xOf(lastHR), yOf(pwr), 6, 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = '#131920'; ctx.lineWidth = 1.5; ctx.stroke();
  }

  // Legend
  ctx.font = '8px Share Tech Mono'; ctx.textAlign = 'left';
  let lx = PAD.l + 2;
  ctx.fillStyle = 'rgba(170,102,255,.6)'; ctx.fillText('■ stored',  lx, PAD.t + 10); lx += 52;
  ctx.fillStyle = 'rgba(255,170,0,.9)';   ctx.fillText('■ session', lx, PAD.t + 10); lx += 58;
  if (fit) {
    ctx.fillStyle = 'rgba(0,212,255,.7)';
    ctx.fillText(`trend ${fit.a >= 0 ? '+' : ''}${fit.a.toFixed(1)}W/bpm`, lx, PAD.t + 10);
  }

  // Axis labels
  ctx.fillStyle = '#3d5068'; ctx.textAlign = 'right';
  ctx.fillText('W ↑', PAD.l - 3, PAD.t + 6);
  ctx.fillText('HR →', W - PAD.r + 14, H - 8);
}
