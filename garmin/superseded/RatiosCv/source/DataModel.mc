import Toybox.Lang;

// Holds all ride state: rolling buffers, NP accumulation, per-minute scatter data.
class DataModel {

    // --- config ---
    var windowSecs as Number;

    // --- NP: 30s circular power buffer ---
    private var _npBuf   as Array<Number>;
    private var _npIdx   as Number = 0;
    private var _npFill  as Number = 0;   // slots filled, up to 30
    private var _np4Sum  as Double = 0.0d;
    private var _np4Count as Number = 0;

    // --- rolling window: parallel power + HR buffers ---
    private var _winPwBuf as Array<Number>;
    private var _winHrBuf as Array<Number>;
    private var _winIdx   as Number = 0;
    private var _winFill  as Number = 0;

    // --- per-minute accumulation ---
    private var _minPwSum  as Number = 0;
    private var _minHrLast as Number = 0;
    private var _secInMin  as Number = 0;
    var perMinPw as Array<Float> = [];
    var perMinHr as Array<Number> = [];

    // --- activity totals ---
    private var _totalPwSum as Double = 0.0d;
    private var _totalHrSum as Double = 0.0d;
    var totalTicks as Number = 0;

    // --- last raw readings ---
    var lastPower as Number = 0;
    var lastHr    as Number = 0;
    var hasData   as Boolean = false;

    function initialize(winSecs as Number) {
        windowSecs = winSecs;
        _npBuf    = new [30] as Array<Number>;
        _winPwBuf = new [winSecs] as Array<Number>;
        _winHrBuf = new [winSecs] as Array<Number>;
        for (var i = 0; i < 30; i++)    { _npBuf[i]    = 0; }
        for (var i = 0; i < winSecs; i++) {
            _winPwBuf[i] = 0;
            _winHrBuf[i] = 0;
        }
    }

    // Called once per second by SensorLoop. power/hr are raw sensor values.
    function tick(power as Number, hr as Number) as Void {
        lastPower = power;
        lastHr    = hr;
        hasData   = true;

        // NP buffer (30s)
        _npBuf[_npIdx] = power;
        _npIdx = (_npIdx + 1) % 30;
        if (_npFill < 30) { _npFill++; }
        if (_npFill == 30) {
            var avg30 = _bufMean(_npBuf, 30);
            var p4 = avg30 * avg30 * avg30 * avg30;
            _np4Sum += p4;
            _np4Count++;
        }

        // Rolling window buffer
        _winPwBuf[_winIdx] = power;
        _winHrBuf[_winIdx] = hr;
        _winIdx = (_winIdx + 1) % windowSecs;
        if (_winFill < windowSecs) { _winFill++; }

        // Activity totals
        _totalPwSum += power;
        _totalHrSum += hr;
        totalTicks++;

        // Per-minute accumulation
        _minPwSum += power;
        _minHrLast = hr;
        _secInMin++;
        if (_secInMin >= 60) {
            perMinPw.add((_minPwSum / 60.0).toFloat());
            perMinHr.add(_minHrLast);
            _minPwSum = 0;
            _secInMin = 0;
        }
    }

    function getNP() as Float {
        if (_np4Count == 0) { return 0.0; }
        var avg4 = _np4Sum / _np4Count;
        // 4th root via sqrt(sqrt(x))
        return Math.sqrt(Math.sqrt(avg4)).toFloat();
    }

    function getAvgPower() as Float {
        if (totalTicks == 0) { return 0.0; }
        return (_totalPwSum / totalTicks).toFloat();
    }

    function getAvgHr() as Float {
        if (totalTicks == 0) { return 0.0; }
        return (_totalHrSum / totalTicks).toFloat();
    }

    function getActivityWPerBpm() as Float {
        var hr = getAvgHr();
        if (hr < 1.0) { return 0.0; }
        return getAvgPower() / hr;
    }

    function getWindowWPerBpm() as Float {
        if (_winFill == 0) { return 0.0; }
        var pw = _bufMean(_winPwBuf, _winFill);
        var hr = _bufMean(_winHrBuf, _winFill);
        if (hr < 1.0) { return 0.0; }
        return (pw / hr).toFloat();
    }

    function getCurrentWPerBpm() as Float {
        if (lastHr < 1) { return 0.0; }
        return lastPower.toFloat() / lastHr.toFloat();
    }

    function getNpPerBpm() as Float {
        var hr = getAvgHr();
        if (hr < 1.0) { return 0.0; }
        return getNP() / hr;
    }

    function getVI() as Float {
        var avg = getAvgPower();
        if (avg < 1.0) { return 0.0; }
        return getNP() / avg;
    }

    private function _bufMean(buf as Array<Number>, count as Number) as Double {
        var sum = 0.0d;
        for (var i = 0; i < count; i++) { sum += buf[i]; }
        return sum / count;
    }
}
