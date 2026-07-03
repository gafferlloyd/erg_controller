import Toybox.Lang;
import Toybox.Math;
import Toybox.Application;
import Toybox.UserProfile;

class RatiosModel {

    // ── Physical constants ─────────────────────────────────────────────
    private const G     as Float = 9.81;
    private const RHO0  as Float = 1.225;
    private const DBSCL as Double = 4.342944819d;

    // ── Regression memory (dynamic λ: grows until N_MEM_MAX, then fixes) ─
    private const N_MEM_MAX as Number = 1000;  // λ fixes at 1 - 1/1000 = 0.999

    // ── CdA tracker EMA coefficients ──────────────────────────────────
    private const CDA_ALPHA_FAST as Float = 0.005;  // 1/200 s
    private const CDA_ALPHA_SLOW as Float = 0.001;  // 1/1000 s
    private const CRR_LOCK_BINS  as Number = 3;     // min freewheel bins for Crr lock

    // ── Freewheel bin geometry ─────────────────────────────────────────
    private const N_BINS as Number = 8;
    private const V_MIN  as Float  = 4.0;   // m/s (~14 km/h)
    private const BIN_W  as Float  = 2.0;   // m/s per bin

    // ── Config ────────────────────────────────────────────────────────
    private var _mass  as Float = 78.0;
    private var _eta   as Float = 0.98;
    private var _ftp   as Float = 250.0;
    private var _alpha as Float = 0.1;

    // ── EMA-smoothed signals ───────────────────────────────────────────
    private var _pS    as Float   = 0.0;
    private var _vS    as Float   = 0.0;
    private var _hS    as Float   = 0.0;
    private var _vPrev as Float   = 0.0;
    private var _hPrev as Float   = 0.0;
    private var _init  as Boolean = false;

    // ── Power decomposition outputs (W) ───────────────────────────────
    var pIn    as Float = 0.0;
    var pPE    as Float = 0.0;
    var pKE    as Float = 0.0;
    var pLoss  as Float = 0.0;
    var pWheel as Float = 0.0;  // pIn × η — denominator for percentage display

    // ── dB outputs ────────────────────────────────────────────────────
    var dbFtp  as Float = -8.0;
    var dbLoss as Float = -20.0;
    var dbPE   as Float = -20.0;
    var dbKE   as Float = -20.0;

    // ── Powered regression accumulators ───────────────────────────────
    // Model: F_drag = A·v² + B·(m·g),  A = ½ρCdA,  B = Crr (dimensionless)
    private var _rSuu    as Double = 0.0d;
    private var _rSuw    as Double = 0.0d;
    private var _rSww    as Double = 0.0d;
    private var _rSuL    as Double = 0.0d;
    private var _rSwL    as Double = 0.0d;
    private var _rNCount as Number = 0;   // powered sample count, capped at N_MEM_MAX

    // ── Freewheel envelope ─────────────────────────────────────────────
    private var _binDecel as Array = new [8];
    private var _binValid as Array = new [8];
    private var _binTick  as Number = 0;

    // ── Joint 2×2 regression outputs (reference / Crr source) ────────
    var cdaPowered   as Float or Null = null;
    var crrPowered   as Float or Null = null;
    var cdaFreewheel as Float or Null = null;
    var crrFreewheel as Float or Null = null;

    // ── Phase-2 outputs ────────────────────────────────────────────────
    var crrLocked as Float or Null = null;  // best Crr (freewheel preferred)
    var cdaFast   as Float or Null = null;  // 200s EMA — local/position tracking
    var cdaSlow   as Float or Null = null;  // 1000s EMA — stable ride average

    private var _cdaFastS as Float  = 0.0;
    private var _cdaSlowS as Float  = 0.0;
    private var _cdaCount as Number = 0;

    function initialize() {
        for (var i = 0; i < N_BINS; i++) {
            _binDecel[i] = 999.0;
            _binValid[i] = false;
        }
        _loadConfig();
    }

    // ── Configuration ─────────────────────────────────────────────────
    private function _loadConfig() as Void {
        var riderMass = 68.0;
        var profile = UserProfile.getProfile();
        if (profile != null && profile.weight != null) {
            riderMass = (profile.weight as Number).toFloat() / 1000.0;
        }
        var bm = Application.Properties.getValue("bikeSystemMass");
        _mass = riderMass + ((bm != null) ? (bm as Float) : 10.0);
        var eta = Application.Properties.getValue("drivetrainEff");
        if (eta != null) { _eta = eta as Float; }
        var f = Application.Properties.getValue("ftpWatts");
        if (f != null) {
            var fVal = (f as Number).toFloat();
            if (fVal > 50.0) { _ftp = fVal; }
        }
        var sw = Application.Properties.getValue("smoothingWindow");
        if (sw != null) {
            var swN = sw as Number;
            if (swN >= 3 && swN <= 30) { _alpha = 1.0 / swN.toFloat(); }
        }
    }

    // ── Main tick ─────────────────────────────────────────────────────
    function tick(pw as Number, speed as Float, alt as Float) as Void {
        if (!_init) {
            _pS = pw.toFloat(); _vS = speed; _hS = alt;
            _vPrev = speed; _hPrev = alt;
            _init = true;
            return;
        }

        _vPrev = _vS; _hPrev = _hS;

        var a = _alpha; var a1 = 1.0 - a;
        _pS = a * pw.toFloat() + a1 * _pS;
        _vS = a * speed        + a1 * _vS;
        _hS = a * alt          + a1 * _hS;

        var dv = _vS - _vPrev;
        var dh = _hS - _hPrev;

        pIn   = _pS;
        pPE   = _mass * G * dh;
        pKE   = _mass * _vS * dv;
        pLoss  = pIn * _eta - pPE - pKE;
        pWheel = pIn * _eta;

        dbFtp  = _toDb(pIn, _ftp);
        dbLoss = (pIn > 1.0 && pLoss > 0.0) ? _toDb(pLoss, pIn) : -20.0;
        dbPE   = (pIn > 1.0 && pPE   > 0.0) ? _toDb(pPE,   pIn) : -20.0;
        dbKE   = (pIn > 1.0 && pKE   > 0.0) ? _toDb(pKE,   pIn) : -20.0;

        var rho = (RHO0 * Math.pow(Math.E, -_hS.toDouble() / 8500.0d)).toFloat();

        var dvAbs = (dv < 0.0) ? -dv : dv;
        var dhAbs = (dh < 0.0) ? -dh : dh;

        _updatePowered(dvAbs);
        _updateFreewheel(pw, dv, dhAbs);

        _binTick++;
        if (_binTick >= 300) { _decayBins(); _binTick = 0; }

        _solvePowered(rho);
        _solveFreewheel(rho);
        _updateCdaTrackers(dvAbs, rho);
    }

    // ── dB conversion ─────────────────────────────────────────────────
    private function _toDb(x as Float, ref as Float) as Float {
        if (ref < 0.1 || x < 0.1) { return -20.0; }
        var db = (DBSCL * Math.log(x.toDouble() / ref.toDouble(), Math.E)).toFloat();
        if (db < -20.0) { return -20.0; }
        if (db >   3.0) { return   3.0; }
        return db;
    }

    // ── Powered regression ─────────────────────────────────────────────
    private function _updatePowered(dvAbs as Float) as Void {
        if (_pS   < 20.0)  { return; }
        if (_vS   < V_MIN) { return; }
        if (pLoss <= 0.0)  { return; }
        if (dvAbs > 0.3)   { return; }

        if (_rNCount < N_MEM_MAX) { _rNCount++; }
        var lam = 1.0d - 1.0d / _rNCount.toDouble();

        var fDrag = pLoss / _vS;
        var u = (_vS * _vS).toDouble();
        var w = (_mass * G).toDouble();
        var f = fDrag.toDouble();

        _rSuu = lam * _rSuu + u * u;
        _rSuw = lam * _rSuw + u * w;
        _rSww = lam * _rSww + w * w;
        _rSuL = lam * _rSuL + u * f;
        _rSwL = lam * _rSwL + w * f;
    }

    private function _solvePowered(rho as Float) as Void {
        if (_rNCount < 60) { cdaPowered = null; crrPowered = null; return; }
        var det = _rSuu * _rSww - _rSuw * _rSuw;
        if (det < 1.0d)    { cdaPowered = null; crrPowered = null; return; }

        var A = ((_rSuL * _rSww - _rSwL * _rSuw) / det).toFloat();
        var B = ((_rSuu * _rSwL - _rSuw * _rSuL) / det).toFloat();

        var cda = (2.0d * A.toDouble() / rho.toDouble()).toFloat();
        var crr = B;   // B is the coefficient of (m·g) → dimensionless = Crr

        if (cda < 0.05 || cda > 1.5 || crr < 0.001 || crr > 0.03) {
            cdaPowered = null; crrPowered = null; return;
        }
        cdaPowered = cda;
        crrPowered = crr;
    }

    // ── Freewheel envelope ─────────────────────────────────────────────
    private function _updateFreewheel(pw as Number, dv as Float,
                                       dhAbs as Float) as Void {
        if (pw    >  5)     { return; }
        if (_vS   <  V_MIN) { return; }
        if (dv    >= 0.0)   { return; }
        if (dhAbs >  0.15)  { return; }

        var decel = -dv;
        // Reject near-zero decels — slight downhill almost cancelling drag
        if (decel < 0.003)  { return; }

        var bin = ((_vS - V_MIN) / BIN_W).toNumber();
        if (bin < 0)        { bin = 0; }
        if (bin >= N_BINS)  { bin = N_BINS - 1; }

        if (decel < (_binDecel[bin] as Float)) {
            _binDecel[bin] = decel;
            _binValid[bin] = true;
        }
    }

    private function _decayBins() as Void {
        for (var i = 0; i < N_BINS; i++) {
            if (_binValid[i] as Boolean) {
                _binDecel[i] = (_binDecel[i] as Float) * 1.05;
            }
        }
    }

    private function _solveFreewheel(rho as Float) as Void {
        var Suu = 0.0d; var Suw = 0.0d; var Sww = 0.0d;
        var SuL = 0.0d; var SwL = 0.0d;
        var n   = 0;
        var w   = (_mass * G).toDouble();

        for (var i = 0; i < N_BINS; i++) {
            if (!(_binValid[i] as Boolean)) { continue; }
            var v  = V_MIN + (i.toFloat() + 0.5) * BIN_W;
            var fD = (_mass * (_binDecel[i] as Float)).toDouble();
            var u  = (v * v).toDouble();
            Suu += u * u; Suw += u * w; Sww += w * w;
            SuL += u * fD; SwL += w * fD;
            n++;
        }

        if (n < 2) { cdaFreewheel = null; crrFreewheel = null; return; }
        var det = Suu * Sww - Suw * Suw;
        if (det < 1.0d) { cdaFreewheel = null; crrFreewheel = null; return; }

        var A = ((SuL * Sww - SwL * Suw) / det).toFloat();
        var B = ((Suu * SwL - Suw * SuL) / det).toFloat();

        var cda = (2.0d * A.toDouble() / rho.toDouble()).toFloat();
        var crr = B;   // dimensionless coefficient of (m·g)

        if (cda < 0.05 || cda > 1.5 || crr < 0.001 || crr > 0.03) {
            cdaFreewheel = null; crrFreewheel = null; return;
        }
        cdaFreewheel = cda;
        crrFreewheel = crr;
    }

    // ── Crr locking + dual CdA trackers ───────────────────────────────
    private function _updateCdaTrackers(dvAbs as Float, rho as Float) as Void {
        // Lock Crr: freewheel preferred (no power-meter noise), else long-memory powered
        var fwBins = 0;
        for (var i = 0; i < N_BINS; i++) {
            if (_binValid[i] as Boolean) { fwBins++; }
        }
        if (fwBins >= CRR_LOCK_BINS && crrFreewheel != null) {
            crrLocked = crrFreewheel;
        } else if (_rNCount >= N_MEM_MAX && crrPowered != null) {
            crrLocked = crrPowered;
        }

        if (crrLocked == null) { return; }

        // Gate: same as powered regression
        if (_pS   < 20.0)  { return; }
        if (_vS   < V_MIN) { return; }
        if (pLoss <= 0.0)  { return; }
        if (dvAbs > 0.3)   { return; }

        // 1D CdA from residual after subtracting known rolling force
        var fDrag    = pLoss / _vS;
        var aReduced = (fDrag - (crrLocked as Float) * _mass * G) / (_vS * _vS);
        if (aReduced <= 0.0) { return; }
        var cdaSample = (2.0d * aReduced.toDouble() / rho.toDouble()).toFloat();
        if (cdaSample < 0.05 || cdaSample > 1.5) { return; }

        if (_cdaCount == 0) {
            _cdaFastS = cdaSample;
            _cdaSlowS = cdaSample;
        } else {
            _cdaFastS += CDA_ALPHA_FAST * (cdaSample - _cdaFastS);
            _cdaSlowS += CDA_ALPHA_SLOW * (cdaSample - _cdaSlowS);
        }
        _cdaCount++;

        if (_cdaCount >= 30)  { cdaFast = _cdaFastS; }
        if (_cdaCount >= 120) { cdaSlow = _cdaSlowS; }
    }
}
