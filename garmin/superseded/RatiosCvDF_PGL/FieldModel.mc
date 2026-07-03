import Toybox.Lang;
import Toybox.Math;

// All per-second accumulation and derived metrics for the CV data field.
class FieldModel {

    // Rolling 30s power buffer for NP (circular, fixed size)
    private var _np30    as Array = new [30];
    private var _np30Idx as Number = 0;
    private var _np30N   as Number = 0;   // valid samples (caps at 30)

    // Per-minute accumulation
    private var _minPwSum  as Float  = 0.0;
    private var _minNp4Sum as Double = 0.0d;
    private var _minCount  as Number = 0;
    private var _secInMin  as Number = 0;
    private var _lastHr    as Number = 0;

    // Live running values (updated every tick, not just per minute)
    var livePw as Number = 0;
    var liveHr as Number = 0;

    // Per-minute history (up to ~120 entries for a 2h ride)
    var perMinPw as Array = [];
    var perMinNp as Array = [];
    var perMinHr as Array = [];

    function initialize() {
        for (var i = 0; i < 30; i++) { _np30[i] = 0.0; }
    }

    function tick(pw as Number, hr as Number) as Void {
        _lastHr = hr;
        livePw  = pw;
        liveHr  = hr;

        // Update rolling 30s NP buffer
        _np30[_np30Idx] = pw.toFloat();
        _np30Idx = (_np30Idx + 1) % 30;
        if (_np30N < 30) { _np30N++; }

        var avg30 = _np30Mean();

        // Accumulate this minute
        _minPwSum  += pw.toFloat();
        _minNp4Sum += avg30.toDouble() * avg30.toDouble() * avg30.toDouble() * avg30.toDouble();
        _minCount++;
        _secInMin++;

        if (_secInMin >= 60) {
            var avgPw = _minPwSum / _minCount.toFloat();
            var np    = Math.sqrt(Math.sqrt((_minNp4Sum / _minCount.toDouble()))).toFloat();
            perMinPw.add(avgPw);
            perMinNp.add(np);
            perMinHr.add(_lastHr);
            _minPwSum  = 0.0;
            _minNp4Sum = 0.0d;
            _minCount  = 0;
            _secInMin  = 0;
        }
    }

    // Running = in-progress current minute (live, updates every second)
    function getRunningWPerBpm() as Float {
        if (_minCount < 1 || liveHr < 30) { return 0.0; }
        return (_minPwSum / _minCount.toFloat()) / liveHr.toFloat();
    }

    function getRunningNpPerBpm() as Float {
        if (_minCount < 1 || liveHr < 30) { return 0.0; }
        var np = Math.sqrt(Math.sqrt((_minNp4Sum / _minCount.toDouble()))).toFloat();
        return np / liveHr.toFloat();
    }

    // Current = last completed per-minute point
    function getCurrentWPerBpm() as Float {
        var n = perMinPw.size();
        if (n < 1) { return 0.0; }
        var hr = (perMinHr[n - 1] as Number).toFloat();
        if (hr < 30.0) { return 0.0; }
        return (perMinPw[n - 1] as Float) / hr;
    }

    function getCurrentNpPerBpm() as Float {
        var n = perMinNp.size();
        if (n < 1) { return 0.0; }
        var hr = (perMinHr[n - 1] as Number).toFloat();
        if (hr < 30.0) { return 0.0; }
        return (perMinNp[n - 1] as Float) / hr;
    }

    // Returns [npPerBpm, m, b] for the first (up to 30) per-minute points
    function getFirst30Stats() as Array {
        var to = perMinPw.size();
        if (to > 30) { to = 30; }
        return _sliceStats(0, to);
    }

    // Returns [npPerBpm, m, b] for the last (up to 30) per-minute points
    function getLast30Stats() as Array {
        var n    = perMinPw.size();
        var from = (n > 30) ? n - 30 : 0;
        return _sliceStats(from, n);
    }

    // Positive = last30 more efficient; negative = fatigue / cardiac drift
    function getDecoupling() as Float {
        if (perMinPw.size() < 60) { return 0.0; }
        var f    = getFirst30Stats();
        var l    = getLast30Stats();
        var base = f[0] as Float;
        if (base < 0.001) { return 0.0; }
        return ((l[0] as Float) - base) / base;
    }

    function hasDecoupling() as Boolean {
        return perMinPw.size() >= 60;
    }

    // ── private ──────────────────────────────────────────────────

    private function _np30Mean() as Float {
        if (_np30N == 0) { return 0.0; }
        var sum = 0.0;
        for (var i = 0; i < 30; i++) { sum += (_np30[i] as Float); }
        return sum / _np30N.toFloat();
    }

    // Returns [npPerBpm, m, b] for slice [from, to).
    // Regression: HR = m * avgPw + b  (bpm/W slope, bpm intercept)
    private function _sliceStats(from as Number, to as Number) as Array {
        var n = to - from;
        if (n < 2) { return [0.0, 0.0, 0.0] as Array; }

        var fn    = n.toFloat();
        var npSum = 0.0;
        var hrSum = 0.0;
        var sx    = 0.0;
        var sy    = 0.0;
        var sxy   = 0.0;
        var sx2   = 0.0;

        for (var i = from; i < to; i++) {
            var x = (perMinPw[i] as Float);
            var y = (perMinHr[i] as Number).toFloat();
            npSum += (perMinNp[i] as Float);
            hrSum += y;
            sx += x; sy += y; sxy += x * y; sx2 += x * x;
        }

        var npPerBpm = (hrSum > 0.0) ? (npSum / hrSum) : 0.0;

        var den = fn * sx2 - sx * sx;
        var m   = 0.0;
        var b   = sy / fn;
        if (den > 0.001 || den < -0.001) {
            m = (fn * sxy - sx * sy) / den;
            b = (sy - m * sx) / fn;
        }

        return [npPerBpm, m, b] as Array;
    }
}
