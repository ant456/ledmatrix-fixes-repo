# LEDMatrix Patches

File-based patches for [ChuckBuilds/LEDMatrix](https://github.com/ChuckBuilds/LEDMatrix), fixing several real bugs found while running Starlark (Pixlet/Tronbyt) apps and MQTT-driven on-demand mode switching for an extended period.

These are **file replacements**, not a diff/patch in the traditional sense — LEDMatrix updates (via its own update mechanism) will overwrite these files back to their original, unpatched versions, so `install_all_patches.sh` is designed to be safely re-run any time that happens.

## What's fixed

- **`api_v3.py`** — Starlark Apps backend routes. The Starlark Apps feature ships frontend-only upstream (as of this writing) with no backend routes at all, so the web UI's browse/install/config/schema actions 404 without this.
- **`plugins_manager.js`** — Long Starlark app names overflow their card in the browse grid without word-wrapping.
- **`pixlet_renderer.py`** — Three separate fixes:
  - The original schema extractor uses regex to parse `.star` source directly, which can only ever handle static, inline option lists. It has no way to resolve a `get_schema()` that computes its options dynamically at runtime (e.g. an app that fetches a live list from an external API inside `get_schema()` itself). Replaced with an actual `pixlet schema` subprocess call, which properly executes the script.
  - A security check meant to block shell-injection characters was blocking the literal `|` character in config values — but `subprocess.run()` is called with a list and no `shell=True`, so no shell ever actually interprets these characters in the first place. This broke at least one real app (`penndot_signs.star`) whose own config values legitimately use `|` as a separator.
  - A "successful" render was only checked for file *existence*, not that it actually contained anything — a 0-byte output file was reported as success, silently breaking any app that produced one (confirmed with an app whose config disabled its content under certain states, producing an empty render that looked identical to success).
- **`starlark_apps_manager.py`** (installed as the plugin's own `manager.py`) — Two fixes:
  - `enable_scrolling` was never set at all, meaning the display controller called `display()` at a low, non-animated cadence regardless of an app's actual frame timing.
  - `display()` never actually read the `display_mode` parameter passed to it — it always showed whichever installed app happened to be selected first, regardless of which mode the framework actually requested.
- **`display_controller.py`** — The most involved set of fixes, all related to on-demand mode switching (used by both the web UI's "force display" buttons and anything driving it externally, like MQTT):
  - The on-demand request cache was read with a default in-memory TTL, meaning the *first* read after a process starts gets cached in memory for up to an hour — every subsequent poll (every single frame) just returned that same stale snapshot instead of ever re-checking disk for a different process's write. This made switching modes without a full service restart silently never take effect at all.
  - Stop requests were deliberately always re-processed (to allow repeated stop clicks), but the request was never cleared from cache afterward — combined with the fix above, this caused the exact same stop request to be re-read and re-processed on *every single frame, forever*, which is both a log-spam and a real performance problem.
  - If the service restarted while on-demand mode was still active, startup logic would load *only* the on-demand plugin, leaving every other plugin completely unavailable until the on-demand cache was manually cleared. Now every normally-enabled plugin loads as usual regardless of on-demand state; the on-demand mode itself still correctly resumes on restart.
  - A `pinned` request parameter existed in the API but was never actually read anywhere. It's now used to restrict on-demand rotation to just the specifically-requested mode, instead of every mode belonging to the resolved plugin — needed for plugins like Starlark Apps, where each mode is a completely unrelated app (a printer status display vs. an aquarium animation vs. a music widget), not related views of the same content the way a sports plugin's live/recent/upcoming modes are.
- **`fix-dns-single-request.service`** — Not a LEDMatrix bug at all, but a real Raspberry Pi OS networking issue that broke multiple Starlark apps that call external APIs. glibc's `getaddrinfo()` does a dual A/AAAA DNS lookup by default; on this network, the AAAA half was hanging for ~5 seconds before falling back, even with IPv6 fully disabled at the kernel level (`net.ipv6.conf.all.disable_ipv6=1`) — disabling the interface didn't stop the resolver from attempting and waiting on the query. `options single-request` in `resolv.conf` fixes this at the resolver level; this systemd unit re-applies it on every boot, since NetworkManager/netplan otherwise regenerate `resolv.conf` and silently drop it.

## Installation

```bash
git clone https://github.com/<your-username>/ledmatrix-fixes.git
cd ledmatrix-fixes/patches
chmod +x install_all_patches.sh
./install_all_patches.sh
```

Re-run the same command any time a LEDMatrix update wipes these files. The script prints a verification summary at the end confirming each fix actually landed.

## Caveats

These were written and tested against one specific LEDMatrix install at a specific point in time. Upstream file paths, route names, or internal APIs may have changed since — if a patch fails to apply cleanly, check the current version of the corresponding upstream file before assuming the fix itself is wrong.
