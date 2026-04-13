'use strict';

// ── Servo state ───────────────────────────────────────────────────────────────
let servoActive   = false;
let ergSetpoint   = 100;
let pidIntegral   = 0;
let prevError     = null;
let tickTimer     = null;
let tickCountdown = 0;
let countdownTimer = null;

// ── ERG tracking watchdog ─────────────────────────────────────────────────────
let ergTrackFailCount = 0;
let lastErgChangeTime = 0;

// ── Heartbeat (re-send setpoint every 5 s) ───────────────────────────────────
let heartbeatTimer = null;
let heartbeatCount = 0;
// pendingServoPowerSend is declared in ble.js (shared global)

// ── Warm-up state ─────────────────────────────────────────────────────────────
let warmupActive = false;
let warmupSecs   = 0;
let warmupTimer  = null;

// ── Workout target override ───────────────────────────────────────────────────
// When a workout is playing, workout.js sets this to override the DOM target.
let workoutTargetHR = null;

// ── Pause state ───────────────────────────────────────────────────────────────
// servoPaused = true while the servo is temporarily handed back to the rider.
// servoActive remains true so state is preserved on resume.
let servoPaused = false;

function getTargetHR() {
  if (workoutTargetHR !== null) return workoutTargetHR;
  return parseInt(document.getElementById('target-hr').value) || 145;
}

// ── Servo toggle ──────────────────────────────────────────────────────────────

function toggleServo() {
  if (servoActive) stopServo();
  else             startServo();
}

function startServo() {
  servoActive  = true;
  servoPaused  = false;
  pidIntegral  = 0;
  prevError    = null;
  stableCount  = 0;
  prevSetpointSS      = null;
  heartbeatCount      = 0;
  pendingServoPowerSend = false;
  ergTrackFailCount   = 0;
  lastErgChangeTime   = Date.now();

  const pMin = parseInt(document.getElementById('pmin').value);
  const pMax = parseInt(document.getElementById('pmax').value);
  const tgt  = getTargetHR();
  const pred = predictPower(tgt);
  if (pred) {
    ergSetpoint = Math.max(pMin, Math.min(pMax, pred));
    log(`Feedforward from ${predictPowerSource()}: ${ergSetpoint}W for ${tgt} bpm`, 'info');
  } else {
    ergSetpoint = pMin;
  }

  logPIDParams();
  updateServoBtn();
  updateErgIndicator('active');

  if (wahooCP) {
    sendPower(ergSetpoint);
  } else {
    ftmsHandshake();
  }

  startHeartbeat();
  scheduleNextTick();
  if (!sessionActive) startSession();
  log(`Servo started → ${ergSetpoint}W`, 'ok');
}

function stopServo() {
  servoActive = false;
  servoPaused = false;
  clearTimeout(tickTimer);
  clearInterval(countdownTimer);
  stopHeartbeat();

  // Release resistance — switch KICKR to flat-road simulation (same as MyWhoosh handback)
  if (wahooCP) writeChar(wahooCP, [0x41, 0x00, 0x00]).catch(() => {});
  else         writeCPBytes([0x11, 0x00, 0x00, 0x14, 0x00, 0x28, 0x33]).catch(() => {});

  updateServoBtn();
  updateErgIndicator('idle');
  clearPIDStateDisplay();
  log('Servo stopped', 'warn');
}

function logPIDParams() {
  const Kp      = parseFloat(document.getElementById('kp').value);
  const Ki      = parseFloat(document.getElementById('ki').value);
  const Kd      = parseFloat(document.getElementById('kd').value);
  const tick    = parseInt(document.getElementById('tick').value);
  const maxDlt  = parseFloat(document.getElementById('maxdelta').value);
  const pMin    = parseInt(document.getElementById('pmin').value);
  const pMax    = parseInt(document.getElementById('pmax').value);
  log(`PID Kp=${Kp} Ki=${Ki} Kd=${Kd} tick=${tick}s maxΔ=${maxDlt}W pMin=${pMin} pMax=${pMax}W`, 'info');
}

// ── PID tick ──────────────────────────────────────────────────────────────────

function scheduleNextTick() {
  if (!servoActive) return;
  const interval = parseInt(document.getElementById('tick').value) * 1000;
  tickCountdown  = Math.round(interval / 1000);

  clearInterval(countdownTimer);
  countdownTimer = setInterval(() => {
    if (tickCountdown > 0) {
      document.getElementById('st-next').textContent = `${tickCountdown}s`;
      tickCountdown--;
    }
  }, 1000);

  tickTimer = setTimeout(() => {
    clearInterval(countdownTimer);
    pidTick();
    scheduleNextTick();
  }, interval);
}

function pidTick() {
  if (!servoActive || servoPaused || lastHR === null) return;

  const targetHR = getTargetHR();
  const deadband = parseInt(document.getElementById('deadband').value);
  const Kp       = parseFloat(document.getElementById('kp').value);
  const Ki       = parseFloat(document.getElementById('ki').value);
  const Kd       = parseFloat(document.getElementById('kd').value);
  const maxDelta = parseFloat(document.getElementById('maxdelta').value);
  const pMin     = parseInt(document.getElementById('pmin').value);
  const pMax     = parseInt(document.getElementById('pmax').value);

  const error = targetHR - lastHR;   // positive → HR below target → increase power

  if (Math.abs(error) <= deadband) {
    updatePIDStateDisplay(error, pidIntegral, 0, ergSetpoint);
    log(`Tick — HR ${lastHR} tgt ${targetHR} | deadband ±${deadband} · hold ${ergSetpoint}W`, 'info');
    maybeCollectChar();
    return;
  }

  const derivative = (prevError !== null) ? (error - prevError) : 0;
  prevError        = error;

  // Integral with anti-windup clamping
  pidIntegral += error;
  const intClamp = maxDelta * 5 / Math.max(Ki, 0.001);
  pidIntegral    = Math.max(-intClamp, Math.min(intClamp, pidIntegral));

  const rawDelta = Kp * error + Ki * pidIntegral + Kd * derivative;
  const delta    = Math.max(-maxDelta, Math.min(maxDelta, rawDelta));

  let newSetpoint = Math.round(Math.max(pMin, Math.min(pMax, ergSetpoint + delta)));
  if (newSetpoint !== ergSetpoint) lastErgChangeTime = Date.now();
  ergSetpoint = newSetpoint;

  updatePIDStateDisplay(error, pidIntegral, derivative, ergSetpoint);
  log(`Tick — HR ${lastHR} / tgt ${targetHR} | err ${error.toFixed(1)} | Δ ${delta.toFixed(1)}W → ${ergSetpoint}W`, 'info');
  sendPower(ergSetpoint).catch(e => log(`Tick TX failed: ${e.message}`, 'warn'));
  maybeCollectChar();
}

// ── Heartbeat ─────────────────────────────────────────────────────────────────

function startHeartbeat() {
  stopHeartbeat();
  const secs = Math.max(1, parseInt(document.getElementById('hb-interval').value) || 5);
  heartbeatTimer = setInterval(runHeartbeat, secs * 1000);
}

function stopHeartbeat() {
  clearInterval(heartbeatTimer);
  heartbeatTimer = null;
}

async function runHeartbeat() {
  if (!(servoActive || ergActive) || !(wahooCP || ftmsCP)) return;
  heartbeatCount++;
  document.getElementById('m-hb').textContent = heartbeatCount;

  checkERGTracking();

  try {
    if (ftmsCP && !wahooCP && heartbeatCount % 8 === 0) {
      _suppressResumeLog = true;
      await writeCPBytes([0x07]);
    }
    await sendPower(ergSetpoint, /*silent=*/true);
  } catch (e) {
    log(`Heartbeat TX failed: ${e.message}`, 'warn');
  }
}

function checkERGTracking() {
  const SETTLE_MS = 20000, GAP_W = 20, STRIKES = 3;
  if (lastPower === null || Date.now() - lastErgChangeTime <= SETTLE_MS) return;

  if (Math.abs(lastPower - ergSetpoint) > GAP_W) {
    ergTrackFailCount++;
    if (ergTrackFailCount >= STRIKES) {
      log(`ERG tracking lost — actual ${lastPower}W vs setpoint ${ergSetpoint}W — recovering`, 'warn');
      ergTrackFailCount = 0;
      lastErgChangeTime = Date.now();
      updateErgIndicator('gap');
      recoverERG();
    } else {
      log(`ERG gap: actual ${lastPower}W vs setpoint ${ergSetpoint}W (${ergTrackFailCount}/${STRIKES})`, 'warn');
      updateErgIndicator('gap');
    }
  } else {
    ergTrackFailCount = 0;
    updateErgIndicator('active');
  }
}

function recoverERG() {
  if (ftmsCP && !wahooCP) {
    _suppressResumeLog = true;
    writeCPBytes([0x07])
      .then(() => sendPower(ergSetpoint))
      .catch(e => log(`Watchdog recovery failed: ${e.message}`, 'warn'));
  } else {
    sendPower(ergSetpoint).catch(e => log(`Watchdog recovery failed: ${e.message}`, 'warn'));
  }
}

// ── Warm-up ───────────────────────────────────────────────────────────────────

function toggleWarmup() {
  if (warmupActive) stopWarmup(false);
  else              startWarmup();
}

function startWarmup() {
  warmupActive = true;
  warmupSecs   = parseInt(document.getElementById('wu-dur').value) * 60;

  const wuTarget = warmupHRTarget();
  const wuPMax   = warmupPowerCeil();

  setTarget(wuTarget);
  setSlider('maxdelta', 5);
  setSlider('pmin', 50);
  setSlider('pmax', wuPMax);

  if (servoActive) {
    ergSetpoint = Math.min(ergSetpoint, wuPMax);
    sendPower(ergSetpoint);
  }

  updateWarmupDisplay();
  warmupTimer = setInterval(() => {
    warmupSecs--;
    updateWarmupDisplay();
    if (warmupSecs <= 0) stopWarmup(true);
  }, 1000);

  const btn = document.getElementById('btn-warmup');
  btn.textContent = 'STOP WARM-UP';
  btn.classList.add('on');
  stableCount = 0; prevSetpointSS = null;
  log(`Warm-up started — target ${wuTarget} bpm · ceil ${wuPMax}W`, 'ok');
}

function stopWarmup(expired) {
  warmupActive = false;
  clearInterval(warmupTimer);
  warmupTimer  = null;

  setSlider('maxdelta', 20);
  setSlider('pmax', profile.ftp);

  const msg = expired ? 'Warm-up complete' : 'Warm-up stopped early';
  log(`${msg} — limits: 20W/tick · ${profile.ftp}W ceil`, expired ? 'ok' : 'warn');

  document.getElementById('wu-remaining').textContent = '—';
  const btn = document.getElementById('btn-warmup');
  btn.textContent = 'START WARM-UP';
  btn.classList.remove('on');
  stableCount = 0; prevSetpointSS = null;
}

function updateWarmupDisplay() {
  const m = String(Math.floor(warmupSecs / 60)).padStart(2, '0');
  const s = String(warmupSecs % 60).padStart(2, '0');
  document.getElementById('wu-remaining').textContent = `${m}:${s}`;
}

// ── Servo pause / resume ──────────────────────────────────────────────────────

function pauseServo() {
  if (!servoActive || servoPaused) return;
  servoPaused = true;

  // Stop the PID tick cycle
  clearTimeout(tickTimer);
  clearInterval(countdownTimer);

  // Release trainer resistance — switch KICKR to flat-road simulation (same as MyWhoosh handback)
  if (wahooCP) writeChar(wahooCP, [0x41, 0x00, 0x00]).catch(() => {});
  else         writeCPBytes([0x11, 0x00, 0x00, 0x14, 0x00, 0x28, 0x33]).catch(() => {});

  updateErgIndicator('idle');
  updatePauseBtn();
  log('Servo paused — ERG released to rider', 'warn');
}

function resumeServo() {
  if (!servoActive || !servoPaused) return;
  servoPaused = false;

  // Re-take ERG control and immediately push the current setpoint
  if (wahooCP) {
    sendPower(ergSetpoint).catch(e => log(`Resume TX: ${e.message}`, 'warn'));
  } else {
    ftmsHandshake();
  }

  scheduleNextTick();
  updateErgIndicator('active');
  updatePauseBtn();
  log(`Servo resumed → ${ergSetpoint}W`, 'ok');
}

function toggleServoPause() {
  if (servoPaused) resumeServo();
  else             pauseServo();
}

function updatePauseBtn() {
  const btn = document.getElementById('btn-pause-servo');
  if (!btn) return;
  btn.textContent  = servoPaused ? 'CONTINUE' : 'PAUSE';
  btn.classList.toggle('on', !servoPaused && servoActive);
  btn.disabled = !servoActive;
}

// ── Target HR helpers ─────────────────────────────────────────────────────────

function adjustTarget(delta) {
  const inp = document.getElementById('target-hr');
  const v   = Math.max(60, Math.min(220, parseInt(inp.value || 145) + delta));
  setTarget(v);
}

function setTarget(v) {
  const prev = parseInt(document.getElementById('target-hr').value) || v;
  document.getElementById('target-hr').value       = v;
  document.getElementById('target-hr-big').textContent = v;
  if (servoActive && Math.abs(v - prev) > 3) {
    pidIntegral = 0; prevError = null; stableCount = 0; prevSetpointSS = null;
    log(`Target ${prev}→${v} bpm — integral reset`, 'info');
  }
}

// ── Slider helper ─────────────────────────────────────────────────────────────

function setSlider(id, value) {
  const el = document.getElementById(id);
  if (!el) return;
  el.value = value;
  const vEl = document.getElementById(`${id}-v`);
  if (vEl) vEl.textContent = el.value;
}

// ── Display helpers ───────────────────────────────────────────────────────────

function updatePIDStateDisplay(error, integral, derivative, setpoint) {
  document.getElementById('st-err').textContent = error.toFixed(1);
  document.getElementById('st-int').textContent = integral.toFixed(2);
  document.getElementById('st-der').textContent = derivative.toFixed(2);
  document.getElementById('st-out').textContent = setpoint;
  document.getElementById('cv-tgt').querySelector('.cv-val').textContent = setpoint + 'W';
  document.getElementById('erg-setpoint-display').textContent = setpoint + 'W';
}

function clearPIDStateDisplay() {
  ['st-err','st-int','st-der','st-out','st-next','m-hb'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = '—';
  });
  document.getElementById('cv-tgt').querySelector('.cv-val').textContent = '—';
}
