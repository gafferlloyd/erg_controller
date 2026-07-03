import Toybox.Lang;
import Toybox.Application;

class DynamicsModel {

    private var _pNetBuf   as Array = [];
    private var _vCubedBuf as Array = [];
    private var _vPrev     as Float = 0.0;
    private var _tickCount as Number = 0;

    private var _mass as Float = 85.0;
    private var _rho  as Float = 1.225;

    // Public outputs — null until CdA converges (30+ samples at speed > 15 km/h)
    var cda    as Float or Null = null;
    var pKE    as Float = 0.0;
    var pAero  as Float or Null = null;
    var pClimb as Float = 0.0;
    var pLoss  as Float or Null = null;

    function initialize() {
        var m = Application.Properties.getValue("riderMassFg");
        if (m != null) { _mass = m as Float; }
        var r = Application.Properties.getValue("airDensityFg");
        if (r != null) { _rho  = r as Float; }
    }

    // pw in W, speed in m/s, grade as fraction (e.g. 0.05 = 5% grade, derived from Δalt/Δdist)
    function tick(pw as Float, speed as Float, grade as Float) as Void {
        var v3    = speed * speed * speed;

        pKE    = _mass * speed * (speed - _vPrev);
        pClimb = _mass * 9.81 * grade * speed;

        // Strip KE and climbing from power before regression — leaves P_aero + P_loss
        var pNet = pw - pKE - pClimb;

        // Only accumulate regression data above 15 km/h where aero drag is meaningful
        if (speed > 4.17) {
            _pNetBuf   = BufferUtils.push(_pNetBuf,   pNet, 120);
            _vCubedBuf = BufferUtils.push(_vCubedBuf, v3,   120);
        }

        _tickCount++;
        if (_tickCount % 5 == 0) {
            var est = DynamicsCore.cdaEstimate(_pNetBuf, _vCubedBuf, _rho);
            if (est != null) { cda = est; }
        }

        if (cda != null) {
            var comps = DynamicsCore.powerComponents(pw, speed, _vPrev, grade, _mass,
                                                     cda as Float, _rho);
            pAero = comps[1] as Float;
            pLoss = comps[3] as Float;
        } else {
            pAero = null;
            pLoss = null;
        }

        _vPrev = speed;
    }
}
