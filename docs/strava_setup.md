# Strava Efficiency → Signal: Setup

Data source is intervals.icu (already working — same credentials as `intervals_pull.py`,
`~/PycharmProjects/intervals-icu-dashboard/.env`), not Strava's API. Strava's own token turned
out to be scoped `read` only (confirmed 2026-07-04 via the account's API settings page — not a
subscription/paywall issue, just insufficient OAuth scope), and rather than re-authorize it, the
whole pipeline was switched to pull `.fit` files from intervals.icu instead. `strava_auth.py` /
`strava_client.py` / `strava_resample.py` are left in the repo, tested and working, in case Strava
OAuth is ever worth revisiting — nothing currently imports them.

One manual prerequisite left: **signal-cli linking** (installed, not yet linked).

Installed at `~/.local/share/signal-cli-0.14.5/` (native build — sidesteps a Java-version
mismatch the plain Java distribution hit), symlinked as `signal-cli` on PATH. 2026-07-04.

1. `signal-cli link -n "erg-controller"` — prints a QR code in the terminal.
2. On your phone: Signal → Settings → Linked Devices → Link New Device → scan it.
3. Create `~/signal.env` with `SIGNAL_PHONE_NUMBER=+<your number, with country code>`.
4. Test directly (bypasses the whole analysis pipeline, just checks the send path):
   ```
   python3 -c "import signal_notify; signal_notify.send('test message')"
   ```
   Should land in your own Signal "Note to Self."

The Signal message is meant to be copy-pasted by hand into the ride's Strava description
afterward — this pipeline never writes to Strava at all, only reads (via intervals.icu) and
sends (via Signal).

## Once signal-cli is linked

```bash
python3 strava_efficiency_post.py --dry-run     # confirm it detects and analyzes real rides
python3 strava_efficiency_post.py               # real run -- sends to Signal, marks state
systemctl --user enable --now strava-efficiency-post.timer
```

Detection and analysis already verified end-to-end against real rides (2026-07-04) — only the
Signal send step remains untested pending the linking step above.
