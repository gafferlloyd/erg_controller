'use strict';

// ══════════════════════════════════════════════════════
//  Servo state
// ══════════════════════════════════════════════════════
let servoActive   = false;
let ergSetpoint   = 100;
let pidIntegral   = 0;
let prevError     = null;
let tickTimer     = null;
let tickCountdown = 0;
let countdownTimer = null;

// ── ERG tracking watchdog ──────────────────────────────
// Compares lastPower (CPS) with ergSetpoint after the trainer has had time
// to settle. Three consecutive heartbeat strikes → recovery attempt.
let ergTrackFailCount = 0;
let lastErgChangeTime = 0;    // ms timestamp — when ergSetpoint last changed

// ══════════════════════════════════════════════════════
//  Power heartbeat (re-send every 5 s)
//  FTMS has no "query current ERG target" command —
//  the control point is write-only for targets.
//  Periodic re-send ensures any corrupted value
//  decays within 5 s.
// ══════════════════════════════════════════════════════
let heartbeatTimer = null;
let heartbeatCount = 0;

function startHeartbeat() {
  stopHeartbeat();
  heartbeatTimer = setInterval(async () => {
    if (!servoActive || !(wahooCP || ftmsCP)) return;
    heartbeatCount++;
    document.getElementById('m-hb').textContent = heartbeatCount;

    // ── ERG tracking watchdog ──────────────────────────
    // After a 20 s settle window, check that the trainer's reported power
    // is tracking the setpoint. Three strikes → recovery.
    const SETTLE_MS = 20000, GAP_W = 20, STRIKES = 3;
    if (lastPower !== null && Date.now() - lastErgChangeTime > SETTLE_MS) {
      const gap = Math.abs(lastPower - ergSetpoint);
      if (gap > GAP_W) {
        ergTrackFailCount++;
        if (ergTrackFailCount >= STRIKES) {
          log(`ERG tracking lost — actual ${lastPower}W vs setpoint ${ergSetpoint}W — recovering`, 'warn');
          ergTrackFailCount = 0;
          lastErgChangeTime = Date.now();   // suppress further alerts during recovery
          if (ftmsCP && !wahooCP) {
            _suppressResumeLog = true;
            writeCPBytes([0x07])
              .then(() => sendPower(ergSetpoint))
              .catch(e => log(`Watchdog recovery failed: ${e.message}`, 'warn'));
          } else {
            sendPower(ergSetpoint).catch(e => log(`Watchdog recovery failed: ${e.message}`, 'warn'));
          }
        } else {
          log(`ERG gap: actual ${lastPower}W vs setpoint ${ergSetpoint}W (${ergTrackFailCount}/${STRIKES})`, 'warn');
        }
      } else {
        ergTrackFailCount = 0;   // tracking OK — reset silently
      }
    }

    // ── Re-send current setpoint ───────────────────────
    // The KICKR SHIFT has a ~60 s FTMS Running-state timeout; without a
    // periodic 0x07 it silently drops ERG mode.  Sending 0x07 every 5 s
    // was too frequent — the trainer restarted its ERG ramp each time.
    // Every 8th heartbeat (≈40 s) keeps the machine alive without hitting
    // the ramp during normal steady-state operation.
    try {
      if (ftmsCP && !wahooCP && heartbeatCount % 8 === 0) {
        _suppressResumeLog = true;
        await writeCPBytes([0x07]);
      }
      await sendPower(ergSetpoint, /*silent=*/true);
    } catch(e) {
      log(`Heartbeat TX failed: ${e.message}`, 'warn');
    }
  }, 5000);
}

function stopHeartbeat() {
  clearInterval(heartbeatTimer);
  heartbeatTimer = null;
}

// ══════════════════════════════════════════════════════
//  Warm-up state
// ══════════════════════════════════════════════════════
let warmupActive = false;
let warmupSecs   = 0;
let warmupTimer  = null;

// ══════════════════════════════════════════════════════
//  HR Target — big button adjustment
// ══════════════════════════════════════════════════════
function adjustTarget(delta) {
  const inp = document.getElementById('target-hr');
  const v   = Math.max(60, Math.min(220, parseInt(inp.value || 145) + delta));
  setTarget(v);
}

function setTarget(v) {
  const prev = parseInt(document.getElementById('target-hr').value) || v;
  document.getElementById('target-hr').value = v;
  document.getElementById('target-hr-big').textContent = v;
  document.getElementById('m-target').textContent = v;
  // Large target change while servo is running: reset integral and characteristic
  // stability counter so accumulated windup from the old target doesn't carry over.
  if (servoActive && Math.abs(v - prev) > 3) {
    pidIntegral = 0; prevError = null; stableCount = 0; prevSetpointSS = null;
    log(`Target ${prev}→${v} bpm — integral reset`, 'info');
  }
}

// ══════════════════════════════════════════════════════
//  Slider helper
// ══════════════════════════════════════════════════════
function setSlider(id, value) {
  const el = document.getElementById(id);
  el.value = value;
  // Read back the browser-snapped value (step constraints may adjust it)
  document.getElementById(`${id}-v`).textContent = el.value;
}

// ══════════════════════════════════════════════════════
//  Warm-up
// ══════════════════════════════════════════════════════
function toggleWarmup() {
  if (warmupActive) stopWarmup(false);
  else              startWarmup();
}

function startWarmup() {
  warmupActive = true;
  warmupSecs   = parseInt(document.getElementById('wu-dur').value) * 60;

  const rest = parseInt(document.getElementById('prof-rest').value) || profile.restHR;
  const max  = parseInt(document.getElementById('prof-max').value)  || profile.maxHR;
  const ftp  = parseInt(document.getElementById('prof-ftp').value)  || profile.ftp;
  const wuTarget = Math.round(rest + 0.40 * (max - rest));
  const wuPMax   = Math.round(0.50 * ftp);

  setTarget(wuTarget);
  setSlider('maxdelta', 5);
  setSlider('pmin', 50);
  setSlider('pmax', wuPMax);

  // If servo is already running, clamp current setpoint to warmup ceiling immediately
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
  setBadge('WARM-UP', 'warmup');
  stableCount = 0; prevSetpointSS = null;

  log(`Warm-up started — target ${wuTarget} bpm · ceil ${wuPMax}W · 5W/tick`, 'ok');
}

function stopWarmup(expired) {
  warmupActive = false;
  clearInterval(warmupTimer);
  warmupTimer = null;

  // Both expiry and early stop apply normal limits.
  // If you want to stay at warmup limits, adjust PID sliders manually.
  const ftp = parseInt(document.getElementById('prof-ftp').value) || profile.ftp;
  setSlider('maxdelta', 20);
  setSlider('pmax', ftp);

  if (expired) {
    log(`Warm-up complete — limits: 20W/tick · ${ftp}W ceil`, 'ok');
  } else {
    log(`Warm-up stopped early — limits: 20W/tick · ${ftp}W ceil`, 'warn');
  }

  document.getElementById('wu-remaining').textContent = '—';
  const btn = document.getElementById('btn-warmup');
  btn.textContent = 'START WARM-UP';
  btn.classList.remove('on');
  setBadge('NORMAL', 'normal');
  stableCount = 0; prevSetpointSS = null;
}

function updateWarmupDisplay() {
  const m = String(Math.floor(warmupSecs / 60)).padStart(2, '0');
  const s = String(warmupSecs % 60).padStart(2, '0');
  document.getElementById('wu-remaining').textContent = `${m}:${s}`;
}

function setBadge(text, cls) {
  const el = document.getElementById('mode-badge');
  el.textContent = text;
  el.className = `mode-badge ${cls}`;
}

// ══════════════════════════════════════════════════════
//  Servo toggle
// ══════════════════════════════════════════════════════
function updateServoBtn() {
  document.getElementById('btn-servo').disabled = !(trainerLive && hrLive && (wahooCP || ftmsCP));
}

function toggleServo() {
  servoActive = !servoActive;
  const btn = document.getElementById('btn-servo');

  if (servoActive) {
    pidIntegral = 0; prevError = null;
    stableCount = 0; prevSetpointSS = null;
    heartbeatCount = 0; pendingServoPowerSend = false;
    ergTrackFailCount = 0; lastErgChangeTime = Date.now();

    const tgt      = parseInt(document.getElementById('target-hr').value);
    const pMin     = parseInt(document.getElementById('pmin').value);
    const pMax     = parseInt(document.getElementById('pmax').value);
    const Kp_      = parseFloat(document.getElementById('kp').value);
    const Ki_      = parseFloat(document.getElementById('ki').value);
    const Kd_      = parseFloat(document.getElementById('kd').value);
    const tick_    = parseInt(document.getElementById('tick').value);
    const maxDlt_  = parseFloat(document.getElementById('maxdelta').value);
    const pred     = predictPower(tgt);
    if (pred) {
      ergSetpoint = Math.max(pMin, Math.min(pMax, pred));
      log(`Feedforward from ${predictPowerSource()}: ${ergSetpoint}W for ${tgt} bpm`, 'info');
    } else {
      ergSetpoint = pMin;
    }
    log(`PID Kp=${Kp_} Ki=${Ki_} Kd=${Kd_} tick=${tick_}s maxΔ=${maxDlt_}W pMin=${pMin} pMax=${pMax}W`, 'info');

    btn.textContent = 'SERVO ON';
    btn.classList.add('on');

    if (wahooCP) {
      sendPower(ergSetpoint);            // Wahoo: no handshake, fire immediately
    } else {
      ftmsHandshake();                   // FTMS: 0x00 → wait 0x80 → 0x07 → 0x05
    }

    chartTimer = setInterval(sampleChart, 1000);
    scheduleNextTick();
    startHeartbeat();
    log(`Servo started → ${ergSetpoint}W (${wahooCP ? 'Wahoo' : 'FTMS'})`, 'ok');

  } else {
    servoActive = false;
    btn.textContent = 'SERVO OFF';
    btn.classList.remove('on');
    clearTimeout(tickTimer);
    clearInterval(chartTimer);
    clearInterval(countdownTimer);
    stopHeartbeat();
    document.getElementById('st-next').textContent = '—';
    document.getElementById('m-hb').textContent    = '—';
    document.getElementById('m-err').textContent   = '—';
    document.getElementById('m-err').style.color   = '';
    // Release resistance: Wahoo — set resistance to 0; FTMS — Stop opcode
    if (wahooCP) writeChar(wahooCP, [0x41, 0x00, 0x00]).catch(() => {});
    else         writeCPBytes([0x08]).catch(() => {});
    log('Servo stopped', 'warn');
  }
}

// ══════════════════════════════════════════════════════
//  PID tick
// ══════════════════════════════════════════════════════
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
  if (!servoActive || lastHR === null) return;

  const targetHR = parseInt(document.getElementById('target-hr').value);
  const deadband = parseInt(document.getElementById('deadband').value);
  const Kp       = parseFloat(document.getElementById('kp').value);
  const Ki       = parseFloat(document.getElementById('ki').value);
  const Kd       = parseFloat(document.getElementById('kd').value);
  const maxDelta = parseFloat(document.getElementById('maxdelta').value);
  const pMin     = parseInt(document.getElementById('pmin').value);
  const pMax     = parseInt(document.getElementById('pmax').value);

  // Positive error → HR below target → increase power
  const error = targetHR - lastHR;

  if (Math.abs(error) <= deadband) {
    document.getElementById('st-err').textContent  = error.toFixed(1);
    document.getElementById('st-int').textContent  = pidIntegral.toFixed(2);
    document.getElementById('st-der').textContent  = '0 (deadband)';
    document.getElementById('st-out').textContent  = ergSetpoint;
    document.getElementById('m-target').textContent   = targetHR;
    document.getElementById('m-setpoint').textContent = ergSetpoint;
    log(`Tick — HR ${lastHR} tgt ${targetHR} | deadband ±${deadband} · hold ${ergSetpoint}W`, 'info');
    maybeCollectChar();
    return;
  }

  // Derivative (note: computed on HR which lags power by 30–60 s — keep Kd small)
  const derivative = (prevError !== null) ? (error - prevError) : 0;
  prevError = error;

  // Integral with anti-windup clamping
  pidIntegral += error;
  const intClamp = maxDelta * 5 / Math.max(Ki, 0.001);
  pidIntegral = Math.max(-intClamp, Math.min(intClamp, pidIntegral));

  // PID output
  const rawDelta = Kp * error + Ki * pidIntegral + Kd * derivative;
  const delta    = Math.max(-maxDelta, Math.min(maxDelta, rawDelta));

  let newSetpoint = ergSetpoint + delta;
  newSetpoint = Math.round(Math.max(pMin, Math.min(pMax, newSetpoint)));
  if (newSetpoint !== ergSetpoint) lastErgChangeTime = Date.now();
  ergSetpoint = newSetpoint;

  document.getElementById('st-err').textContent  = error.toFixed(1);
  document.getElementById('st-int').textContent  = pidIntegral.toFixed(2);
  document.getElementById('st-der').textContent  = derivative.toFixed(2);
  document.getElementById('st-out').textContent  = ergSetpoint;
  document.getElementById('m-target').textContent   = targetHR;
  document.getElementById('m-setpoint').textContent = ergSetpoint;

  log(`Tick — HR ${lastHR} / tgt ${targetHR} | err ${error.toFixed(1)} | Δ ${delta.toFixed(1)}W → ${ergSetpoint}W`, 'info');
  sendPower(ergSetpoint).catch(e => log(`Tick TX failed: ${e.message}`, 'warn'));
  maybeCollectChar();
}
