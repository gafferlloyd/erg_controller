import Toybox.Lang;
import Toybox.Math;
import Toybox.Application;

class WPrimeModel {

    // ── Skiba 2012 recovery time-constant coefficients ─────────────────
    private const TAU_A as Float = 546.0;
    private const TAU_B as Float = 316.0;

    // ── Graph buffer: 60 samples × 5 s = 5 minutes ────────────────────
    private const N_GRAPH     as Number = 60;
    private const GRAPH_EVERY as Number = 5;   // ticks between samples

    // ── Config ────────────────────────────────────────────────────────
    private var _cp     as Float = 277.0;
    private var _wPrime as Float = 21000.0;

    // ── State ─────────────────────────────────────────────────────────
    private var _wBal    as Float = 21000.0;
    private var _wBalMin as Float = 21000.0;

    // ── Graph circular buffer ──────────────────────────────────────────
    private var _graphBuf   as Array = new [N_GRAPH];
    private var _graphIdx   as Number = 0;
    private var _graphCount as Number = 0;
    private var _tickCount  as Number = 0;

    // ── Public outputs (read by view) ──────────────────────────────────
    var wBal    as Float = 21000.0;
    var wBalMin as Float = 21000.0;
    var wPrime  as Float = 21000.0;

    function initialize() {
        _loadConfig();
        _wBal    = _wPrime;
        _wBalMin = _wPrime;
        wBal     = _wPrime;
        wBalMin  = _wPrime;
        wPrime   = _wPrime;
        for (var i = 0; i < N_GRAPH; i++) {
            _graphBuf[i] = _wPrime;
        }
    }

    // ── Load FTP and W' from app properties ───────────────────────────
    private function _loadConfig() as Void {
        var f = Application.Properties.getValue("ftpWatts");
        if (f != null) {
            var fv = (f as Number).toFloat();
            if (fv > 50.0) { _cp = fv; }
        }
        var wp = Application.Properties.getValue("wPrime");
        if (wp != null) {
            var wpv = (wp as Number).toFloat();
            if (wpv > 1000.0) { _wPrime = wpv; }
        }
    }

    // ── Called once per second from compute() ─────────────────────────
    function tick(pw as Number) as Void {
        var p      = pw.toFloat();
        var excess = p - _cp;

        if (excess > 0.0) {
            // Above CP: deplete linearly (1 W above CP costs 1 J per second)
            _wBal -= excess;
        } else {
            // Below CP: exponential recovery toward W'
            var tau = TAU_A * (Math.pow(Math.E, (-0.01 * (-excess)).toDouble())).toFloat() + TAU_B;
            _wBal  += (_wPrime - _wBal) * (1.0 - (Math.pow(Math.E, (-1.0 / tau).toDouble())).toFloat());
        }

        if (_wBal < 0.0)     { _wBal = 0.0; }
        if (_wBal > _wPrime) { _wBal = _wPrime; }
        if (_wBal < _wBalMin) { _wBalMin = _wBal; }

        wBal    = _wBal;
        wBalMin = _wBalMin;

        // Push to graph buffer every GRAPH_EVERY ticks
        _tickCount++;
        if (_tickCount >= GRAPH_EVERY) {
            _tickCount = 0;
            _graphBuf[_graphIdx] = _wBal;
            _graphIdx = (_graphIdx + 1) % N_GRAPH;
            if (_graphCount < N_GRAPH) { _graphCount++; }
        }
    }

    function getGraphBuf()   as Array  { return _graphBuf; }
    function getGraphIdx()   as Number { return _graphIdx; }
    function getGraphCount() as Number { return _graphCount; }
}
