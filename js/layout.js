// js/layout.js — Stat box layout: metric library, smart packing, render, config
// ─────────────────────────────────────────────────────────────────────────────

const METRICS = [
  { id: 'np',     lbl: 'NP',       unit: 'W',    cls: 'np'  },
  { id: 'avgpwr', lbl: 'Avg Pwr',  unit: 'W',    cls: 'pwr' },
  { id: 'avghr',  lbl: 'Avg HR',   unit: 'bpm',  cls: 'hr'  },
  { id: 'avgcad', lbl: 'Avg Cad',  unit: 'rpm',  cls: 'cad' },
  { id: 'avgspd', lbl: 'Avg Spd',  unit: 'km/h', cls: ''    },
  { id: 'dist',   lbl: 'Distance', unit: 'km',   cls: ''    },
  { id: 'wpbpm',  lbl: 'W/bpm',    unit: '',     cls: ''    },
  { id: 'npbpm',  lbl: 'NP/bpm',   unit: '',     cls: ''    },
  { id: 'dcpl',   lbl: 'Decouple', unit: '%',    cls: ''    },
  { id: 'if',     lbl: 'IF',       unit: '',     cls: ''    },
  { id: 'tss',    lbl: 'TSS',      unit: '',     cls: ''    },
  { id: 'hrv',    lbl: 'HRV',      unit: 'ms',   cls: 'hrv' },
  { id: 'hm',     lbl: 'Hm',       unit: 'm',    cls: ''    },
  { id: '_',      lbl: '',         unit: '',     cls: ''    },
];
const METRIC_IDX = Object.fromEntries(METRICS.map((m, i) => [m.id, i]));

const LAYOUT_KEY = 'erg_layout_v1';
const LAYOUT_DEFAULTS = {
  scaleWk: 1.0,
  scaleRc: 1.0,
  window:  2,
  wBoxes:  13,
  rBoxes:  8,
  workout: ['np','avgpwr','avghr','avgcad','avgspd','dist','hm','wpbpm','npbpm','dcpl','if','tss','hrv'],
  recent:  ['np','avgpwr','avghr','avgcad','hm','wpbpm','npbpm','hrv','_','_','_','_'],
};
let layoutCfg = { ...LAYOUT_DEFAULTS };

// ── API used by ui.js ─────────────────────────────────────────────────────────

function getRecentWindowSecs() { return (layoutCfg.window || 2) * 60; }

function setStatBox(gridKey, metricId, text) {
  document.querySelectorAll(
    `#grid-${gridKey} [data-metric="${metricId}"] .stat-num`
  ).forEach(el => { el.textContent = text; });
}

// ── Smart packing ─────────────────────────────────────────────────────────────

function smartPack(n, w, h) {
  let best = null, bestScore = Infinity;
  for (let c = 1; c <= Math.min(n, 6); c++) {
    const r      = Math.ceil(n / c);
    const waste  = c * r - n;
    const aspect = (w / c) / (h / r);
    const score  = waste * 3 + Math.abs(aspect - 1.6);
    if (score < bestScore) { bestScore = score; best = { cols: c, rows: r }; }
  }
  return best ?? { cols: 1, rows: 1 };
}

// ── Render ────────────────────────────────────────────────────────────────────

function renderStatGrid(gridId, infoId, assignment, count) {
  const gridEl = document.getElementById(gridId);
  if (!gridEl) return;
  const infoEl = document.getElementById(infoId);

  const rect = gridEl.getBoundingClientRect();
  const w = rect.width  || 500;
  const h = rect.height || 180;
  const { cols, rows } = smartPack(count, w, h);
  const cells = cols * rows;

  gridEl.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;
  gridEl.style.gridTemplateRows    = `repeat(${rows}, 1fr)`;
  if (infoEl) infoEl.textContent   = `${cols}×${rows}`;

  gridEl.innerHTML = '';
  for (let i = 0; i < cells; i++) {
    const id    = (i < count) ? (assignment[i] || '_') : '_';
    const m     = METRICS[METRIC_IDX[id]] ?? METRICS[METRIC_IDX['_']];
    const empty = m.id === '_' || i >= count;
    const box   = document.createElement('div');
    box.className      = 'stat-box' + (empty ? ' stat-empty' : '');
    box.dataset.metric = m.id;
    box.dataset.grid   = gridId;
    box.dataset.pos    = i;
    if (!empty) {
      box.innerHTML =
        `<div class="stat-lbl">${m.lbl}</div>` +
        `<div class="stat-val${m.cls ? ' sv-' + m.cls : ''}">` +
          `<span class="stat-num">—</span>` +
          (m.unit ? `<span class="stat-unit">${m.unit}</span>` : '') +
        `</div>`;
    }
    box.addEventListener('click', onStatBoxClick);
    gridEl.appendChild(box);
  }
}

function renderBothGrids() {
  renderStatGrid('grid-workout', 'wk-grid-info', layoutCfg.workout, layoutCfg.wBoxes);
  renderStatGrid('grid-recent',  'rc-grid-info', layoutCfg.recent,  layoutCfg.rBoxes);
  renderPriorityLists();
}

// ── Click to cycle ────────────────────────────────────────────────────────────

function onStatBoxClick(e) {
  const box    = e.currentTarget;
  const pos    = parseInt(box.dataset.pos);
  const isRec  = box.dataset.grid === 'grid-recent';
  const arr    = isRec ? layoutCfg.recent : layoutCfg.workout;
  const cur    = METRIC_IDX[arr[pos] ?? '_'] ?? 0;
  arr[pos]     = METRICS[(cur + 1) % METRICS.length].id;
  renderBothGrids();
}

// ── CSS scale variables ───────────────────────────────────────────────────────

const SCALE_BASE = { val: 36, lbl: 12, unit: 13 };
function applyScale(prefix, s) {
  const r = document.documentElement.style;
  r.setProperty(`--${prefix}-val-size`,  (SCALE_BASE.val  * s).toFixed(1) + 'px');
  r.setProperty(`--${prefix}-lbl-size`,  (SCALE_BASE.lbl  * s).toFixed(1) + 'px');
  r.setProperty(`--${prefix}-unit-size`, (SCALE_BASE.unit * s).toFixed(1) + 'px');
}

// ── Priority lists ────────────────────────────────────────────────────────────

function renderPriorityLists() {
  ['workout', 'recent'].forEach(key => {
    const el = document.getElementById(`prio-${key}`);
    if (!el) return;
    const arr = layoutCfg[key];
    const n   = key === 'workout' ? layoutCfg.wBoxes : layoutCfg.rBoxes;
    el.innerHTML = arr.slice(0, n).map((id, i) => {
      const m = METRICS[METRIC_IDX[id]] ?? METRICS[METRIC_IDX['_']];
      return `<div class="prio-item"><span class="prio-num">${i + 1}</span>` +
             `<span class="prio-name">${m.id === '_' ? '—' : m.lbl}</span></div>`;
    }).join('');
  });
}

// ── Apply full config to DOM controls ─────────────────────────────────────────

function applyLayoutConfig() {
  applyScale('wk', layoutCfg.scaleWk);
  applyScale('rc', layoutCfg.scaleRc);
  const set = (id, v) => { const el = document.getElementById(id); if (el) el.value = v; };
  const txt = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
  set('cfg-scale-wk', layoutCfg.scaleWk); txt('cfg-scale-wk-val', layoutCfg.scaleWk.toFixed(2) + '×');
  set('cfg-scale-rc', layoutCfg.scaleRc); txt('cfg-scale-rc-val', layoutCfg.scaleRc.toFixed(2) + '×');
  set('cfg-window',  layoutCfg.window);
  set('cfg-wboxes',  layoutCfg.wBoxes);
  set('cfg-rboxes',  layoutCfg.rBoxes);
  txt('recent-head-label', layoutCfg.window + ' min window');
  renderBothGrids();
}

// ── Save / load ───────────────────────────────────────────────────────────────

function saveLayoutConfig() { localStorage.setItem(LAYOUT_KEY, JSON.stringify(layoutCfg)); }

function loadLayoutConfig() {
  const saved = localStorage.getItem(LAYOUT_KEY);
  if (saved) layoutCfg = { ...LAYOUT_DEFAULTS, ...JSON.parse(saved) };
}

// ── Boot ──────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  loadLayoutConfig();
  applyLayoutConfig();

  const on = (id, fn) => document.getElementById(id)?.addEventListener('input', fn);
  on('cfg-scale-wk', () => {
    layoutCfg.scaleWk = parseFloat(document.getElementById('cfg-scale-wk').value);
    applyScale('wk', layoutCfg.scaleWk);
    document.getElementById('cfg-scale-wk-val').textContent = layoutCfg.scaleWk.toFixed(2) + '×';
  });
  on('cfg-scale-rc', () => {
    layoutCfg.scaleRc = parseFloat(document.getElementById('cfg-scale-rc').value);
    applyScale('rc', layoutCfg.scaleRc);
    document.getElementById('cfg-scale-rc-val').textContent = layoutCfg.scaleRc.toFixed(2) + '×';
  });
  on('cfg-window',  () => {
    layoutCfg.window = parseInt(document.getElementById('cfg-window').value) || 2;
    document.getElementById('recent-head-label').textContent = layoutCfg.window + ' min window';
  });
  on('cfg-wboxes',  () => {
    layoutCfg.wBoxes = Math.min(12, Math.max(1, parseInt(document.getElementById('cfg-wboxes').value) || 12));
    renderBothGrids();
  });
  on('cfg-rboxes',  () => {
    layoutCfg.rBoxes = Math.min(12, Math.max(1, parseInt(document.getElementById('cfg-rboxes').value) || 7));
    renderBothGrids();
  });
  document.getElementById('btn-save-layout')?.addEventListener('click', () => {
    saveLayoutConfig();
    const el = document.getElementById('layout-status');
    if (el) { el.textContent = 'saved ✓'; setTimeout(() => { el.textContent = ''; }, 2000); }
  });

  window.addEventListener('resize', renderBothGrids);
});
