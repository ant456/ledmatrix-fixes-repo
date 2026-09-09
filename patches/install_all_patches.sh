#!/bin/bash
# Reapplies our custom LEDMatrix patch (render_width/render_height support
# in the Starlark Apps plugin) after a LEDMatrix update overwrites it.
#
# As of Sep 2026, ChuckBuilds/LEDMatrix upstream has already fixed the
# on-demand-restart plugin-loading bug, the "pinned" mode parameter, 0-byte
# render detection, lazy plugin discovery on /plugins/installed, and the
# enable_scrolling attribute for starlark-apps -- so those patches were
# removed from this repo. Only the render_width/render_height fix (needed
# for apps whose native canvas size differs from Pixlet's 64x32 default,
# e.g. imported Glance apps) remains unmerged upstream.
#
# If the base "starlark-apps" plugin isn't installed yet, this script
# will auto-install it from ChuckBuilds/LEDMatrix before patching. It will
# also install the pixlet binary itself if missing.
#
# Usage: place pixlet_renderer.py and starlark_apps_manager.py in the same
# directory as this script, then run it on the Pi.

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
        echo "The folder may have moved upstream -- install the Starlark Apps"
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

# --- Ensure the pixlet binary is installed (separate from the plugin itself) ---
if ! command -v pixlet >/dev/null 2>&1; then
    echo "pixlet binary not found. Installing from tronbyt/pixlet..."

    ARCH="$(uname -m)"
    case "$ARCH" in
        aarch64|arm64)
            PIXLET_ARCH="linux-arm64"
            ;;
        x86_64|amd64)
            PIXLET_ARCH="linux-amd64"
            ;;
        *)
            echo "ERROR: no prebuilt pixlet binary for architecture '$ARCH'"
            echo "(armv7l/armv6l 32-bit Pis aren't supported by upstream releases)."
            echo "You'll need to build pixlet from source -- see"
            echo "https://github.com/tronbyt/pixlet/blob/main/docs/BUILD.md"
            echo "Skipping pixlet install and continuing with patches..."
            PIXLET_ARCH=""
            ;;
    esac

    if [ -n "$PIXLET_ARCH" ]; then
        PIXLET_TAG="$(curl -s https://api.github.com/repos/tronbyt/pixlet/releases/latest | grep -m1 '"tag_name"' | sed -E 's/.*"([^"]+)".*/\1/')"
        if [ -z "$PIXLET_TAG" ]; then
            echo "ERROR: couldn't determine the latest pixlet release (GitHub API"
            echo "unreachable or rate-limited). Install pixlet manually from"
            echo "https://github.com/tronbyt/pixlet/releases and re-run this script."
        else
            PIXLET_URL="https://github.com/tronbyt/pixlet/releases/download/${PIXLET_TAG}/pixlet_${PIXLET_TAG}_${PIXLET_ARCH}.tar.gz"
            TMP_PIXLET_DIR="$(mktemp -d)"
            if curl -sL "$PIXLET_URL" -o "$TMP_PIXLET_DIR/pixlet.tar.gz" && [ -s "$TMP_PIXLET_DIR/pixlet.tar.gz" ]; then
                tar -xzf "$TMP_PIXLET_DIR/pixlet.tar.gz" -C "$TMP_PIXLET_DIR"
                if [ "$(id -u)" -eq 0 ]; then
                    mv "$TMP_PIXLET_DIR/pixlet" /usr/local/bin/pixlet
                    chmod +x /usr/local/bin/pixlet
                else
                    sudo mv "$TMP_PIXLET_DIR/pixlet" /usr/local/bin/pixlet
                    sudo chmod +x /usr/local/bin/pixlet
                fi
                rm -rf "$TMP_PIXLET_DIR"
                echo "pixlet ${PIXLET_TAG} installed to /usr/local/bin/pixlet"
                pixlet version || true
            else
                echo "ERROR: failed to download $PIXLET_URL"
                echo "Install pixlet manually from https://github.com/tronbyt/pixlet/releases"
                rm -rf "$TMP_PIXLET_DIR"
            fi
        fi
    fi
fi

echo "Reapplying custom LEDMatrix patch (render_width/render_height)..."

cp "$SCRIPT_DIR/pixlet_renderer.py" "$STARLARK_APPS_DIR/pixlet_renderer.py"
cp "$SCRIPT_DIR/starlark_apps_manager.py" "$STARLARK_APPS_DIR/manager.py"

echo "Clearing stale __pycache__..."
find "$STARLARK_APPS_DIR" -iname "__pycache__" -exec rm -rf {} + 2>/dev/null || true

echo "Restarting ledmatrix-web..."
sudo systemctl restart ledmatrix-web

echo "Restarting ledmatrix..."
sudo systemctl restart ledmatrix

echo "Done. Apps that set render_width/render_height in their own config.json will now render at their true native size instead of being clipped."
