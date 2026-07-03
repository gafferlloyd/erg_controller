import Toybox.WatchUi;
import Toybox.Graphics;
import Toybox.Lang;

// Page 2: scatter plot of 1-min avg power vs end-of-minute HR,
// with linear regression lines for first and second halves.
class ScatterPage extends WatchUi.View {

    // Plot area in pixels
    private const PX_LEFT   = 36;
    private const PX_RIGHT  = 234;
    private const PX_TOP    = 22;
    private const PX_BOTTOM = 252;

    // Fixed axis ranges (auto-scale is Phase 2)
    private const PW_MIN = 0;
    private const PW_MAX = 350;
    private const HR_MIN = 60;
    private const HR_MAX = 180;

    function initialize() {
        View.initialize();
    }

    function onUpdate(dc as Graphics.Dc) as Void {
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_BLACK);
        dc.clear();

        // Title
        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(PX_LEFT, 2, Graphics.FONT_TINY, "Power vs HR", Graphics.TEXT_JUSTIFY_LEFT);

        var model = gModel;
        if (model == null) { return; }

        _drawAxes(dc);

        var pts = model.perMinPw.size();
        if (pts < 2) {
            dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
            dc.drawText(123, 140, Graphics.FONT_TINY, pts.toString() + " pts", Graphics.TEXT_JUSTIFY_CENTER);
            return;
        }

        var mid = pts / 2;

        // Draw points
        for (var i = 0; i < pts; i++) {
            var px = _pwToX(model.perMinPw[i]);
            var py = _hrToY(model.perMinHr[i].toFloat());
            dc.setColor(i < mid ? Graphics.COLOR_BLUE : Graphics.COLOR_RED, Graphics.COLOR_TRANSPARENT);
            dc.fillCircle(px, py, 3);
        }

        // Regression lines
        if (mid >= 2) {
            var r1 = _linReg(model.perMinPw, model.perMinHr, 0, mid);
            var r2 = _linReg(model.perMinPw, model.perMinHr, mid, pts);
            _drawReg(dc, r1, Graphics.COLOR_BLUE,  model.perMinPw, 0,   mid);
            _drawReg(dc, r2, Graphics.COLOR_RED,   model.perMinPw, mid, pts);
            _drawRegLabel(dc, r1, r2, pts);
        }
    }

    private function _drawAxes(dc as Graphics.Dc) as Void {
        dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
        // Y axis
        dc.drawLine(PX_LEFT, PX_TOP, PX_LEFT, PX_BOTTOM);
        // X axis
        dc.drawLine(PX_LEFT, PX_BOTTOM, PX_RIGHT, PX_BOTTOM);

        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        // Y labels (HR)
        for (var hr = 80; hr <= 160; hr += 40) {
            var y = _hrToY(hr.toFloat());
            dc.drawText(PX_LEFT - 2, y - 7, Graphics.FONT_TINY, hr.toString(), Graphics.TEXT_JUSTIFY_RIGHT);
            dc.drawLine(PX_LEFT - 2, y, PX_LEFT, y);
        }
        // X labels (power)
        for (var pw = 100; pw <= 300; pw += 100) {
            var x = _pwToX(pw.toFloat());
            dc.drawText(x, PX_BOTTOM + 2, Graphics.FONT_TINY, pw.toString(), Graphics.TEXT_JUSTIFY_CENTER);
            dc.drawLine(x, PX_BOTTOM, x, PX_BOTTOM + 2);
        }
        dc.drawText(PX_RIGHT, PX_BOTTOM + 2, Graphics.FONT_XTINY, "W", Graphics.TEXT_JUSTIFY_RIGHT);
    }

    // Least-squares linear regression on a slice [from, to) of the arrays.
    // Returns {m, b} such that HR ≈ m * power + b.
    private function _linReg(pw as Array<Float>, hr as Array<Number>,
                              from as Number, to as Number) as Array<Double> {
        var n   = (to - from).toDouble();
        var sx  = 0.0d;
        var sy  = 0.0d;
        var sxy = 0.0d;
        var sx2 = 0.0d;
        for (var i = from; i < to; i++) {
            var x = pw[i].toDouble();
            var y = hr[i].toDouble();
            sx  += x;
            sy  += y;
            sxy += x * y;
            sx2 += x * x;
        }
        var denom = n * sx2 - sx * sx;
        if (denom < 0.001d && denom > -0.001d) { return [0.0d, sy / n] as Array<Double>; }
        var m = (n * sxy - sx * sy) / denom;
        var b = (sy - m * sx) / n;
        return [m, b] as Array<Double>;
    }

    // Draw regression line spanning only the x range of the data slice [from,to).
    private function _drawReg(dc as Graphics.Dc, reg as Array<Double>, color as Number,
                              pw as Array<Float>, from as Number, to as Number) as Void {
        var m = reg[0];
        var b = reg[1];
        // Find min/max power in this slice
        var xMin = pw[from].toDouble();
        var xMax = xMin;
        for (var i = from + 1; i < to; i++) {
            var v = pw[i].toDouble();
            if (v < xMin) { xMin = v; }
            if (v > xMax) { xMax = v; }
        }
        var x1  = _pwToX(xMin.toFloat());
        var x2  = _pwToX(xMax.toFloat());
        var py1 = _hrToY((m * xMin + b).toFloat());
        var py2 = _hrToY((m * xMax + b).toFloat());
        py1 = py1 < PX_TOP ? PX_TOP : (py1 > PX_BOTTOM ? PX_BOTTOM : py1);
        py2 = py2 < PX_TOP ? PX_TOP : (py2 > PX_BOTTOM ? PX_BOTTOM : py2);
        dc.setColor(color, Graphics.COLOR_TRANSPARENT);
        dc.drawLine(x1, py1, x2, py2);
    }

    private function _drawRegLabel(dc as Graphics.Dc, r1 as Array<Double>,
                                   r2 as Array<Double>, pts as Number) as Void {
        var mid = pts / 2;
        var s1 = "1st(" + mid.toString() + "): " + r1[0].toFloat().format("%.3f") + "xW+" + r1[1].toFloat().format("%.1f");
        var s2 = "2nd(" + (pts - mid).toString() + "): " + r2[0].toFloat().format("%.3f") + "xW+" + r2[1].toFloat().format("%.1f");
        dc.setColor(Graphics.COLOR_BLUE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(PX_LEFT, 256, Graphics.FONT_TINY, s1, Graphics.TEXT_JUSTIFY_LEFT);
        dc.setColor(Graphics.COLOR_RED, Graphics.COLOR_TRANSPARENT);
        dc.drawText(PX_LEFT, 274, Graphics.FONT_TINY, s2, Graphics.TEXT_JUSTIFY_LEFT);
        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(PX_LEFT, 292, Graphics.FONT_TINY, "pts: " + pts.toString(), Graphics.TEXT_JUSTIFY_LEFT);
    }

    private function _pwToX(pw as Float) as Number {
        return (PX_LEFT + (pw - PW_MIN).toFloat() / (PW_MAX - PW_MIN).toFloat() * (PX_RIGHT - PX_LEFT)).toNumber();
    }

    private function _hrToY(hr as Float) as Number {
        return (PX_BOTTOM - (hr - HR_MIN).toFloat() / (HR_MAX - HR_MIN).toFloat() * (PX_BOTTOM - PX_TOP)).toNumber();
    }
}
