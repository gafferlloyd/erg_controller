import Toybox.Lang;
import Toybox.Math;

class RatiosModel {

    // 60-second circular buffer for normalised power
    private var _np60    as Array = new [60];
    private var _np60Idx as Number = 0;
    private var _np60N   as Number = 0;   // slots filled so far (caps at 60)

    // Ratio outputs — updated every tick
    // Power input = 60s NP,  HR input = live,  speed input = live
    var wPerBpm   as Float or Null = null;  // NP60 / live HR          (W/bpm)
    var mhPerBpm  as Float or Null = null;  // live m/h / live HR      (m/h/bpm)
    var mhPerW    as Float or Null = null;  // live m/h / NP60         (m/h/W)

    // Live raw values — updated every tick
    var livePower as Number = 0;
    var liveHr    as Number = 0;
    var liveKmh   as Float  = 0.0;   // for bottom display box
    var liveMh    as Float  = 0.0;   // meters per hour, for ratios

    function initialize() {
        for (var i = 0; i < 60; i++) { _np60[i] = 0.0; }
    }

    // pw in W, hr in bpm, speed in m/s — called once per second
    function tick(pw as Number, hr as Number, speed as Float) as Void {
        livePower = pw;
        liveHr    = hr;
        liveKmh   = speed * 3.6;
        liveMh    = speed * 3600.0;

        // Roll the 60s NP buffer
        _np60[_np60Idx] = pw.toFloat();
        _np60Idx = (_np60Idx + 1) % 60;
        if (_np60N < 60) { _np60N++; }

        var np = _computeNp60();

        if (hr > 30) {
            var hrF  = hr.toFloat();
            wPerBpm  = (np > 0.0) ? np / hrF : null;
            mhPerBpm = liveMh / hrF;
        } else {
            wPerBpm  = null;
            mhPerBpm = null;
        }

        mhPerW = (np > 1.0) ? liveMh / np : null;
    }

    // 4th-power mean of the filled portion of the buffer.
    private function _computeNp60() as Float {
        if (_np60N == 0) { return 0.0; }
        var sum4 = 0.0d;
        for (var i = 0; i < 60; i++) {
            var v = (_np60[i] as Float).toDouble();
            sum4 += v * v * v * v;
        }
        return Math.sqrt(Math.sqrt(sum4 / _np60N.toDouble())).toFloat();
    }
}
