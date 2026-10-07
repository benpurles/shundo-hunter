# Shundo Hunter

## September 28 update: Wi-Fi and Catch Lab

Settings now supports paired Wi-Fi phones as well as USB. Enable Wi-Fi pairing
over USB once; stop hunting before unplugging, keep both devices on the same
network, check for **Wi-Fi connected**, then prepare again. The Mac must stay
awake. Existing USB streams are not migrated live.

**Catch Lab** is a supervised, one-throw experiment using a separately signed
WebDriverAgent helper. It does not automatically catch Shundos. Start controller,
open an ordinary encounter, capture its preview, select ball/destination, and
explicitly confirm before a single test throw. Captures are not automatically
verified or added to hunt statistics. End preparation before testing; Shundo
stops remain untouched. See the project-root `WIRELESS_CATCH_LAB.md` for build,
validation, guardrails and rollback details. Historical runtime notes below
predate the currently supported iPogo 4.3.9 / runtime v8.

This Mac app receives 100-IV sightings from a deliberately installed Chrome relay, stores a normalized queue in SQLite, and runs a connected iPhone through fresh targets while watching iPogo's local alerts. It stops and sends a Mac notification when iPogo reports a Shundo. It does not read, copy, or store Discord authorization tokens, cookies, passwords, or browser profile data.

## Open the Mac app

The built application is:

```text
dist/Shundo Hunter.app
```

The app starts the local feed automatically. Its database, log, and installable Chrome relay live under:

```text
~/Library/Application Support/Shundo Hunter
```

Hunt timing is adjustable in Settings. The map-loading wait controls how long a coordinate is allowed to populate, while the Hundo cooldown holds the current location after a confirmed Hundo before the next teleport. The cooldown defaults to 30 seconds, accepts 0 through 600 seconds, pauses with the hunt, and never delays a Shundo stop.

The Hunt, Statistics, and Settings screens are functional. Connect the iPhone, choose **Prepare phone**, then start the hunt. The app honors each Discord sighting's despawn timer (with a 30-minute fallback), follows the configured species ranking, teleports to each target, then walks a continuous 20-meter circle at about 10 km/h. It watches each target for up to 45 seconds so the map and spawns have time to load. A regular Hundo alert proves the target loaded and advances the queue immediately; a Shundo alert stops the hunt and raises the Mac alert.

Queue order is deterministic: manually prioritized sightings first, then species ranking. All live Squirtle sightings are exhausted from highest to lowest level before the hunter moves to the next ranked species. After the ranked list is exhausted, PokeXperience and iPogo targets use highest CP first; Discord targets retain highest-level-first ordering. The Settings picker searches every species previously observed, including species with zero live sightings, and also accepts a typed name that has never appeared in the local feed.

For the iPogo internal source, **Sync iPogo feed now** launches the isolated Hunter Lab, waits for iPogo to restore its authenticated state, requests the fresh 100-IV snapshot automatically, and returns to production iPogo after the complete batch is stored. No feed navigation or phone tap is required. Another refresh is scheduled every two minutes while the hunter is idle; it defers during prepared, running, or paused hunts so it cannot interrupt a check. Coordinates are removed from SQLite as soon as they expire.

For the PokeXperience source, Hunter reads the complete encrypted 100-IV snapshot directly in the background once per minute. The snapshot already contains coordinates, CP, level, location, and exact despawn time, so Hunter never scrolls the PokeXperience window, changes its search field, intercepts Teleport links, or uses the clipboard.

The phone must use the versioned, verified iPogo 4.3.3 Hunter Runtime v2. The accepted release is the exact signed artifact empirically confirmed on the physical phone on 2026-07-31; it is not a rebuilt approximation. It reapplies the external-location compatibility mask whenever iPogo launches and also exposes a USB log marker for diagnostics. It adds no helper framework or Mach-O load command. **Prepare phone** checks the `empirical-gold-20260731` install receipt and exact IPA SHA-256, refusing older, experimental, or merely code-equivalent IPAs.

The native Mac detector is the authoritative automation source because live testing proved it receives the visible mirrored iPhone Hundo alerts while the USB syslog process can stop silently. The detector reports a heartbeat every two seconds, accepts repeated identical alerts after a short scan-noise cooldown, and scopes species-bearing alerts to the current target. The USB marker remains a diagnostic fallback and is stopped whenever the native detector is live so one alert cannot be counted twice.

## Run the local feed

From the project root:

```sh
python3 -m shundo_hunter.feed_server
```

The service listens only on `127.0.0.1:8765`.

- Health and counts: `http://127.0.0.1:8765/api/status`
- Recent sightings: `http://127.0.0.1:8765/api/sightings`
- Relay input: `POST http://127.0.0.1:8765/api/ingest`

Sightings are stored in `shundo_hunter/data/shundo_hunter.db`.

## Connect the Chrome relay

### Overnight announcement recovery (September 2026)

The GO Pass news card can cover the map while Hundo notifications still arrive.
Recovery recognizes the paired **SEE DETAILS** and **DISMISS** controls and may
tap only the locally OCR-confirmed bottom-center **DISMISS**. The recovery-only
image crop ends at 98% of screen height; encounter-selection crops are unchanged.
Unknown dialogs, consent/purchase screens, and existing encounters remain untouched.

Ordinary Hundo alerts yield out of cleanup once. The hunt retains that alert,
resumes interrupted cleanup at the same coordinate, then polls again before
crediting the check and moving on. A fresh Shundo always wins. The UI shows
“Hundo received · clearing the screen” during this phase. Same-process hatch
history and the last delivered action survive an interruption, preventing a
blind repeated tap. Cleanup keeps its 8-image/6-tap/180-second limits and hourly
image budget; failed/unknown recovery pauses rather than guessing. Local probes
of ordinary maps do not send cloud images or extend bad-coordinate deadlines.

Regression coverage lives in `test_screen_recovery.py`, `test_overnight.py`, and
`test_hunt_service.py`. Do not alter the verified IPA/spawn runtime to fix UI overlays.

### Relay setup

1. Open Shundo Hunter and choose Settings.
2. Copy the relay-folder path shown there.
3. Open `chrome://extensions` in Chrome.
4. Enable Developer mode.
5. Choose Load unpacked and select the relay folder.
6. Keep `#gen1` open in a Discord tab. Open one tab for each additional 100-IV channel to monitor.

The extension observes only rendered Discord channel messages, resolves Pokedex100 coordinate links inside the existing Chrome session, and sends the local service these fields:

- guild, channel, and message IDs
- channel name and rendered message text
- visible links
- resolved latitude and longitude
- observation time

It never calls Discord's private API and never reads or exports Discord cookies or authorization headers.

Only a channel rendered in a Discord tab can be observed. The relay deduplicates messages in memory, and the local database enforces durable deduplication.

Extension installation is intentionally left as a user-confirmed step because Chrome will display permissions for Discord, Pokedex100, and the local service.
