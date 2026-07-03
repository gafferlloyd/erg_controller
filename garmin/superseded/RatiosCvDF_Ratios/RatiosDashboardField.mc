import Toybox.WatchUi;
import Toybox.Graphics;
import Toybox.Activity;
import Toybox.Lang;

class RatiosDashboardField extends WatchUi.DataField {

    private var _model as RatiosModel;

    function initialize() {
        DataField.initialize();
        _model = new RatiosModel();
    }

    function compute(info as Activity.Info) {
        var pw    = info.currentPower;
        var hr    = info.currentHeartRate;
        var speed = info.currentSpeed;
        var dist  = info.elapsedDistance;

        var pwVal    = (pw    != null) ? (pw as Number)   : 0;
        var hrVal    = (hr    != null) ? (hr as Number)   : 0;
        var speedVal = (speed != null) ? (speed as Float) : 0.0;
        var distVal  = (dist  != null) ? (dist as Float)  : 0.0;

        _model.tick(pwVal, hrVal, speedVal, distVal);
        return 0;
    }

    function onUpdate(dc as Graphics.Dc) as Void {
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_BLACK);
        dc.clear();

        var w  = dc.getWidth();
        var h  = dc.getHeight();
        var rh = h / 6;
        var m  = _model;

        // Row 0: W/HR — 1-min avg power per heartbeat
        var whrStr  = (m.minWPerBpm != null) ? (m.minWPerBpm as Float).format("%.2f") : "---";
        var whrNorm = (m.minWPerBpm != null) ? _norm(m.minWPerBpm as Float, 0.0, 4.0) : 0.0;
        _row(dc, w, rh, 0, "W/HR", whrStr, whrNorm, _effColor(whrNorm));

        // Row 1: W/kg — 1-min avg power per kg body mass
        var wkgStr  = (m.wPerKg != null) ? (m.wPerKg as Float).format("%.1f") : "---";
        var wkgNorm = (m.wPerKg != null) ? _norm(m.wPerKg as Float, 0.0, 6.0) : 0.0;
        _row(dc, w, rh, 1, "W/kg", wkgStr, wkgNorm, _effColor(wkgNorm));

        // Row 2: km/HR — speed (km/h) per heartbeat
        var vhrStr  = (m.vPerHr > 0.0) ? m.vPerHr.format("%.3f") : "---";
        var vhrNorm = _norm(m.vPerHr, 0.0, 0.5);
        _row(dc, w, rh, 2, "km/h/HR", vhrStr, vhrNorm, _effColor(vhrNorm));

        // Row 3: J/m — cumulative energy cost per metre
        var jmStr  = (m.jPerM > 0.0) ? m.jPerM.format("%.0f") : "---";
        var jmNorm = _norm(m.jPerM, 0.0, 100.0);
        _row(dc, w, rh, 3, "J/m", jmStr, jmNorm, _costColor(jmNorm));

        // Row 4: NP/HR — 30s normalised power per heartbeat
        var nphrStr  = (m.npPerHr > 0.0) ? m.npPerHr.format("%.2f") : "---";
        var nphrNorm = _norm(m.npPerHr, 0.0, 4.0);
        _row(dc, w, rh, 4, "NP/HR", nphrStr, nphrNorm, _effColor(nphrNorm));

        // Row 5: Decouple — W/bpm drift: +% = improving, -% = cardiac drift
        var dcplStr = "---";
        var dcplNorm = 0.5;
        if (m.decoupling != null) {
            var d    = m.decoupling as Float;
            var sign = (d >= 0.0) ? "+" : "";
            dcplStr  = sign + d.format("%.1f") + "%";
            dcplNorm = _norm(d, -20.0, 20.0);
        }
        _row(dc, w, rh, 5, "Dcpl", dcplStr, dcplNorm, _dcplColor(dcplNorm));
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

        var valueH   = dc.getFontHeight(Graphics.FONT_NUMBER_MEDIUM);
        var valueTop = y + (rh - valueH) / 2;
        var labelH   = dc.getFontHeight(Graphics.FONT_SMALL);

        dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(4, y + 2 + labelH, Graphics.FONT_SMALL, label, Graphics.TEXT_JUSTIFY_LEFT);

        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(w - 4, valueTop, Graphics.FONT_NUMBER_MEDIUM, value, Graphics.TEXT_JUSTIFY_RIGHT);

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

    // Efficiency ratio: red (low) → yellow → green (high)
    private function _effColor(n as Float) as Number {
        if (n < 0.33) { return Graphics.COLOR_RED; }
        if (n < 0.66) { return Graphics.COLOR_YELLOW; }
        return Graphics.COLOR_GREEN;
    }

    // Energy cost: green (low cost) → yellow → red (high cost)
    private function _costColor(n as Float) as Number {
        if (n < 0.33) { return Graphics.COLOR_GREEN; }
        if (n < 0.66) { return Graphics.COLOR_YELLOW; }
        return Graphics.COLOR_RED;
    }

    // Decoupling: red (drifting) → yellow → green (improving)
    // n=0 → -20% drift, n=0.5 → 0%, n=1.0 → +20% improvement
    private function _dcplColor(n as Float) as Number {
        if (n < 0.4) { return Graphics.COLOR_RED; }
        if (n < 0.6) { return Graphics.COLOR_YELLOW; }
        return Graphics.COLOR_GREEN;
    }
}
