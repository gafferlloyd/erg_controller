import Toybox.WatchUi;
import Toybox.Graphics;
import Toybox.Lang;

// Page 1: arc gauge + three-column efficiency table.
class GaugePage extends WatchUi.View {

    private const GAUGE_CX  = 123;
    private const GAUGE_CY  = 148;
    private const GAUGE_R   = 80;
    private const GAUGE_MIN = 0.5f;
    private const GAUGE_MAX = 3.0f;
    private const ARC_START = 210;
    private const ARC_SWEEP = 240;

    function initialize() {
        View.initialize();
    }

    function onUpdate(dc as Graphics.Dc) as Void {
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_BLACK);
        dc.clear();

        var model = gModel;
        var loop  = gLoop;

        // Header row
        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(4, 2, Graphics.FONT_XTINY, "Ratios: CV", Graphics.TEXT_JUSTIFY_LEFT);
        if (loop != null) {
            var t  = loop.elapsedSecs;
            var ts = (t / 3600).format("%02d") + ":" + ((t % 3600) / 60).format("%02d") + ":" + (t % 60).format("%02d");
            dc.drawText(242, 2, Graphics.FONT_XTINY, ts, Graphics.TEXT_JUSTIFY_RIGHT);
        }

        if (model == null || !model.hasData) {
            dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
            dc.drawText(GAUGE_CX, 160, Graphics.FONT_MEDIUM, "Waiting...", Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);
            return;
        }

        var wbpm = model.getCurrentWPerBpm();

        // Track arc
        dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.setPenWidth(14);
        dc.drawArc(GAUGE_CX, GAUGE_CY, GAUGE_R, Graphics.ARC_CLOCKWISE, ARC_START, ARC_START - ARC_SWEEP);

        // Value arc
        var fraction = (wbpm - GAUGE_MIN) / (GAUGE_MAX - GAUGE_MIN);
        if (fraction < 0.0) { fraction = 0.0; }
        if (fraction > 1.0) { fraction = 1.0; }
        var fillSweep = (fraction * ARC_SWEEP).toNumber();
        if (fillSweep > 0) {
            dc.setColor(_gaugeColor(wbpm), Graphics.COLOR_TRANSPARENT);
            dc.setPenWidth(14);
            dc.drawArc(GAUGE_CX, GAUGE_CY, GAUGE_R, Graphics.ARC_CLOCKWISE, ARC_START, ARC_START - fillSweep);
        }
        dc.setPenWidth(1);

        // Centre value
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(GAUGE_CX, GAUGE_CY - 22, Graphics.FONT_NUMBER_MEDIUM, wbpm.format("%.2f"), Graphics.TEXT_JUSTIFY_CENTER);
        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(GAUGE_CX, GAUGE_CY + 20, Graphics.FONT_TINY, "W / bpm", Graphics.TEXT_JUSTIFY_CENTER);

        // Divider
        dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawLine(10, 238, 236, 238);

        // Column headers
        var winSecs  = model.windowSecs;
        var winLabel = winSecs <= 30 ? "30s" : (winSecs <= 60 ? "60s" : "5m");
        var cx = [41, 123, 205] as Array<Number>;
        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx[0], 242, Graphics.FONT_XTINY, "Now",     Graphics.TEXT_JUSTIFY_CENTER);
        dc.drawText(cx[1], 242, Graphics.FONT_XTINY, winLabel,  Graphics.TEXT_JUSTIFY_CENTER);
        dc.drawText(cx[2], 242, Graphics.FONT_XTINY, "All",     Graphics.TEXT_JUSTIFY_CENTER);

        // W/bpm row
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx[0], 254, Graphics.FONT_NUMBER_MEDIUM, model.getCurrentWPerBpm().format("%.2f"),  Graphics.TEXT_JUSTIFY_CENTER);
        dc.drawText(cx[1], 254, Graphics.FONT_NUMBER_MEDIUM, model.getWindowWPerBpm().format("%.2f"),   Graphics.TEXT_JUSTIFY_CENTER);
        dc.drawText(cx[2], 254, Graphics.FONT_NUMBER_MEDIUM, model.getActivityWPerBpm().format("%.2f"), Graphics.TEXT_JUSTIFY_CENTER);

        // NP/bpm label + activity value only
        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(4, 302, Graphics.FONT_XTINY, "NP/bpm", Graphics.TEXT_JUSTIFY_LEFT);
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx[2], 302, Graphics.FONT_NUMBER_MEDIUM, model.getNpPerBpm().format("%.2f"), Graphics.TEXT_JUSTIFY_CENTER);
    }

    private function _gaugeColor(wbpm as Float) as Number {
        if (wbpm >= 1.5) { return Graphics.COLOR_GREEN; }
        if (wbpm >= 1.0) { return Graphics.COLOR_YELLOW; }
        return Graphics.COLOR_RED;
    }
}
