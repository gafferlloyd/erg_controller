# CP / W' calibration

This project uses a rider-specific Critical Power (CP) and W' (anaerobic work capacity) pair in
three places, and none of them derive it automatically — all three just consume a number that
has to be set and periodically reviewed:

- **Garmin datafields** — `garmin/WPrimeValueDF/WPrimeModel.mc` and
  `garmin/WPrimeGraphDF/WPrimeModel.mc` (identical copies). `_cp`/`_wPrime` are fallback
  defaults, overridden on-device by the `ftpWatts`/`wPrime` app settings if set.
- **Live pacing tool** — `js/profile.js` (`profile.ftp`, `profile.wprime`) feeds
  `js/wbal.js`'s W'bal chart on the main `index.html` session view. Defaults come from the code;
  editing the profile fields in the UI persists a rider's own values (see `saveProfile()` /
  `loadProfile()` in `profile.js`).
- **Offline analysis** — `wprime_locus.py` / `wprime_aggregate.py` / `wprime_plot.py` estimate
  CP/W' from a directory of `.fit` files (per-ride feasibility locus → upper envelope across
  rides → knee detection). Useful for visualizing a ride library, but see the caveat below
  before trusting its output as-is for this rider.

## Current calibration

**CP = 277W, W' = 21000J**, set 2026-06-27. Status: **pending a dedicated field-test
validation** — see "What would resolve this" below.

An unresolved alternate candidate exists on the same breakeven line: **CP = 267W, W' = 26.6kJ**.
Both fit the same constraint (see derivation); nothing so far distinguishes them.

## How it was derived

Not a single curve fit — several independent estimates were triangulated and cross-checked:

- Garmin's own auto-FTP (234W) and a naive whole-season power-duration-curve fit (~235W) were
  both **rejected**: run through the live W'bal model, they predicted this rider running out of
  W' on rides that were confirmed non-maximal (no exhaustion, heart rate nowhere near
  threshold/max).
- intervals.icu's eFTP (257W/21kJ) and a season MAP of 340W (a 75.6% ratio, normal for an
  aerobic/diesel profile) pointed higher.
- A block of genuinely-maximal indoor sessions (Jan–Feb 2026, some hitting max HR) gave an
  independent CP fit of ~256.6W indoor — corrected to ~267W outdoor-equivalent using a quantified
  ~10W indoor-vs-outdoor power suppression (same HR, lower power indoors: no airflow/cooling).
- The single cleanest unconfounded data point: a ride on 2025-09-11 (the "Falkenberg-Steinsee"
  route — a frequently-repeated ride with two named climbs, rider-confirmed as totally
  controlled effort, no hard efforts, favourable weather, low training load at the time). Solving
  for the CP that makes *that* ride's W'bal model exactly bottom out at zero, at W'=21kJ, gives
  **276.7W** — rounded to 277W in code.

A historical cross-check: scanning the full Edge530 archive (2023–2026, 398 rides) for segments
where normalized power landed within ±2W of 277W, mean max HR during those segments was
158.3bpm (2023, n=7), 162.0 (2024, n=2), 152.8 (2025, n=32), **150.4 (2026, n=12)**. Producing
277W cost 6–10bpm more in 2023/2024 than it does now — i.e. fitness has genuinely improved, and
**2023/2024 ride data should not be pooled into current CP/W' estimates.**

Two outdoor rides checked after the fact both cleared CP=277W/W'=21kJ comfortably (+7.6kJ and
+6.1kJ floors), with the hardest moments in each staying below threshold HR even 3+ hours in —
consistent with this rider's rides essentially never reaching a true limit (see below).

## Validation rule for any future candidate

Before trusting *any* new CP/W' estimate for this rider — from Garmin, intervals.icu, a curve
fit, or anywhere else — run it through the live W'bal differential model (Skiba 2012/2015
formula, `tau = 546*exp(-0.01*dcp) + 316`, see `calcWbal()` in `js/wbal.js`) against a ride
that's *known to be non-maximal*. If W'bal goes negative on that ride, the candidate is too low.
Reject it regardless of source or how "clean" the fit looks.

**Why this matters here specifically:** every naive source for this rider's FTP has turned out
low, in the same direction, repeatedly:

- Outdoor rides for this rider structurally hold reserve back (deliberate pacing to get home,
  plus terrain/heat). **More outdoor data does not fix this** — it dilutes the few genuinely-hard
  efforts with more conservative ones. Confirmed empirically: a 77-ride/4-month blended
  power-curve fit gave a *worse* (lower) CP estimate than a 13-session indoor-only fit.
  Across the entire 398-ride, ~4-year archive, no single ride's *whole-ride average* HR reaches
  the 156bpm threshold — meaning no ride was ever going to hand over a clean CP read on its own.
- Heat and indoor riding (no airflow) both suppress power for a given physiological strain —
  quantified at roughly −10W indoors vs outdoors at the same HR for this rider. Genuinely-maximal
  indoor efforts still need that correction before being treated as outdoor-equivalent CP.
- W'bal reaching 0 does **not** mean physical exhaustion — it means the rider can no longer
  produce power *above* CP, not that they can't keep riding at/below it. Don't design or
  interpret field tests around an expectation of "falling off the bike" at 0kJ.

### Worked example: why the offline aggregate tool undersells this rider

Running `wprime_aggregate.py` against the full 398-file Edge530 archive gives **CP≈220W,
W'≈36kJ**; restricted to the last 90 days it gives **CP≈194W, W'≈18kJ**. Both are lower CP than
the triangulated 277W figure — exactly the failure mode described above. The script's
upper-envelope method has no way to know whether any given ride was a maximal effort; for a rider
whose rides essentially never reach one, it will systematically read low. Treat its output as a
visualization aid (particularly `wprime_plot.py`'s per-ride loci), not a replacement for the
triangulation-and-sanity-check approach above.

## What would resolve the 277W/21kJ vs 267W/26.6kJ ambiguity

A dedicated maximal effort test on the same day: a 3-minute all-out effort plus a 20-minute
all-out effort, both confirmed maximal (HR at or near personal max). That's the only kind of data
point specific enough to separate the two candidates, which currently sit on the same W'bal
breakeven line.

## Open items

- No dedicated 3min+20min maximal test has been done yet (see above) — still needed to resolve
  277W/21kJ vs. the 267W/26.6kJ alternate candidate.

## Change log

- **2026-07-03**: a ride that day (`2026-07-03-14-52-50.fit`) hit W'bal=0 twice on-device.
  Investigation found the on-device settings for both datafields were still `ftpWatts=250,
  wPrime=20019` (saved 2026-05-24, before this calibration existed) — decoded directly from the
  `.SET` file bytes. Replayed through `wbal_review.py`, the current 277W/21000J candidate passed
  this ride cleanly (min 17% floor, never negative) while 250W/20019J failed exactly as observed.
  No change to the calibration; rebuilt and redeployed `WPrimeValueDF`/`WPrimeGraphDF` to the
  Edge 530 with the settings reset so the device now actually reflects 277W/21000J.

- **2026-07-05**: another real ride (85km, `i162857839`) hit W'bal=0 on-device; the automated
  Signal summary disagreed (7% floor at 277W/21kJ, not zero). Two real bugs found and fixed along
  the way: `normalized_power()` wasn't NaN-safe (poisoned FTP estimates with "nan" whenever a
  best-effort window touched a data gap), and W'bal/CP-solving used wall-clock elapsed time
  instead of moving time, letting a device auto-pause (this ride had ~43min across 3 stops) grant
  free recovery credit a live datafield never actually gives (see `moving_time.py`). Neither fix
  closed the gap on its own (7%→7% floor). Root cause turned out to be the device settings again
  — decoding the `.SET` bytes found `ftpWatts=241, wPrime=20019`, neither the old nor the new
  default. **Not** a Garmin Connect Mobile sync issue (this is a sideloaded app, no Store listing,
  the phone app has no relationship with it) — Connect IQ field settings are exposed through the
  Edge 530's own on-device menu regardless of store status, so this was set directly on the
  device at some point. Once replayed against the *intended* 277W/21kJ, this ride's 7% floor is
  consistent with the established pattern (max HR only 161bpm all ride, nowhere near this
  rider's 173bpm max) — **no change to the calibration**. Settings reset again; durable this time
  against everything except another on-device edit.
