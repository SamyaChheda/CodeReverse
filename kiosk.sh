#!/usr/bin/env bash
# Run on each participant PC:  ./kiosk.sh 192.168.1.50
URL="http://${1:?usage: kiosk.sh SERVER_IP [port]}:${2:-5000}/"
for c in chromium-browser chromium google-chrome; do command -v $c >/dev/null && B=$c && break; done
if [ -n "$B" ]; then exec $B --kiosk --incognito --no-first-run --overscroll-history-navigation=0 "$URL"; fi
exec firefox --kiosk --private-window "$URL"
