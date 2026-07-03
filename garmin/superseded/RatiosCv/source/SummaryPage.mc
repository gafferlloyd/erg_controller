import Toybox.WatchUi;
import Toybox.Graphics;
import Toybox.Lang;

// Page 3: end-of-ride summary table.
class SummaryPage extends WatchUi.View {

    function initialize() {
        View.initialize();
    }

    function onUpdate(dc as Graphics.Dc) as Void {
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_BLACK);
        dc.clear();

        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(123, 2, Graphics.FONT_XTINY, "Summary", Graphics.TEXT_JUSTIFY_CENTER);

        var model = gModel;
        var loop  = gLoop;
        if (model == null || !model.hasData) {
            dc.drawText(123, 160, Graphics.FONT_MEDIUM, "No data", Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);
            return;
        }

        var lx = 8;
        var vx = 238;
        var y  = 22;
        var dy = 38;

        var t = (loop != null) ? loop.elapsedSecs : 0;
        var tStr = (t / 3600).format("%02d") + ":" + ((t % 3600) / 60).format("%02d") + ":" + (t % 60).format("%02d");

        _row(dc, lx, vx, y, "Time",    tStr,                                        "");    y += dy;
        _row(dc, lx, vx, y, "Avg W",   model.getAvgPower().format("%.0f"),           "W");   y += dy;
        _row(dc, lx, vx, y, "NP",      model.getNP().format("%.0f") + "  VI " + model.getVI().format("%.2f"), "W"); y += dy;
        _row(dc, lx, vx, y, "Avg HR",  model.getAvgHr().format("%.0f"),              "bpm"); y += dy;
        _row(dc, lx, vx, y, "W/bpm",   model.getActivityWPerBpm().format("%.2f"),    "");    y += dy;
        _row(dc, lx, vx, y, "NP/bpm",  model.getNpPerBpm().format("%.2f"),           "");    y += dy;
        _row(dc, lx, vx, y, "Points",  model.perMinPw.size().toString(),             "");
    }

    private function _row(dc as Graphics.Dc, lx as Number, vx as Number, y as Number,
                          label as String, value as String, unit as String) as Void {
        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(lx, y, Graphics.FONT_TINY, label, Graphics.TEXT_JUSTIFY_LEFT);
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        var display = (unit.length() > 0) ? value + " " + unit : value;
        dc.drawText(vx, y, Graphics.FONT_MEDIUM, display, Graphics.TEXT_JUSTIFY_RIGHT);
    }
}
