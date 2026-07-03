import Toybox.Lang;
import Toybox.Math;
import Toybox.Application;

class RatiosModel {

    // 30s NP circular buffer
    private var _np30    as Array = new [30];
    private var _np30Idx as Number = 0;
    private var _np30N   as Number = 0;

    // Per-minute accumulators
    private var _minPwSum as Float  = 0.0;
    private var _minCount as Number = 0;
    private var _secInMin as Number = 0;
    private var _lastHr   as Number = 0;

    // Per-minute W/bpm history (max 120 entries = 2h ride)
    private var _perMinWPerBpm as Array = [];

    // Cumulative energy and distance (distance derived from speed, not elapsedDistance)
    private var _totalJoules as Float = 0.0;
    private var _totalDist   as Float = 0.0;

    private var _mass as Float = 85.0;

    // Public outputs
    var minWPerBpm as Float or Null = null;  // last completed minute avg W / end-min HR
    var wPerKg     as Float or Null = null;  // last completed minute avg W / mass
    var vPerHr     as Float = 0.0;           // live speed (km/h) / HR
    var jPerM      as Float = 0.0;           // cumulative J / elapsed distance m
    var npPerHr    as Float = 0.0;           // 30s NP / live HR
    var decoupling as Float or Null = null;  // null until 60 min elapsed

    function initialize() {
        for (var i = 0; i < 30; i++) { _np30[i] = 0.0; }
        var m = Application.Properties.getValue("riderMassFg");
        if (m != null) { _mass = m as Float; }
    }

    // pw in W (Number), hr in bpm (Number), speed in m/s, distM cumulative metres
    function tick(pw as Number, hr as Number, speed as Float, distM as Float) as Void {
        _lastHr = hr;

        // Update 30s NP buffer (circular, fixed-size array)
        _np30[_np30Idx] = pw.toFloat();
        _np30Idx = (_np30Idx + 1) % 30;
        if (_np30N < 30) { _np30N++; }

        var np = _computeNp();

        // Live speed/HR ratio
        if (hr > 30) {
            var hrF = hr.toFloat();
            vPerHr  = (speed * 3.6) / hrF;
            npPerHr = (np > 0.0) ? np / hrF : 0.0;
        } else {
            vPerHr  = 0.0;
            npPerHr = 0.0;
        }

        // Per-minute accumulation
        _minPwSum += pw.toFloat();
        _minCount++;
        _secInMin++;

        if (_secInMin >= 60) {
            var avgPw = _minPwSum / _minCount.toFloat();
            var hrF   = _lastHr.toFloat();
            if (hrF > 30.0) {
                var wbpm = avgPw / hrF;
                _perMinWPerBpm = BufferUtils.push(_perMinWPerBpm, wbpm, 120);
                minWPerBpm = wbpm;
                wPerKg     = avgPw / _mass;
            }
            _minPwSum = 0.0;
            _minCount = 0;
            _secInMin = 0;
        }

        // Cumulative energy cost — distance accumulated from speed (1 tick = 1 s)
        _totalJoules += pw.toFloat();
        _totalDist   += speed;
        if (_totalDist > 0.5) { jPerM = _totalJoules / _totalDist; }

        decoupling = _computeDecoupling();
    }

    private function _computeNp() as Float {
        if (_np30N == 0) { return 0.0; }
        var sum4 = 0.0d;
        for (var i = 0; i < 30; i++) {
            var v = (_np30[i] as Float).toDouble();
            sum4 += v * v * v * v;
        }
        return Math.sqrt(Math.sqrt(sum4 / _np30N.toDouble())).toFloat();
    }

    // Returns decoupling as %, null if < 60 completed minutes.
    // Positive = last 30 min more efficient than first 30 min.
    private function _computeDecoupling() as Float or Null {
        var n = _perMinWPerBpm.size();
        if (n < 60) { return null; }
        var first = 0.0;
        var last  = 0.0;
        for (var i = 0; i < 30; i++) { first += _perMinWPerBpm[i] as Float; }
        for (var i = n - 30; i < n; i++) { last += _perMinWPerBpm[i] as Float; }
        var base = first / 30.0;
        if (base < 0.001) { return null; }
        return ((last / 30.0) - base) / base * 100.0;
    }
}
