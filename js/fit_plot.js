'use strict';

// ── FIT multi-channel canvas plot ─────────────────────────────────────────────
// load({ channels, elapsed }) → returns band-descriptor array for HTML value boxes.
// Each channel occupies a fixed BAND_PX-tall strip; canvas scrolls in its container.
//
// Freeze behaviour:
//   - Drag → selection → values frozen until next plain click.
//   - Plain click (< 3px travel) → unfreeze, show hover values, clear selection.

const fitPlot = (() => {
  const BAND_PX     = 140;    // CSS pixels per channel band
  const TIME_AXIS_H = 20;     // CSS pixels reserved for time labels at bottom

  const C = {
    smooth:    '#ff9800',
    grid:      'rgba(255,255,255,0.08)',
    label:     'rgba(255,255,255,0.40)',
    sep:       'rgba(255,255,255,0.12)',
    sel:       'rgba(79,195,247,0.12)',
    selBorder: 'rgba(79,195,247,0.6)',
    cross:     'rgba(255,255,255,0.35)',
    bg:        '#0d1117',
  };

  // ── State ─────────────────────────────────────────────────────────────────
  let canvas, ctx, dpr;
  let channels  = [];      // ordered channel array from buildChannels()
  let elapsed   = [];      // parallel elapsed-seconds array
  let bands     = [];      // one entry per channel, with pixel positions + data
  let hoverIdx  = -1;
  let selStart  = -1, selEnd = -1;
  let dragging  = false;
  let selFrozen = false;
  let rafPending = false;
  let onHover   = () => {};
  let onSelect  = () => {};

  // ── Band builder ──────────────────────────────────────────────────────────

  function buildBands(chArr) {
    return chArr.map((ch, i) => {
      const vals = ch.data.filter(v => v != null);
      const lo   = vals.length ? Math.min(...vals) : 0;
      const hi   = vals.length ? Math.max(...vals) : 1;
      return {
        id: ch.id, name: ch.name, unit: ch.unit, color: ch.color,
        data: ch.data, smooth: ch.smooth || null,
        topPx: i * BAND_PX, botPx: (i + 1) * BAND_PX,
        min: lo, max: hi > lo ? hi : lo + 1,
      };
    });
  }

  // ── Canvas resize ─────────────────────────────────────────────────────────

  function resize() {
    if (!canvas) return;
    dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    if (!rect.width) return;
    canvas.width  = Math.round(rect.width  * dpr);
    canvas.height = Math.round(rect.height * dpr);
    ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);
    schedule();
  }

  // ── Coordinate helpers ────────────────────────────────────────────────────

  function xToIdx(xPx) {
    const n = elapsed.length;
    if (!n) return 0;
    const w = canvas.getBoundingClientRect().width;
    return Math.round(Math.max(0, Math.min(1, xPx / w)) * (n - 1));
  }

  function idxToX(i, w) {
    return elapsed.length > 1 ? i / (elapsed.length - 1) * w : 0;
  }

  function valToY(v, band) {
    const frac = 1 - (v - band.min) / (band.max - band.min);
    return band.topPx + frac * BAND_PX;
  }

  function niceTicks(lo, hi, n) {
    const range = hi - lo || 1;
    const step  = Math.pow(10, Math.floor(Math.log10(range / n)));
    const nice  = [1, 2, 5, 10].map(f => f * step).find(s => range / s <= n + 1) || step;
    const start = Math.ceil(lo / nice) * nice;
    const ticks = [];
    for (let v = start; v <= hi + 0.001; v += nice) ticks.push(Math.round(v * 1000) / 1000);
    return ticks;
  }

  // ── Draw ──────────────────────────────────────────────────────────────────

  function draw() {
    rafPending = false;
    if (!ctx || !bands.length) return;
    const rect = canvas.getBoundingClientRect();
    const w    = rect.width;
    const h    = bands.length * BAND_PX + TIME_AXIS_H;
    const n    = elapsed.length;

    ctx.fillStyle = C.bg;
    ctx.fillRect(0, 0, w, h);

    bands.forEach(band => {
      // Band separator
      ctx.strokeStyle = C.sep;
      ctx.lineWidth   = 1;
      ctx.beginPath(); ctx.moveTo(0, band.topPx); ctx.lineTo(w, band.topPx); ctx.stroke();

      // Grid lines + tick labels
      const ticks = niceTicks(band.min, band.max, 3);
      ctx.strokeStyle = C.grid;
      ctx.fillStyle   = C.label;
      ctx.font        = '9px monospace';
      ctx.textAlign   = 'left';
      ctx.lineWidth   = 0.5;
      for (const t of ticks) {
        const y = valToY(t, band);
        if (y < band.topPx + 4 || y > band.botPx - 4) continue;
        ctx.beginPath(); ctx.moveTo(32, y); ctx.lineTo(w, y); ctx.stroke();
        ctx.fillText(t, 2, y - 2);
      }

      // Channel label (top-right of band)
      ctx.fillStyle = band.color;
      ctx.font      = 'bold 9px monospace';
      ctx.textAlign = 'right';
      ctx.fillText(`${band.name}${band.unit ? ' '+band.unit : ''}`, w - 2, band.topPx + 11);

      // Data line
      drawLine(ctx, band.data, band, w, n, band.color, 1.5);

      // Smooth overlay for power
      if (band.smooth) drawLine(ctx, band.smooth, band, w, n, C.smooth, 2);
    });

    // Time axis
    const totalSec = elapsed[n - 1] || 1;
    const totalMin = Math.round(totalSec / 60);
    const step     = totalMin <= 30 ? 5 : totalMin <= 90 ? 10 : totalMin <= 180 ? 20 : 30;
    const axisY    = bands.length * BAND_PX + TIME_AXIS_H * 0.7;
    ctx.fillStyle  = C.label;
    ctx.font       = '9px monospace';
    ctx.textAlign  = 'center';
    for (let m = 0; m <= totalMin; m += step) {
      ctx.fillText(`${m}m`, (m / totalMin) * w, axisY);
    }

    // Selection highlight
    if (selStart >= 0 && selEnd >= 0) {
      const x0 = idxToX(Math.min(selStart, selEnd), w);
      const x1 = idxToX(Math.max(selStart, selEnd), w);
      ctx.fillStyle   = C.sel;
      ctx.fillRect(x0, 0, x1 - x0, bands.length * BAND_PX);
      ctx.strokeStyle = C.selBorder;
      ctx.lineWidth   = 1;
      ctx.strokeRect(x0, 0, x1 - x0, bands.length * BAND_PX);
    }

    // Hover crosshair
    if (hoverIdx >= 0 && hoverIdx < n) {
      const x = idxToX(hoverIdx, w);
      ctx.strokeStyle = C.cross;
      ctx.lineWidth   = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, bands.length * BAND_PX); ctx.stroke();
      ctx.setLineDash([]);
    }
  }

  function drawLine(ctx, data, band, w, n, color, lw) {
    ctx.strokeStyle = color;
    ctx.lineWidth   = lw;
    ctx.lineJoin    = 'round';
    ctx.beginPath();
    let started = false;
    for (let i = 0; i < n; i++) {
      const v = data[i];
      if (v == null) { started = false; continue; }
      const x = (i / (n - 1)) * w;
      const y = valToY(v, band);
      if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }

  function schedule() {
    if (!rafPending) { rafPending = true; requestAnimationFrame(draw); }
  }

  // ── Mouse events ──────────────────────────────────────────────────────────

  function hoverVals(idx) {
    const vals = { elapsed: elapsed[idx] };
    bands.forEach(b => { vals[b.id] = b.data[idx]; });
    return vals;
  }

  function onMouseMove(e) {
    if (!bands.length) return;
    hoverIdx = xToIdx(e.offsetX);
    if (dragging) {
      selEnd = hoverIdx;
      const i0 = Math.min(selStart, selEnd), i1 = Math.max(selStart, selEnd);
      if (i1 - i0 > 2) onSelect(i0, i1, selectionStats(channels, i0, i1));
    } else if (!selFrozen) {
      onHover(hoverIdx, hoverVals(hoverIdx));
    }
    schedule();
  }

  function onMouseDown(e) {
    if (!bands.length) return;
    if (selFrozen) { selFrozen = false; selStart = selEnd = -1; }
    dragging = true;
    selStart = selEnd = xToIdx(e.offsetX);
    schedule();
  }

  function onMouseUp(e) {
    if (!dragging) return;
    dragging = false;
    const i0 = Math.min(selStart, selEnd), i1 = Math.max(selStart, selEnd);
    if (i1 - i0 < 3) {
      selStart = selEnd = -1;
      selFrozen = false;
      const idx = xToIdx(e.offsetX);
      onHover(idx, hoverVals(idx));
    } else {
      selFrozen = true;
      onSelect(i0, i1, selectionStats(channels, i0, i1));
    }
    schedule();
  }

  function onMouseLeave() { hoverIdx = -1; schedule(); }

  // ── Public API ────────────────────────────────────────────────────────────

  function init(canvasEl) {
    canvas = canvasEl;
    new ResizeObserver(resize).observe(canvas);
    canvas.addEventListener('mousemove',  onMouseMove);
    canvas.addEventListener('mousedown',  onMouseDown);
    canvas.addEventListener('mouseup',    onMouseUp);
    canvas.addEventListener('mouseleave', onMouseLeave);
    resize();
  }

  // load() sets canvas height and returns band descriptors for HTML value boxes.
  function load(fitChannels) {
    channels  = fitChannels.channels;
    elapsed   = fitChannels.elapsed;
    bands     = buildBands(channels);
    hoverIdx  = selStart = selEnd = -1;
    selFrozen = false;
    canvas.style.height = bands.length * BAND_PX + TIME_AXIS_H + 'px';
    resize();
    schedule();
    return bands.map(b => ({ id: b.id, name: b.name, unit: b.unit, color: b.color }));
  }

  function clear() {
    channels = []; elapsed = []; bands = [];
    hoverIdx = selStart = selEnd = -1; selFrozen = false;
    canvas.style.height = '';
    schedule();
  }

  return {
    init, load, clear,
    BAND_PX, TIME_AXIS_H,
    set onHover(fn)  { onHover  = fn; },
    set onSelect(fn) { onSelect = fn; },
  };
})();
