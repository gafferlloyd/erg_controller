# Garmin Connect IQ datafields

Monkey C datafield projects for the Edge 530. See
`/home/gareth/.claude/briefings/garmin_datafields.md` for SDK paths, build/deploy commands, and
language gotchas — read it before making changes here.

## Active

- **ratios_dynamics/** — "Ratios Dynamics". Decomposes ride power into four segmented-meter rows
  (P_in vs FTP, P_loss, P_grav/climbing, P_kin) plus a live CdA (aero drag) / Crr (rolling
  resistance) regression fit from powered and freewheel (coasting) samples. Inputs are power,
  speed, and altitude only — no heart rate. Includes `fit_simulator.py`, a Python port of
  `RatiosModel.mc` used to validate the physics against a real `.fit` file before changing the
  on-device model.
- **WPrimeValueDF/** — "WBal Value". Numeric W' balance field using the Skiba 2012 model
  (CP-based depletion above threshold, exponential recovery below). FTP and W' are configurable
  via in-app settings.
- **WPrimeGraphDF/** — "WBal Graph". Same model as WPrimeValueDF, plus a 5-minute rolling graph
  (60 samples @ 5s) of W' balance.

## superseded/

Earlier iterations, kept for reference — not maintained:

- `RatiosCv` → `RatiosCvDF` → `RatiosCvDF_PGL` / `RatiosCvDF_Gauges` → `RatiosCvDF_Dynamics` /
  `RatiosCvDF_Ratios` → `Ratios_V_HR_P` — the lineage that preceded `ratios_dynamics`. These were
  HR/power/speed cardiovascular-efficiency ratios; the model was later reworked into the
  power/CdA/Crr physics decomposition now in `ratios_dynamics` (heart rate was dropped entirely).
- `WPrimeDF` — combined W'bal dashboard prototype (readout + built-in bar chart), no settings UI;
  superseded by the `WPrimeValueDF` / `WPrimeGraphDF` pair.
- `MyApp` — unrelated "Hello Garmin" tutorial scaffold.
