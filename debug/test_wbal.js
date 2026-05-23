// debug/test_wbal.js — smoke tests for calcWbal (run in browser console with wbal.js loaded)
// Usage: paste into console or load via <script> after wbal.js

(function () {
  const CP = 250, WP = 20000;

  function assert(label, cond, detail) {
    console.log(cond ? `PASS: ${label}` : `FAIL: ${label} — ${detail}`);
  }

  // 1. All-zero power: wbal must stay at WP throughout
  {
    const samps = Array.from({ length: 120 }, () => ({ power: 0 }));
    const arr = calcWbal(samps, CP, WP);
    assert('zero power stays at WP', arr.every(v => Math.abs(v - WP) < 1), `last=${arr[arr.length-1]}`);
  }

  // 2. Sustained 50 W above CP for 60 s: drain = 50 × 60 = 3000 J exactly
  {
    const samps = Array.from({ length: 60 }, () => ({ power: CP + 50 }));
    const arr = calcWbal(samps, CP, WP);
    const expected = WP - 3000;
    assert('sustained +50W drains 3000J', Math.abs(arr[59] - expected) < 1, `got=${arr[59]} expected=${expected}`);
  }

  // 3. Full drain then recovery: wbal must increase (not decrease) below CP
  {
    const drain  = Array.from({ length: 400 }, () => ({ power: CP + 50 }));
    const recov  = Array.from({ length: 120 }, () => ({ power: CP - 100 }));
    const arr = calcWbal([...drain, ...recov], CP, WP);
    const atEnd  = arr[arr.length - 1];
    const midway = arr[drain.length];
    assert('recovery increases wbal', atEnd > midway, `end=${atEnd.toFixed(0)} mid=${midway.toFixed(0)}`);
  }

  // 4. Empty array returns empty
  {
    const arr = calcWbal([], CP, WP);
    assert('empty input returns []', arr.length === 0, `length=${arr.length}`);
  }

  // 5. Wbal never exceeds WP
  {
    const samps = Array.from({ length: 300 }, (_, i) => ({ power: i % 2 === 0 ? 0 : CP + 100 }));
    const arr = calcWbal(samps, CP, WP);
    assert('wbal never exceeds WP', arr.every(v => v <= WP + 0.001), `max=${Math.max(...arr)}`);
  }

  console.log('calcWbal tests done');
})();
