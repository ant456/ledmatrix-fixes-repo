# Pixlet Config Editor

A small, standalone Flask web page for editing any installed Starlark app's configuration through Pixlet's own real config UI — the one with working cascading dropdowns, live-fetched option lists, etc. — instead of hand-editing `config.json` or dealing with the LEDMatrix web UI's own config form (which is built from a schema extractor that has its own limitations, see [`../patches/README.md`](../patches/README.md)).

This is a companion tool, separate from both `patches/` and `mqtt-bridge/` — it doesn't require either, though the schema-extraction fix in `patches/` fixes a related but different problem (the LEDMatrix web UI's own config forms), while this tool sidesteps that entirely by using Pixlet's real, built-in config server instead.

## Why this exists

Some Starlark apps have config fields whose valid options can only be determined by actually running the app's `get_schema()` function — for example, an app that fetches a live, current list of choices from an external API. Pixlet's own `pixlet serve` command runs a real local web server that does exactly this correctly, with real cascading dropdowns (pick one field, a second field's options update based on that choice) and live data. This tool is just a thin wrapper: it finds the right `.star` file for whichever app you pick, launches `pixlet serve` pointed at it with `--saveconfig` writing directly to the app's real config file, and stops the display service while you're editing (to avoid it reading `config.json` mid-write) — restarting it automatically the moment you close the editor.

## Setup

```bash
cd pixlet-editor
python3 -c "import flask; print('Flask OK')"   # confirm Flask is available; install if needed
```

Edit the paths in `app.py` if your LEDMatrix install isn't at the default `~/LEDMatrix`, then install as a systemd service:

```bash
mkdir -p ~/pixlet-editor-app
cp app.py ~/pixlet-editor-app/
sudo cp pixlet-editor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pixlet-editor
```

Adjust the `WorkingDirectory`/`ExecStart` paths in the `.service` file first if you're not using `~/pixlet-editor-app`.

## Usage

Visit `http://<your-pi>:5050/` from any browser on your network. Every installed Starlark app is listed with an **Edit Config** button. Clicking one:

1. Backs up the app's existing config to `config.json.backup`
2. Stops the LEDMatrix display service
3. Launches `pixlet serve` for that specific app, saving live to its real config as you make changes
4. Shows a link to the actual editor, running on port 8080

Click **Stop Editing & Restart Display** when you're done — this kills the `pixlet serve` process and restarts the display service so your changes take effect immediately.

## Limitations

- Only one editing session can run at a time (both this tool and `pixlet serve` itself are single-instance).
- If this Flask process itself restarts while a session is active (rare, but possible), the in-memory session tracking is lost — use the **Force Cleanup / Restart Display** button on the home page to recover (it force-restarts the display service regardless of what this process currently thinks is running).
- Built and tested against one specific LEDMatrix install; hasn't been exercised outside that environment.
