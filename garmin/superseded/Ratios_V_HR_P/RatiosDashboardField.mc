import Toybox.WatchUi;
import Toybox.Graphics;
import Toybox.Activity;
import Toybox.Lang;

class RatiosDashboardField extends WatchUi.DataField {

    private var _model      as RatiosModel;
    private var _iconPower  as WatchUi.BitmapResource;
    private var _iconHeart  as WatchUi.BitmapResource;
    private var _iconSpeed  as WatchUi.BitmapResource;

    function initialize() {
        DataField.initialize();
        _model     = new RatiosModel();
        _iconPower = WatchUi.loadResource(Rez.Drawables.IconPower) as WatchUi.BitmapResource;
        _iconHeart = WatchUi.loadResource(Rez.Drawables.IconHeart) as WatchUi.BitmapResource;
        _iconSpeed = WatchUi.loadResource(Rez.Drawables.IconSpeed) as WatchUi.BitmapResource;
    }

    function compute(info as Activity.Info) {
        var pw    = info.currentPower;
        var hr    = info.currentHeartRate;
        var speed = info.currentSpeed;

        _model.tick(
            (pw    != null) ? (pw    as Number) : 0,
            (hr    != null) ? (hr    as Number) : 0,
            (speed != null) ? (speed as Float)  : 0.0
        );
        return 0;
    }

    function onUpdate(dc as Graphics.Dc) as Void {
        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_WHITE);
        dc.clear();

        var w    = dc.getWidth();
        var h    = dc.getHeight();
        var topH = h * 2 / 3;
        var botH = h - topH;
        var rowH = topH / 3;
        var m    = _model;

        // ── Top 2/3 : three ratio rows ────────────────────────────────
        // Row 0: W/bpm
        _ratioRow(dc, w, rowH, 0,
                  _iconPower, _iconHeart,
                  m.wPerBpm, "%.2f", [0.0, 4.0] as Array<Float>);

        // Row 1: m/h/bpm
        _ratioRow(dc, w, rowH, 1,
                  _iconSpeed, _iconHeart,
                  m.mhPerBpm, "%.0f", [0.0, 500.0] as Array<Float>);

        // Row 2: m/h/W
        _ratioRow(dc, w, rowH, 2,
                  _iconSpeed, _iconPower,
                  m.mhPerW, "%.1f", [0.0, 150.0] as Array<Float>);

        // ── Divider ───────────────────────────────────────────────────
        dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawLine(0, topH, w, topH);

        // ── Bottom 1/3 : live raw values, vertically stacked ─────────
        _rawRow(dc, w, topH, botH, m);
    }

    // Draws one ratio row:
    //   left:   iconA "/" iconB
    //   centre: numerical value  (FONT_NUMBER_MEDIUM)
    //   right:  units label      (FONT_TINY, bottom-aligned with number)
    //   bottom: progress bar
    private function _ratioRow(dc as Graphics.Dc, w as Number, rh as Number,
                                idx as Number,
                                iconA as WatchUi.BitmapResource,
                                iconB as WatchUi.BitmapResource,
                                value as Float or Null,
                                fmt as String,
                                range as Array<Float>) as Void {
        var lo = range[0];
        var hi = range[1];
        var y  = idx * rh;

        if (idx > 0) {
            dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
            dc.drawLine(0, y, w, y);
        }

        // Icons + "/" separator, left-aligned, vertically centred
        var sepFont = Graphics.FONT_TINY;
        var sepH    = dc.getFontHeight(sepFont);
        var iconY   = y + (rh - 18) / 2;
        var sepY    = y + (rh - sepH) / 2;

        dc.drawBitmap(2, iconY, iconA);
        dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(21, sepY, sepFont, "/", Graphics.TEXT_JUSTIFY_LEFT);
        dc.drawBitmap(30, iconY, iconB);

        // Numerical value — FONT_NUMBER_MEDIUM, centred horizontally
        var valFont = Graphics.FONT_NUMBER_MEDIUM;
        var valH    = dc.getFontHeight(valFont);
        var valY    = y + (rh - valH) / 2;
        var valStr  = (value != null) ? (value as Float).format(fmt) : "---";
        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_TRANSPARENT);
        dc.drawText(w / 2, valY, valFont, valStr, Graphics.TEXT_JUSTIFY_CENTER);

        // Units label — FONT_TINY, right-aligned, bottom-aligned with number
        var unitsFont = Graphics.FONT_TINY;
        var unitsH    = dc.getFontHeight(unitsFont);
        var unitsY    = valY + valH - unitsH;
        var unitsStr  = "";
        if (idx == 0)      { unitsStr = "W/bpm"; }
        else if (idx == 1) { unitsStr = "m/h/bpm"; }
        else               { unitsStr = "m/h/W"; }
        dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(w - 4, unitsY, unitsFont, unitsStr, Graphics.TEXT_JUSTIFY_RIGHT);

        // Progress bar at bottom of row
        var barX = 50;
        var barW = w - barX - 4;
        var barH = 5;
        var barY = y + rh - barH - 2;

        if (barW > 4) {
            var norm = (value != null) ? _norm(value as Float, lo as Float, hi as Float) : 0.0;
            var fill = (norm * barW).toNumber();
            if (fill < 0)    { fill = 0; }
            if (fill > barW) { fill = barW; }

            dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
            dc.drawRectangle(barX, barY, barW, barH);
            if (fill > 0) {
                dc.setColor(_effColor(norm), Graphics.COLOR_TRANSPARENT);
                dc.fillRectangle(barX, barY, fill, barH);
            }
        }
    }

    // Draws the live raw values, stacked vertically in each of 3 columns:
    //   [icon]    ← 18px, centred
    //   [number]  ← FONT_SMALL, centred
    //   [unit]    ← FONT_TINY, centred
    private function _rawRow(dc as Graphics.Dc, w as Number,
                              topH as Number, botH as Number,
                              m as RatiosModel) as Void {
        var numFont  = Graphics.FONT_SMALL;
        var unitFont = Graphics.FONT_TINY;
        var numH     = dc.getFontHeight(numFont);
        var unitH    = dc.getFontHeight(unitFont);
        var colW     = w / 3;

        // Vertically centre the whole stack (18px icon + gaps + number + unit)
        var stackH  = 18 + 2 + numH + 2 + unitH;
        var startY  = topH + (botH - stackH) / 2;
        var iconY   = startY;
        var numY    = startY + 18 + 2;
        var unitY   = numY + numH + 2;

        var nums  = [m.livePower.format("%d"),
                     m.liveHr.format("%d"),
                     m.liveKmh.format("%.1f")] as Array<String>;
        var units = ["W", "bpm", "km/h"] as Array<String>;
        var icons = [_iconPower, _iconHeart, _iconSpeed] as Array<WatchUi.BitmapResource>;

        for (var i = 0; i < 3; i++) {
            var cx   = i * colW + colW / 2;
            var icon = icons[i] as WatchUi.BitmapResource;

            dc.drawBitmap(cx - 9, iconY, icon);

            dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, numY, numFont, nums[i] as String, Graphics.TEXT_JUSTIFY_CENTER);

            dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, unitY, unitFont, units[i] as String, Graphics.TEXT_JUSTIFY_CENTER);

            if (i < 2) {
                dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
                dc.drawLine((i + 1) * colW, topH + 4, (i + 1) * colW, topH + botH - 4);
            }
        }
    }

    private function _norm(v as Float, lo as Float, hi as Float) as Float {
        if (hi <= lo) { return 0.0; }
        var n = (v - lo) / (hi - lo);
        if (n < 0.0) { n = 0.0; }
        if (n > 1.0) { n = 1.0; }
        return n;
    }

    // Efficiency colour: red → yellow → green
    private function _effColor(n as Float) as Number {
        if (n < 0.33) { return Graphics.COLOR_RED; }
        if (n < 0.66) { return Graphics.COLOR_YELLOW; }
        return Graphics.COLOR_GREEN;
    }
}
