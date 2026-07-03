import Toybox.Lang;
import Toybox.System;

// Test harness for RatiosModel.
// Not compiled in production build (not in root sourcePath).
// To run: temporarily change RatiosApp to return [new TestRatiosRunner()].

class TestRatiosRunner {

    function run() as Void {
        _testMinuteBoundary();
        _testJPerM();
        _testDecouplingGate();
        _testVPerHr();
        System.println("TestRatiosRunner: all checks logged");
    }

    // After 60 ticks at 60s boundary, minWPerBpm and wPerKg should be set
    // 200 W, 140 bpm → W/bpm = 200/140 ≈ 1.43; W/kg = 200/85 ≈ 2.35
    private function _testMinuteBoundary() as Void {
        var m = new RatiosModel();
        for (var i = 0; i < 60; i++) {
            m.tick(200, 140, 8.0, 480.0);
        }
        var whr = m.minWPerBpm;
        var wkg = m.wPerKg;
        System.println("W/HR after 60s (expect ~1.43): " +
                       ((whr != null) ? (whr as Float).format("%.2f") : "null"));
        System.println("W/kg after 60s (expect ~2.35): " +
                       ((wkg != null) ? (wkg as Float).format("%.2f") : "null"));
    }

    // 1 W for 60 s over 60 m → J/m = 60/60 = 1.0
    private function _testJPerM() as Void {
        var m = new RatiosModel();
        for (var i = 1; i <= 60; i++) {
            m.tick(1, 140, 1.0, i.toFloat());  // distM increments by 1 each tick
        }
        System.println("J/m (expect 1.0): " + m.jPerM.format("%.2f"));
    }

    // decoupling should be null until 60 completed minutes
    private function _testDecouplingGate() as Void {
        var m = new RatiosModel();
        // 59 minutes
        for (var i = 0; i < 59 * 60; i++) {
            m.tick(200, 140, 8.0, (i * 8).toFloat());
        }
        System.println("Dcpl at 59 min (expect null): " +
                       ((m.decoupling == null) ? "null" : "NOT null"));

        // push to 60 minutes
        for (var i = 0; i < 60; i++) {
            m.tick(200, 140, 8.0, (3600 + i * 8).toFloat());
        }
        System.println("Dcpl at 60 min (expect Float): " +
                       ((m.decoupling != null) ? (m.decoupling as Float).format("%.1f") + "%" : "null"));
    }

    // 30 km/h (8.33 m/s) at 140 bpm → vPerHr = 30/140 ≈ 0.214 km/h/bpm
    private function _testVPerHr() as Void {
        var m = new RatiosModel();
        m.tick(200, 140, 8.333, 8.333);
        System.println("vPerHr (expect ~0.214): " + m.vPerHr.format("%.3f"));
    }
}
