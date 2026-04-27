#!/usr/bin/env bash
# Start the ERG bridge. KICKR connects via BLE; pass --host <IP> for DIRCON/WiFi mode.
# Output is logged to bridge_log.txt and also shown in the terminal.
cd "$(dirname "$0")"
echo "Pulling latest code..."
git pull
echo ""
echo "Starting bridge..."
echo ""
python3 dircon_bridge.py --hr-name CB100 --hr-name Fenix -v 2>&1 | tee bridge_log.txt
