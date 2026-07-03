import Toybox.WatchUi;
import Toybox.Activity;
import Toybox.Lang;

// 3-second rolling W/bpm ratio data field.
// Garmin calls compute() once per second during an activity.
class RatiosCvField extends WatchUi.SimpleDataField {

    private var _pwBuf  as Array<Number> = [0, 0, 0] as Array<Number>;
    private var _hrBuf  as Array<Number> = [0, 0, 0] as Array<Number>;
    private var _idx    as Number = 0;
    private var _filled as Number = 0;  // counts up to 3 then stays

    function initialize() {
        SimpleDataField.initialize();
        label = "W/bpm 3s";
    }

    function compute(info as Activity.Info) as Object {
        var pw = info.currentPower;
        var hr = info.currentHeartRate;

        if (pw == null || hr == null || (hr as Number) < 30) {
            return "--";
        }

        _pwBuf[_idx] = pw as Number;
        _hrBuf[_idx] = hr as Number;
        _idx = (_idx + 1) % 3;
        if (_filled < 3) { _filled++; }

        var n = _filled.toFloat();
        var avgPw = (_pwBuf[0] + _pwBuf[1] + _pwBuf[2]).toFloat() / (3.0 < n ? 3.0 : n);
        var avgHr = (_hrBuf[0] + _hrBuf[1] + _hrBuf[2]).toFloat() / (3.0 < n ? 3.0 : n);

        if (avgHr < 1.0) { return "--"; }
        return (avgPw / avgHr).format("%.2f");
    }
}
