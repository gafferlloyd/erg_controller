'use strict';

// ── Raw workout display segments ──────────────────────────────────────────────
// Stored separately from workoutSegments (which are mode-converted for playback).
// Each entry: { durationSecs, lo, hi, ramp?, freeride? }
// lo/hi are raw %FTP fractions (not converted to HR).
let workoutRawSegs = [];

// ── ZWO → raw display segments ────────────────────────────────────────────────

function parseZwoRaw(xmlText) {
  const doc     = new DOMParser().parseFromString(xmlText, 'application/xml');
  const workout = doc.querySelector('workout');
  if (!workout) return [];
  const segs = [];
  for (const node of workout.children) {
    const dur = parseInt(node.getAttribute('Duration') || 0);
    const tag = node.tagName;
    if (tag === 'Warmup' || tag === 'Cooldown') {
      const lo = parseFloat(node.getAttribute('PowerLow')  || 0.25);
      const hi = parseFloat(node.getAttribute('PowerHigh') || 0.75);
      segs.push({ durationSecs: dur, lo, hi, ramp: true });
    } else if (tag === 'SteadyState') {
      const frac = parseFloat(node.getAttribute('Power') || 0.75);
      segs.push({ durationSecs: dur, lo: frac, hi: frac });
    } else if (tag === 'IntervalsT') {
      const rep    = parseInt(node.getAttribute('Repeat')      || 1);
      const onDur  = parseInt(node.getAttribute('OnDuration')  || 30);
      const offDur = parseInt(node.getAttribute('OffDuration') || 90);
      const onFrac = parseFloat(node.getAttribute('OnPower')   || 1.0);
      const offFrac= parseFloat(node.getAttribute('OffPower')  || 0.5);
      for (let i = 0; i < rep; i++) {
        segs.push({ durationSecs: onDur,  lo: onFrac,  hi: onFrac  });
        segs.push({ durationSecs: offDur, lo: offFrac, hi: offFrac });
      }
    } else if (tag === 'FreeRide') {
      segs.push({ durationSecs: dur, lo: 0.5, hi: 0.5, freeride: true });
    }
  }
  return segs;
}

// ── Zone colour ───────────────────────────────────────────────────────────────

function zoneColor(frac) {
  if (frac < 0.55) return '#606060';   // Z1 Recovery
  if (frac < 0.75) return '#4a86c8';   // Z2 Endurance
  if (frac < 0.87) return '#5aa83a';   // Z3 Tempo
  if (frac < 0.95) return '#d4a017';   // Z4 Sweet Spot
  if (frac < 1.05) return '#e06c00';   // Z5 Threshold
  if (frac < 1.20) return '#cc2222';   // Z6 VO2max
  return '#9c3fff';                     // Z7 Anaerobic
}

// ── Draw ──────────────────────────────────────────────────────────────────────

function drawWorkoutProfile(segs, elapsedSecs) {
  const canvas = document.getElementById('workout-profile-canvas');
  if (!canvas) return;
  const dpr  = window.devicePixelRatio || 1;
  const cssW = canvas.offsetWidth;
  const cssH = canvas.offsetHeight;
  if (cssW < 4 || cssH < 4) return;

  canvas.width  = Math.round(cssW * dpr);
  canvas.height = Math.round(cssH * dpr);
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, cssW, cssH);

  if (!segs || !segs.length) {
    ctx.fillStyle = 'rgba(139,148,158,0.25)';
    ctx.font = '11px monospace';
    ctx.textAlign = 'center';
    ctx.fillText('Drop a .zwo file to preview', cssW / 2, cssH / 2 + 4);
    return;
  }

  const totalSecs = segs.reduce((a, s) => a + s.durationSecs, 0);
  const maxFrac   = Math.max(1.35, ...segs.map(s => Math.max(s.lo, s.hi)));
  const padTop    = 4;
  const padBot    = 16;  // space for time labels
  const drawH     = cssH - padTop - padBot;
  const baseY     = padTop + drawH;

  // Background
  ctx.fillStyle = '#0d1117';
  ctx.fillRect(0, 0, cssW, cssH);

  // Draw segments
  let x = 0;
  for (const seg of segs) {
    const segW = (seg.durationSecs / totalSecs) * cssW;
    if (seg.ramp) {
      const yLo  = baseY - (seg.lo / maxFrac) * drawH;
      const yHi  = baseY - (seg.hi / maxFrac) * drawH;
      const mid  = (seg.lo + seg.hi) / 2;
      ctx.fillStyle = zoneColor(mid);
      ctx.beginPath();
      ctx.moveTo(x,        baseY);
      ctx.lineTo(x,        yLo);
      ctx.lineTo(x + segW, yHi);
      ctx.lineTo(x + segW, baseY);
      ctx.closePath();
      ctx.fill();
    } else {
      const barH = (seg.lo / maxFrac) * drawH;
      ctx.fillStyle = zoneColor(seg.lo);
      ctx.fillRect(Math.floor(x), baseY - barH, Math.ceil(segW), barH);
    }
    x += segW;
  }

  // FTP reference line at 1.0
  const ftpY = baseY - (1.0 / maxFrac) * drawH;
  ctx.save();
  ctx.strokeStyle = 'rgba(255,255,255,0.22)';
  ctx.setLineDash([3, 4]);
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(0, ftpY);
  ctx.lineTo(cssW, ftpY);
  ctx.stroke();
  ctx.restore();

  // FTP label
  ctx.fillStyle = 'rgba(255,255,255,0.28)';
  ctx.font = '8px monospace';
  ctx.textAlign = 'right';
  ctx.fillText('FTP', cssW - 2, ftpY - 2);

  // Time axis labels
  const totalMins = totalSecs / 60;
  const step = totalMins <= 30 ? 5 : totalMins <= 60 ? 10 : 15;
  ctx.fillStyle = 'rgba(139,148,158,0.65)';
  ctx.font = '9px monospace';
  for (let m = 0; m <= totalMins; m += step) {
    const lx = (m / totalMins) * cssW;
    ctx.textAlign = m === 0 ? 'left' : m >= totalMins - 1 ? 'right' : 'center';
    ctx.fillText(`${m}′`, lx, cssH - 3);
  }

  // Playback cursor
  if (elapsedSecs != null && elapsedSecs > 0 && elapsedSecs < totalSecs) {
    const cx = (elapsedSecs / totalSecs) * cssW;
    ctx.save();
    ctx.strokeStyle = 'rgba(255,255,255,0.85)';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.moveTo(cx, padTop);
    ctx.lineTo(cx, baseY);
    ctx.stroke();
    ctx.restore();

    // Elapsed fill overlay
    ctx.fillStyle = 'rgba(0,0,0,0.35)';
    ctx.fillRect(0, padTop, cx, drawH);
  }
}

// Called every second during workout playback.
function updateWorkoutProfileCursor(player) {
  if (!player || !workoutRawSegs.length) return;
  drawWorkoutProfile(workoutRawSegs, player.totalElapsed);
}
