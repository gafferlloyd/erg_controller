'use strict';

// ── FIT multi-channel canvas plot ─────────────────────────────────────────────
// Handles: stacked bands, hover crosshair, drag range selection.
//
// Usage:
//   fitPlot.load(channels, hasVAM);
//   fitPlot.onHover  = (idx, vals)         => { … };
//   fitPlot.onSelect = (i0, i1, stats)     => { … };
//   fitPlot.clear();

const fitPlot = (() => {
  // ── Colours (matching existing chart.js palette) ────────────────────────
  const C = {
    power:   '#4fc3f7', smooth: '#ff9800', hr: '#ef5350',
    cadence: '#66bb6a', wpbpm: '#bc8cff',  vam: '#e3b341',
    grid:    'rgba(255,255,255,0.08)', label: 'rgba(255,255,255,0.45)',
    sel:     'rgba(79,195,247,0.12)', selBorder: 'rgba(79,195,247,0.6)',
    cross:   'rgba(255,255,255,0.35)', bg: '#0d1117',
  };

  // ── State ────────────────────────────────────────────────────────────────
  let canvas, ctx, dpr;
  let channels = null;
  let bands    = [];          // [{id, top, bot, color, label, unit, min, max}]
  let hoverIdx = -1;
  let selStart = -1, selEnd = -1, dragging = false;
  let rafPending = false;

  // Callbacks set by caller
  let onHover  = () => {};
  let onSelect = () => {};

  // ── Band layout ──────────────────────────────────────────────────────────

  function buildBands(ch, hasVAM) {
    const result = [];
    const add = (id, label, unit, color, data, extra) => {
      const vals = data.filter(v => v != null);
      if (!vals.length) return;
      const lo = Math.min(...vals);
      const hi = Math.max(...vals);
      result.push({ id, label, unit, color, data, extra,
                    min: lo, max: hi > lo ? hi : lo + 1 });
    };

    add('power',   'Power',   'W',     C.power,   ch.power);
    add('hr',      'HR',      'bpm',   C.hr,      ch.hr);
    add('cadence', 'Cadence', 'rpm',   C.cadence, ch.cadence);
    add('wpbpm',   'W/bpm',   '',      C.wpbpm,   ch.wpbpm);
    if (hasVAM && ch.vam) add('vam', 'VAM', 'm/hr', C.vam, ch.vam);

    // Assign vertical bands evenly
    const n = result.length;
    const gap = 0.01;
    const h = (1 - gap * (n - 1)) / n;
    result.forEach((b, i) => {
      b.top = i * (h + gap);
      b.bot = b.top + h;
    });
    return result;
  }

  // ── Canvas / DPR setup ───────────────────────────────────────────────────

  function resize() {
    dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width  = Math.round(rect.width  * dpr);
    canvas.height = Math.round(rect.height * dpr);
    ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);
    schedule();
  }

  // ── Coordinate mapping ───────────────────────────────────────────────────

  function xToIdx(xPx) {
    if (!channels || !channels.elapsed.length) return 0;
    const rect = canvas.getBoundingClientRect();
    const frac = Math.max(0, Math.min(1, xPx / rect.width));
    return Math.round(frac * (channels.elapsed.length - 1));
  }

  function idxToX(i) {
    const rect = canvas.getBoundingClientRect();
    return i / (channels.elapsed.length - 1) * rect.width;
  }

  function valToY(v, band, h) {
    const frac = 1 - (v - band.min) / (band.max - band.min);
    return (band.top + frac * (band.bot - band.top)) * h;
  }

  // ── Tick helper ──────────────────────────────────────────────────────────

  function niceTicks(lo, hi, n) {
    const range = hi - lo || 1;
    const step  = Math.pow(10, Math.floor(Math.log10(range / n)));
    const nice  = [1, 2, 5, 10].map(f => f * step).find(s => range / s <= n + 1) || step;
    const start = Math.ceil(lo / nice) * nice;
    const ticks = [];
    for (let v = start; v <= hi + 0.001; v += nice) ticks.push(Math.round(v * 100) / 100);
    return ticks;
  }

  // ── Draw ─────────────────────────────────────────────────────────────────

  function draw() {
    rafPending = false;
    if (!ctx || !channels) return;
    const rect = canvas.getBoundingClientRect();
    const w = rect.width, h = rect.height;

    ctx.fillStyle = C.bg;
    ctx.fillRect(0, 0, w, h);

    if (!bands.length) return;

    const n = channels.elapsed.length;

    // ── For each band: grid, line, label ──────────────────────────────────
    bands.forEach(band => {
      const top = band.top * h;
      const bot = band.bot * h;

      // Separator
      ctx.strokeStyle = 'rgba(255,255,255,0.12)';
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(0, top); ctx.lineTo(w, top); ctx.stroke();

      // Grid ticks
      const ticks = niceTicks(band.min, band.max, 3);
      ctx.strokeStyle = C.grid;
      ctx.fillStyle   = C.label;
      ctx.font        = '9px monospace';
      ctx.textAlign   = 'left';
      ctx.lineWidth   = 0.5;
      for (const t of ticks) {
        const y = valToY(t, band, h);
        if (y < top + 2 || y > bot - 2) continue;
        ctx.beginPath(); ctx.moveTo(30, y); ctx.lineTo(w, y); ctx.stroke();
        ctx.fillText(t, 2, y - 2);
      }

      // Label
      ctx.fillStyle = band.color;
      ctx.font = 'bold 9px monospace';
      ctx.textAlign = 'right';
      ctx.fillText(`${band.label}${band.unit ? ' ' + band.unit : ''}`, w - 2, top + 11);

      // ── Data line ───────────────────────────────────────────────────────
      ctx.strokeStyle = band.color;
      ctx.lineWidth   = 1.5;
      ctx.lineJoin    = 'round';
      ctx.beginPath();
      let started = false;
      for (let i = 0; i < n; i++) {
        const v = band.data[i];
        if (v == null) { started = false; continue; }
        const x = (i / (n - 1)) * w;
        const y = valToY(v, band, h);
        if (!started) { ctx.moveTo(x, y); started = true; }
        else            ctx.lineTo(x, y);
      }
      ctx.stroke();

      // Power: overlay smooth line
      if (band.id === 'power' && channels.smooth) {
        ctx.strokeStyle = C.smooth;
        ctx.lineWidth   = 2;
        ctx.beginPath();
        started = false;
        for (let i = 0; i < n; i++) {
          const v = channels.smooth[i];
          if (v == null) { started = false; continue; }
          const x = (i / (n - 1)) * w;
          const y = valToY(v, band, h);
          if (!started) { ctx.moveTo(x, y); started = true; }
          else            ctx.lineTo(x, y);
        }
        ctx.stroke();
      }
    });

    // ── Time axis ─────────────────────────────────────────────────────────
    const totalMin = Math.round(channels.elapsed[n - 1] / 60);
    ctx.fillStyle  = C.label;
    ctx.font       = '9px monospace';
    ctx.textAlign  = 'center';
    const step = totalMin <= 30 ? 5 : totalMin <= 90 ? 10 : 20;
    for (let m = 0; m <= totalMin; m += step) {
      const x = (m / totalMin) * w;
      ctx.fillText(`${m}m`, x, h - 2);
    }

    // ── Selection highlight ───────────────────────────────────────────────
    if (selStart >= 0 && selEnd >= 0) {
      const x0 = idxToX(Math.min(selStart, selEnd));
      const x1 = idxToX(Math.max(selStart, selEnd));
      ctx.fillStyle   = C.sel;
      ctx.fillRect(x0, 0, x1 - x0, h);
      ctx.strokeStyle = C.selBorder;
      ctx.lineWidth   = 1;
      ctx.strokeRect(x0, 0, x1 - x0, h);
    }

    // ── Hover crosshair ───────────────────────────────────────────────────
    if (hoverIdx >= 0 && hoverIdx < n) {
      const x = idxToX(hoverIdx);
      ctx.strokeStyle = C.cross;
      ctx.lineWidth   = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
      ctx.setLineDash([]);
    }
  }

  function schedule() {
    if (!rafPending) { rafPending = true; requestAnimationFrame(draw); }
  }

  // ── Mouse events ─────────────────────────────────────────────────────────

  function onMouseMove(e) {
    if (!channels) return;
    const idx = xToIdx(e.offsetX);
    hoverIdx = idx;

    if (dragging) {
      selEnd = idx;
      const i0 = Math.min(selStart, selEnd);
      const i1 = Math.max(selStart, selEnd);
      if (i1 - i0 > 2) {
        onSelect(i0, i1, selectionStats(channels, i0, i1));
      }
    } else {
      const vals = {};
      bands.forEach(b => { vals[b.id] = b.data[idx]; });
      vals.elapsed = channels.elapsed[idx];
      onHover(idx, vals);
    }
    schedule();
  }

  function onMouseDown(e) {
    if (!channels) return;
    dragging  = true;
    selStart  = xToIdx(e.offsetX);
    selEnd    = selStart;
    schedule();
  }

  function onMouseUp(e) {
    if (!dragging) return;
    dragging = false;
    const i0 = Math.min(selStart, selEnd);
    const i1 = Math.max(selStart, selEnd);
    if (i1 - i0 < 3) {
      selStart = selEnd = -1;   // treat as click → clear selection
      const vals = {};
      bands.forEach(b => { vals[b.id] = b.data[xToIdx(e.offsetX)]; });
      vals.elapsed = channels.elapsed[xToIdx(e.offsetX)];
      onHover(xToIdx(e.offsetX), vals);
    } else {
      onSelect(i0, i1, selectionStats(channels, i0, i1));
    }
    schedule();
  }

  function onMouseLeave() {
    hoverIdx = -1;
    schedule();
  }

  // ── Public API ────────────────────────────────────────────────────────────

  function init(canvasEl) {
    canvas = canvasEl;
    resize();
    canvas.addEventListener('mousemove',  onMouseMove);
    canvas.addEventListener('mousedown',  onMouseDown);
    canvas.addEventListener('mouseup',    onMouseUp);
    canvas.addEventListener('mouseleave', onMouseLeave);
    new ResizeObserver(resize).observe(canvas);
  }

  function load(ch, hasVAM) {
    channels = ch;
    bands    = buildBands(ch, hasVAM);
    hoverIdx = selStart = selEnd = -1;
    schedule();
  }

  function clear() {
    channels = null;
    bands    = [];
    hoverIdx = selStart = selEnd = -1;
    schedule();
  }

  return {
    init, load, clear,
    set onHover(fn)  { onHover  = fn; },
    set onSelect(fn) { onSelect = fn; },
  };
})();
