import Toybox.WatchUi;
import Toybox.Graphics;
import Toybox.Activity;
import Toybox.Lang;

class WPrimeValueField extends WatchUi.DataField {

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

        var w = dc.getWidth();
        var h = dc.getHeight();
        var m = _model;

        var fNum  = Graphics.FONT_NUMBER_MEDIUM;
        var fTiny = Graphics.FONT_TINY;
        var fhNum = dc.getFontHeight(fNum);
        var fhTiny = dc.getFontHeight(fTiny);

        var pct   = m.wBal / m.wPrime;
        var color = _wbalColor(pct);

        var valStr  = (m.wBal / 1000.0).format("%.1f");
        var unitStr = "kJ";

        // Measure widths to centre the number+unit pair
        var valW  = dc.getTextWidthInPixels(valStr, fNum);
        var unitW = dc.getTextWidthInPixels(unitStr, fTiny);
        var pairW = valW + 2 + unitW;
        var xVal  = (w - pairW) / 2;

        // Vertical: number row + min row, centred together
        var minStr  = "min " + (m.wBalMin / 1000.0).format("%.1f") + "kJ";
        var gap     = 2;
        var blockH  = fhNum + gap + fhTiny;
        var yNum    = (h - blockH) / 2;
        var yMin    = yNum + fhNum + gap;

        // ── W'bal number ──────────────────────────────────────────────
        dc.setColor(color, Graphics.COLOR_TRANSPARENT);
        dc.drawText(xVal, yNum, fNum, valStr, Graphics.TEXT_JUSTIFY_LEFT);

        // ── "kJ" unit label — baseline-aligned with number ────────────
        dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(xVal + valW + 2, yNum + (fhNum - fhTiny), fTiny, unitStr,
                    Graphics.TEXT_JUSTIFY_LEFT);

        // ── Ride minimum ───────────────────────────────────────────────
        var minColor = _wbalColor(m.wBalMin / m.wPrime);
        dc.setColor(minColor, Graphics.COLOR_TRANSPARENT);
        dc.drawText(w / 2, yMin, fTiny, minStr, Graphics.TEXT_JUSTIFY_CENTER);
    }

    private function _wbalColor(frac as Float) as Number {
        if (frac > 0.6) { return COL_GREEN; }
        if (frac > 0.3) { return COL_AMBER; }
        return COL_RED;
    }
}
