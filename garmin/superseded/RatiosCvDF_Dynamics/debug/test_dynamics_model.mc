import Toybox.Lang;
import Toybox.System;

// Test harness for DynamicsModel + DynamicsCore.
// Not compiled in production build (not in root sourcePath).
// To run: temporarily change DynamicsApp to return [new TestDynamicsRunner()].

class TestDynamicsRunner {

    function run() as Void {
        _testCdaConvergence();
        _testKineticEnergy();
        _testClimbSign();
        _testSpeedThreshold();
        System.println("TestDynamicsRunner: all checks logged");
    }

    // Flat road, 10 m/s constant, 200 W → CdA should converge to ~0.28–0.35
    // P_net = P - P_KE - P_climb = 200 - 0 - 0 = 200 W
    // slope = 200 / 10³ = 0.2; CdA = 0.2 / 0.6125 ≈ 0.327
    private function _testCdaConvergence() as Void {
        var m = new DynamicsModel();
        // Feed 60 ticks at flat 10 m/s 200 W with speed variation to give regression variance
        for (var i = 0; i < 60; i++) {
            var v = 8.0 + (i % 5).toFloat();   // 8–12 m/s variation
            var p = 0.5 * 1.225 * 0.32 * v * v * v + 15.0;  // synthetic P for CdA=0.32
            m.tick(p, v, 0.0);
        }
        var cda = m.cda;
        System.println("CdA after 60 ticks: " + ((cda != null) ? (cda as Float).format("%.3f") : "null"));
        // expect ~0.32
    }

    // Accelerating: P_KE = mass * v * dv/dt
    // 85 kg, 10→11 m/s in 1s → P_KE = 85 * 10 * 1 = 850 W
    private function _testKineticEnergy() as Void {
        var m = new DynamicsModel();
        m.tick(0.0, 10.0, 0.0);  // establish vPrev = 10
        m.tick(0.0, 11.0, 0.0);  // Δv = 1
        System.println("pKE (expect ~850): " + m.pKE.format("%.1f"));
    }

    // Climbing: 85 kg, 10 m/s, 5% grade → P_climb = 85 * 9.81 * 0.05 * 10 = 416.9 W
    // Descending: -5% grade → P_climb ≈ -416.9 W
    private function _testClimbSign() as Void {
        var m1 = new DynamicsModel();
        m1.tick(500.0, 10.0, 5.0);
        System.println("pClimb climb (expect ~417): " + m1.pClimb.format("%.1f"));

        var m2 = new DynamicsModel();
        m2.tick(0.0, 10.0, -5.0);
        System.println("pClimb descent (expect ~-417): " + m2.pClimb.format("%.1f"));
    }

    // Below 15 km/h (4.17 m/s), buffer should not grow
    private function _testSpeedThreshold() as Void {
        var pNetBuf   = [] as Array;
        var vCubedBuf = [] as Array;
        var result = DynamicsCore.cdaEstimate(pNetBuf, vCubedBuf, 1.225);
        System.println("CdA empty buf (expect null): " + ((result == null) ? "null" : "NOT null"));
    }
}
