import Toybox.Lang;

class DynamicsCore {

    // Regress P_net (y) against v³ (x) to estimate CdA.
    // P_net should already have P_KE and P_climb stripped out.
    // Returns CdA in m², or null if data is insufficient or v³ has too little variance.
    static function cdaEstimate(pNetBuf as Array, vCubedBuf as Array, rho as Float) as Float or Null {
        var n = pNetBuf.size();
        if (n < 30) { return null; }
        if (vCubedBuf.size() < n) { n = vCubedBuf.size(); }

        var sx  = 0.0;
        var sy  = 0.0;
        var sxy = 0.0;
        var sx2 = 0.0;
        var fn  = n.toFloat();

        for (var i = 0; i < n; i++) {
            var x = vCubedBuf[i] as Float;
            var y = pNetBuf[i] as Float;
            sx  += x;
            sy  += y;
            sxy += x * y;
            sx2 += x * x;
        }

        // Denominator is proportional to Var(v³) — near zero means constant speed
        var den = (fn * sx2) - (sx * sx);
        if (den < 1.0 && den > -1.0) { return null; }

        var slope = ((fn * sxy) - (sx * sy)) / den;
        var halfRho = 0.5 * rho;
        if (halfRho < 0.001) { return null; }

        var cda = slope / halfRho;
        // Sanity bounds: 0.10 (extreme TT) to 1.20 (very upright cargo)
        if (cda < 0.10 || cda > 1.20) { return null; }
        return cda;
    }

    // Decompose total power into four physical sinks.
    // grade is already in fraction (not percent).
    // Returns [pKE, pAero, pClimb, pLoss].
    static function powerComponents(p as Float, v as Float, vPrev as Float,
                                    grade as Float, mass as Float,
                                    cda as Float, rho as Float) as Array {
        var pKE   = mass * v * (v - vPrev);
        var pAero = 0.5 * rho * cda * v * v * v;
        var pClimb = mass * 9.81 * grade * v;
        var pLoss = p - pKE - pAero - pClimb;
        return [pKE, pAero, pClimb, pLoss] as Array;
    }
}
