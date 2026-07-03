import Toybox.WatchUi;
import Toybox.Graphics;
import Toybox.Activity;
import Toybox.Lang;
import Toybox.Math;

class CVDashboardField extends WatchUi.DataField {

    // Rolling 30s NP buffer
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

        _row(dc, w, rh, 0, "W",      _pw.toString());
        _row(dc, w, rh, 1, "NP",     (_np > 0.0) ? _np.format("%.0f") : "--");
        _row(dc, w, rh, 2, "bpm",    (_hr > 0) ? _hr.toString() : "--");
        _row(dc, w, rh, 3, "W/bpm",  (wPerBpm  > 0.0) ? wPerBpm.format("%.2f")  : "--");
        _row(dc, w, rh, 4, "NP/bpm", (npPerBpm > 0.0) ? npPerBpm.format("%.2f") : "--");
    }

    private function _row(dc as Graphics.Dc, w as Number, rh as Number,
                          idx as Number, label as String, value as String) as Void {
        var y = idx * rh;

        // Divider above each row except the first
        if (idx > 0) {
            dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
            dc.drawLine(0, y, w, y);
        }

        dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(4, y + 2, Graphics.FONT_TINY, label, Graphics.TEXT_JUSTIFY_LEFT);

        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(w - 4, y + 14, Graphics.FONT_NUMBER_MEDIUM, value, Graphics.TEXT_JUSTIFY_RIGHT);
    }
}
