# ledmatrix-fixes

A collection of patches and a Home Assistant MQTT bridge for [ChuckBuilds/LEDMatrix](https://github.com/ChuckBuilds/LEDMatrix), an open-source RGB LED matrix display controller for Raspberry Pi. Built while running a matrix driven heavily by Starlark (Pixlet/Tronbyt) apps and controlled externally via MQTT for an extended period — the patches here fix real bugs found in that process, and the bridge is what actually exposes control to Home Assistant.

## What's in here

- **[`patches/`](patches)** — File-based fixes to several LEDMatrix core files: broken Starlark app schema extraction, on-demand mode switching that silently stopped working without a full restart, a plugin that always showed the same app regardless of which mode was requested, and a Raspberry Pi DNS resolver quirk that broke any Starlark app calling an external API. See [`patches/README.md`](patches/README.md) for the full list with explanations.

- **[`mqtt-bridge/`](mqtt-bridge)** — A standalone service that lets Home Assistant control the display over MQTT: force any mode on demand, adjust brightness, toggle power, and manage installed Starlark apps, all as real HA entities via MQTT Discovery. See [`mqtt-bridge/README.md`](mqtt-bridge/README.md) for setup and usage.

- **[`pixlet-editor/`](pixlet-editor)** — A small standalone web page for editing any installed Starlark app's config through Pixlet's own real config UI (working cascading dropdowns, live-fetched option lists) instead of the LEDMatrix web UI's own, more limited config form. See [`pixlet-editor/README.md`](pixlet-editor/README.md).

The bridge depends on the patches being applied — several of the on-demand mode-switching fixes in `patches/` are what make MQTT-driven control actually reliable in the first place. `pixlet-editor` is independent of both.

## Quick start

```bash
git clone https://github.com/ant456/ledmatrix-fixes.git
cd ledmatrix-fixes

# Apply the core file patches
cd patches
chmod +x install_all_patches.sh
./install_all_patches.sh

# Set up the MQTT bridge
cd ../mqtt-bridge
cp bridge_config.example.json bridge_config.json
# edit bridge_config.json with your MQTT broker details
sudo cp starlark-mqtt-bridge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now starlark-mqtt-bridge
```

## Why this exists

LEDMatrix's own update mechanism overwrites core files back to their upstream versions, so any direct edit gets silently reverted the next time an update runs. Keeping the fixes as a small, re-runnable install script (rather than a one-time manual edit) means recovering from that is a single command instead of re-diagnosing the same bugs again.

## License

MIT — see [LICENSE](LICENSE).
