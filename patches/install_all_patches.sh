#!/bin/bash
# Reapplies our custom LEDMatrix patches (api_v3.py backend routes,
# plugins_manager.js frontend, pixlet_renderer.py render fixes, manager.py
# enable_scrolling fix, display_controller.py) after a LEDMatrix update
# overwrites them.
#
# If the base "starlark-apps" plugin isn't installed yet, this script
# will auto-install it from ChuckBuilds/ledmatrix-plugins before patching.
#
# Usage: place api_v3.py, plugins_manager.js, pixlet_renderer.py,
# starlark_apps_manager.py, and display_controller.py in the same directory
# as this script, then run it on the Pi.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# If invoked with sudo, $HOME resolves to /root instead of the real user's
# home directory. Resolve the actual invoking user's home so we don't go
# looking for (or installing) LEDMatrix under /root by mistake.
if [ -n "$SUDO_USER" ]; then
    REAL_HOME="$(eval echo "~$SUDO_USER")"
else
    REAL_HOME="$HOME"
fi
LEDMATRIX_DIR="$REAL_HOME/LEDMatrix"
STARLARK_APPS_DIR="$LEDMATRIX_DIR/plugin-repos/starlark-apps"
LEDMATRIX_REPO="https://github.com/ChuckBuilds/LEDMatrix.git"

# --- Ensure the base starlark-apps plugin exists before patching it ---
if [ ! -d "$STARLARK_APPS_DIR" ]; then
    echo "starlark-apps plugin not found at $STARLARK_APPS_DIR"
    echo "Installing it from ChuckBuilds/LEDMatrix..."

    TMP_DIR="$(mktemp -d)"
    git clone --depth 1 --filter=blob:none --sparse "$LEDMATRIX_REPO" "$TMP_DIR" >/dev/null 2>&1
    git -C "$TMP_DIR" sparse-checkout set plugin-repos/starlark-apps >/dev/null 2>&1

    if [ ! -d "$TMP_DIR/plugin-repos/starlark-apps" ]; then
        echo "ERROR: couldn't find plugin-repos/starlark-apps in $LEDMATRIX_REPO."
        echo "The folder may have moved upstream — install the Starlark Apps"
        echo "plugin manually via the LEDMatrix web UI first, then re-run"
        echo "this script."
        rm -rf "$TMP_DIR"
        exit 1
    fi

    mkdir -p "$LEDMATRIX_DIR/plugin-repos"
    cp -r "$TMP_DIR/plugin-repos/starlark-apps" "$STARLARK_APPS_DIR"
    rm -rf "$TMP_DIR"

    if [ -n "$SUDO_USER" ]; then
        chown -R "$SUDO_USER:$SUDO_USER" "$STARLARK_APPS_DIR"
    fi

    echo "starlark-apps plugin installed to $STARLARK_APPS_DIR"
fi

echo "Reapplying custom LEDMatrix patches..."

cp "$SCRIPT_DIR/api_v3.py" "$LEDMATRIX_DIR/web_interface/blueprints/api_v3.py"
cp "$SCRIPT_DIR/plugins_manager.js" "$LEDMATRIX_DIR/web_interface/static/v3/plugins_manager.js"
cp "$SCRIPT_DIR/pixlet_renderer.py" "$STARLARK_APPS_DIR/pixlet_renderer.py"
cp "$SCRIPT_DIR/starlark_apps_manager.py" "$STARLARK_APPS_DIR/manager.py"
cp "$SCRIPT_DIR/display_controller.py" "$LEDMATRIX_DIR/src/display_controller.py"

echo "Clearing stale __pycache__..."
find "$STARLARK_APPS_DIR" -iname "__pycache__" -exec rm -rf {} + 2>/dev/null || true

echo "Restarting ledmatrix-web..."
sudo systemctl restart ledmatrix-web

echo "Restarting ledmatrix..."
sudo systemctl restart ledmatrix

echo "Done. Starlark Apps browse/install/config/render/animation-speed and on-demand mode switching should all work again."
