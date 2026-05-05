'use strict';

// Auto-showing 5s popup at every 30-second mark with enlarged Power Curve + HR vs Power.
// Depends on: drawPowerCurve (chart.js), drawHRPower (hrpower.js)

function showChartPopup() {
  const el = document.getElementById('chart-popup');
  if (!el) return;
  drawPowerCurve('popup-power-curve-canvas', 20);
  drawHRPower('popup-hr-power-canvas', 20);
  el.classList.remove('cp-show');
  void el.offsetWidth;
  el.classList.add('cp-show');
}
