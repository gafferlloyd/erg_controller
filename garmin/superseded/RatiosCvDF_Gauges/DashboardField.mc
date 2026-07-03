import Toybox.WatchUi;
import Toybox.Graphics;
import Toybox.Activity;
import Toybox.Lang;
import Toybox.Math;

class CVDashboardField extends WatchUi.DataField {

    private var _np30    as Array = new [30];
    private var _np30Idx as Number = 0;
    private var _np30N   as Number = 0;
    private var _np      as Float  = 0.0;

    private var _pw as Number = 0;
    private var _hr as Number = 0;

    function initialize() {
        DataField.initialize();
        for (var i = 0; i < 30; i++) { _np30[i] = 0.0; }
    }

    function compute(info as Activity.Info) {
        var pw = info.currentPower;
        var hr = info.currentHeartRate;
        if (pw != null) { _pw = pw as Number; }
        if (hr != null) { _hr = hr as Number; }

        if (pw != null) {
            _np30[_np30Idx] = (pw as Number).toFloat();
            _np30Idx = (_np30Idx + 1) % 30;
            if (_np30N < 30) { _np30N++; }

            var sum4 = 0.0d;
            for (var i = 0; i < 30; i++) {
                var v = (_np30[i] as Float).toDouble();
                sum4 += v * v * v * v;
            }
            _np = Math.sqrt(Math.sqrt(sum4 / _np30N.toDouble())).toFloat();
        }

        return 0;
    }

    function onUpdate(dc as Graphics.Dc) as Void {
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_BLACK);
        dc.clear();

        var w  = dc.getWidth();
        var h  = dc.getHeight();
        var rh = h / 5;

        var wPerBpm  = (_hr > 0) ? (_pw.toFloat() / _hr.toFloat())  : 0.0;
        var npPerBpm = (_hr > 0 && _np > 0.0) ? (_np / _hr.toFloat()) : 0.0;

        // norm functions: returns 0.0–1.0
        var normPw  = _norm(_pw.toFloat(),    0.0, 400.0);
        var normNp  = _norm(_np,              0.0, 400.0);
        var normHr  = _norm(_hr.toFloat(),   60.0, 180.0);
        var normW   = _norm(wPerBpm,          0.5, 2.5);
        var normNpR = _norm(npPerBpm,         0.5, 2.5);

        // gauge colours: power/ratio = efficiency (green=good), HR = effort (red=high)
        _row(dc, w, rh, 0, "W",      _pw.toString(),                          normPw,  _powerColor(normPw));
        _row(dc, w, rh, 1, "NP",     (_np > 0.0) ? _np.format("%.0f") : "--", normNp,  _powerColor(normNp));
        _row(dc, w, rh, 2, "bpm",    (_hr > 0) ? _hr.toString() : "--",       normHr,  _hrColor(normHr));
        _row(dc, w, rh, 3, "W/bpm",  (wPerBpm  > 0.0) ? wPerBpm.format("%.2f")  : "--", normW,   _ratioColor(normW));
        _row(dc, w, rh, 4, "NP/bpm", (npPerBpm > 0.0) ? npPerBpm.format("%.2f") : "--", normNpR, _ratioColor(normNpR));
    }

    private function _row(dc as Graphics.Dc, w as Number, rh as Number,
                          idx as Number, label as String, value as String,
                          norm as Float, color as Number) as Void {
        var y    = idx * rh;
        var barH = 8;
        var barY = y + rh - barH - 1;

        if (idx > 0) {
            dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
            dc.drawLine(0, y, w, y);
        }

        // Label: top-left corner of the row
        // Number: vertically centred in the full row height, right-aligned
        var valueH   = dc.getFontHeight(Graphics.FONT_NUMBER_MEDIUM);
        var valueTop = y + (rh - valueH) / 2;

        var labelH = dc.getFontHeight(Graphics.FONT_SMALL);
        dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(4, y + 2 + labelH, Graphics.FONT_SMALL, label, Graphics.TEXT_JUSTIFY_LEFT);

        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(w - 4, valueTop, Graphics.FONT_NUMBER_MEDIUM, value, Graphics.TEXT_JUSTIFY_RIGHT);

        // Gauge bar at the bottom of each row
        var fill = (norm * (w - 2)).toNumber();
        if (fill < 0)     { fill = 0; }
        if (fill > w - 2) { fill = w - 2; }
        dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawRectangle(1, barY, w - 2, barH);
        if (fill > 0) {
            dc.setColor(color, Graphics.COLOR_TRANSPARENT);
            dc.fillRectangle(1, barY, fill, barH);
        }
    }

    private function _norm(v as Float, lo as Float, hi as Float) as Float {
        if (hi <= lo) { return 0.0; }
        var n = (v - lo) / (hi - lo);
        if (n < 0.0) { n = 0.0; }
        if (n > 1.0) { n = 1.0; }
        return n;
    }

    // Power gauge: dim at low watts, bright green at high
    private function _powerColor(n as Float) as Number {
        if (n < 0.33) { return Graphics.COLOR_BLUE; }
        if (n < 0.66) { return Graphics.COLOR_YELLOW; }
        return Graphics.COLOR_GREEN;
    }

    // HR gauge: green when low, red when high
    private function _hrColor(n as Float) as Number {
        if (n < 0.33) { return Graphics.COLOR_GREEN; }
        if (n < 0.66) { return Graphics.COLOR_YELLOW; }
        return Graphics.COLOR_RED;
    }

    // Ratio gauge: green = efficient
    private function _ratioColor(n as Float) as Number {
        if (n < 0.33) { return Graphics.COLOR_RED; }
        if (n < 0.66) { return Graphics.COLOR_YELLOW; }
        return Graphics.COLOR_GREEN;
    }
}
