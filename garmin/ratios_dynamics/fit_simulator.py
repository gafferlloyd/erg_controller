#!/usr/bin/env python3
"""
Pre-Garmin physics simulator for ratios_dynamics.

Ports RatiosModel.mc tick-by-tick onto a real .fit file so the math and
physics can be validated before re-creating the Garmin datafield.

Usage:
    python fit_simulator.py <fitfile> [options]
"""

import argparse
import math
import sys
from pathlib import Path

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
from fitparse import FitFile

# ── Physical constants (match RatiosModel.mc exactly) ─────────────────────────
G      = 9.81
RHO0   = 1.225        # kg/m³ sea-level air density
DBSCL  = 4.342944819  # 10/ln(10)
N_MEM_MAX    = 1000   # Crr memory cap: λ fixes at 0.999 once 1000 powered samples seen
CDA_TAU_FAST = 200    # CdA fast-tracker EMA window (seconds) — tracks position/wind changes
CDA_TAU_SLOW = 1000   # CdA slow-tracker EMA window (seconds) — stable ride average
CRR_LOCK_BINS = 3     # min freewheel bins to trust freewheel Crr over powered Crr

# Freewheel bin geometry
N_BINS = 8
V_MIN  = 4.0   # m/s
BIN_W  = 2.0   # m/s per bin


class RatiosModel:
    """Exact Python port of RatiosModel.mc."""

    def __init__(self, mass=78.0, eta=0.98, ftp=250.0, smoothing=10):
        self._mass  = float(mass)
        self._eta   = float(eta)
        self._ftp   = float(ftp)
        self._alpha = 1.0 / float(smoothing)

        # EMA state
        self._pS    = 0.0
        self._vS    = 0.0
        self._hS    = 0.0
        self._vPrev = 0.0
        self._hPrev = 0.0
        self._init  = False

        # Power decomposition outputs
        self.p_in   = 0.0
        self.p_pe   = 0.0
        self.p_ke   = 0.0
        self.p_loss = 0.0

        # dB outputs
        self.db_ftp  = -8.0
        self.db_loss = -20.0
        self.db_pe   = -20.0
        self.db_ke   = -20.0

        # Powered regression accumulators
        self._rSuu     = 0.0
        self._rSuw     = 0.0
        self._rSww     = 0.0
        self._rSuL     = 0.0
        self._rSwL     = 0.0
        self._rN_count = 0    # powered sample counter; λ = 1 - 1/count, capped at N_MEM_MAX

        # Freewheel bins
        self._bin_decel = [999.0] * N_BINS
        self._bin_valid = [False] * N_BINS
        self._bin_tick  = 0

        # Joint 2×2 regression outputs
        self.cda_powered   = None
        self.crr_powered   = None
        self.cda_freewheel = None
        self.crr_freewheel = None

        # Phase-2 outputs: locked Crr + two CdA trackers
        self.crr_locked  = None   # best available Crr (freewheel preferred, else powered)
        self.cda_fast    = None   # 200s EMA — tracks local aero conditions
        self.cda_slow    = None   # 1000s EMA — stable ride average
        self._cda_fast_s = 0.0    # EMA state
        self._cda_slow_s = 0.0
        self._cda_count  = 0      # samples since Crr locked

    # ── Main tick ─────────────────────────────────────────────────────────────
    def tick(self, pw: float, speed: float, alt: float):
        if not self._init:
            self._pS = pw
            self._vS = speed
            self._hS = alt
            self._vPrev = speed
            self._hPrev = alt
            self._init = True
            return

        self._vPrev = self._vS
        self._hPrev = self._hS

        a  = self._alpha
        a1 = 1.0 - a
        self._pS = a * pw    + a1 * self._pS
        self._vS = a * speed + a1 * self._vS
        self._hS = a * alt   + a1 * self._hS

        dv = self._vS - self._vPrev
        dh = self._hS - self._hPrev

        # Power decomposition
        self.p_in   = self._pS
        self.p_pe   = self._mass * G * dh
        self.p_ke   = self._mass * self._vS * dv
        self.p_loss = self.p_in * self._eta - self.p_pe - self.p_ke

        # dB values
        self.db_ftp  = self._to_db(self.p_in, self._ftp)
        self.db_loss = self._to_db(self.p_loss, self.p_in) if (self.p_in > 1.0 and self.p_loss > 0.0) else -20.0
        self.db_pe   = self._to_db(self.p_pe,   self.p_in) if (self.p_in > 1.0 and self.p_pe   > 0.0) else -20.0
        self.db_ke   = self._to_db(self.p_ke,   self.p_in) if (self.p_in > 1.0 and self.p_ke   > 0.0) else -20.0

        # Air density (ISA barometric model)
        rho = RHO0 * math.exp(-self._hS / 8500.0)

        dv_abs = abs(dv)
        dh_abs = abs(dh)

        self._update_powered(dv_abs)
        self._update_freewheel(pw, dv, dh_abs)

        self._bin_tick += 1
        if self._bin_tick >= 300:
            self._decay_bins()
            self._bin_tick = 0

        self._solve_powered(rho)
        self._solve_freewheel(rho)
        self._update_cda_trackers(dv_abs, rho)

    # ── Crr locking + dual CdA trackers ───────────────────────────────────────
    def _update_cda_trackers(self, dv_abs: float, rho: float):
        # Determine best available Crr — freewheel preferred (direct measurement, no power noise)
        fw_bins = sum(self._bin_valid)
        if fw_bins >= CRR_LOCK_BINS and self.crr_freewheel is not None:
            self.crr_locked = self.crr_freewheel
        elif self._rN_count >= N_MEM_MAX and self.crr_powered is not None:
            self.crr_locked = self.crr_powered

        if self.crr_locked is None:
            return

        # Gate: same as powered regression
        if self._pS < 20.0 or self._vS < V_MIN or self.p_loss <= 0.0 or dv_abs > 0.3:
            return

        # 1D CdA estimate with Crr fixed
        f_drag   = self.p_loss / self._vS
        a_sample = (f_drag - self.crr_locked * self._mass * G) / (self._vS ** 2)
        if a_sample <= 0:
            return
        cda_sample = 2.0 * a_sample / rho
        if not (0.05 <= cda_sample <= 1.5):
            return

        # Seed on first valid sample, then apply EMAs
        if self._cda_count == 0:
            self._cda_fast_s = cda_sample
            self._cda_slow_s = cda_sample
        else:
            self._cda_fast_s += (cda_sample - self._cda_fast_s) / CDA_TAU_FAST
            self._cda_slow_s += (cda_sample - self._cda_slow_s) / CDA_TAU_SLOW

        self._cda_count += 1

        # Gate output: fast needs 30 samples, slow needs 120
        if self._cda_count >= 30:
            self.cda_fast = self._cda_fast_s
        if self._cda_count >= 120:
            self.cda_slow = self._cda_slow_s

    # ── dB conversion (clamped −20 .. +3) ─────────────────────────────────────
    def _to_db(self, x: float, ref: float) -> float:
        if ref < 0.1 or x < 0.1:
            return -20.0
        db = DBSCL * math.log(x / ref)
        return max(-20.0, min(3.0, db))

    # ── Powered regression ─────────────────────────────────────────────────────
    def _update_powered(self, dv_abs: float):
        if self._pS    < 20.0:  return
        if self._vS    < V_MIN: return
        if self.p_loss <= 0.0:  return
        if dv_abs      > 0.3:   return

        f_drag = self.p_loss / self._vS
        u = self._vS ** 2
        w = self._mass * G
        f = f_drag

        self._rN_count = min(self._rN_count + 1, N_MEM_MAX)
        lam = 1.0 - 1.0 / self._rN_count
        self._rSuu = lam * self._rSuu + u * u
        self._rSuw = lam * self._rSuw + u * w
        self._rSww = lam * self._rSww + w * w
        self._rSuL = lam * self._rSuL + u * f
        self._rSwL = lam * self._rSwL + w * f

    def _solve_powered(self, rho: float):
        if self._rN_count < 60:
            self.cda_powered = None; self.crr_powered = None; return
        det = self._rSuu * self._rSww - self._rSuw ** 2
        if det < 1.0:
            self.cda_powered = None; self.crr_powered = None; return

        A = (self._rSuL * self._rSww - self._rSwL * self._rSuw) / det
        B = (self._rSuu * self._rSwL - self._rSuw * self._rSuL) / det

        cda = 2.0 * A / rho
        crr = B   # B is already dimensionless: coefficient of (m·g) in F_drag = A·v² + B·(m·g)

        if not (0.05 <= cda <= 1.5 and 0.001 <= crr <= 0.03):
            self.cda_powered = None; self.crr_powered = None; return
        self.cda_powered = cda
        self.crr_powered = crr

    # ── Freewheel binning ──────────────────────────────────────────────────────
    def _update_freewheel(self, pw: float, dv: float, dh_abs: float):
        if pw     >  5.0:   return
        if self._vS < V_MIN: return
        if dv     >= 0.0:   return
        if dh_abs >  0.15:  return

        decel = -dv
        bin_i = int((self._vS - V_MIN) / BIN_W)
        bin_i = max(0, min(N_BINS - 1, bin_i))

        # Minimum physically plausible decel even on perfectly flat road ≈ Crr*g ≈ 0.003 m/s²
        # Values below this floor mean slight downhill was almost cancelling drag — reject.
        if decel > 0.003 and decel < self._bin_decel[bin_i]:
            self._bin_decel[bin_i] = decel
            self._bin_valid[bin_i] = True

    def _decay_bins(self):
        for i in range(N_BINS):
            if self._bin_valid[i]:
                self._bin_decel[i] *= 1.05

    def _solve_freewheel(self, rho: float):
        Suu = Suw = Sww = SuL = SwL = 0.0
        n = 0
        w = self._mass * G

        for i in range(N_BINS):
            if not self._bin_valid[i]:
                continue
            v  = V_MIN + (i + 0.5) * BIN_W
            fD = self._mass * self._bin_decel[i]
            u  = v ** 2

            Suu += u * u
            Suw += u * w
            Sww += w * w
            SuL += u * fD
            SwL += w * fD
            n   += 1

        if n < 2:
            self.cda_freewheel = None; self.crr_freewheel = None; return

        det = Suu * Sww - Suw ** 2
        if det < 1.0:
            self.cda_freewheel = None; self.crr_freewheel = None; return

        A = (SuL * Sww - SwL * Suw) / det
        B = (Suu * SwL - Suw * SuL) / det

        cda = 2.0 * A / rho
        crr = B   # same convention: B is dimensionless coefficient of (m·g)

        if not (0.05 <= cda <= 1.5 and 0.001 <= crr <= 0.03):
            self.cda_freewheel = None; self.crr_freewheel = None; return
        self.cda_freewheel = cda
        self.crr_freewheel = crr


# ── FIT loading ────────────────────────────────────────────────────────────────
def load_fit(path: str) -> pd.DataFrame:
    ff = FitFile(path)
    rows = []
    for msg in ff.get_messages("record"):
        d = {f.name: f.value for f in msg}
        rows.append(d)
    df = pd.DataFrame(rows)

    # fitparse returns speed in m/s, altitude in m, power in W
    for col in ("power", "speed", "altitude", "timestamp"):
        if col not in df.columns:
            df[col] = None

    df["power"]    = pd.to_numeric(df["power"],    errors="coerce")
    df["speed"]    = pd.to_numeric(df["speed"],    errors="coerce")
    df["altitude"] = pd.to_numeric(df["altitude"], errors="coerce").fillna(0.0)
    df = df.dropna(subset=["power", "speed"]).reset_index(drop=True)
    if df["altitude"].isna().all():
        df["altitude"] = 0.0
    return df


# ── Simulation ─────────────────────────────────────────────────────────────────
def simulate(df: pd.DataFrame, model: RatiosModel) -> pd.DataFrame:
    rows = []
    for _, row in df.iterrows():
        model.tick(float(row["power"]), float(row["speed"]), float(row["altitude"]))
        rows.append({
            "timestamp":    row.get("timestamp"),
            "p_raw":        float(row["power"]),
            "v_raw":        float(row["speed"]),
            "alt_raw":      float(row["altitude"]),
            "p_in":         model.p_in,
            "p_pe":         model.p_pe,
            "p_ke":         model.p_ke,
            "p_loss":       model.p_loss,
            "db_ftp":       model.db_ftp,
            "db_loss":      model.db_loss,
            "db_pe":        model.db_pe,
            "db_ke":        model.db_ke,
            "cda_powered":   model.cda_powered,
            "crr_powered":   model.crr_powered,
            "cda_freewheel": model.cda_freewheel,
            "crr_freewheel": model.crr_freewheel,
            "crr_locked":    model.crr_locked,
            "cda_fast":      model.cda_fast,
            "cda_slow":      model.cda_slow,
            "mem_pct":       model._rN_count / N_MEM_MAX * 100,
        })
    return pd.DataFrame(rows)


# ── Summary ────────────────────────────────────────────────────────────────────
def print_summary(df_fit: pd.DataFrame, sim: pd.DataFrame, model: RatiosModel, args):
    n = len(sim)
    ts = sim["timestamp"]
    if ts.notna().any():
        first = ts.dropna().iloc[0]
        last  = ts.dropna().iloc[-1]
        try:
            dur = (last - first).total_seconds()
            dur_str = f"{int(dur//60)}m{int(dur%60):02d}s"
            date_str = str(first.date()) if hasattr(first, "date") else str(first)
        except Exception:
            dur_str = f"{n}s"
            date_str = "unknown"
    else:
        dur_str = f"{n}s"
        date_str = "unknown"

    powered = sim[sim["p_in"] > 20]
    avg_pwr = powered["p_raw"].mean() if len(powered) else float("nan")
    avg_spd = sim["v_raw"].mean() * 3.6  # km/h

    print(f"\nRide: {date_str}  duration={dur_str}  avg_power={avg_pwr:.0f}W  avg_speed={avg_spd:.1f}km/h")
    print(f"Records: {n}  (powered: {len(powered)})")
    print(f"Parameters: mass={args.rider_mass+args.bike_mass:.1f}kg  eta={args.eta}  FTP={args.ftp}W  smoothing={args.smoothing}s")

    if len(powered) > 10:
        med_loss = (powered["p_loss"] / powered["p_in"].clip(lower=1)).median() * 100
        med_pe   = (powered["p_pe"]   / powered["p_in"].clip(lower=1)).median() * 100
        med_ke   = (powered["p_ke"]   / powered["p_in"].clip(lower=1)).median() * 100
        print(f"\nPower decomposition (medians, powered segments):")
        print(f"  P_loss: {med_loss:5.1f}%   P_PE: {med_pe:5.1f}%   P_KE: {med_ke:5.1f}%")

    # Final coefficient estimates
    final_cda_p  = sim["cda_powered"].dropna().iloc[-1]   if sim["cda_powered"].notna().any()   else None
    final_crr_p  = sim["crr_powered"].dropna().iloc[-1]   if sim["crr_powered"].notna().any()   else None
    final_cda_fw = sim["cda_freewheel"].dropna().iloc[-1] if sim["cda_freewheel"].notna().any() else None
    final_crr_fw = sim["crr_freewheel"].dropna().iloc[-1] if sim["crr_freewheel"].notna().any() else None

    n_fw_bins = sum(model._bin_valid)

    final_cda_fast = sim["cda_fast"].dropna().iloc[-1] if sim["cda_fast"].notna().any() else None
    final_cda_slow = sim["cda_slow"].dropna().iloc[-1] if sim["cda_slow"].notna().any() else None
    final_crr_lock = sim["crr_locked"].dropna().iloc[-1] if sim["crr_locked"].notna().any() else None
    crr_src = "freewheel" if (n_fw_bins >= CRR_LOCK_BINS and final_crr_fw) else "powered (joint)"

    print(f"\nAerodynamic coefficients (final values):")
    print(f"  Crr locked ({crr_src}): {f'{final_crr_lock:.5f}' if final_crr_lock else 'not yet locked'}")
    print(f"  CdA fast ({CDA_TAU_FAST}s): {f'{final_cda_fast:.4f} m²' if final_cda_fast else 'insufficient data'}")
    print(f"  CdA slow ({CDA_TAU_SLOW}s): {f'{final_cda_slow:.4f} m²' if final_cda_slow else 'insufficient data'}")
    print(f"  --- joint 2×2 (reference) ---")
    print(f"  Powered   CdA: {f'{final_cda_p:.4f} m²' if final_cda_p else 'n/a'}")
    print(f"  Freewheel CdA: {f'{final_cda_fw:.4f} m²' if final_cda_fw else 'n/a'}  (bins: {n_fw_bins}/{N_BINS})")
    print()


# ── Plots ──────────────────────────────────────────────────────────────────────
def plot(sim: pd.DataFrame, model: RatiosModel):
    t = np.arange(len(sim))  # seconds index

    fig, axes = plt.subplots(3, 2, figsize=(14, 12))
    fig.suptitle("ratios_dynamics — pre-Garmin simulator", fontsize=13)

    # ── (0,0) Power decomposition in watts ───────────────────────────────────
    ax = axes[0, 0]
    ax.plot(t, sim["p_in"],   color="steelblue",  lw=1.2, label="P_in")
    ax.plot(t, sim["p_loss"], color="crimson",     lw=1.0, label="P_loss (aero+roll)")
    ax.plot(t, sim["p_pe"],   color="darkorange",  lw=0.9, label="P_PE (gravity)")
    ax.plot(t, sim["p_ke"],   color="olive",       lw=0.9, label="P_KE (accel)")
    ax.axhline(0, color="k", lw=0.5, ls="--")
    ax.set_title("Power decomposition (W)")
    ax.set_ylabel("Watts")
    ax.legend(fontsize=8, loc="upper right")
    ax.set_xlabel("Time (s)")

    # ── (0,1) Loss fractions % ────────────────────────────────────────────────
    ax = axes[0, 1]
    p_in_safe = sim["p_in"].clip(lower=1.0)
    powered   = sim["p_in"] > 20.0
    loss_pct  = np.where(powered, sim["p_loss"] / p_in_safe * 100, np.nan)
    pe_pct    = np.where(powered, sim["p_pe"]   / p_in_safe * 100, np.nan)
    ke_pct    = np.where(powered, sim["p_ke"]   / p_in_safe * 100, np.nan)
    ax.plot(t, loss_pct, color="crimson",    lw=1.0, label="P_loss %")
    ax.plot(t, pe_pct,   color="darkorange", lw=0.9, label="P_PE %")
    ax.plot(t, ke_pct,   color="olive",      lw=0.9, label="P_KE %")
    ax.axhline(0, color="k", lw=0.5, ls="--")
    ax.set_title("Loss fractions (% of P_in, powered only)")
    ax.set_ylabel("%")
    ax.legend(fontsize=8)
    ax.set_xlabel("Time (s)")

    # ── (1,0) F_drag vs v² scatter (regression diagnostic) ──────────────────
    ax = axes[1, 0]
    powered_mask = (sim["p_in"] > 20.0) & (sim["p_loss"] > 0) & (sim["v_raw"] >= V_MIN)
    v_pow  = sim.loc[powered_mask, "v_raw"].to_numpy()
    fl_pow = (sim.loc[powered_mask, "p_loss"] / sim.loc[powered_mask, "v_raw"].clip(lower=0.1)).to_numpy()
    sc = ax.scatter(v_pow**2, fl_pow, c=v_pow*3.6, cmap="viridis", s=2, alpha=0.4)
    plt.colorbar(sc, ax=ax, label="Speed (km/h)")
    # overlay fitted line from final powered CdA/Crr
    rho_surf = RHO0 * math.exp(-sim["alt_raw"].mean() / 8500.0)
    v2_range = np.linspace(V_MIN**2, (sim["v_raw"].max()**2)*1.05, 200)
    if model.cda_powered is not None:
        A_fit = rho_surf * model.cda_powered / 2.0
        B_fit = model.crr_powered * model._mass * G
        ax.plot(v2_range, A_fit * v2_range + B_fit, "r-", lw=2,
                label=f"fit: CdA={model.cda_powered:.3f}, Crr={model.crr_powered:.4f}")
        ax.legend(fontsize=8)
    ax.set_title("F_drag vs v²  (powered samples)")
    ax.set_xlabel("v²  (m²/s²)")
    ax.set_ylabel("F_drag = P_loss/v  (N)")

    # ── (1,1) Freewheel bin state (final) ────────────────────────────────────
    ax = axes[1, 1]
    bin_speeds = [V_MIN + (i + 0.5) * BIN_W for i in range(N_BINS)]
    bin_decels = [model._bin_decel[i] if model._bin_valid[i] else np.nan
                  for i in range(N_BINS)]
    colors = ["steelblue" if model._bin_valid[i] else "lightgrey" for i in range(N_BINS)]
    bars = ax.bar(bin_speeds, [d if not np.isnan(d) else 0 for d in bin_decels],
                  width=BIN_W * 0.8, color=colors, edgecolor="k", linewidth=0.5)
    ax.set_title("Freewheel bins — min deceleration per speed band (final)")
    ax.set_xlabel("Speed (m/s)")
    ax.set_ylabel("Deceleration (m/s per tick)")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(
        lambda x, _: f"{x:.0f} m/s\n({x*3.6:.0f} km/h)"))
    for i, (v, d) in enumerate(zip(bin_speeds, bin_decels)):
        if not np.isnan(d):
            ax.text(v, d + 0.0002, f"{d:.4f}", ha="center", va="bottom", fontsize=7)

    # ── (2,0) CdA evolution ───────────────────────────────────────────────────
    ax = axes[2, 0]
    mem_full_t = t[sim["mem_pct"] >= 100].min() if (sim["mem_pct"] >= 100).any() else t[-1]
    ax.axvspan(0, mem_full_t, alpha=0.07, color="orange", label="Crr warming up")
    ax.plot(t, sim["cda_powered"].to_numpy(dtype=float),
            color="lightsteelblue", lw=1.0, ls="--", label="CdA joint 2×2")
    ax.plot(t, sim["cda_fast"].to_numpy(dtype=float),
            color="crimson",    lw=1.4, label=f"CdA fast ({CDA_TAU_FAST}s)")
    ax.plot(t, sim["cda_slow"].to_numpy(dtype=float),
            color="steelblue",  lw=1.4, label=f"CdA slow ({CDA_TAU_SLOW}s)")
    ax.set_title("CdA evolution (m²)  — fast=local aero, slow=ride average")
    ax.set_ylabel("CdA (m²)")
    ax.legend(fontsize=8)
    ax.set_xlabel("Time (s)")
    ax.set_ylim(0, 0.6)

    # ── (2,1) Crr evolution ───────────────────────────────────────────────────
    ax = axes[2, 1]
    ax.plot(t, sim["crr_powered"].to_numpy(dtype=float),
            color="lightsteelblue", lw=1.0, ls="--", label="Crr powered (joint)")
    ax.plot(t, sim["crr_freewheel"].to_numpy(dtype=float),
            color="darkorange", lw=1.2, label="Crr freewheel")
    ax.plot(t, sim["crr_locked"].to_numpy(dtype=float),
            color="steelblue",  lw=2.0, label="Crr locked (active)")
    ax.set_title("Crr  — locked value drives CdA trackers")
    ax.set_ylabel("Crr")
    ax.legend(fontsize=8)
    ax.set_xlabel("Time (s)")
    ax.set_ylim(0, 0.025)

    plt.tight_layout()
    plt.show()


# ── Lambda comparison plot ─────────────────────────────────────────────────────
def plot_lambda_compare(df_fit: pd.DataFrame, total_mass: float, args):
    # Compare different memory caps — all using the same dynamic-λ scheme
    caps    = [100, 200, 333, 500, 1000]
    colors  = ["#e41a1c", "#ff7f00", "#4daf4a", "#377eb8", "#984ea3"]
    labels  = [f"cap={c}s  (fixes at λ={1-1/c:.4f})" for c in caps]

    fig, axes = plt.subplots(2, 1, figsize=(13, 8), sharex=True)
    fig.suptitle(f"Dynamic-λ memory cap sensitivity — {Path(args.fitfile).name}", fontsize=12)

    print("Running dynamic-λ cap comparison …")
    for cap, color, label in zip(caps, colors, labels):
        sim = _simulate_with_lambda(df_fit, cap, total_mass, args.eta, args.smoothing)
        t   = np.arange(len(sim))
        cda = sim["cda_powered"].to_numpy(dtype=float)
        crr = sim["crr_powered"].to_numpy(dtype=float)
        axes[0].plot(t, cda, color=color, lw=1.2, alpha=0.85, label=label)
        axes[1].plot(t, crr, color=color, lw=1.2, alpha=0.85, label=label)
        final_cda = sim["cda_powered"].dropna().iloc[-1] if sim["cda_powered"].notna().any() else None
        final_crr = sim["crr_powered"].dropna().iloc[-1] if sim["crr_powered"].notna().any() else None
        print(f"  {label}  →  CdA={f'{final_cda:.4f}' if final_cda else '---'}"
              f"  Crr={f'{final_crr:.5f}' if final_crr else '---'}")

    for ax, ylabel, ylim in zip(axes, ["CdA (m²)", "Crr"], [(0.0, 0.6), (0.0, 0.025)]):
        ax.set_ylabel(ylabel)
        ax.set_ylim(*ylim)
        ax.legend(fontsize=8, loc="upper right")
        ax.axvline(600,  color="k", lw=0.7, ls=":", alpha=0.4)
        ax.axvline(2000, color="k", lw=0.7, ls=":",  alpha=0.4)
        ax.text(610,  ylim[1]*0.97, "10min", fontsize=7, va="top", color="gray")
        ax.text(2010, ylim[1]*0.97, "33min", fontsize=7, va="top", color="gray")
        ax.grid(True, alpha=0.2)
    axes[1].set_xlabel("Time (s)")

    plt.tight_layout()
    plt.show()


def _simulate_with_lambda(df: pd.DataFrame, n_cap: int,
                          mass: float, eta: float, smoothing: int) -> pd.DataFrame:
    """Simulate powered regression with dynamic-λ scheme capped at n_cap powered samples."""
    alpha = 1.0 / smoothing
    pS = vS = hS = vPrev = hPrev = 0.0
    init = False
    rSuu = rSuw = rSww = rSuL = rSwL = 0.0
    n_count = 0

    rows = []
    for _, row in df.iterrows():
        pw = float(row["power"]); spd = float(row["speed"]); alt = float(row["altitude"])

        if not init:
            pS=pw; vS=spd; hS=alt; vPrev=spd; hPrev=alt; init=True
            rows.append({"cda_powered": None, "crr_powered": None}); continue

        vPrev=vS; hPrev=hS
        pS = alpha*pw + (1-alpha)*pS
        vS = alpha*spd + (1-alpha)*vS
        hS = alpha*alt + (1-alpha)*hS
        dv = vS-vPrev; dh = hS-hPrev

        p_loss = pS*eta - mass*G*dh - mass*vS*dv
        rho    = RHO0 * math.exp(-hS / 8500.0)

        if pS >= 20 and vS >= V_MIN and p_loss > 0 and abs(dv) <= 0.3:
            n_count = min(n_count + 1, n_cap)
            lam = 1.0 - 1.0 / n_count
            fD = p_loss/vS; u = vS**2; w = mass*G
            rSuu = lam*rSuu + u*u; rSuw = lam*rSuw + u*w
            rSww = lam*rSww + w*w; rSuL = lam*rSuL + u*fD
            rSwL = lam*rSwL + w*fD

        cda_p = crr_p = None
        if n_count >= 60:
            det = rSuu*rSww - rSuw**2
            if det >= 1.0:
                A = (rSuL*rSww - rSwL*rSuw) / det
                B = (rSuu*rSwL - rSuw*rSuL) / det
                cda = 2.0*A/rho; crr = B
                if 0.05 <= cda <= 1.5 and 0.001 <= crr <= 0.03:
                    cda_p = cda; crr_p = crr

        rows.append({"cda_powered": cda_p, "crr_powered": crr_p})

    return pd.DataFrame(rows)


# ── CLI ────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Pre-Garmin offline simulator for ratios_dynamics CdA/Crr estimation"
    )
    parser.add_argument("fitfile", help="Path to .fit file")
    parser.add_argument("--rider-mass", type=float, default=68.0,   metavar="KG", help="Rider mass kg (default 68)")
    parser.add_argument("--bike-mass",  type=float, default=10.0,   metavar="KG", help="Bike+kit mass kg (default 10)")
    parser.add_argument("--eta",        type=float, default=0.98,                 help="Drivetrain efficiency (default 0.98)")
    parser.add_argument("--ftp",        type=float, default=250.0,  metavar="W",  help="FTP watts (default 250)")
    parser.add_argument("--smoothing",  type=int,   default=10,     metavar="S",  help="EMA window seconds (default 10)")
    parser.add_argument("--no-plot",    action="store_true",                      help="Print summary only, no plots")
    parser.add_argument("--lambda-compare", action="store_true",                  help="Plot CdA/Crr convergence across multiple LAMBDA values")
    args = parser.parse_args()

    fit_path = Path(args.fitfile)
    if not fit_path.exists():
        sys.exit(f"File not found: {fit_path}")

    print(f"Loading {fit_path.name} …")
    df_fit = load_fit(str(fit_path))
    print(f"  {len(df_fit)} records with power/speed/altitude")

    total_mass = args.rider_mass + args.bike_mass

    if args.lambda_compare:
        plot_lambda_compare(df_fit, total_mass, args)
        return

    model = RatiosModel(mass=total_mass, eta=args.eta, ftp=args.ftp, smoothing=args.smoothing)

    print("Running simulation …")
    sim = simulate(df_fit, model)

    print_summary(df_fit, sim, model, args)

    if not args.no_plot:
        plot(sim, model)


if __name__ == "__main__":
    main()
