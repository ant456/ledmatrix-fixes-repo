"""
LEDMatrix MQTT Bridge

Lets Home Assistant control the whole LEDMatrix display over MQTT — not
just Starlark apps. Subscribes to one command topic and translates each
message into a call to the same api_v3.py routes the web UI itself
already uses (on-demand display, Starlark render/toggle/config), so this
reuses tested, working code rather than reimplementing any of it.

On startup, this also publishes Home Assistant MQTT Discovery config for
real entities, so you get actual dashboard controls in HA instead of
needing to manually call mqtt.publish every time:

  select.ledmatrix_display_mode — every available mode across all
    installed plugins (read directly from each plugin's manifest.json).
    Picking one force-displays it immediately, same as clicking
    force-display in the web UI.

  button.ledmatrix_stop_display — returns to normal rotation.

  switch.ledmatrix_power — turns the whole display on/off (starts/stops
    the ledmatrix service). Reflects real current state on startup.

  number.ledmatrix_brightness — 0-100 brightness slider. Reflects the
    real current value (read from config.json) on startup.

For anything the dashboard controls don't cover (Starlark-specific
actions, passing duration/pinned to on-demand display, etc.), the raw
JSON command topic below still works exactly as before — the discovery
entities are a convenience layer on top of it, not a replacement.

Publish a JSON payload to the raw command topic to trigger an action:

  Force ANY plugin/mode on-demand (works for anything on the matrix,
  not just Starlark — e.g. weather, nfl_live, clock-simple, etc.):
    {"action": "display", "plugin_id": "ledmatrix-weather", "mode": "weather"}
    {"action": "display", "mode": "nfl_live"}   # plugin_id can be omitted if mode is unique
    Optional: "duration" (seconds), "pinned" (bool, stays until stopped)

  Return to normal rotation:
    {"action": "stop_display"}

  Turn the whole display on/off:
    {"action": "power", "state": "on"}
    {"action": "power", "state": "off"}

  Set brightness (0-100):
    {"action": "brightness", "value": 75}

  Force-render a specific Starlark app:
    {"action": "render", "app_id": "bambuprinterstatus"}

  Enable/disable a specific Starlark app:
    {"action": "toggle", "app_id": "penndot_signs", "enabled": true}

  Update a Starlark app's config values:
    {"action": "config", "app_id": "penndot_signs",
     "config": {"roadway": "I-476 North"}}

Each action publishes a result to a corresponding status topic
(<command_topic>/status) so HA can confirm success/failure if wanted.
"""
import json
import logging
import subprocess
import time
from pathlib import Path

import paho.mqtt.client as mqtt
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ledmatrix-mqtt-bridge")

CONFIG_PATH = Path(__file__).parent / "bridge_config.json"

DISCOVERY_PREFIX = "homeassistant"
DEVICE_INFO = {
    "identifiers": ["ledmatrix_bridge"],
    "name": "LEDMatrix",
    "manufacturer": "Custom",
    "model": "LEDMatrix Display",
}


def load_config():
    if not CONFIG_PATH.exists():
        logger.error(f"Missing config file: {CONFIG_PATH}")
        logger.error("Copy bridge_config.example.json to bridge_config.json and fill in your MQTT credentials.")
        raise SystemExit(1)
    with open(CONFIG_PATH) as f:
        return json.load(f)


def _humanize(mode: str) -> str:
    """Turn a raw mode string like 'ncaa_fb_live' or 'clock-simple' into
    something readable like 'Ncaa Fb Live' / 'Clock Simple'. Not
    acronym-aware (won't capitalize "NCAA" correctly), but good enough
    for a dropdown without needing a per-mode name source, which doesn't
    exist for regular plugin modes the way it does for Starlark apps."""
    return mode.replace("_", " ").replace("-", " ").title()


def fetch_available_modes(ledmatrix_home: Path) -> dict:
    """Every display_mode across all installed, enabled plugins, mapped
    to its owning plugin_id and a human-readable display name -- read
    directly from each plugin's own manifest.json (the same source
    display_controller itself uses), since /api/v3/plugins/installed
    turned out not to carry mode info at all despite looking like it
    should (confirmed on real hardware, 2026-09-02 -- that endpoint's
    plugin entries have version/author/category metadata, no
    display_modes key whatsoever).

    Returns {mode: {"plugin_id": ..., "display_name": ...}}. plugin_id
    matters specifically for Starlark apps: each installed app is its
    own dynamic mode (the app_id itself), not something listed in a
    static manifest.json display_modes array, and confirmed on real
    hardware (2026-09-04) that the API's own find_plugin_for_mode()
    lookup -- used whenever plugin_id is omitted -- has no idea these
    modes exist at all and 404s on every single one. Knowing each
    mode's plugin_id up front lets us pass it explicitly and skip that
    broken lookup entirely, rather than only working for modes whose
    plugin happens to be inferable from a static manifest.

    display_name uses each Starlark app's own real "name" field (e.g.
    "Bambu Printer Status") where available, since that's genuinely more
    readable than the raw app_id -- everything else falls back to a
    humanized version of the raw mode string.
    """
    modes = {}
    config_path = ledmatrix_home / "config" / "config.json"
    plugin_repos_dir = ledmatrix_home / "plugin-repos"

    try:
        with open(config_path) as f:
            full_config = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.error(f"Could not read config.json: {e}")
        full_config = {}

    if plugin_repos_dir.is_dir():
        for plugin_dir in plugin_repos_dir.iterdir():
            manifest_path = plugin_dir / "manifest.json"
            if not manifest_path.is_file():
                continue
            try:
                with open(manifest_path) as f:
                    manifest = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue

            plugin_id = plugin_dir.name
            plugin_config = full_config.get(plugin_id, {})
            if plugin_config.get("enabled") is False:
                continue

            plugin_display_modes = manifest.get("display_modes") or []
            plugin_name = manifest.get("name") or _humanize(plugin_id)
            for m in plugin_display_modes:
                if len(plugin_display_modes) == 1:
                    # Single-mode plugin: the plugin's own real name is
                    # already the right display name (e.g. "Weather
                    # Display" for a plugin with just one mode).
                    display_name = plugin_name
                else:
                    # Multi-mode plugin (e.g. ledmatrix-weather has
                    # weather/hourly_forecast/daily_forecast/almanac/
                    # radar): no per-mode name exists in the manifest,
                    # so combine the plugin's real name with a humanized
                    # version of the specific mode to keep them
                    # distinguishable while still using the real name as
                    # a base, e.g. "Weather Display - Almanac".
                    display_name = f"{plugin_name} - {_humanize(m)}"
                modes[m] = {"plugin_id": plugin_id, "display_name": display_name}

    # starlark-apps: each enabled sub-app is its own mode, tracked in a
    # separate manifest.json under the starlark-apps data directory --
    # explicitly mapped to the "starlark-apps" plugin_id itself, since
    # that's what actually owns these modes at runtime. Uses each app's
    # own real "name" field (e.g. "Bambu Printer Status") rather than
    # humanizing the app_id, since these apps already have good, proper
    # display names on hand.
    starlark_manifest_path = ledmatrix_home / "starlark-apps" / "manifest.json"
    try:
        with open(starlark_manifest_path) as f:
            starlark_manifest = json.load(f)
        for app_id, info in starlark_manifest.get("apps", {}).items():
            if info.get("enabled"):
                modes[app_id] = {
                    "plugin_id": "starlark-apps",
                    "display_name": info.get("name") or _humanize(app_id),
                }
    except (OSError, json.JSONDecodeError):
        pass

    return modes


def get_current_brightness(ledmatrix_home: Path):
    """Reads the current brightness value straight from config.json, so
    the HA number entity can show the real current value on startup
    instead of defaulting to unknown."""
    try:
        with open(ledmatrix_home / "config" / "config.json") as f:
            cfg = json.load(f)
        return cfg.get("display", {}).get("hardware", {}).get("brightness")
    except (OSError, json.JSONDecodeError, KeyError):
        return None


def get_power_state() -> str:
    """ON if the ledmatrix display service is actively running, else OFF.
    Checked directly via systemctl rather than an API call, since the
    bridge runs on the same Pi and this is the simplest, most reliable
    source of truth."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "ledmatrix"],
            capture_output=True, text=True, timeout=10,
        )
        return "ON" if result.stdout.strip() == "active" else "OFF"
    except Exception as e:
        logger.error(f"Could not check ledmatrix service state: {e}")
        return "OFF"


def get_current_mode(api_base: str):
    """The mode currently actually showing on the display, straight from
    the same route the web UI's System Logs page uses. Used to publish a
    real initial state for the select entity on startup/reconnect, since
    without this it has no way to recover from "unavailable" on its own
    -- its state was only ever set after a successful user-initiated
    command, never on startup, confirmed on real hardware (2026-09-05) to
    leave it stuck unavailable indefinitely after any bridge restart."""
    try:
        resp = requests.get(f"{api_base}/api/v3/display/current-status", timeout=10)
        resp.raise_for_status()
        return resp.json().get("data", {}).get("mode")
    except requests.RequestException as e:
        logger.error(f"Could not fetch current mode: {e}")
        return None


def publish_discovery(client: mqtt.Client, modes: dict) -> dict:
    """Registers the select (mode dropdown) and button (stop) entities
    with HA via MQTT Discovery. HA auto-creates real entities from these
    retained config messages — nothing needs configuring on the HA side
    beyond having the MQTT integration set up at all.

    Returns a {display_name: mode} reverse map, since the dropdown's
    options are display names but the API needs the raw mode string —
    the caller needs this to translate a selection back. If two modes
    happen to humanize/name to the same display string, the second one
    gets its raw mode id appended in parentheses to keep every option
    distinct and unambiguously reversible.
    """
    display_to_mode = {}
    for mode, info in sorted(modes.items(), key=lambda kv: kv[1]["display_name"]):
        name = info["display_name"]
        if name in display_to_mode:
            name = f"{name} ({mode})"
        display_to_mode[name] = mode

    display_names = list(display_to_mode.keys())
    select_config = {
        "name": "LEDMatrix Display Mode",
        "unique_id": "ledmatrix_display_mode",
        "command_topic": "ledmatrix/select/display_mode/set",
        "state_topic": "ledmatrix/select/display_mode/state",
        "options": display_names if display_names else ["(no modes found)"],
        "icon": "mdi:led-strip-variant",
        "device": DEVICE_INFO,
    }
    client.publish(
        f"{DISCOVERY_PREFIX}/select/ledmatrix/display_mode/config",
        json.dumps(select_config), retain=True,
    )

    button_config = {
        "name": "LEDMatrix Stop On-Demand",
        "unique_id": "ledmatrix_stop_display",
        "command_topic": "ledmatrix/button/stop_display/press",
        "icon": "mdi:stop-circle-outline",
        "device": DEVICE_INFO,
    }
    client.publish(
        f"{DISCOVERY_PREFIX}/button/ledmatrix/stop_display/config",
        json.dumps(button_config), retain=True,
    )

    power_config = {
        "name": "LEDMatrix Power",
        "unique_id": "ledmatrix_power",
        "command_topic": "ledmatrix/switch/power/set",
        "state_topic": "ledmatrix/switch/power/state",
        "payload_on": "ON",
        "payload_off": "OFF",
        "icon": "mdi:led-strip-variant",
        "device": DEVICE_INFO,
    }
    client.publish(
        f"{DISCOVERY_PREFIX}/switch/ledmatrix/power/config",
        json.dumps(power_config), retain=True,
    )

    brightness_config = {
        "name": "LEDMatrix Brightness",
        "unique_id": "ledmatrix_brightness",
        "command_topic": "ledmatrix/number/brightness/set",
        "state_topic": "ledmatrix/number/brightness/state",
        "min": 0,
        "max": 100,
        "step": 1,
        "icon": "mdi:brightness-6",
        "device": DEVICE_INFO,
    }
    client.publish(
        f"{DISCOVERY_PREFIX}/number/ledmatrix/brightness/config",
        json.dumps(brightness_config), retain=True,
    )

    logger.info(f"Published MQTT Discovery config — {len(modes)} modes available in the dropdown")
    return display_to_mode


def handle_command(api_base: str, payload: dict) -> dict:
    action = payload.get("action")

    if not action:
        return {"status": "error", "message": "'action' is required"}

    try:
        if action == "display":
            plugin_id = payload.get("plugin_id")
            mode = payload.get("mode")
            if not plugin_id and not mode:
                return {"status": "error", "message": "'plugin_id' or 'mode' is required for display"}
            body = {}
            if plugin_id:
                body["plugin_id"] = plugin_id
            if mode:
                body["mode"] = mode
            if "duration" in payload:
                body["duration"] = payload["duration"]
            if "pinned" in payload:
                body["pinned"] = payload["pinned"]
            body["start_service"] = payload.get("start_service", False)
            resp = requests.post(f"{api_base}/api/v3/display/on-demand/start", json=body, timeout=45)

        elif action == "stop_display":
            resp = requests.post(f"{api_base}/api/v3/display/on-demand/stop", json={}, timeout=15)

        elif action == "power":
            state = str(payload.get("state", "")).lower()
            if state not in ("on", "off"):
                return {"status": "error", "message": "'state' must be 'on' or 'off'"}
            sys_action = "start_display" if state == "on" else "stop_display"
            resp = requests.post(f"{api_base}/api/v3/system/action", json={"action": sys_action}, timeout=15)

        elif action == "brightness":
            value = payload.get("value")
            if value is None:
                return {"status": "error", "message": "'value' (0-100) is required for brightness"}
            try:
                value = int(value)
            except (ValueError, TypeError):
                return {"status": "error", "message": "'value' must be an integer"}
            if not 0 <= value <= 100:
                return {"status": "error", "message": "'value' must be between 0 and 100"}
            resp = requests.post(f"{api_base}/api/v3/config/main", json={"brightness": value}, timeout=15)

        elif action == "render":
            app_id = payload.get("app_id")
            if not app_id:
                return {"status": "error", "message": "'app_id' is required for render"}
            resp = requests.post(f"{api_base}/api/v3/starlark/apps/{app_id}/render", timeout=30)

        elif action == "toggle":
            app_id = payload.get("app_id")
            enabled = payload.get("enabled")
            if not app_id:
                return {"status": "error", "message": "'app_id' is required for toggle"}
            if enabled is None:
                return {"status": "error", "message": "'enabled' (true/false) is required for toggle"}
            resp = requests.post(
                f"{api_base}/api/v3/starlark/apps/{app_id}/toggle",
                json={"enabled": bool(enabled)}, timeout=15,
            )

        elif action == "config":
            app_id = payload.get("app_id")
            config = payload.get("config")
            if not app_id:
                return {"status": "error", "message": "'app_id' is required for config"}
            if not isinstance(config, dict) or not config:
                return {"status": "error", "message": "'config' must be a non-empty object"}
            resp = requests.put(
                f"{api_base}/api/v3/starlark/apps/{app_id}/config",
                json=config, timeout=15,
            )

        else:
            return {"status": "error", "message": f"Unknown action: {action}"}

        try:
            body = resp.json()
        except ValueError:
            body = {"raw": resp.text}
        return {"status": "success" if resp.ok else "error", "http_status": resp.status_code, "response": body}

    except requests.RequestException as e:
        return {"status": "error", "message": f"Request to LEDMatrix API failed: {e}"}


def main():
    cfg = load_config()
    command_topic = cfg.get("mqtt_topic", "ledmatrix/command")
    status_topic = f"{command_topic}/status"
    api_base = cfg.get("ledmatrix_api_base", "http://localhost:5000")
    ledmatrix_home = Path(cfg.get("ledmatrix_home", str(Path.home() / "LEDMatrix")))

    select_command_topic = "ledmatrix/select/display_mode/set"
    select_state_topic = "ledmatrix/select/display_mode/state"
    button_command_topic = "ledmatrix/button/stop_display/press"
    power_command_topic = "ledmatrix/switch/power/set"
    power_state_topic = "ledmatrix/switch/power/state"
    brightness_command_topic = "ledmatrix/number/brightness/set"
    brightness_state_topic = "ledmatrix/number/brightness/state"

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id=cfg.get("mqtt_client_id", "ledmatrix-mqtt-bridge"))
    if cfg.get("mqtt_username"):
        client.username_pw_set(cfg["mqtt_username"], cfg.get("mqtt_password", ""))

    # Shared with on_message via closure: mode_plugin_map looks up each
    # mode's correct plugin_id (needed because the API's own
    # find_plugin_for_mode() 404s on every Starlark app mode), and
    # display_to_mode translates a selected display name back to its
    # raw mode string, since the dropdown shows names but the API needs
    # the raw mode.
    mode_plugin_map = {}
    display_to_mode = {}

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            logger.info("Connected to MQTT broker, subscribing to command topics")

            # Warm up the API's plugin discovery -- confirmed in
            # web_interface/app.py's own comment (2026-09-05) that
            # discover_plugins() is deliberately never called at web
            # service startup, only lazily by whichever endpoint needs
            # it first (normally triggered by a human opening the
            # dashboard). Since this bridge only ever calls
            # /api/v3/display/on-demand/start directly and never visits
            # the dashboard, every on-demand request would 404 with
            # "Mode/Plugin X not found" after any ledmatrix-web restart
            # until something else happened to trigger discovery. This
            # call does that ourselves, so it's never dependent on
            # someone coincidentally opening a browser first.
            try:
                requests.get(f"{api_base}/api/v3/plugins/installed", timeout=15)
                logger.info("Warmed up plugin discovery")
            except requests.RequestException as e:
                logger.warning(f"Could not warm up plugin discovery (will likely need a browser visit to /: {e}")

            client.subscribe(command_topic)
            client.subscribe(select_command_topic)
            client.subscribe(button_command_topic)
            client.subscribe(power_command_topic)
            client.subscribe(brightness_command_topic)
            modes = fetch_available_modes(ledmatrix_home)
            mode_plugin_map.clear()
            mode_plugin_map.update({m: info["plugin_id"] for m, info in modes.items()})
            display_to_mode.clear()
            display_to_mode.update(publish_discovery(client, modes))

            # Publish real current state so HA doesn't show "unavailable"
            # until the next time something changes these from the HA
            # side -- the select entity especially, which otherwise has
            # no way to recover on its own after a bridge restart.
            client.publish(power_state_topic, get_power_state(), retain=True)
            current_brightness = get_current_brightness(ledmatrix_home)
            if current_brightness is not None:
                client.publish(brightness_state_topic, str(current_brightness), retain=True)
            current_mode = get_current_mode(api_base)
            if current_mode:
                mode_to_display = {m: name for name, m in display_to_mode.items()}
                current_display_name = mode_to_display.get(current_mode, current_mode)
                client.publish(select_state_topic, current_display_name, retain=True)
        else:
            logger.error(f"MQTT connection failed with code {rc}")

    def on_message(client, userdata, msg):
        logger.info(f"Received on {msg.topic}: {msg.payload}")

        if msg.topic == select_command_topic:
            selected_name = msg.payload.decode("utf-8").strip()
            mode = display_to_mode.get(selected_name, selected_name)
            # Only pass plugin_id explicitly for Starlark modes -- confirmed
            # on real hardware (2026-09-04) two contradictory things:
            # (1) the API's find_plugin_for_mode() (used whenever plugin_id
            # is omitted) has no idea Starlark app modes exist at all and
            # 404s on every one, so those need plugin_id sent explicitly;
            # (2) sending plugin_id for *regular* plugins (built from their
            # folder name on disk) breaks them with "Plugin X not found" --
            # apparently plugin_manager's internal registry doesn't use
            # that same naming for every plugin, even though mode-only
            # lookup resolves them correctly on its own. So: explicit
            # plugin_id only for the one case it's actually needed for.
            display_payload = {"action": "display", "mode": mode}
            plugin_id = mode_plugin_map.get(mode)
            if plugin_id == "starlark-apps":
                display_payload["plugin_id"] = plugin_id
                # Without this, picking one Starlark app rotates through
                # every other installed Starlark app too, since the API's
                # on-demand activation defaults to showing every mode that
                # belongs to the resolved plugin -- fine for something like
                # football-scoreboard's related live/recent/upcoming views,
                # wrong for Starlark apps, where each mode is a completely
                # separate, unrelated app.
                display_payload["pinned"] = True
            result = handle_command(api_base, display_payload)
            logger.info(f"Result: {result}")
            if result.get("status") == "success":
                client.publish(select_state_topic, selected_name, retain=True)
            client.publish(status_topic, json.dumps(result))
            return

        if msg.topic == button_command_topic:
            result = handle_command(api_base, {"action": "stop_display"})
            logger.info(f"Result: {result}")
            client.publish(status_topic, json.dumps(result))
            return

        if msg.topic == power_command_topic:
            state = msg.payload.decode("utf-8").strip()
            result = handle_command(api_base, {"action": "power", "state": state})
            logger.info(f"Result: {result}")
            if result.get("status") == "success":
                client.publish(power_state_topic, state.upper(), retain=True)
            client.publish(status_topic, json.dumps(result))
            return

        if msg.topic == brightness_command_topic:
            try:
                value = int(msg.payload.decode("utf-8").strip())
            except ValueError:
                logger.error(f"Invalid brightness payload: {msg.payload}")
                return
            result = handle_command(api_base, {"action": "brightness", "value": value})
            logger.info(f"Result: {result}")
            if result.get("status") == "success":
                client.publish(brightness_state_topic, str(value), retain=True)
            client.publish(status_topic, json.dumps(result))
            return

        # Raw JSON command topic — advanced/scripted use
        try:
            payload = json.loads(msg.payload)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON payload: {e}")
            client.publish(status_topic, json.dumps({"status": "error", "message": "Invalid JSON"}))
            return

        result = handle_command(api_base, payload)
        logger.info(f"Result: {result}")
        client.publish(status_topic, json.dumps(result))

    client.on_connect = on_connect
    client.on_message = on_message

    while True:
        try:
            client.connect(cfg["mqtt_host"], cfg.get("mqtt_port", 1883), 60)
            client.loop_forever()
        except Exception as e:
            logger.error(f"MQTT connection error, retrying in 10s: {e}")
            time.sleep(10)


if __name__ == "__main__":
    main()
