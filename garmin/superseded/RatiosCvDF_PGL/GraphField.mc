import Toybox.WatchUi;
import Toybox.Graphics;
import Toybox.Activity;
import Toybox.Lang;

class CVGraphField extends WatchUi.DataField {

    private var _hr as Array = [] as Array;
    private var _pw as Array = [] as Array;

    function initialize() {
        DataField.initialize();
    }

    function compute(info as Activity.Info) as Object or Null {
        var hr = info.currentHeartRate;
        var pw = info.currentPower;
        if (hr == null || pw == null) { return null; }
        _hr = BufferUtils.push(_hr, (hr as Number).toFloat(), 60);
        _pw = BufferUtils.push(_pw, (pw as Number).toFloat(), 60);
        return 0;
    }

    function onUpdate(dc as Graphics.Dc) as Void {
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_BLACK);
        dc.clear();

        var w = dc.getWidth();
        var s = (_hr.size() >= 10) ? CVCore.slope(_hr, _pw) : 0.0;

        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(w / 2, 10, Graphics.FONT_MEDIUM, "CV Trend", Graphics.TEXT_JUSTIFY_CENTER);
        dc.drawText(w / 2, 36, Graphics.FONT_NUMBER_MEDIUM, s.format("%.2f"), Graphics.TEXT_JUSTIFY_CENTER);
        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(w / 2, 90, Graphics.FONT_TINY, _hr.size().toString() + " pts", Graphics.TEXT_JUSTIFY_CENTER);
    }
}
