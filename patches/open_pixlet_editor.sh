#!/bin/bash
# Launches Pixlet's own interactive config editor (the real one, with
# working cascading dropdowns etc.) for any installed Starlark app —
# saving directly to the app's real config.json as you make changes
# (confirmed on real hardware, 2026-08-27: pixlet serve --saveconfig
# writes on every change, no manual export/copy step needed at all).
#
# Usage:
#   ./open_pixlet_editor.sh <app_id>
#
# Example:
#   ./open_pixlet_editor.sh penndot_signs
#
# Then visit http://ledpi.local:8080/ from any browser on your network
# and change settings — they save to the real config automatically.
# Press Ctrl+C when you're done; this script restarts the display
# service for you so the changes take effect immediately.
#
# A backup of the config as it was before you started is kept at
# config.json.backup in the app's folder, in case something needs
# reverting.

set -e

if [ -z "$1" ]; then
    echo "Usage: $0 <app_id>"
    echo ""
    echo "Installed apps:"
    ls ~/LEDMatrix/starlark-apps/ 2>/dev/null | grep -v '^\.' || echo "  (none found)"
    exit 1
fi

APP_ID="$1"
APP_DIR="$HOME/LEDMatrix/starlark-apps/$APP_ID"

if [ ! -d "$APP_DIR" ]; then
    echo "No such app: $APP_ID"
    echo ""
    echo "Installed apps:"
    ls ~/LEDMatrix/starlark-apps/ 2>/dev/null | grep -v '^\.'
    exit 1
fi

STAR_FILE=$(find "$APP_DIR" -maxdepth 1 -iname "*.star" | head -1)

if [ -z "$STAR_FILE" ]; then
    echo "No .star file found in $APP_DIR"
    exit 1
fi

CONFIG_FILE="$APP_DIR/config.json"

# Back up whatever config currently exists, so there's an easy way back
# if something goes wrong while editing.
if [ -f "$CONFIG_FILE" ]; then
    cp "$CONFIG_FILE" "$CONFIG_FILE.backup"
    echo "Backed up existing config to: $CONFIG_FILE.backup"
else
    echo "{}" > "$CONFIG_FILE"
fi

# Restart the display service automatically once the editor is closed,
# so changes take effect without a separate manual step.
cleanup() {
    echo ""
    echo "Stopping editor, restarting display service..."
    sudo systemctl restart ledmatrix
    echo "Done. If something looks wrong, your previous config is saved at:"
    echo "  $CONFIG_FILE.backup"
}
trap cleanup EXIT INT TERM

echo "Stopping display service while editing (avoids it reading the config mid-write)..."
sudo systemctl stop ledmatrix

echo "Starting Pixlet config editor for: $APP_ID"
echo "Star file: $STAR_FILE"
echo ""
echo "Visit http://ledpi.local:8080/ from any browser on your network."
echo "Changes save automatically to the real config as you make them."
echo ""
echo "Press Ctrl+C when finished — this will restart the display for you."
echo ""

cd "$APP_DIR"
pixlet serve "$(basename "$STAR_FILE")" --host 0.0.0.0 --port 8080 --no-browser --saveconfig "$CONFIG_FILE"
