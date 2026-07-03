import Toybox.WatchUi;
import Toybox.Graphics;
import Toybox.Activity;
import Toybox.Lang;

// Filled continuous W'bal area chart.
// X-axis = time (left = oldest, right = newest), last 5 minutes.
// Y-axis = W'bal (0 at bottom, W' at top).
// Dotted line + label mark the ride minimum.

class WPrimeGraphField extends WatchUi.DataField {

    private const COL_GREEN as Number = 0x00AA00;
    private const COL_AMBER as Number = 0xCC6600;
    private const COL_RED   as Number = 0xCC0000;
    private const COL_GRID  as Number = 0xCCCCCC;
    private const COL_MIN   as Number = 0x444444;

    private var _model as WPrimeModel;

    function initialize() {
        DataField.initialize();
        _model = new WPrimeModel();
    }

    function compute(info as Activity.Info) as Object or Null {
        var pw = info.currentPower;
        _model.tick((pw != null) ? (pw as Number) : 0);
        return 0;
    }

    function onUpdate(dc as Graphics.Dc) as Void {
        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_WHITE);
        dc.clear();

        var w = dc.getWidth();
        var h = dc.getHeight();
        var m = _model;

        var buf = m.getGraphBuf();
        var idx = m.getGraphIdx();
        var n   = buf.size();   // 60
        var wp  = m.wPrime;

        var visN     = (n < w) ? n : w;
        var startOff = n - visN;
        var maxBarH  = h - 2;
        var yBase    = h - 1;

        // ── Reference lines at 60 % and 30 % ──────────────────────────
        dc.setColor(COL_GRID, Graphics.COLOR_TRANSPARENT);
        dc.drawLine(0, yBase - maxBarH * 60 / 100, w, yBase - maxBarH * 60 / 100);
        dc.drawLine(0, yBase - maxBarH * 30 / 100, w, yBase - maxBarH * 30 / 100);

        // ── Filled area ────────────────────────────────────────────────
        for (var x = 0; x < w; x++) {
            var si = (x.toFloat() * visN.toFloat() / w.toFloat()).toNumber();
            if (si >= visN) { si = visN - 1; }

            var bufIdx = (idx + startOff + si) % n;
            var val    = buf[bufIdx] as Float;
            if (val <= 0.0) { continue; }

            var frac = val / wp;
            var barH = (frac * maxBarH.toFloat()).toNumber();
            if (barH < 1) { barH = 1; }

            dc.setColor(_wbalColor(frac), Graphics.COLOR_TRANSPARENT);
            dc.fillRectangle(x, yBase - barH, 1, barH);
        }

        // ── Min dotted line + label (only once W'bal has dropped) ──────
        if (m.wBalMin < wp) {
            var minFrac = m.wBalMin / wp;
            var yMin    = yBase - (minFrac * maxBarH.toFloat()).toNumber();

            // Dotted line: 2 px on, 3 px off
            dc.setColor(COL_MIN, Graphics.COLOR_TRANSPARENT);
            var x = 0;
            while (x < w) {
                var segW = (x + 2 < w) ? 2 : w - x;
                dc.fillRectangle(x, yMin, segW, 1);
                x += 5;
            }

            // Min value label — largest font whose height <= h / 2
            var font = _pickFont(dc, h / 2);
            var minStr = (m.wBalMin / 1000.0).format("%.1f") + "kJ";
            dc.setColor(COL_MIN, Graphics.COLOR_TRANSPARENT);
            dc.drawText(2, 2, font, minStr, Graphics.TEXT_JUSTIFY_LEFT);
        }
    }

    // Largest font that fits within targetH pixels tall
    private function _pickFont(dc as Graphics.Dc, targetH as Number) as Graphics.FontDefinition {
        if (dc.getFontHeight(Graphics.FONT_MEDIUM) <= targetH) {
            return Graphics.FONT_MEDIUM;
        }
        if (dc.getFontHeight(Graphics.FONT_SMALL) <= targetH) {
            return Graphics.FONT_SMALL;
        }
        if (dc.getFontHeight(Graphics.FONT_TINY) <= targetH) {
            return Graphics.FONT_TINY;
        }
        return Graphics.FONT_XTINY;
    }

    private function _wbalColor(frac as Float) as Number {
        if (frac > 0.6) { return COL_GREEN; }
        if (frac > 0.3) { return COL_AMBER; }
        return COL_RED;
    }
}
