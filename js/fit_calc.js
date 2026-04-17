'use strict';

// ── FIT derived-series and summary calculations ───────────────────────────────

// ── Rolling helpers ───────────────────────────────────────────────────────────

function rollingSMA(arr, win) {
  const out = new Array(arr.length).fill(null);
  let sum = 0, count = 0;
  for (let i = 0; i < arr.length; i++) {
    const v = arr[i] ?? 0;
    sum += v; count++;
    if (i >= win) { sum -= arr[i - win] ?? 0; count--; }
    out[i] = sum / count;
  }
  return out;
}

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

function avg(arr) {
  const v = arr.filter(x => x != null);
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
}

// ── Normalised Power (30 s SMA → ^4 → mean → ^0.25) ─────────────────────────

function calcNP(powers) {
  if (powers.length < 30) return null;
  const sma = rollingSMA(powers, 30);
  let sum4 = 0, n = 0;
  for (let i = 29; i < sma.length; i++) { const v = sma[i]; sum4 += v*v*v*v; n++; }
  return Math.round(Math.pow(sum4 / n, 0.25));
}

// ── Computed series ───────────────────────────────────────────────────────────

function computeVAM(records, win = 60) {
  if (!records.some(r => r.altitude != null)) return null;
  const alts = records.map(r => r.altitude ?? null);
  const raw  = new Array(alts.length).fill(null);
  for (let i = win; i < alts.length; i++) {
    const a0 = alts[i - win], a1 = alts[i];
    if (a0 != null && a1 != null) raw[i] = Math.max(0, (a1 - a0) / win * 3600);
  }
  return rollingSMA(raw, 30).map((v, i) => raw[i] == null ? null : v);
}

function computeWpBpm(records) {
  return records.map(r =>
    (r.power != null && r.hr != null && r.hr > 40)
      ? parseFloat((r.power / r.hr).toFixed(2)) : null
  );
}

// ── Aerobic decoupling (NP/avgHR: first half vs second half) ─────────────────

function calcDecoupling(records) {
  const n = records.length;
  if (n < 120) return null;
  const half = Math.floor(n / 2);
  const np1  = calcNP(records.slice(0, half).map(r => r.power ?? 0));
  const np2  = calcNP(records.slice(half).map(r => r.power ?? 0));
  const hr1  = avg(records.slice(0, half).map(r => r.hr).filter(Boolean));
  const hr2  = avg(records.slice(half).map(r => r.hr).filter(Boolean));
  if (!np1 || !np2 || !hr1 || !hr2) return null;
  return parseFloat(((np1/hr1 - np2/hr2) / (np1/hr1) * 100).toFixed(1));
}

// ── Summary metrics ───────────────────────────────────────────────────────────

function computeSummary(records, ftp, weight) {
  if (!records.length) return {};
  const powers = records.map(r => r.power ?? 0);
  const hrs    = records.map(r => r.hr).filter(Boolean);
  const cads   = records.map(r => r.cadence).filter(Boolean);
  const speeds = records.map(r => r.speed).filter(Boolean);
  const alts   = records.map(r => r.altitude).filter(v => v != null);

  const duration = records[records.length - 1].elapsed;
  const avgPwr   = Math.round(avg(records.map(r => r.power).filter(Boolean)) ?? 0);
  const np       = calcNP(powers) ?? 0;
  const IF_val   = ftp ? parseFloat((np / ftp).toFixed(3)) : null;
  const TSS      = (ftp && np) ? Math.round(duration / 3600 * np * IF_val / ftp * 100) : null;
  const wkg      = (weight && np) ? parseFloat((np / weight).toFixed(2)) : null;

  const avgHR  = hrs.length   ? Math.round(avg(hrs))  : null;
  const maxHR  = hrs.length   ? Math.max(...hrs)       : null;
  const avgCad = cads.length  ? Math.round(avg(cads)) : null;
  const avgSpd = speeds.length ? parseFloat(avg(speeds).toFixed(1)) : null;

  const distRec = records.map(r => r.distance).filter(v => v != null);
  const distM   = distRec.length ? distRec[distRec.length - 1]
    : records.reduce((a, r) => a + (r.speed != null ? r.speed / 3.6 : 0), 0);
  const distKm  = parseFloat((distM / 1000).toFixed(2));

  let elevGain = 0;
  for (let i = 1; i < alts.length; i++) { const d = alts[i] - alts[i-1]; if (d > 0) elevGain += d; }

  return {
    duration, totalWork: Math.round(powers.reduce((a, v) => a + v, 0) / 1000),
    avgPwr, np, IF: IF_val, TSS, wkg,
    avgHR, maxHR, ef: (np && avgHR) ? parseFloat((np / avgHR).toFixed(2)) : null,
    decoupling: calcDecoupling(records),
    avgCad, avgSpd, distKm,
    elevGain: Math.round(elevGain),
    avgVAM: alts.length > 1 ? Math.round(avg(
      alts.slice(1).map((a, i) => a > alts[i] ? (a - alts[i]) * 3600 : null).filter(Boolean)
    )) : null,
    peak1min: peakAvg(powers, 60), peak5min: peakAvg(powers, 300), peak20min: peakAvg(powers, 1200),
  };
}

// ── Channel builder ───────────────────────────────────────────────────────────
// Returns { channels: [{id, name, unit, color, data, [smooth]}], elapsed }
// Channels are ordered for display; computed (W/bpm, VAM) inserted at anchor points.

const CH_COLOR = {
  power:'#4fc3f7', hr:'#ef5350', cadence:'#66bb6a', speed:'#e3b341',
  grade:'#80deea', altitude:'#79c0ff', vspeed:'#80cbc4', temp:'#ce93d8',
  distance:'#8b949e', lte:'#ffd54f', rte:'#ffca28', lps:'#c5e1a5',
  rps:'#a5d6a7', cps:'#b2dfdb', smo2:'#f06292', thb:'#f48fb1',
  calories:'#fff176',
  wpbpm:'#bc8cff', vam:'#ffd54f',
};

const CH_DISPLAY_ORDER = [
  'power','hr','cadence','speed','grade','altitude','vspeed',
  'temp','distance','lte','rte','lps','rps','cps','smo2','thb','calories',
];

function buildChannels(records, presentFields) {
  const present  = new Set(presentFields.map(f => f.key));
  const channels = [];
  const elapsed  = records.map(r => r.elapsed);

  for (const key of CH_DISPLAY_ORDER) {
    if (!present.has(key)) continue;
    const data = records.map(r => r[key] ?? null);
    if (data.every(v => v == null)) continue;

    const meta = presentFields.find(f => f.key === key);
    const ch   = { id: key, name: meta.name, unit: meta.unit,
                   color: CH_COLOR[key] || '#aaa', data };
    if (key === 'power') ch.smooth = rollingSMA(data, 30);
    channels.push(ch);

    if (key === 'hr' && present.has('power')) {
      const wpbpm = computeWpBpm(records);
      if (wpbpm.some(v => v != null))
        channels.push({ id:'wpbpm', name:'W/bpm', unit:'', color:CH_COLOR.wpbpm, data:wpbpm });
    }
    if (key === 'altitude') {
      const vam = computeVAM(records, 60);
      if (vam && vam.some(v => v != null))
        channels.push({ id:'vam', name:'VAM', unit:'m/hr', color:CH_COLOR.vam, data:vam });
    }
  }

  return { channels, elapsed };
}

// ── Selection statistics ──────────────────────────────────────────────────────
// channelArr = channels array from buildChannels().

function selectionStats(channelArr, i0, i1) {
  const result = {};
  for (const ch of channelArr) {
    const v = ch.data.slice(i0, i1 + 1).filter(x => x != null);
    if (!v.length) { result[ch.id] = null; continue; }
    const s = v.reduce((a, b) => a + b, 0);
    result[ch.id] = { avg: s / v.length, min: Math.min(...v), max: Math.max(...v) };
  }
  return result;
}
