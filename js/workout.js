'use strict';

// ── Workout segment schema ────────────────────────────────────────────────────
// Each segment: { label, durationSecs, targetType, targetValue }
// targetType: 'power-frac' | 'hr-hrr'
// targetValue for 'power-frac': fraction of FTP (e.g. 0.75)
// targetValue for 'hr-hrr':    %HRR (e.g. 70 = 70 %HRR)

let workoutSegments  = [];   // parsed segment list
let workoutPlayer    = null; // active WorkoutPlayer instance

// ── .ZWO parser ───────────────────────────────────────────────────────────────

function parseZwo(xmlText, mode) {
  const doc      = new DOMParser().parseFromString(xmlText, 'application/xml');
  const workout  = doc.querySelector('workout');
  if (!workout) throw new Error('No <workout> element in ZWO file');

  const segments = [];
  for (const node of workout.children) {
    const parsed = parseZwoNode(node, mode);
    if (parsed) segments.push(...parsed);
  }
  return segments;
}

function parseZwoNode(node, mode) {
  const dur    = parseInt(node.getAttribute('Duration') || 0);
  const tag    = node.tagName;

  if (tag === 'Warmup' || tag === 'Cooldown') {
    const lo = parseFloat(node.getAttribute('PowerLow')  || 0.25);
    const hi = parseFloat(node.getAttribute('PowerHigh') || 0.75);
    return buildRampSegments(tag, dur, lo, hi, mode);
  }

  if (tag === 'SteadyState') {
    const frac = parseFloat(node.getAttribute('Power') || 0.75);
    return [buildSteadySegment(tag, dur, frac, mode)];
  }

  if (tag === 'IntervalsT') {
    return buildIntervalSegments(node, mode);
  }

  if (tag === 'FreeRide') {
    return [{ label: 'Free Ride', durationSecs: dur, targetType: null, targetValue: null }];
  }

  return null;
}

// Build a series of 5-second micro-segments approximating a ramp.
function buildRampSegments(label, durationSecs, loFrac, hiFrac, mode) {
  const steps   = Math.max(1, Math.floor(durationSecs / 5));
  const stepDur = Math.round(durationSecs / steps);
  const segs    = [];
  for (let i = 0; i < steps; i++) {
    const frac = loFrac + (hiFrac - loFrac) * (i / Math.max(steps - 1, 1));
    segs.push(buildSteadySegment(`${label} ${i + 1}/${steps}`, stepDur, frac, mode));
  }
  return segs;
}

function buildSteadySegment(label, durationSecs, powerFrac, mode) {
  if (mode === 'hr-servo') {
    // Convert %FTP power to %HRR, clip at 100 %HRR
    const watts  = powerFrac * profile.ftp;
    const estHR  = profile.modelA * watts + profile.modelB;
    const hrrPct = Math.min(100, calcHRR(estHR, profile.restHR, profile.maxHR) ?? 100);
    return { label, durationSecs, targetType: 'hr-hrr', targetValue: hrrPct };
  }
  return { label, durationSecs, targetType: 'power-frac', targetValue: powerFrac };
}

function buildIntervalSegments(node, mode) {
  const repeat  = parseInt(node.getAttribute('Repeat')      || 1);
  const onDur   = parseInt(node.getAttribute('OnDuration')  || 30);
  const offDur  = parseInt(node.getAttribute('OffDuration') || 90);
  const onFrac  = parseFloat(node.getAttribute('OnPower')   || 1.0);
  const offFrac = parseFloat(node.getAttribute('OffPower')  || 0.5);
  const segs    = [];
  for (let i = 0; i < repeat; i++) {
    segs.push(buildSteadySegment(`Interval ${i + 1} ON`,  onDur,  onFrac,  mode));
    segs.push(buildSteadySegment(`Interval ${i + 1} OFF`, offDur, offFrac, mode));
  }
  return segs;
}

// ── ASCII parser ──────────────────────────────────────────────────────────────
// Format (time in minutes, value in %HRR or %FTP fraction):
//   # Comment
//   0   40       ← at 0 min, target = 40 %HRR (or 0.40 FTP)
//   5   60
//   10  75
// Values are linearly interpolated between points.
// The mode parameter ('hr-servo' | 'power-erg') determines targetType.

function parseAscii(text, mode) {
  const points = [];
  for (const line of text.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const parts = trimmed.split(/[\s,]+/);
    if (parts.length < 2) continue;
    const timeMins = parseFloat(parts[0]);
    let   value    = parseFloat(parts[1]);
    if (isNaN(timeMins) || isNaN(value)) continue;
    // Normalise: if value >1 treat as percentage, else as fraction
    if (value > 1) value = value / 100;
    points.push({ timeSecs: Math.round(timeMins * 60), value });
  }
  if (points.length < 2) throw new Error('Need at least 2 data points');
  return interpolateAsciiToSegments(points, mode);
}

function interpolateAsciiToSegments(points, mode) {
  const STEP = 5;   // interpolate every 5 seconds
  const segs  = [];
  const last  = points[points.length - 1];

  for (let t = points[0].timeSecs; t < last.timeSecs; t += STEP) {
    const frac = interpolateAt(points, t);
    const seg  = buildSteadySegment(`t=${Math.round(t/60)}min`, STEP, frac, mode);
    segs.push(seg);
  }
  return segs;
}

function interpolateAt(points, t) {
  for (let i = 0; i < points.length - 1; i++) {
    if (t >= points[i].timeSecs && t <= points[i + 1].timeSecs) {
      const span = points[i + 1].timeSecs - points[i].timeSecs;
      const alpha = span > 0 ? (t - points[i].timeSecs) / span : 0;
      return points[i].value + alpha * (points[i + 1].value - points[i].value);
    }
  }
  return points[points.length - 1].value;
}

// ── Workout Player ────────────────────────────────────────────────────────────

class WorkoutPlayer {
  constructor(segments) {
    this.segments     = segments;
    this.segIdx       = 0;
    this.segElapsed   = 0;
    this.totalElapsed = 0;
    this.timer        = null;
    this.done         = false;
  }

  get totalDuration() {
    return this.segments.reduce((a, s) => a + s.durationSecs, 0);
  }

  get currentSegment() { return this.segments[this.segIdx] || null; }

  start() {
    this.timer = setInterval(() => this._tick(), 1000);
    this._applyTarget();
    log(`Workout started — ${this.segments.length} segments, ${Math.round(this.totalDuration / 60)} min`, 'ok');
  }

  stop() {
    clearInterval(this.timer);
    this.timer = null;
    workoutTargetHR = null;
  }

  pause() {
    if (!this.timer || this.done) return;
    clearInterval(this.timer);
    this.timer = null;
    // Hand ERG back to the rider via servo pause
    if (servoActive && !servoPaused) pauseServo();
    log('Workout paused', 'warn');
    updateWorkoutPauseBtn();
  }

  resume() {
    if (this.timer || this.done) return;
    this.timer = setInterval(() => this._tick(), 1000);
    // Re-apply current segment target and re-take servo control
    this._applyTarget();
    if (servoActive && servoPaused) resumeServo();
    log('Workout resumed', 'ok');
    updateWorkoutPauseBtn();
  }

  get isPaused() { return !this.timer && !this.done; }

  _tick() {
    this.segElapsed++;
    this.totalElapsed++;
    const seg = this.currentSegment;
    if (!seg) { this._finish(); return; }

    if (this.segElapsed >= seg.durationSecs) {
      this.segIdx++;
      this.segElapsed = 0;
      if (this.segIdx >= this.segments.length) { this._finish(); return; }
      this._applyTarget();
    }

    updateWorkoutBar(this);
    updateWorkoutProfileCursor(this);
  }

  // Resolve the current segment's target and push it to the appropriate controller.
  _applyTarget() {
    const seg = this.currentSegment;
    if (!seg || !seg.targetType) return;

    if (seg.targetType === 'hr-hrr') {
      // HR-Servo mode: convert %HRR back to absolute HR and override PID target
      const hr = Math.round(profile.restHR + seg.targetValue / 100 * (profile.maxHR - profile.restHR));
      workoutTargetHR = hr;
      setTarget(hr);
    } else if (seg.targetType === 'power-frac') {
      // Power-ERG mode: set power directly
      const watts = Math.round(seg.targetValue * profile.ftp);
      ergSetpoint = Math.max(0, Math.min(2000, watts));
      sendPower(ergSetpoint).catch(e => log(`Workout TX: ${e.message}`, 'warn'));
      document.getElementById('erg-setpoint-display').textContent = ergSetpoint + 'W';
    }
  }

  _finish() {
    this.done = true;
    clearInterval(this.timer);
    workoutTargetHR = null;
    log('Workout complete', 'ok');
    updateWorkoutBarDone();
  }
}

// ── File loading ──────────────────────────────────────────────────────────────

// Accept a raw File object — used by both the file input and drag-and-drop.
function handleWorkoutFile(file) {
  if (!file) return;
  const reader = new FileReader();
  reader.onload = e => {
    try {
      const mode = currentMode;   // 'hr-servo' | 'power-erg'
      if (file.name.endsWith('.zwo')) {
        workoutSegments = parseZwo(e.target.result, mode);
        workoutRawSegs  = parseZwoRaw(e.target.result);
      } else {
        workoutSegments = parseAscii(e.target.result, mode);
        workoutRawSegs  = [];
      }
      const totalMin = Math.round(workoutSegments.reduce((a, s) => a + s.durationSecs, 0) / 60);
      document.getElementById('seg-name').textContent = `${file.name} — ${totalMin} min`;
      document.getElementById('btn-start-workout').disabled = false;
      setTimeout(() => drawWorkoutProfile(workoutRawSegs), 30);
      log(`Workout loaded: ${workoutSegments.length} segments, ${totalMin} min`, 'ok');
    } catch (err) {
      log(`Workout load failed: ${err.message}`, 'err');
    }
  };
  reader.readAsText(file);
}

function loadWorkoutFile(input) {
  handleWorkoutFile(input.files[0]);
}

function startWorkout() {
  if (!workoutSegments.length) return;
  if (workoutPlayer) workoutPlayer.stop();
  workoutPlayer = new WorkoutPlayer(workoutSegments);
  workoutPlayer.start();
  updateWorkoutPauseBtn();
}

function stopWorkout() {
  if (workoutPlayer) {
    workoutPlayer.stop();
    workoutPlayer = null;
  }
  workoutTargetHR = null;
  updateWorkoutBarDone();
  updateWorkoutPauseBtn();
  log('Workout stopped', 'warn');
}

function toggleWorkoutPause() {
  if (!workoutPlayer) return;
  if (workoutPlayer.isPaused) workoutPlayer.resume();
  else                        workoutPlayer.pause();
}

function updateWorkoutPauseBtn() {
  const btn = document.getElementById('btn-pause-workout');
  if (!btn) return;
  const paused = workoutPlayer ? workoutPlayer.isPaused : false;
  btn.textContent = paused ? '▶ Continue' : '⏸ Pause';
  btn.disabled    = !workoutPlayer || workoutPlayer.done;
}

// ── Power ERG (direct, no PID) ────────────────────────────────────────────────

let ergActive = false;

function startPowerErg() {
  if (!trainerLive) return;
  ergActive = true;
  ergHandshakeDone = false;
  pendingServoPowerSend = false;
  updateErgIndicator('active');
  if (wahooCP) {
    sendPower(ergSetpoint);
  } else {
    ftmsHandshake();
  }
  startHeartbeat();
  if (!sessionActive) startSession();
  log('Power ERG started', 'ok');
}

function stopPowerErg() {
  ergActive = false;
  stopHeartbeat();
  // Release resistance — switch KICKR to flat-road simulation (same as MyWhoosh handback)
  if (wahooCP) writeChar(wahooCP, [0x41, 0x00, 0x00]).catch(() => {});
  else         writeCPBytes([0x11, 0x00, 0x00, 0x14, 0x00, 0x28, 0x33]).catch(() => {});
  updateErgIndicator('idle');
  log('Power ERG stopped', 'warn');
}
