'use strict';

// ── Log buffer (survives the whole session for download) ──────────────────────
const _logBuffer = [];

// Append a line to the on-screen log and the download buffer.
// cls: 'info' | 'ok' | 'warn' | 'err' | 'tx'
function log(msg, cls = 'info') {
  const ts   = new Date().toTimeString().slice(0, 8);
  const line = `[${ts}] [${cls.toUpperCase().padEnd(4)}] ${msg}`;
  _logBuffer.push(line);

  const el = document.getElementById('log');
  if (!el) return;
  const d = document.createElement('div');
  d.className = cls;
  d.textContent = `[${ts}] ${msg}`;
  el.prepend(d);

  // Cap DOM entries to avoid memory growth
  while (el.children.length > 500) el.removeChild(el.lastChild);
}

// Download the full session log as a .txt file.
function downloadLog() {
  const ts   = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const body = _logBuffer.join('\n');
  triggerDownload(`log_${ts}.txt`, new Blob([body], { type: 'text/plain' }));
}

// ── Generic download helper used by all modules ───────────────────────────────
function triggerDownload(filename, blob) {
  const url = URL.createObjectURL(blob);
  const a   = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// ── Log panel toggle ──────────────────────────────────────────────────────────
function toggleLog() {
  const section = document.getElementById('log-section');
  const toggle  = document.getElementById('log-toggle');
  section.classList.toggle('log-collapsed');
  toggle.textContent = section.classList.contains('log-collapsed') ? '▶' : '▼';
}
