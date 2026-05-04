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
  minutePoints.push({ avgPwr, np, hr: lastHR, t: Date.now() });
}

// Least-squares linear regression: y = mx + c  (x = avgPwr, y = hr)
// Returns {m, c, r2} or null if fewer than 3 points.
function calcLinFit() {
  const pts = minutePoints.filter(p => p.avgPwr > 0 && p.hr > 0);
  if (pts.length < 3) return null;
  const n = pts.length;
  let sx = 0, sy = 0, sxy = 0, sx2 = 0;
  for (const p of pts) {
    sx  += p.avgPwr;
    sy  += p.hr;
    sxy += p.avgPwr * p.hr;
    sx2 += p.avgPwr ** 2;
  }
  const denom = n * sx2 - sx * sx;
  if (Math.abs(denom) < 1e-9) return null;
  const m    = (n * sxy - sx * sy) / denom;
  const c    = (sy - m * sx) / n;
  const meanY = sy / n;
  let ss_tot = 0, ss_res = 0;
  for (const p of pts) {
    ss_tot += (p.hr - meanY) ** 2;
    ss_res += (p.hr - (m * p.avgPwr + c)) ** 2;
  }
  const r2 = ss_tot > 0 ? 1 - ss_res / ss_tot : 0;
  return { m, c, r2 };
}

function clearMinutePoints() { minutePoints.length = 0; }
