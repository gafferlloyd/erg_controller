import Toybox.WatchUi;
import Toybox.Graphics;
import Toybox.Activity;
import Toybox.Lang;

class WPrimeDashboardField extends WatchUi.DataField {

    // ── W'bal colour thresholds ────────────────────────────────────────
    private const COL_GREEN as Number = 0x00AA00;
    private const COL_AMBER as Number = 0xCC6600;
    private const COL_RED   as Number = 0xCC0000;

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

        var w    = dc.getWidth();
        var h    = dc.getHeight();
        var topH = h * 38 / 100;
        var m    = _model;

        var pct   = m.wBal / m.wPrime;
        var color = _wbalColor(pct);

        // ── Current W'bal (kJ) — large centred number ──────────────────
        var fontLarge = Graphics.FONT_NUMBER_MEDIUM;
        var fontSmall = Graphics.FONT_SMALL;
        var fhLarge   = dc.getFontHeight(fontLarge);
        var fhSmall   = dc.getFontHeight(fontSmall);

        var blockH = fhLarge + fhSmall;
        var textY  = (topH - blockH) / 2;

        var kJStr = (m.wBal / 1000.0).format("%.1f") + "kJ";
        dc.setColor(color, Graphics.COLOR_TRANSPARENT);
        dc.drawText(w / 2, textY, fontLarge, kJStr, Graphics.TEXT_JUSTIFY_CENTER);

        // ── Ride minimum ───────────────────────────────────────────────
        var minColor = _wbalColor(m.wBalMin / m.wPrime);
        var minStr   = "min " + (m.wBalMin / 1000.0).format("%.1f") + "kJ";
        dc.setColor(minColor, Graphics.COLOR_TRANSPARENT);
        dc.drawText(w / 2, textY + fhLarge, fontSmall, minStr,
                    Graphics.TEXT_JUSTIFY_CENTER);

        // ── Divider ────────────────────────────────────────────────────
        dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawLine(0, topH, w, topH);

        // ── Scrolling bar chart ────────────────────────────────────────
        _drawGraph(dc, w, topH, h - topH, m);
    }

    // ── Graph rendering ────────────────────────────────────────────────
    private function _drawGraph(dc   as Graphics.Dc,
                                 w    as Number,
                                 yOff as Number,
                                 gh   as Number,
                                 m    as WPrimeModel) as Void {
        var buf    = m.getGraphBuf();
        var idx    = m.getGraphIdx();
        var n      = buf.size();   // N_GRAPH = 60
        var wp     = m.wPrime;

        var barW   = (w - 4) / n;
        if (barW < 1) { barW = 1; }
        var graphW  = n * barW;
        var xOff    = (w - graphW) / 2;
        var yBase   = yOff + gh - 2;
        var maxBarH = gh - 4;

        for (var i = 0; i < n; i++) {
            var bufIdx = (idx + i) % n;
            var val    = buf[bufIdx] as Float;
            var frac   = val / wp;
            var barH   = (frac * maxBarH.toFloat()).toNumber();
            if (barH < 1) { barH = 1; }

            var bx = xOff + i * barW;
            var by = yBase - barH;
            var bw = (barW > 1) ? barW - 1 : 1;

            dc.setColor(_wbalColor(frac), Graphics.COLOR_TRANSPARENT);
            dc.fillRectangle(bx, by, bw, barH);
        }
    }

    // ── Map W'bal fraction → display colour ───────────────────────────
    private function _wbalColor(frac as Float) as Number {
        if (frac > 0.6) { return COL_GREEN; }
        if (frac > 0.3) { return COL_AMBER; }
        return COL_RED;
    }
}
