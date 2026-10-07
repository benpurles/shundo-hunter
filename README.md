# Shundo Hunter

Personal macOS app for collecting 100-IV Pokémon sightings, managing a hunt
queue, and coordinating a paired iPhone. Includes a Swift/AppKit shell, Python
local service, web interface, Chrome relay, phone controller integration,
Catch Lab, and overnight monitoring.

This repository preserves the source behind the installed **Shundo Hunter.app**
as of October 7, 2026. It includes native sources and tests that are absent from
the installed bundle. Local databases, credentials, pairing records, signed
iOS apps, provisioning profiles, and generated binaries are excluded.

## Quick start: local feed and browser UI

Use Python 3.10 or newer (verified here with Python 3.14.6). The feed and core
unit tests use the Python standard library; there is no Python package install
step for this mode.

```sh
git clone https://github.com/benpurles/shundo-hunter.git
cd shundo-hunter
python3 -m venv .venv
source .venv/bin/activate
python -m shundo_hunter.feed_server
```

Open **http://127.0.0.1:8765**. Status is available at
**http://127.0.0.1:8765/api/status**. Press Ctrl+C in the terminal to stop.
Quit the installed Mac app first if it already occupies port 8765. For a
separate development instance, pass `--port 8766`; the Chrome relay is fixed
to port 8765, so use the default port when testing the relay.

This starts the feed/UI. Full hunting needs the native Mac app, paired phone,
controller, and verified phone runtime described below. The service may poll
for connected devices when `pymobiledevice3` is installed; starting the feed
does not start a hunt.

Standalone data defaults to `shundo_hunter/data/shundo_hunter.db`. Override it
with `--database /path/to/database.db`. The packaged Mac app keeps its database,
log, relay copy, and runtime receipt under
`~/Library/Application Support/Shundo Hunter/`.

## Build and run the Mac app

### Prerequisites

- A Mac; the bundle declares macOS 13+, but phone/OS compatibility depends on
  your Xcode and iOS versions. The preserved setup used Xcode 27.
- Full Xcode, with its command-line tools selected and license accepted.
- Python 3 installed at `/opt/homebrew/bin/python3`, `/usr/local/bin/python3`,
  or `/usr/bin/python3` (the native launcher checks these locations).
- `pipx`, and a working Apple Development signing identity and provisioning
  access for your iPhone. Command Line Tools alone cannot build the iOS runner.
- For device features, an unlocked iPhone trusted over USB, Developer Mode,
  and Settings → Developer → Enable UI Automation enabled.

Install the base phone transport version used by this source snapshot:

```sh
pipx install 'pymobiledevice3==10.3.0'
pipx ensurepath
```

If it is already installed, inspect `pipx list` before changing that environment.
Hunter discovers it through PATH, `~/.local/bin`, or Homebrew's bin directories.

### 1. Prepare the preserved dependency sources

The `vendor/` directory contains the local WebDriverAgent 16.12.11 and
pymobiledevice3 Wi-Fi source snapshots used by this project, with their
licenses. This avoids relying on a moving upstream branch.

From the repository root, in a fresh checkout:

```sh
mkdir -p build/wda build/wifi-runtime
cp -R vendor/WebDriverAgent build/wda/WebDriverAgent-master
cp -R vendor/pymobiledevice3 build/wifi-runtime/pymobiledevice3-master
cp shundo_hunter/native/wda/FBDebugCommands.m \
  build/wda/WebDriverAgent-master/WebDriverAgentLib/Commands/FBDebugCommands.m
python3 -m venv build/dependency-env
build/dependency-env/bin/python -m pip install --no-deps \
  --target build/wifi-runtime/dependencies -r requirements-wifi.txt
```

The Wi-Fi directory is an overlay loaded ahead of the base phone transport's
Python environment. `requirements-wifi.txt` records the exact supplemental
versions present in the installed build; it is not a standalone replacement
for the base `pymobiledevice3` environment. On repeat builds, reuse the prepared
directories rather than nesting another copy inside them.

### 2. Build the signed iPhone controller

Set your Apple development team ID, then run:

```sh
export SHUNDO_DEVELOPMENT_TEAM='YOUR_APPLE_TEAM_ID'
xcodebuild build-for-testing \
  -project build/wda/WebDriverAgent-master/WebDriverAgent.xcodeproj \
  -scheme WebDriverAgentRunner \
  -destination 'generic/platform=iOS' \
  -derivedDataPath build/wda/DerivedData \
  DEVELOPMENT_TEAM="$SHUNDO_DEVELOPMENT_TEAM" \
  PRODUCT_BUNDLE_IDENTIFIER=com.benpurles.shundohunter.wda \
  CODE_SIGN_STYLE=Automatic -allowProvisioningUpdates
```

The controller bundle ID is part of the existing app integration. If signing
under another account requires a different ID, update the corresponding
controller references in `shundo_hunter/phone_helper.py`,
`shundo_hunter/catch_lab.py`, and associated tests as well. Use a signing
profile that includes the intended phone. Do not commit signing material.

### 3. Package and open

```sh
zsh shundo_hunter/native/build_app.sh
open 'dist/Shundo Hunter.app'
```

The build compiles the Swift app and two native helpers, archives the signed
iPhone controller, bundles the Python/web sources and Wi-Fi transport, and
signs the Mac app. It automatically selects an Apple Development identity;
set `SHUNDO_CODESIGN_IDENTITY` explicitly if you have several. This is a local
development build, not a notarized release.

The build requires exactly one `.xctestrun` file under
`build/wda/DerivedData/Build/Products/`. If older builds left multiple plans,
move the obsolete products aside and build the controller again.

## Set up the phone and feeds

1. Open the Mac app and inspect Settings. Trust the phone over USB and keep it
   unlocked during preparation. Grant the Mac permissions requested for the
   features you use, such as notifications and screen/accessibility access.
2. Full hunting requires the **exact verified iPogo 4.3.9 runtime v8 artifact**
   and its local install receipt. These are not in Git. The authoritative
   version/build/hash checks are in `shundo_hunter/device_service.py`.
   `install_ipogo_runtime.py --help` describes installation of an existing
   verified artifact. A stock install or newly signed approximation will not
   pass the current checks. See [runtime notes](SPAWN_RUNTIME_LOCK.md).
3. For the Chrome feed, load `shundo_hunter/browser_relay` using
   `chrome://extensions` → Developer mode → Load unpacked. Alternatively use
   the relay path shown in the app's Settings. Keep the relevant Discord
   channels rendered in browser tabs. The relay observes visible messages.
4. Use **Prepare phone**, then follow the app's readiness checks before starting.
   Configure any optional AI credentials through the app; they are stored
   locally and are not included in this repository.
5. For Wi-Fi, pair over USB first, use the same network, stop hunting before
   unplugging, confirm the Wi-Fi connection, then prepare again. Keep the Mac
   awake. Existing USB sessions do not migrate live.

The iPogo internal feed additionally needs the separately built Hunter Lab
app; see [HUNTER_LAB.md](HUNTER_LAB.md). PokeXperience integration has its own
external app/session requirements. The Chrome relay is the simplest feed
integration to configure independently.

## Tests

Run from the repository root:

```sh
python3 -m unittest discover -s shundo_hunter/tests -v
python3 -m unittest discover -s tests -v
node --test shundo_hunter/tests/test_hunt_setup.cjs
```

Node.js is only required for the JavaScript tests. The separate
`test_overnight_ui.cjs` browser harness additionally requires Playwright,
Google Chrome at the standard macOS install path, a running feed at port 8765
to read fixture responses, and a `build/` directory for screenshots. It mocks
browser writes, but is not part of the dependency-free unit-test command.

## Source map and detailed notes

- `shundo_hunter/native/`: Swift shell, Vision helpers, packaging script,
  and the customized WebDriverAgent notification endpoint.
- `shundo_hunter/`: feed server, queue/parser, device transport, hunt logic,
  notifications, Catch Lab, overnight and recovery services.
- `shundo_hunter/web/` and `browser_relay/`: UI and Chrome extension.
- Root Python/Objective-C/assembly files: historical phone-runtime build,
  signing, verification, and diagnostic tools. Some retain Ben's Apple team
  ID and require separately supplied input artifacts; they are not needed
  to start the local feed.
- [WIRELESS_CATCH_LAB.md](WIRELESS_CATCH_LAB.md),
  [OVERNIGHT_MODE.md](OVERNIGHT_MODE.md), [SCREEN_RECOVERY.md](SCREEN_RECOVERY.md),
  and [HEALTH_WATCHDOG.md](HEALTH_WATCHDOG.md): implementation and validation notes.

Historical notes describe earlier runtime versions and local experiments.
Use this README for checkout setup and the current source constants for
runtime compatibility. A fresh build still needs device testing; unit tests
do not prove end-to-end operation on a different phone or iOS release.

See [THIRD_PARTY.md](THIRD_PARTY.md) for dependency provenance and licenses.
