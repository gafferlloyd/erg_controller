# Strava Efficiency → Signal: Setup

Two manual prerequisites block this running end-to-end. Both need your hands-on action once;
after that it's fully automated via the systemd timer.

## 1. Strava OAuth scope (currently insufficient)

Confirmed via a real API call (2026-07-04): `GET /athlete/activities` returns 403 with the
current token in `~/strava.env`. It doesn't have `activity:read` scope or higher, so it can't
even list activities, let alone fetch streams.

**Fix — re-authorize the app with broader scope:**
1. Find your app's Client ID and registered redirect URI at
   https://www.strava.com/settings/api (Client ID should match `STRAVA_CLIENT_ID` in
   `~/strava.env`).
2. Build this URL, filling in your redirect URI:
   ```
   https://www.strava.com/oauth/authorize?client_id=<CLIENT_ID>&redirect_uri=<YOUR_REDIRECT_URI>&response_type=code&scope=activity:read_all,profile:read_all&approval_prompt=force
   ```
3. Visit it in a browser, log in if needed, click Authorize.
4. You'll land on `<YOUR_REDIRECT_URI>?code=<CODE>&scope=...` — copy the `code` value.
5. Exchange it: `POST https://www.strava.com/oauth/token` with `client_id`, `client_secret`,
   `code`, `grant_type=authorization_code`. Save the returned `access_token`/`refresh_token`
   into `~/strava.env` (or tell me the code and I'll do the exchange + save).

`activity:read_all` (not just `activity:read`) also covers private activities.
`profile:read_all` enables the W/kg figures — optional, omitted gracefully if missing.

## 2. signal-cli linking (installed, not yet linked)

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

## Once both are done

```bash
python3 strava_efficiency_post.py --dry-run     # confirm it detects and analyzes real rides
python3 strava_efficiency_post.py               # real run -- sends to Signal, marks state
systemctl --user enable --now strava-efficiency-post.timer
```
