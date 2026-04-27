#!/usr/bin/env bash
# Start the DIRCON proxy bridge.
# The KICKR is found automatically via mDNS — no --host needed on Linux.
# Output is logged to bridge_log.txt and also shown in the terminal.
cd "$(dirname "$0")"
python3 dircon_bridge.py --name "KICKR BIKE SHIFT B7C3" -v 2>&1 | tee bridge_log.txt
