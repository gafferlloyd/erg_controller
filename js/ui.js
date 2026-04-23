'use strict';

// ── Mode management ───────────────────────────────────────────────────────────
// currentMode: 'passive' | 'hr-servo' | 'power-erg'
let currentMode = 'passive';

function setMode(mode) {
  currentMode = mode;
  if (mode === 'passive') {
    if (servoActive) stopServo();
    if (ergActive)   stopPowerErg();
  }
  document.body.className = `show-${mode}`;
  document.querySelectorAll('.mode-tab').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.mode === mode);
  });
  if (mode !== 'passive') {
    setTimeout(() => drawWorkoutProfile(workoutRawSegs), 50);
  }
}

// ── Connection pill ───────────────────────────────────────────────────────────

function setPill(role, live, label) {
  const pill = document.getElementById(`pill-${role}`);
  const lbl  = document.getElementById(`plbl-${role}`);
  const dot  = document.getElementById(`pdot-${role}`);
  const vals = document.getElementById(`pill-${role}-vals`);
  if (!pill) return;
  if (lbl) lbl.textContent = label;
  pill.classList.toggle('live', !!live);
  if (dot) dot.className = `dot${live ? ' live' : ''}`;
  if (!live && vals) vals.textContent = '';
}

// ── Servo button ──────────────────────────────────────────────────────────────

function updateServoBtn() {
  const btn = document.getElementById('btn-servo');
  if (!btn) return;
  const canRun = trainerLive && hrLive;
  btn.disabled = !canRun;
  btn.textContent = servoActive ? 'STOP SERVO' : 'START SERVO';
  btn.classList.toggle('on', servoActive);

  // Keep pause button state consistent
  updatePauseBtn();

  const ergStart = document.getElementById('btn-start-power-erg');
  if (ergStart) ergStart.disabled = !trainerLive;
}

// ── ERG indicator ─────────────────────────────────────────────────────────────
// state: 'idle' | 'active' | 'gap'

function updateErgIndicator(state) {
  const el    = document.getElementById('erg-indicator');
  const dot   = document.getElementById('erg-dot');
  const label = document.getElementById('erg-label');
  if (!el) return;
  el.className = `erg-indicator`;
  if (dot) dot.className = `erg-dot ${state}`;
  const labels = { idle: 'ERG IDLE', active: 'ERG ACTIVE', gap: 'ERG GAP' };
  if (label) label.textContent = labels[state] ?? state.toUpperCase();
}

// ── Slider sync ───────────────────────────────────────────────────────────────

function syncSlider(id) {
  const el  = document.getElementById(id);
  const vEl = document.getElementById(`${id}-v`);
  if (!el || !vEl) return;
  vEl.textContent = el.value;
  el.addEventListener('input', () => { vEl.textContent = el.value; });
}

// ── New HR / power handlers ───────────────────────────────────────────────────

function onNewHR(hr) {
  setVal('cv-hr', hr);
  const vals = document.getElementById('pill-hr-vals');
  if (vals) {
    const hrv = currentRMSSD != null ? ` HRV:${currentRMSSD}` : '';
    vals.textContent = `${hr}bpm${hrv}`;
  }
}

function onNewPower(power, cadence) {
  setVal('cv-power',   power   ?? '—');
  setVal('cv-cadence', cadence ?? '—');
  setVal('cv-speed',   lastSpeed != null ? lastSpeed.toFixed(1) : '—');
  const vals = document.getElementById('pill-trainer-vals');
  if (vals) {
    const pw  = power   != null ? `${power}W` : '';
    const cad = cadence != null ? ` ${cadence}rpm` : '';
    vals.textContent = pw + cad;
  }
}

// ── ERG confirmed / control lost ─────────────────────────────────────────────

function onErgConfirmed(watts) {
  updateErgIndicator('active');
  setText('erg-setpoint-display', `${watts}W`);
}

function onErgControlLost() {
  updateErgIndicator('idle');
  log('ERG control lost — another device may have taken over', 'warn');
}

// ── Session lifecycle callbacks ───────────────────────────────────────────────

function onSessionStarted() {
  document.getElementById('btn-start-session').disabled = true;
  document.getElementById('btn-stop-session').disabled  = false;
  clearChartData();
  startChartLoop();
  _timerInterval = setInterval(updateSessionTimer, 1000);
}

function onSessionStopped() {
  document.getElementById('btn-start-session').disabled = false;
  document.getElementById('btn-stop-session').disabled  = true;
  document.getElementById('btn-dl-csv').disabled        = false;
  document.getElementById('btn-dl-fit').disabled        = false;
  clearInterval(_timerInterval);
  stopChartLoop();
  drawOverview();
  drawRolling();
  drawPowerCurve();
  drawHRPower();
  updateSessionMetrics();
  downloadFit();
  downloadLog();
}

let _timerInterval = null;

function updateSessionTimer() {
  setText('session-timer', sessionElapsed());
}

// ── Per-sample callback ───────────────────────────────────────────────────────

function onSampleTaken() {
  const s  = samples[samples.length - 1];
  const np = calcNP(samples);

  setVal('cv-np',  np ?? '—');
  setVal('cv-hrv', currentRMSSD != null ? `${currentRMSSD}` : '—');

  // Push to chart
  const target = (servoActive || ergActive) ? ergSetpoint : null;
  pushChartPoint(s.hr, s.power, np, s.cadence, target);

  // Refresh metrics every 5 samples; charts every 30 s
  if (samples.length % 5  === 0) updateSessionMetrics();
  if (samples.length % 30 === 0) { drawPowerCurve(); drawHRPower(); }
}

// ── Metrics panel ─────────────────────────────────────────────────────────────

function updateSessionMetrics() {
  const all  = samples;
  const last = recentSamples(getRecentWindowSecs());

  const sw = (v, unit) => v != null ? `${v}` : '—';

  // NP
  const np     = calcNP(all);
  const npLast = calcNP(last);
  setStatBox('workout', 'np',     sw(np));
  setStatBox('recent',  'np',     sw(npLast));

  // Avg Power
  const pwAll  = all.filter(s => s.power != null && s.power > 0);
  const pwLast = last.filter(s => s.power != null && s.power > 0);
  const avgPw  = pwAll.length  ? Math.round(pwAll.reduce((a, s)  => a + s.power, 0) / pwAll.length)  : null;
  const avgPw2 = pwLast.length ? Math.round(pwLast.reduce((a, s) => a + s.power, 0) / pwLast.length) : null;
  setStatBox('workout', 'avgpwr', sw(avgPw));
  setStatBox('recent',  'avgpwr', sw(avgPw2));

  // Avg HR
  const hrAll  = all.filter(s => s.hr > 0);
  const hrLast = last.filter(s => s.hr > 0);
  const avgHR  = hrAll.length  ? Math.round(hrAll.reduce((a, s)  => a + s.hr, 0) / hrAll.length)  : null;
  const avgHR2 = hrLast.length ? Math.round(hrLast.reduce((a, s) => a + s.hr, 0) / hrLast.length) : null;
  setStatBox('workout', 'avghr', sw(avgHR));
  setStatBox('recent',  'avghr', sw(avgHR2));

  // Avg Cadence
  const cadAll  = all.filter(s => s.cadence != null && s.cadence > 0);
  const cadLast = last.filter(s => s.cadence != null && s.cadence > 0);
  const avgCad  = cadAll.length  ? Math.round(cadAll.reduce((a, s)  => a + s.cadence, 0) / cadAll.length)  : null;
  const avgCad2 = cadLast.length ? Math.round(cadLast.reduce((a, s) => a + s.cadence, 0) / cadLast.length) : null;
  setStatBox('workout', 'avgcad', sw(avgCad));
  setStatBox('recent',  'avgcad', sw(avgCad2));

  // Speed and Distance (workout only)
  const spdAll = all.filter(s => s.speed != null && s.speed > 0);
  const avgSpd = spdAll.length ? (spdAll.reduce((a, s) => a + s.speed, 0) / spdAll.length).toFixed(1) : null;
  const distKm = (sessionDistance / 1000).toFixed(2);
  setStatBox('workout', 'avgspd', sw(avgSpd));
  setStatBox('workout', 'dist',   distKm);

  // Efficiency (W/bpm and NP/bpm)
  const wpbpm  = calcEfficiency(all);
  const wpbpm2 = calcEfficiency(last);
  const npbpm  = calcNPEfficiency(all);
  const npbpm2 = calcNPEfficiency(last);
  setStatBox('workout', 'wpbpm',  sw(wpbpm));
  setStatBox('recent',  'wpbpm',  sw(wpbpm2));
  setStatBox('workout', 'npbpm',  sw(npbpm));
  setStatBox('recent',  'npbpm',  sw(npbpm2));

  // Session-only
  setStatBox('workout', 'if',  sw(calcIF(all, profile.ftp)));
  setStatBox('workout', 'tss', sw(calcTSS(all, profile.ftp)));

  // Decoupling
  const dcpl = calcDecoupling(all);
  setStatBox('workout', 'dcpl', dcpl != null ? `${dcpl}` : '—');

  // HRV — use current live RMSSD value
  const hrvTxt = currentRMSSD != null ? `${currentRMSSD}` : '—';
  setStatBox('workout', 'hrv', hrvTxt);
  setStatBox('recent',  'hrv', hrvTxt);
}

// ── DOM text helpers ──────────────────────────────────────────────────────────

function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

// Set the .cv-val child of a cv-block
function setVal(blockId, val) {
  const el = document.getElementById(blockId);
  if (!el) return;
  const v = el.querySelector('.cv-val');
  if (v) v.textContent = val;
}

// ── Workout bar ───────────────────────────────────────────────────────────────

function updateWorkoutBar(player) {
  const seg = player.currentSegment;
  if (!seg) return;
  setText('seg-name', seg.label);
  const rem = player.totalDuration - player.totalElapsed;
  const m   = String(Math.floor(rem / 60)).padStart(2, '0');
  const s   = String(rem % 60).padStart(2, '0');
  setText('seg-remaining', `${m}:${s}`);
}

function updateWorkoutBarDone() {
  setText('seg-name', 'Workout complete');
  setText('seg-remaining', '00:00');
  drawWorkoutProfile(workoutRawSegs, Infinity);  // cursor past end
}

// ── Workout file + mode button wiring ────────────────────────────────────────

function wireWorkoutButtons() {
  const fileInput  = document.getElementById('workout-file');
  const btnStart   = document.getElementById('btn-start-workout');
  const btnPause   = document.getElementById('btn-pause-workout');
  const btnStop    = document.getElementById('btn-stop-workout');

  if (fileInput) fileInput.addEventListener('change', () => loadWorkoutFile(fileInput));
  if (btnStart)  btnStart.addEventListener('click',   startWorkout);
  if (btnPause)  btnPause.addEventListener('click',   toggleWorkoutPause);
  if (btnStop)   btnStop.addEventListener('click',    stopWorkout);
}

// ── Drag-and-drop workout import ──────────────────────────────────────────────

function wireDragDrop() {
  const zone = document.getElementById('workout-bar');
  if (!zone) return;

  zone.addEventListener('dragenter', e => { e.preventDefault(); });
  zone.addEventListener('dragover',  e => { e.preventDefault(); zone.classList.add('drag-over'); });
  zone.addEventListener('dragleave', e => {
    // Only remove if leaving the zone itself, not a child element
    if (!zone.contains(e.relatedTarget)) zone.classList.remove('drag-over');
  });
  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (file) handleWorkoutFile(file);
  });
}

// ── Power ERG setpoint display sync ──────────────────────────────────────────

function wireErgSetpoint() {
  const inp = document.getElementById('erg-setpoint');
  if (!inp) return;
  ergSetpoint = Math.max(0, Math.min(2000, parseInt(inp.value) || 0));
  setText('erg-setpoint-display', `${ergSetpoint}W`);
  inp.addEventListener('input', () => {
    ergSetpoint = Math.max(0, Math.min(2000, parseInt(inp.value) || 0));
    setText('erg-setpoint-display', `${ergSetpoint}W`);
  });
}

// ── Target HR input ───────────────────────────────────────────────────────────

function wireTargetHR() {
  const inp = document.getElementById('target-hr');
  if (!inp) return;
  inp.addEventListener('change', () => setTarget(parseInt(inp.value) || 145));
}

// ── ERG power adjust ─────────────────────────────────────────────────────────

function adjustErg(delta) {
  ergSetpoint = Math.max(0, Math.min(2000, ergSetpoint + delta));
  const inp = document.getElementById('erg-setpoint');
  if (inp) inp.value = ergSetpoint;
  setText('erg-setpoint-display', `${ergSetpoint}W`);
  if (ergActive) sendPower(ergSetpoint).catch(e => log(`ERG adjust: ${e.message}`, 'warn'));
}

// ── Global button wiring ──────────────────────────────────────────────────────

function wireButtons() {
  bindClick('btn-connect-trainer', () => connectDevice('trainer'));
  bindClick('btn-connect-dircon',  () => connectDircon());
  bindClick('btn-connect-hr',      () => connectDevice('hr'));
  bindClick('btn-servo',           () => toggleServo());
  bindClick('btn-pause-servo',     () => toggleServoPause());
  bindClick('btn-pause-workout',   () => toggleWorkoutPause());
  bindClick('btn-skip-workout',    () => skipWorkoutSegment());
  bindClick('btn-warmup',          () => toggleWarmup());
  bindClick('btn-start-power-erg', () => startPowerErg());
  bindClick('btn-stop-power-erg',  () => stopPowerErg());
  bindClick('btn-start-session',   () => startSession());
  bindClick('btn-stop-session',    () => stopSession());
  bindClick('btn-dl-csv',          () => downloadCsv());
  bindClick('btn-dl-fit',          () => downloadFit());
  bindClick('btn-dl-log',          () => downloadLog());
  bindClick('btn-save-profile',    () => saveProfile());
  bindClick('btn-toggle-log',      () => toggleLog());

  bindClick('btn-hr-up',   () => adjustTarget(+1));
  bindClick('btn-hr-down', () => adjustTarget(-1));
  bindClick('btn-hr-up5',  () => adjustTarget(+5));
  bindClick('btn-hr-down5',() => adjustTarget(-5));

  bindClick('btn-erg-up10',   () => adjustErg(+10));
  bindClick('btn-erg-down10', () => adjustErg(-10));
  bindClick('btn-erg-up50',   () => adjustErg(+50));
  bindClick('btn-erg-down50', () => adjustErg(-50));

  document.querySelectorAll('.mode-tab').forEach(btn => {
    btn.addEventListener('click', () => setMode(btn.dataset.mode));
  });
}

function bindClick(id, fn) {
  const el = document.getElementById(id);
  if (el) el.addEventListener('click', fn);
}

// ── Slider wiring ─────────────────────────────────────────────────────────────

function wireSliders() {
  ['kp','ki','kd','tick','maxdelta','deadband','pmin','pmax','wu-dur'].forEach(syncSlider);
}

// ── Resize handler ────────────────────────────────────────────────────────────

function wireResize() {
  let debounce = null;
  window.addEventListener('resize', () => {
    clearTimeout(debounce);
    debounce = setTimeout(() => {
      drawOverview();
      drawRolling();
      drawWorkoutProfile(workoutRawSegs);
    }, 150);
  });
}

// ── Init ──────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  loadProfile();
  const defaultHR = Math.round(profile.restHR + 0.5 * (profile.maxHR - profile.restHR));
  setTarget(defaultHR);
  wireButtons();
  wireSliders();
  wireWorkoutButtons();
  wireDragDrop();
  wireErgSetpoint();
  wireTargetHR();
  wireResize();
  setMode('passive');
  updateServoBtn();
  updateErgIndicator('idle');
  setText('session-timer', '00:00:00');
  log('ERG Controller ready', 'ok');
});
