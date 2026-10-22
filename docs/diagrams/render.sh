#!/bin/bash
# Render the HTML diagrams to docs/figures/*.png with a headless Chromium (Edge or Chrome).
cd "$(dirname "$0")/../.."
B="${BROWSER_BIN:-$(command -v chromium || command -v google-chrome || echo "/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")}"
for n in architecture:1050 agent:1000; do
  f=${n%%:*}; h=${n##*:}
  "$B" --headless --disable-gpu --hide-scrollbars --force-device-scale-factor=1 --window-size=1800,$h \
       --screenshot="$PWD/docs/figures/$f.png" "file://$PWD/docs/diagrams/$f.html"
done
