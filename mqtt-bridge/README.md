# ledmatrix-mqtt-bridge

Control a [ChuckBuilds/LEDMatrix](https://github.com/ChuckBuilds/LEDMatrix) display from Home Assistant over MQTT — force any plugin/mode on demand, toggle power, adjust brightness, and manage installed Starlark (Pixlet) apps, all from HA dashboards and automations.

This is a small bridge service: it subscribes to MQTT topics and translates messages into calls against LEDMatrix's own web API (`api_v3.py`) — the exact same routes the LEDMatrix web UI itself uses. It doesn't reimplement any display logic; it just gives Home Assistant a way to drive what's already there. It relies on the fixes in [`../patches`](../patches) actually being applied — without them, on-demand mode switching won't reliably work.

## What you get

On startup, this publishes [Home Assistant MQTT Discovery](https://www.home-assistant.io/integrations/mqtt/#mqtt-discovery) config, so these show up automatically as real entities — no manual HA configuration needed beyond having the MQTT integration set up:

- **`select.ledmatrix_display_mode`** — dropdown of every available mode across all installed, enabled plugins. Picking one force-displays it immediately. Reflects the real current mode on startup/reconnect, not just "unknown" until the next change.
- **`button.ledmatrix_stop_display`** — returns to normal rotation.
- **`switch.ledmatrix_power`** — turns the whole display on/off (starts/stops the `ledmatrix` service). Reflects real current state on startup.
- **`number.ledmatrix_brightness`** — 0–100 brightness slider, reflecting the real current value from `config.json`.

For anything the dashboard entities don't cover, publish raw JSON to the main command topic:

```jsonc
// Force any plugin/mode on demand
{"action": "display", "plugin_id": "ledmatrix-weather", "mode": "weather"}
{"action": "display", "mode": "nfl_live"}   // plugin_id can be omitted if mode is unique
// optional: "duration" (seconds), "pinned" (bool -- restricts on-demand
// rotation to just this one mode instead of every mode belonging to the
// resolved plugin; the bridge already sends this automatically for
// Starlark app modes, since each one is a separate, unrelated app)

// Return to normal rotation
{"action": "stop_display"}

// Power
{"action": "power", "state": "on"}
{"action": "power", "state": "off"}

// Brightness (0-100)
{"action": "brightness", "value": 75}

// Starlark apps
{"action": "render", "app_id": "bambuprinterstatus"}
{"action": "toggle", "app_id": "penndot_signs", "enabled": true}
{"action": "config", "app_id": "penndot_signs", "config": {"roadway": "I-476 North"}}
```

Each command publishes a result to `<command_topic>/status` for confirmation.

## Requirements

- A running [LEDMatrix](https://github.com/ChuckBuilds/LEDMatrix) install, with the patches in [`../patches`](../patches) applied, and its web UI reachable (default `http://localhost:5000`)
- An MQTT broker Home Assistant is also connected to
- Python 3 with `paho-mqtt` (2.x) and `requests`

## Setup

```bash
cd mqtt-bridge
pip install paho-mqtt requests --break-system-packages   # if needed on your system
cp bridge_config.example.json bridge_config.json
```

Edit `bridge_config.json` with your actual MQTT broker details:

```json
{
  "mqtt_host": "192.168.1.10",
  "mqtt_port": 1883,
  "mqtt_username": "your_mqtt_username",
  "mqtt_password": "your_mqtt_password",
  "mqtt_client_id": "ledmatrix-mqtt-bridge",
  "mqtt_topic": "ledmatrix/command",
  "ledmatrix_api_base": "http://localhost:5000",
  "ledmatrix_home": "/home/pi/LEDMatrix"
}
```

`bridge_config.json` is gitignored on purpose — never commit your real credentials.

Run it directly to test:

```bash
python3 starlark_mqtt_bridge.py
```

Or install as a systemd service (recommended for actual use):

```bash
sudo cp starlark-mqtt-bridge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now starlark-mqtt-bridge
sudo systemctl status starlark-mqtt-bridge
```

Adjust the `User`, `WorkingDirectory`, and `ExecStart` paths in the `.service` file first if your install lives somewhere other than `/home/pi/ledmatrix-mqtt-bridge`.

## How it finds available modes

Rather than calling a LEDMatrix API endpoint (none exposes this cleanly — the closest one, `/plugins/installed`, carries version/author/category metadata but no mode info at all), the bridge reads each installed plugin's `manifest.json` directly under `<ledmatrix_home>/plugin-repos/*/manifest.json`, combined with `config.json` to filter out disabled plugins. Starlark apps are handled separately, since each installed app is its own dynamic mode tracked in `<ledmatrix_home>/starlark-apps/manifest.json` rather than a static plugin manifest.

Display names use each plugin's real `name` field from its manifest where possible (falling back to a humanized version of the raw mode string for multi-mode plugins, since there's no per-mode name field), and each Starlark app's own real `name` (e.g. "Bambu Printer Status" instead of the raw `bambuprinterstatus` app ID).

## A note on plugin_id

The LEDMatrix API's own `find_plugin_for_mode()` lookup (used whenever `plugin_id` is omitted) has no knowledge of Starlark app modes at all — they're generated dynamically, not listed in any static manifest it scans — so it 404s on every one. The bridge works around this by sending `plugin_id: "starlark-apps"` explicitly for those modes specifically. Sending `plugin_id` for *regular* plugins was tested and found to break them instead (their internal registry doesn't always match the plugin's folder name on disk) — so this is deliberately scoped to just the one case it's actually needed for.

On startup and every reconnect, the bridge also calls `/api/v3/plugins/installed` once purely to trigger the API's plugin discovery — that discovery is lazy by design (only triggered by whichever endpoint needs it first, normally a human opening the web UI dashboard), so without this warm-up call, every on-demand request from a bridge that never visits the dashboard would 404 until something else happened to trigger discovery first.

## Notes / limitations

- Only one thing can be "on-demand" at a time — same constraint the LEDMatrix web UI itself has.
- Brightness and power cover the two settings most people would realistically want on a day-to-day HA dashboard. LEDMatrix's `config.json` has many more hardware-level fields (PWM bits, scan mode, orientation, etc.) that could technically be exposed the same way, but those are typically one-time setup values rather than things worth a live dashboard control.
- This was built and tested against one specific LEDMatrix install; API route shapes could differ across versions. If something 404s, check your LEDMatrix version's actual `api_v3.py` routes.
