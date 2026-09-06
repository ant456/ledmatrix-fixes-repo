#!/bin/bash
# Full LEDMatrix patch installer.
#
# Covers every core-file fix accumulated across an extended debugging
# session:
#
#   api_v3.py            Starlark Apps backend routes (browse/install/
#                         config/schema, on-demand display routes) --
#                         these ship frontend-only upstream with no
#                         backend, so the web UI 404s without this.
#
#   plugins_manager.js   Starlark Apps browse-grid app-name wrapping fix.
#
#   pixlet_renderer.py   Real `pixlet schema` extraction instead of a
#                         fragile regex parser that couldn't handle
#                         dynamically-computed dropdown options; a
#                         security check that was blocking legitimate "|"
#                         characters in config values; and a check that a
#                         successful-looking render actually produced a
#                         non-empty file (a 0-byte "success" was
#                         previously indistinguishable from a real one).
#
#   starlark_apps_manager.py (installed as manager.py)
#                         enable_scrolling fix (animations played at a
#                         low, sluggish frame rate without it) and a
#                         display_mode fix (the plugin always showed
#                         whichever installed app was selected first,
#                         regardless of which mode was actually
#                         requested).
#
#   display_controller.py
#                         Multiple on-demand display fixes: a stale
#                         in-memory cache meant mode switches without a
#                         full service restart silently never took
#                         effect; stop requests were never cleared from
#                         cache, causing them to be re-processed on every
#                         single frame forever; restarting while
#                         on-demand mode was active caused every OTHER
#                         plugin to become unavailable until the on-demand
#                         cache was manually cleared; and a `pinned`
#                         request parameter that existed but was never
#                         actually read is now used to restrict on-demand
#                         rotation to just the requested mode, instead of
#                         every mode belonging to the resolved plugin
#                         (needed for plugins like starlark-apps, where
#                         each mode is a completely unrelated app).
#
#   fix-dns-single-request.service
#                         Fixes a real, general Pi networking issue:
#                         glibc's dual A/AAAA DNS lookup was hanging for
#                         ~5 seconds on every external HTTPS request, even
#                         with IPv6 disabled at the kernel level -- this
#                         was causing Starlark apps that call external
#                         APIs (Spotify, PennDOT, etc.) to fail with HTTP
#                         timeouts.
#
# Run this any time a LEDMatrix update wipes these file-based patches, or
# on a fresh install to set everything up in one shot.
#
# Usage: run this script from inside this same directory (patches/) on
# the Pi -- it expects every file above to be present alongside it.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LEDMATRIX_DIR="$HOME/LEDMatrix"

echo "=== Reapplying LEDMatrix file patches ==="

cp "$SCRIPT_DIR/api_v3.py" "$LEDMATRIX_DIR/web_interface/blueprints/api_v3.py"
cp "$SCRIPT_DIR/plugins_manager.js" "$LEDMATRIX_DIR/web_interface/static/v3/plugins_manager.js"
cp "$SCRIPT_DIR/pixlet_renderer.py" "$LEDMATRIX_DIR/plugin-repos/starlark-apps/pixlet_renderer.py"
cp "$SCRIPT_DIR/starlark_apps_manager.py" "$LEDMATRIX_DIR/plugin-repos/starlark-apps/manager.py"
cp "$SCRIPT_DIR/display_controller.py" "$LEDMATRIX_DIR/src/display_controller.py"

echo "Clearing stale __pycache__..."
find "$LEDMATRIX_DIR/plugin-repos/starlark-apps" -iname "__pycache__" -exec rm -rf {} + 2>/dev/null || true

echo ""
echo "=== Installing DNS single-request fix ==="
sudo cp "$SCRIPT_DIR/fix-dns-single-request.service" /etc/systemd/system/fix-dns-single-request.service
sudo systemctl daemon-reload
sudo systemctl enable --now fix-dns-single-request

echo ""
echo "=== Restarting services ==="
sudo systemctl restart ledmatrix-web
sudo systemctl restart ledmatrix

echo ""
echo "=== Done ==="
echo "Verifying key fixes are in place:"
grep -q "memory_ttl=0" "$LEDMATRIX_DIR/src/display_controller.py" && echo "  [ok] on-demand cache staleness fix present" || echo "  [MISSING] on-demand cache staleness fix"
grep -q "if pinned:" "$LEDMATRIX_DIR/src/display_controller.py" && echo "  [ok] on-demand pinned-mode fix present" || echo "  [MISSING] on-demand pinned-mode fix"
grep -q "will resume on plugin" "$LEDMATRIX_DIR/src/display_controller.py" && echo "  [ok] restart-while-on-demand fix present" || echo "  [MISSING] restart-while-on-demand fix"
grep -q "if display_mode and display_mode in self.apps" "$LEDMATRIX_DIR/plugin-repos/starlark-apps/manager.py" && echo "  [ok] starlark manager display_mode fix present" || echo "  [MISSING] starlark manager display_mode fix"
grep -q "options single-request" /etc/resolv.conf && echo "  [ok] DNS fix active in resolv.conf" || echo "  [MISSING] DNS fix not yet in resolv.conf (may need a moment after boot)"
echo ""
echo "Starlark Apps browse/install/config/render, on-demand mode switching"
echo "(including after a restart), and external API calls from Starlark"
echo "apps (Spotify, PennDOT, etc.) should all work correctly now."
