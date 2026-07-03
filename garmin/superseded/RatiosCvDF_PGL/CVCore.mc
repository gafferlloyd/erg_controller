import Toybox.Lang;

class CVCore {

    // Least-squares slope of power on HR: returns dW/dHR.
    static function slope(hr as Array, pw as Array) as Float {
        var n = hr.size();
        if (n < 10) { return 0.0; }

        var sx  = 0.0;
        var sy  = 0.0;
        var sxy = 0.0;
        var sx2 = 0.0;

        for (var i = 0; i < n; i++) {
            sx  += hr[i];
            sy  += pw[i];
            sxy += hr[i] * pw[i];
            sx2 += hr[i] * hr[i];
        }

        var den = (n * sx2) - (sx * sx);
        if (den > -0.001 && den < 0.001) { return 0.0; }

        return ((n * sxy) - (sx * sy)) / den;
    }

    // Fractional drift from baseline: positive = efficiency declining.
    static function decoupling(base as Float, now as Float) as Float {
        if (base < 0.001 && base > -0.001) { return 0.0; }
        return (now - base) / base;
    }

    // Map slope to 0–1 gauge fill. Calibrated for dW/dHR range ~0.5–4.5.
    static function normalizeCV(cv as Float) as Float {
        var v = (cv - 0.5) / 4.0;
        if (v < 0.0) { v = 0.0; }
        if (v > 1.0) { v = 1.0; }
        return v;
    }
}
