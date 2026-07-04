# Strava Efficiency → Signal: Setup

**Status: fully live since 2026-07-04.** Data source is intervals.icu (same credentials as
`intervals_pull.py`, `~/PycharmProjects/intervals-icu-dashboard/.env`), not Strava's API. Strava's
own token turned out to be scoped `read` only (confirmed via the account's API settings page —
not a subscription/paywall issue, just insufficient OAuth scope), and rather than re-authorize it,
the whole pipeline was switched to pull `.fit` files from intervals.icu instead. `strava_auth.py` /
`strava_client.py` / `strava_resample.py` are left in the repo, tested and working, in case Strava
OAuth is ever worth revisiting — nothing currently imports them.

`signal-cli` is installed (`~/.local/share/signal-cli-0.14.5/`, native build — sidesteps a
Java-version mismatch the plain Java distribution hit, symlinked as `signal-cli` on PATH) **and
linked** to the rider's own Signal account as a secondary device. Config lives at
`~/signal.env` (`SIGNAL_PHONE_NUMBER=...`, outside the repo). Verified working with real test
sends.

The `strava-efficiency-post.timer` systemd user timer is **enabled and running** — checks
intervals.icu hourly (5 past the hour) for new qualifying rides (cycling, ≥20km, power meter, HR),
analyzes each, and sends a Signal message to the rider's own Note-to-Self. The Signal message is
meant to be copy-pasted by hand into the ride's Strava description afterward — this pipeline never
writes to Strava at all, only reads (via intervals.icu) and sends (via Signal).

## Re-linking signal-cli (if it's ever unlinked/needs redoing)

1. `signal-cli link -n "erg-controller"` — prints a linking URI. **Don't rely on the terminal's
   ASCII-art QR rendering** — it frequently fails to scan due to terminal font/sizing issues.
   Instead, generate a real QR image from the URI:
   ```bash
   qr "sgnl://linkdevice?uuid=...&pub_key=..." > /tmp/link_qr.png   # pipx install qrcode; pipx inject qrcode pillow
   DISPLAY=:0 display /tmp/link_qr.png   # NOT eog -- broken snap library conflict on this machine
   ```
2. On the phone: Signal → Settings → Linked Devices → Link New Device → scan the displayed image.
3. `signal-cli listAccounts` to confirm the linked number, update `~/signal.env` if it changed.
4. Signal's server rate-limits repeated failed link attempts ("tried too often") — if hit, wait
   at least a minute before retrying.

## Manual operations

```bash
python3 strava_efficiency_post.py --dry-run                    # compute + print, no send/save
python3 strava_efficiency_post.py --activity-id <id> --force    # re-process one specific ride
systemctl --user status strava-efficiency-post.timer            # check schedule/last run
```
