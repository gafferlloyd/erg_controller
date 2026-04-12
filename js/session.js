'use strict';

// ── Session state ─────────────────────────────────────────────────────────────
let sessionActive = false;
let sessionStart  = null;
let sampleTimer   = null;

// Timestamped samples — one per second while session is active.
// { t: ms_epoch, hr: bpm|null, power: W|null, cadence: rpm|null, rmssd: ms|null }
const samples = [];

// ── Session control ───────────────────────────────────────────────────────────

function startSession() {
  if (sessionActive) return;
  samples.length = 0;
  sessionStart   = Date.now();
  sessionActive  = true;
  sampleTimer    = setInterval(takeSample, 1000);
  log('Session started', 'ok');
  onSessionStarted();   // ui.js callback
}

function stopSession() {
  if (!sessionActive) return;
  clearInterval(sampleTimer);
  sampleTimer   = null;
  sessionActive = false;
  log(`Session stopped — ${samples.length} samples`, 'ok');
  onSessionStopped();   // ui.js callback
}

function takeSample() {
  samples.push({
    t:       Date.now(),
    hr:      lastHR,
    power:   lastPower,
    cadence: lastCadence,
    rmssd:   currentRMSSD,
  });
  onSampleTaken();      // ui.js callback — updates metrics display
}

// ── Pure metric functions (no side effects) ───────────────────────────────────

// Normalised Power — 30 s rolling average, 4th-power mean.
// Returns null if fewer than 30 samples are available.
function calcNP(sampleArr) {
  const powers = sampleArr.map(s => s.power ?? 0);
  if (powers.length < 30) return null;
  let sum4 = 0;
  let count = 0;
  for (let i = 29; i < powers.length; i++) {
    const window30 = powers.slice(i - 29, i + 1);
    const avg30    = window30.reduce((a, b) => a + b, 0) / 30;
    sum4 += avg30 ** 4;
    count++;
  }
  return Math.round((sum4 / count) ** 0.25);
}

// W/bpm efficiency — mean power divided by mean HR over the given slice.
// Returns null if no valid paired samples.
function calcEfficiency(sampleArr) {
  const valid = sampleArr.filter(s => s.hr > 0 && s.power != null && s.power > 0);
  if (valid.length < 5) return null;
  const avgPwr = valid.reduce((a, s) => a + s.power, 0) / valid.length;
  const avgHR  = valid.reduce((a, s) => a + s.hr, 0)    / valid.length;
  return (avgPwr / avgHR).toFixed(2);
}

// NP / avg HR — same idea but uses normalised power.
function calcNPEfficiency(sampleArr) {
  const np = calcNP(sampleArr);
  if (!np) return null;
  const hrSamples = sampleArr.filter(s => s.hr > 0);
  if (hrSamples.length < 5) return null;
  const avgHR = hrSamples.reduce((a, s) => a + s.hr, 0) / hrSamples.length;
  return (np / avgHR).toFixed(2);
}

// Intensity Factor = NP / FTP.
function calcIF(sampleArr, ftp) {
  if (!ftp) return null;
  const np = calcNP(sampleArr);
  return np ? (np / ftp).toFixed(2) : null;
}

// Training Stress Score = (duration_h × NP × IF) / FTP × 100.
function calcTSS(sampleArr, ftp) {
  if (!ftp || sampleArr.length < 30) return null;
  const np = calcNP(sampleArr);
  if (!np) return null;
  const durationH = sampleArr.length / 3600;
  const IF        = np / ftp;
  return Math.round(durationH * np * IF / ftp * 100);
}

// Aerobic decoupling (Pa:HR) — compare efficiency in first vs second half.
// A value <5% indicates good aerobic fitness.
function calcDecoupling(sampleArr) {
  if (sampleArr.length < 60) return null;
  const half  = Math.floor(sampleArr.length / 2);
  const first = sampleArr.slice(0, half);
  const last  = sampleArr.slice(half);
  const eff1  = parseFloat(calcEfficiency(first));
  const eff2  = parseFloat(calcEfficiency(last));
  if (!eff1 || !eff2) return null;
  // Positive = HR drifted up relative to power (decoupled)
  return (((eff1 - eff2) / eff1) * 100).toFixed(1);
}

// Heart Rate Reserve % — (HR - restHR) / (maxHR - restHR) × 100.
function calcHRR(hr, restHR, maxHR) {
  if (!hr || !restHR || !maxHR || maxHR <= restHR) return null;
  return Math.round((hr - restHR) / (maxHR - restHR) * 100);
}

// HR zone (1–5) based on %HRR thresholds: Z1<50, Z2<60, Z3<70, Z4<80, Z5≥80.
function calcHRZone(hr, restHR, maxHR) {
  const hrr = calcHRR(hr, restHR, maxHR);
  if (hrr === null) return null;
  if (hrr < 50) return 'Z1';
  if (hrr < 60) return 'Z2';
  if (hrr < 70) return 'Z3';
  if (hrr < 80) return 'Z4';
  return 'Z5';
}

// ── Power curve ───────────────────────────────────────────────────────────────
// Standard durations (seconds) used for Mean Maximal Power and NP curves.
const MMP_DURATIONS = [1, 2, 5, 10, 15, 20, 30, 60, 120, 300, 600, 1200, 2400, 3600];

// Mean Maximal Power — best average power for each duration window.
// Returns [{dur, power}] for durations that fit within sampleArr.
function calcMMP(sampleArr) {
  const powers = sampleArr.map(s => s.power ?? 0);
  const result = [];
  for (const dur of MMP_DURATIONS) {
    if (powers.length < dur) break;
    let sum = powers.slice(0, dur).reduce((a, b) => a + b, 0);
    let best = sum;
    for (let i = dur; i < powers.length; i++) {
      sum += powers[i] - powers[i - dur];
      if (sum > best) best = sum;
    }
    result.push({ dur, power: Math.round(best / dur) });
  }
  return result;
}

// NP curve — normalised power computed over the best MMP window for each
// duration >= 120 s.  Returns [{dur, power}].
function calcNPCurve(sampleArr) {
  const powers = sampleArr.map(s => s.power ?? 0);
  const result = [];
  for (const dur of MMP_DURATIONS.filter(d => d >= 120)) {
    if (powers.length < dur) break;
    // Find start index of the best avg-power window
    let sum  = powers.slice(0, dur).reduce((a, b) => a + b, 0);
    let best = sum;
    let bestIdx = 0;
    for (let i = dur; i < powers.length; i++) {
      sum += powers[i] - powers[i - dur];
      if (sum > best) { best = sum; bestIdx = i - dur + 1; }
    }
    const slice = sampleArr.slice(bestIdx, bestIdx + dur);
    const np = calcNP(slice);
    if (np) result.push({ dur, power: np });
  }
  return result;
}

// Convenience: return last N samples (or all if N is null).
function recentSamples(n) {
  return n ? samples.slice(-n) : samples;
}

// Elapsed session time as "HH:MM:SS" string.
function sessionElapsed() {
  if (!sessionStart) return '00:00:00';
  const s   = Math.floor((Date.now() - sessionStart) / 1000);
  const hh  = String(Math.floor(s / 3600)).padStart(2, '0');
  const mm  = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
  const ss  = String(s % 60).padStart(2, '0');
  return `${hh}:${mm}:${ss}`;
}
