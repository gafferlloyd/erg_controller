import Toybox.WatchUi;
import Toybox.Graphics;
import Toybox.Activity;
import Toybox.Lang;

// ── Layout constants ───────────────────────────────────────────────────
// Segment meter dimensions
const N_SEG   = 10;  // segments per meter
const SEG_H   = 21;  // segment height px (3× original)
const SEG_GAP = 2;   // gap between segments px

// Horizontal zones
const ICON_W   = 36;  // top-row icon width px
const ICON_PAD = 3;   // icon left margin px
const ICON_GAP = 4;   // gap between icon and meter
const METER_X  = ICON_PAD + ICON_W + ICON_GAP;  // meter left edge px (43)
const VAL_W    = 60;  // value text reservation px (right side)
const VAL_PAD  = 3;   // value right margin px

// Row colours: P_in=blue, P_loss=red, P_grav=amber, P_kin=olive
const COL_PIN  = 0x1A5FB4;
const COL_LOSS = 0xB80000;
const COL_PE   = 0xC04000;
const COL_KE   = 0x808000;

class RatiosDashboardField extends WatchUi.DataField {

    private var _model as RatiosModel;

    private var _iconPower as WatchUi.BitmapResource;
    private var _iconFlame as WatchUi.BitmapResource;
    private var _iconClimb as WatchUi.BitmapResource;
    private var _iconSpeed as WatchUi.BitmapResource;
    private var _iconWind  as WatchUi.BitmapResource;
    private var _iconCrr   as WatchUi.BitmapResource;

    function initialize() {
        DataField.initialize();
        _model     = new RatiosModel();
        _iconPower = WatchUi.loadResource(Rez.Drawables.IconPower) as WatchUi.BitmapResource;
        _iconFlame = WatchUi.loadResource(Rez.Drawables.IconFlame) as WatchUi.BitmapResource;
        _iconClimb = WatchUi.loadResource(Rez.Drawables.IconClimb) as WatchUi.BitmapResource;
        _iconSpeed = WatchUi.loadResource(Rez.Drawables.IconSpeed) as WatchUi.BitmapResource;
        _iconWind  = WatchUi.loadResource(Rez.Drawables.IconWind)  as WatchUi.BitmapResource;
        _iconCrr   = WatchUi.loadResource(Rez.Drawables.IconCrr)   as WatchUi.BitmapResource;
    }

    function compute(info as Activity.Info) {
        var pw    = info.currentPower;
        var speed = info.currentSpeed;
        var alt   = info.altitude;

        _model.tick(
            (pw    != null) ? (pw    as Number) : 0,
            (speed != null) ? (speed as Float)  : 0.0,
            (alt   != null) ? (alt   as Float)  : 0.0
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
        var rowH = topH / 4;
        var m    = _model;

        var meterW = w - METER_X - VAL_W - VAL_PAD;

        // ── Row 0: P_in — dB(FTP), range −8..+2, 10 × 1 dB ────────
        var litPin = _dbToSeg(m.dbFtp, -8.0, 2.0);
        var pwStr  = m.pIn.toNumber().format("%d") + "W";
        _meterRow(dc, w, meterW, rowH, 0, COL_PIN, [litPin, 8], pwStr, _iconPower);

        // ── Row 1: P_loss — dB(P_in), range −20..0, 10 × 2 dB ─────
        var litLoss = _dbToSeg(m.dbLoss, -20.0, 0.0);
        var lossStr = _pctStr(m.pLoss, m.pWheel);
        _meterRow(dc, w, meterW, rowH, 1, COL_LOSS, [litLoss, -1], lossStr, _iconFlame);

        // ── Row 2: P_grav — dB(P_in), range −20..0 ─────────────────
        var litPE  = _dbToSeg(m.dbPE, -20.0, 0.0);
        var peStr  = _pctStr(m.pPE, m.pWheel);
        _meterRow(dc, w, meterW, rowH, 2, COL_PE, [litPE, -1], peStr, _iconClimb);

        // ── Row 3: P_kin — dB(P_in), range −20..0 ──────────────────
        var litKE  = _dbToSeg(m.dbKE, -20.0, 0.0);
        var keStr  = _pctStr(m.pKE, m.pWheel);
        _meterRow(dc, w, meterW, rowH, 3, COL_KE, [litKE, -1], keStr, _iconSpeed);

        // ── Divider ───────────────────────────────────────────────────
        dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawLine(0, topH, w, topH);

        // ── Bottom section: CdA and Crr ───────────────────────────────
        _coeffSection(dc, w, topH, botH, m);
    }

    // ── Meter row ──────────────────────────────────────────────────────
    // seg = [litCount, markerAt]
    private function _meterRow(dc as Graphics.Dc,
                                w as Number, meterW as Number,
                                rh as Number, idx as Number,
                                color as Number, seg as Array,
                                valStr as String,
                                icon as WatchUi.BitmapResource) as Void {
        var litCount = seg[0] as Number;
        var markerAt = seg[1] as Number;
        var y = idx * rh;

        if (idx > 0) {
            dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
            dc.drawLine(0, y, w, y);
        }

        // Icon — 36 px, vertically centred
        dc.drawBitmap(ICON_PAD, y + (rh - ICON_W) / 2, icon);

        // Value text — FONT_MEDIUM; green when negative (gravity/KE source)
        var font = Graphics.FONT_MEDIUM;
        var fh   = dc.getFontHeight(font);
        var isNeg = valStr.length() > 0 &&
                    (valStr.substring(0, 1) as String).equals("-");
        dc.setColor(isNeg ? 0x1A7A2A : Graphics.COLOR_BLACK,
                    Graphics.COLOR_TRANSPARENT);
        dc.drawText(w - VAL_PAD, y + (rh - fh) / 2, font, valStr,
                    Graphics.TEXT_JUSTIFY_RIGHT);

        // Bar — 2/3 of available width, SEG_H tall
        var barW = meterW * 2 / 3;
        _segMeter(dc, METER_X, y + (rh - SEG_H) / 2, barW, litCount, markerAt, color);
    }

    // ── Segment bar ────────────────────────────────────────────────────
    private function _segMeter(dc as Graphics.Dc,
                                 x as Number, y as Number, totalW as Number,
                                 litCount as Number, markerAt as Number,
                                 color as Number) as Void {
        var segW = (totalW - (N_SEG - 1) * SEG_GAP) / N_SEG;
        if (segW < 2) { segW = 2; }

        for (var i = 0; i < N_SEG; i++) {
            var sx = x + i * (segW + SEG_GAP);
            if (i < litCount) {
                dc.setColor(color, Graphics.COLOR_TRANSPARENT);
                dc.fillRectangle(sx, y, segW, SEG_H);
            } else {
                dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
                dc.drawRectangle(sx, y, segW, SEG_H);
            }
        }

        if (markerAt >= 0 && markerAt < N_SEG) {
            var mx = x + markerAt * (segW + SEG_GAP) - 1;
            dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
            dc.drawLine(mx, y - 2, mx, y + SEG_H + 2);
        }
    }

    // ── Map dB value → lit segment count ──────────────────────────────
    private function _dbToSeg(db as Float, dbLow as Float, dbHigh as Float) as Number {
        var frac = (db - dbLow) / (dbHigh - dbLow);
        var n    = (frac * N_SEG.toFloat()).toNumber();
        if (n < 0)     { return 0; }
        if (n > N_SEG) { return N_SEG; }
        return n;
    }

    // ── Format component as signed integer percentage of ref (P_in × η) ──
    private function _pctStr(component as Float, ref as Float) as String {
        if (ref < 1.0) { return "---"; }
        var pct = (component / ref * 100.0).toNumber();
        if (pct < 0) { return "-" + (-pct).format("%d") + "%"; }
        return pct.format("%d") + "%";
    }

    // ── Bottom coefficient section ─────────────────────────────────────
    // Layout: 3 sub-rows, vertical divider at 2/3 width
    //   Left  2/3 — CdA: [icon] | 200s value | 1000s value
    //   Right 1/3 — Crr: [icon] | value | lock source
    private function _coeffSection(dc as Graphics.Dc, w as Number,
                                    topH as Number, botH as Number,
                                    m as RatiosModel) as Void {
        var fVal  = Graphics.FONT_SMALL;
        var fLbl  = Graphics.FONT_TINY;
        var fhV   = dc.getFontHeight(fVal);
        var fhL   = dc.getFontHeight(fLbl);
        var rH    = botH / 3;           // sub-row height ≈ 36 px
        var divX  = w * 2 / 3;         // CdA | Crr divider (164 px at w=246)
        var crrCx = divX + (w - divX) / 2;  // centre of Crr column (205 px)

        // Vertical divider (full section height)
        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawLine(divX, topH + 2, divX, topH + botH - 2);

        // ── Row 0: icons ─────────────────────────────────────────────
        var y0 = topH;
        dc.drawBitmap(3, y0 + (rH - 18) / 2, _iconWind);
        dc.drawBitmap(divX + (w - divX - 36) / 2, y0 + (rH - 36) / 2, _iconCrr);

        // ── Row 1: CdA fast  |  Crr value ───────────────────────────
        var y1  = topH + rH;
        var yR1 = y1 + (rH - fhV) / 2;

        dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(26, yR1, fLbl, "200s:", Graphics.TEXT_JUSTIFY_LEFT);

        var cdaFastStr = (m.cdaFast != null) ? (m.cdaFast as Float).format("%.3f") : "---";
        dc.setColor(0xC04000, Graphics.COLOR_TRANSPARENT);
        dc.drawText(divX - 4, yR1, fVal, cdaFastStr, Graphics.TEXT_JUSTIFY_RIGHT);

        var crrStr = (m.crrLocked != null) ? (m.crrLocked as Float).format("%.4f") : "---";
        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_TRANSPARENT);
        dc.drawText(crrCx, yR1, fVal, crrStr, Graphics.TEXT_JUSTIFY_CENTER);

        // ── Row 2: CdA slow  |  lock source ─────────────────────────
        var y2  = topH + 2 * rH;
        var yR2 = y2 + (rH - fhV) / 2;

        dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(26, yR2, fLbl, "1000s:", Graphics.TEXT_JUSTIFY_LEFT);

        var cdaSlowStr = (m.cdaSlow != null) ? (m.cdaSlow as Float).format("%.3f") : "---";
        dc.setColor(0x1A5FB4, Graphics.COLOR_TRANSPARENT);
        dc.drawText(divX - 4, yR2, fVal, cdaSlowStr, Graphics.TEXT_JUSTIFY_RIGHT);

        var srcStr = "";
        if (m.crrLocked != null) {
            srcStr = (m.crrFreewheel != null) ? "FW" : "P";
        }
        dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(crrCx, yR2, fLbl, srcStr, Graphics.TEXT_JUSTIFY_CENTER);
    }
}
