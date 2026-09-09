# LEDMatrix patches

**Updated Sep 2026:** ChuckBuilds/LEDMatrix upstream has since fixed most of
what used to live in this repo. Confirmed already merged into `main`:

- On-demand mode surviving a `ledmatrix` service restart (only the on-demand
  plugin's modes loading instead of all enabled plugins) — fixed via
  `_select_startup_plugins()` in `display_controller.py`.
- The `pinned` on-demand API parameter now has real effect.
- 0-byte Pixlet renders are now detected and reported as failures.
- Lazy plugin discovery — `/api/v3/plugins/installed` now calls
  `discover_plugins()` itself, so an MQTT bridge or other external caller no
  longer needs to "warm up" discovery by hitting the web UI first.
- `enable_scrolling = True` is now set on the Starlark Apps plugin, so
  multi-frame `.star` apps animate correctly instead of showing one frame.

**Still needed** — not yet merged upstream as of this writing:

- **`render_width` / `render_height`** — lets a `.star` app declare a native
  render size different from Pixlet's 64×32 default (e.g. an imported Glance
  app whose own canvas is 128 wide). Without this, Pixlet always renders at
  its default and any app with a genuinely different native size gets half
  its content silently clipped before magnification ever runs. Patches
  `pixlet_renderer.py` (adds `width`/`height` params to `render()`, passed
  through as Pixlet's own `-w`/`-t` flags when set) and `starlark_apps_manager.py`
  / `manager.py` (reads `render_width`/`render_height` from an app's own
  `config.json` and passes them through).

## Install

```bash
git clone https://github.com/ant456/ledmatrix-fixes-repo.git
cd ledmatrix-fixes-repo/patches
./install_all_patches.sh
```

The script will:
1. Auto-install the base `starlark-apps` plugin from
   `ChuckBuilds/LEDMatrix` if it isn't present yet.
2. Auto-install the `pixlet` binary from the latest `tronbyt/pixlet` release
   if it isn't on `PATH` yet (arm64/amd64 only — 32-bit Pis need to build
   from source).
3. Apply the `render_width`/`render_height` patch and restart the
   `ledmatrix` and `ledmatrix-web` services.

An app opts into this by adding to its own `config.json`, e.g.:

```json
{"render_width": 128, "render_height": 32, "magnify": 1}
```

Apps that don't set these keys are completely unaffected — behavior is
identical to stock LEDMatrix.
