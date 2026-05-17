'use strict';

// Per-minute HR/Power snapshots and linear regression (y=HR, x=avg power).
// Depends on globals: samples, calcNP (session.js), lastHR (ble.js)

const minutePoints = [];  // [{avgPwr, np, hr, t}]

function snapshotMinute() {
  const slice   = samples.slice(-60);
  const withPwr = slice.filter(s => s.power != null && s.power > 0);
  if (withPwr.length < 30) return;
  if (!lastHR || lastHR <= 0) return;
  const avgPwr = Math.round(withPwr.reduce((a, s) => a + s.power, 0) / withPwr.length);
  const np     = calcNP(slice);

  const withCad = slice.filter(s => s.cadence != null && s.cadence > 0);
  const avgCad  = withCad.length
    ? Math.round(withCad.reduce((a, s) => a + s.cadence, 0) / withCad.length)
    : null;

  const withSpd = slice.filter(s => s.speed != null && s.speed > 0);
  const avgSpd  = withSpd.length
    ? (withSpd.reduce((a, s) => a + s.speed, 0) / withSpd.length).toFixed(1)
    : null;

  const totalVert = slice.reduce((a, s) => {
    if (s.speed == null || s.grade == null) return a;
    const dh = (s.speed / 3.6) * (s.grade / 100);
    return a + (dh > 0 ? dh : 0);
  }, 0);
  const avgVam = Math.round(totalVert * 60);

  minutePoints.push({ avgPwr, np, hr: lastHR, avgCad, avgSpd, avgVam, t: Date.now() });
}

// Least-squares slope with intercept fixed at 20% HRR (aerobic baseline).
// c = restHR + 0.20 × (maxHR − restHR);  m = Σ xᵢ(yᵢ − c) / Σ xᵢ²
// Returns {m, c, r2} or null if fewer than 3 points.
function calcLinFit() {
  const pts = minutePoints.filter(p => p.avgPwr > 0 && p.hr > 0);
  if (pts.length < 3) return null;
  const c = profile.restHR + 0.20 * (profile.maxHR - profile.restHR);
  let sxy = 0, sx2 = 0;
  for (const p of pts) {
    sxy += p.avgPwr * (p.hr - c);
    sx2 += p.avgPwr ** 2;
  }
  if (sx2 < 1e-9) return null;
  const m = sxy / sx2;
  const meanY = pts.reduce((a, p) => a + p.hr, 0) / pts.length;
  let ss_tot = 0, ss_res = 0;
  for (const p of pts) {
    ss_tot += (p.hr - meanY) ** 2;
    ss_res += (p.hr - (m * p.avgPwr + c)) ** 2;
  }
  const r2 = ss_tot > 0 ? 1 - ss_res / ss_tot : 0;
  return { m, c, r2 };
}

function clearMinutePoints() { minutePoints.length = 0; }

// Populate and show the minute popup for 5 s (CSS animation handles timing).
function showMinutePopup() {
  const el = document.getElementById('minute-popup');
  if (!el) return;
  const last = minutePoints.length ? minutePoints[minutePoints.length - 1] : null;
  const fit  = calcLinFit();

  function set(id, val) {
    const node = el.querySelector(`[data-mp="${id}"]`);
    if (node) node.textContent = val != null ? String(val) : '—';
  }

  set('avgpwr',  last ? last.avgPwr : null);
  set('np',      last && last.np != null ? last.np : null);
  set('hr',      last ? last.hr : null);
  set('fit_m',   fit && fit.m ? (1 / fit.m).toFixed(1) : null);
  set('fit_c',   fit  ? Math.round(fit.c) : null);
  set('hrv',     currentRMSSD != null ? currentRMSSD : null);
  set('cadence', last ? last.avgCad : null);
  set('speed',   last ? last.avgSpd : null);
  set('vam',     last ? last.avgVam : null);
  set('minute',  minutePoints.length);

  el.classList.remove('mp-show');
  void el.offsetWidth;          // force reflow to restart animation
  el.classList.add('mp-show');
}
