import Toybox.WatchUi;
import Toybox.Graphics;
import Toybox.Activity;
import Toybox.Lang;

class DynamicsDashboardField extends WatchUi.DataField {

    private var _model    as DynamicsModel;
    private var _altPrev  as Float = 0.0;
    private var _distPrev as Float = 0.0;

    function initialize() {
        DataField.initialize();
        _model = new DynamicsModel();
    }

    function compute(info as Activity.Info) {
        var pw    = info.currentPower;
        var speed = info.currentSpeed;
        var alt   = info.altitude;
        var dist  = info.elapsedDistance;

        var pwVal    = (pw    != null) ? (pw as Number).toFloat() : 0.0;
        var speedVal = (speed != null) ? (speed as Float)         : 0.0;
        var altVal   = (alt   != null) ? (alt as Float)           : _altPrev;
        var distVal  = (dist  != null) ? (dist as Float)          : _distPrev;

        // Derive grade fraction from consecutive altitude / distance readings
        var dDist = distVal - _distPrev;
        var grade = (dDist > 0.5) ? (altVal - _altPrev) / dDist : 0.0;

        _altPrev  = altVal;
        _distPrev = distVal;

        _model.tick(pwVal, speedVal, grade);
        return 0;
    }

    function onUpdate(dc as Graphics.Dc) as Void {
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_BLACK);
        dc.clear();

        var w  = dc.getWidth();
        var h  = dc.getHeight();
        var rh = h / 5;
        var m  = _model;

        // Row 0: KE — kinetic energy rate (signed: + accelerating, - braking)
        _rowSigned(dc, w, rh, 0, "KE (W)",
                   m.pKE, 200.0,
                   Graphics.COLOR_YELLOW,   // accelerating
                   Graphics.COLOR_BLUE);    // decelerating / recovering

        // Row 1: Aero — aerodynamic drag power (requires CdA estimate)
        var aeroStr  = (m.pAero != null) ? (m.pAero as Float).format("%.0f") : "---";
        var aeroNorm = (m.pAero != null) ? _norm(m.pAero as Float, 0.0, 300.0) : 0.0;
        _row(dc, w, rh, 1, "Aero (W)", aeroStr, aeroNorm, _heatColor(aeroNorm));

        // Row 2: Climb — gravitational power (signed: + climbing, - descending)
        _rowSigned(dc, w, rh, 2, "Climb (W)",
                   m.pClimb, 400.0,
                   Graphics.COLOR_RED,      // climbing
                   Graphics.COLOR_BLUE);    // descending / recovering

        // Row 3: Loss — residual (rolling resistance + drivetrain; requires CdA)
        var lossStr  = (m.pLoss != null) ? (m.pLoss as Float).format("%.0f") : "---";
        var lossNorm = (m.pLoss != null) ? _norm(m.pLoss as Float, 0.0, 80.0) : 0.0;
        _row(dc, w, rh, 3, "Loss (W)", lossStr, lossNorm, _heatColor(lossNorm));

        // Row 4: CdA — rolling regression estimate (m²)
        var cdaStr  = (m.cda != null) ? (m.cda as Float).format("%.3f") : "---";
        var cdaNorm = (m.cda != null) ? _norm(m.cda as Float, 0.15, 0.45) : 0.0;
        _row(dc, w, rh, 4, "CdA (m2)", cdaStr, cdaNorm, _cdaColor(cdaNorm));
    }

    // Standard row: label left, value right, gauge bar at bottom
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

    // Signed row: bar fills proportional to |value|, colour indicates sign
    private function _rowSigned(dc as Graphics.Dc, w as Number, rh as Number,
                                idx as Number, label as String, value as Float,
                                maxAbs as Float, posColor as Number, negColor as Number) as Void {
        var absVal  = (value >= 0.0) ? value : -value;
        var absNorm = _norm(absVal, 0.0, maxAbs);
        var color   = (value >= 0.0) ? posColor : negColor;
        _row(dc, w, rh, idx, label, value.format("%.0f"), absNorm, color);
    }

    private function _norm(v as Float, lo as Float, hi as Float) as Float {
        if (hi <= lo) { return 0.0; }
        var n = (v - lo) / (hi - lo);
        if (n < 0.0) { n = 0.0; }
        if (n > 1.0) { n = 1.0; }
        return n;
    }

    // Green → yellow → red (low = good, high = bad, for losses)
    private function _heatColor(n as Float) as Number {
        if (n < 0.33) { return Graphics.COLOR_GREEN; }
        if (n < 0.66) { return Graphics.COLOR_YELLOW; }
        return Graphics.COLOR_RED;
    }

    // Green (low CdA = aero) → yellow → red (high CdA = boxy)
    private function _cdaColor(n as Float) as Number {
        if (n < 0.33) { return Graphics.COLOR_GREEN; }
        if (n < 0.66) { return Graphics.COLOR_YELLOW; }
        return Graphics.COLOR_RED;
    }
}
