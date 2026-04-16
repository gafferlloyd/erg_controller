'use strict';

// ── FIT derived-series and summary calculations ───────────────────────────────
// All functions take the records array from parseFit().

// ── Rolling helpers ───────────────────────────────────────────────────────────

function rollingSMA(arr, win) {
  const out = new Array(arr.length).fill(null);
  let sum = 0, count = 0;
  for (let i = 0; i < arr.length; i++) {
    const v = arr[i] ?? 0;
    sum += v;  count++;
    if (i >= win) { sum -= arr[i - win] ?? 0;  count--; }
    out[i] = sum / count;
  }
  return out;
}

// Peak average power over a sliding window of `win` seconds.
function peakAvg(powers, win) {
  if (powers.length < win) return null;
  let sum = 0;
  for (let i = 0; i < win; i++) sum += powers[i] ?? 0;
  let best = sum;
  for (let i = win; i < powers.length; i++) {
    sum += powers[i] ?? 0;
    sum -= powers[i - win] ?? 0;
    if (sum > best) best = sum;
  }
  return Math.round(best / win);
}

// ── Normalised Power ──────────────────────────────────────────────────────────
// Standard algorithm: 30 s SMA → ^4 → mean → ^0.25

function calcNP(powers) {
  if (powers.length < 30) return null;
  const sma = rollingSMA(powers, 30);
  let sum4 = 0, n = 0;
  for (let i = 29; i < sma.length; i++) {
    const v = sma[i];
    sum4 += v * v * v * v;
    n++;
  }
  return Math.round(Math.pow(sum4 / n, 0.25));
}

// ── Smoothed power series (30 s SMA, for chart display) ──────────────────────

function smoothedPower(records, win = 30) {
  return rollingSMA(records.map(r => r.power ?? null), win);
}

// ── VAM (Velocità Ascensionale Media) series ─────────────────────────────────
// Requires altitude data. Returns m/hr values.
// Computed over `win` seconds, then smoothed again.

function computeVAM(records, win = 60) {
  if (!records.some(r => r.altitude != null)) return null;
  const alts  = records.map(r => r.altitude ?? null);
  const raw   = new Array(alts.length).fill(null);

  for (let i = win; i < alts.length; i++) {
    const a0 = alts[i - win];
    const a1 = alts[i];
    if (a0 == null || a1 == null) continue;
    raw[i] = Math.max(0, (a1 - a0) / win * 3600);   // m/hr, clamp negatives
  }
  return rollingSMA(raw, 30).map((v, i) => raw[i] == null ? null : v);
}

// ── W/bpm instantaneous series ────────────────────────────────────────────────

function computeWpBpm(records) {
  return records.map(r =>
    (r.power != null && r.hr != null && r.hr > 40)
      ? parseFloat((r.power / r.hr).toFixed(2))
      : null
  );
}

// ── Aerobic decoupling (Pa:Hr) ────────────────────────────────────────────────
// Compares NP/avgHR for first vs second half.
// Returns % drift (positive = HR drifted up relative to power).

function calcDecoupling(records) {
  const n = records.length;
  if (n < 120) return null;
  const half = Math.floor(n / 2);
  const h1   = records.slice(0, half);
  const h2   = records.slice(half);

  const np1 = calcNP(h1.map(r => r.power ?? 0));
  const np2 = calcNP(h2.map(r => r.power ?? 0));
  const hr1 = avg(h1.map(r => r.hr).filter(Boolean));
  const hr2 = avg(h2.map(r => r.hr).filter(Boolean));

  if (!np1 || !np2 || !hr1 || !hr2) return null;
  const ef1 = np1 / hr1;
  const ef2 = np2 / hr2;
  return parseFloat(((ef1 - ef2) / ef1 * 100).toFixed(1));
}

// ── Summary metrics ───────────────────────────────────────────────────────────

function avg(arr) {
  const v = arr.filter(x => x != null);
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
}

function computeSummary(records, ftp, weight) {
  if (!records.length) return {};

  const powers  = records.map(r => r.power ?? 0);
  const hrs     = records.map(r => r.hr).filter(Boolean);
  const cads    = records.map(r => r.cadence).filter(Boolean);
  const speeds  = records.map(r => r.speed).filter(Boolean);
  const alts    = records.map(r => r.altitude).filter(v => v != null);

  const duration   = records[records.length - 1].elapsed;   // seconds
  const movingTime = records.filter(r => (r.speed ?? 0) > 1 || (r.power ?? 0) > 10).length;

  const avgPwr = Math.round(avg(records.map(r => r.power).filter(Boolean)) ?? 0);
  const np     = calcNP(powers) ?? 0;
  const IF_val = ftp ? parseFloat((np / ftp).toFixed(3)) : null;
  const TSS    = (ftp && np && duration)
    ? Math.round(duration / 3600 * np * IF_val / ftp * 100)
    : null;
  const wkg    = (weight && np) ? parseFloat((np / weight).toFixed(2)) : null;

  const avgHR  = hrs.length  ? Math.round(avg(hrs))   : null;
  const maxHR  = hrs.length  ? Math.max(...hrs)        : null;
  const avgCad = cads.length ? Math.round(avg(cads))  : null;
  const avgSpd = speeds.length ? parseFloat(avg(speeds).toFixed(1)) : null;

  // Distance: prefer last record's distance field, else integrate speed
  const distRec = records.map(r => r.distance).filter(v => v != null);
  const distM   = distRec.length
    ? distRec[distRec.length - 1]
    : records.reduce((a, r) => a + (r.speed != null ? r.speed / 3.6 : 0), 0);
  const distKm  = parseFloat((distM / 1000).toFixed(2));

  // Elevation gain
  let elevGain = 0;
  for (let i = 1; i < alts.length; i++) {
    const d = alts[i] - alts[i - 1];
    if (d > 0) elevGain += d;
  }

  // VAM summary: avg over positive segments only
  const vamVals = records
    .map(r => r.altitude)
    .filter((_, i) => i > 0)
    .map((a, i) => {
      const prev = records[i].altitude;
      return (a != null && prev != null && a > prev) ? (a - prev) * 3600 : null;
    })
    .filter(Boolean);
  const avgVAM = vamVals.length ? Math.round(avg(vamVals)) : null;

  const decoupling = calcDecoupling(records);

  const ef = (np && avgHR) ? parseFloat((np / avgHR).toFixed(2)) : null;

  const totalWork = Math.round(powers.reduce((a, v) => a + v, 0) / 1000); // kJ

  const peak1min  = peakAvg(powers, 60);
  const peak5min  = peakAvg(powers, 300);
  const peak20min = peakAvg(powers, 1200);

  return {
    duration, movingTime, totalWork,
    avgPwr, np, IF: IF_val, TSS, wkg,
    avgHR, maxHR, ef, decoupling,
    avgCad, avgSpd, distKm,
    elevGain: Math.round(elevGain), avgVAM,
    peak1min, peak5min, peak20min,
  };
}

// ── Build all chart channels from records ─────────────────────────────────────
// Returns an object of named Float arrays for the plotter.

function buildChannels(records, hasAltitude) {
  return {
    power:   records.map(r => r.power   ?? null),
    smooth:  smoothedPower(records, 30),
    hr:      records.map(r => r.hr      ?? null),
    cadence: records.map(r => r.cadence ?? null),
    speed:   records.map(r => r.speed   ?? null),
    wpbpm:   computeWpBpm(records),
    vam:     hasAltitude ? computeVAM(records, 60) : null,
    elapsed: records.map(r => r.elapsed),
  };
}

// ── Selection statistics ──────────────────────────────────────────────────────
// Returns per-channel {avg, min, max} for the slice [i0, i1].

function selectionStats(channels, i0, i1) {
  const slice = (arr) => arr ? arr.slice(i0, i1 + 1).filter(v => v != null) : [];
  const stat  = (arr) => {
    const v = slice(arr);
    if (!v.length) return null;
    return { avg: parseFloat((v.reduce((a, b) => a + b, 0) / v.length).toFixed(1)),
             min: Math.min(...v),
             max: Math.max(...v) };
  };
  return {
    power:   stat(channels.power),
    hr:      stat(channels.hr),
    cadence: stat(channels.cadence),
    speed:   stat(channels.speed),
    wpbpm:   stat(channels.wpbpm),
    vam:     stat(channels.vam),
  };
}
