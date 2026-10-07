# Wireless connection and supervised catch prototype — 2026-09-28

## Scope and invariants

This update does NOT change the iPogo IPA, spawn runtime trust constants,
notification matching, hunt ordering, timing, or Shundo stop/alarm behavior.
`autoCatchEnabled` is always false. A gesture is never counted as a capture.
Do not wire the Shundo notification directly to a throw: the current detector
can intentionally accept a species-mismatched fresh Shundo alert. Exact
encounter identity, shiny/IV verification, cooldown tracking and catch-result
verification are still required for unattended catching.

## Wireless changes

- `device_service.py` accepts USB and Network records from usbmux.
- Selection pins to the runtime receipt's device UDID; otherwise a single
  unambiguous phone. Prefer USB only within the SAME phone's records.
- A disconnected selected phone never falls back to another paired phone.
- Settings shows USB / Wi-Fi and includes Enable Wi-Fi pairing with readback.
- Pair/trust by USB once, keep both devices on the same network, keep Mac awake.
- Stop the hunt/controller BEFORE removing USB. Existing location/controller
  streams do not seamlessly migrate; reconnect and prepare/start fresh.
- On iOS 26.7, usbmux was empty after unplugging despite valid pairing. Added
  `native_wifi.py`: isolated upstream pymobiledevice3 native Apple tunnel,
  bundled under Resources/wifi-runtime. Existing USB dependency is unchanged.
- Native discovery opens/closes a live authenticated RSD handle for the pinned
  UDID; only an explicit metadata allowlist is returned (never pairing keys).
- Runtime app verification and iPogo PID lookup both succeeded with USB
  physically unplugged. WDA xcuitest also started and `/status` reported ready.
- DVT routes/recovery, app verification, and notification/world log readers
  dispatch through the isolated native transport when selected; USB unchanged.
- A full cable-free hunt, notification pass, and location-route restart still
  need live validation. iPogo internal-feed lab refresh remains USB-oriented.

## Phone controller

Source: https://github.com/appium/WebDriverAgent (Appium, not any other org).
Downloaded master source reports version 16.12.11. Archive SHA-256:
`52bf628ee35a771fddbc4d5fc20c1029df3d27b71187d396e05b24e835fbb7b5`.
Source retained at `build/wda/WebDriverAgent-master`; signed output is at
`build/wda/DerivedData/Build/Products/Debug-iphoneos/WebDriverAgentRunner-Runner.app`.
Installed bundle: `com.benpurles.shundohunter.wda.xctrunner`.
Xcode 27, development team H37AFANDDZ, existing local signing identity.

Build command from project root:

```sh
xcodebuild build-for-testing -project build/wda/WebDriverAgent-master/WebDriverAgent.xcodeproj -scheme WebDriverAgentRunner -destination 'generic/platform=iOS' -derivedDataPath build/wda/DerivedData DEVELOPMENT_TEAM=H37AFANDDZ PRODUCT_BUNDLE_IDENTIFIER=com.benpurles.shundohunter.wda CODE_SIGN_STYLE=Automatic -allowProvisioningUpdates -quiet
```

Xcode's test-without-building installed the runner but twice timed out enabling
automation mode. User confirmed enabling iPhone Settings → Developer → Enable
UI Automation. Mac DevToolsSecurity reports disabled; it was NOT changed.
The successful alternative is the existing pymobiledevice3 DVT xcuitest route:

```sh
pymobiledevice3 developer dvt xcuitest --userspace --udid DEVICE_UDID --timeout 600 com.benpurles.shundohunter.wda.xctrunner
```

Hunter Settings → Catch Lab → Start controller now owns this launch and a
loopback-only usbmux forwarder `127.0.0.1:18100` to device port 8100.
On native Wi-Fi, its forwarder discovers the paired phone by Bonjour and
authenticates against the existing usbmux pair record before each connection;
credentials remain in memory. WDA itself listens on the phone's network port,
so only use Catch Lab on trusted private Wi-Fi and stop it after testing.
`phone_helper.py` supervises both children, bounds the session to 10 minutes,
and stops them if Hunter exits. Never expose the WDA debug server publicly.
No broad Mac developer-security changes are necessary for this launch path.

## Supervised test flow

1. Stop hunt / end preparation. Wait for its worker to finish.
2. Start controller; phone must remain unlocked. It may briefly show runner.
3. Open an ordinary Pokémon encounter manually; select a non-Master Ball.
4. Capture iPogo preview; click ball, then throw destination on the preview.
5. Explicitly confirm ordinary Pokémon, non-Master Ball, and game cooldown.
6. Test one throw; visually inspect actual result. No automatic retry.

The backend refuses non-iPogo foreground apps, active/prepared hunts, consumed
or >30-second-old previews, invalid points, changed orientation, and missing
confirmation. The preview nonce is one-use even on an error. The prototype does
not automatically verify the user's ordinary-Pokémon/ball/cooldown assertions;
these are supervised prerequisites, NOT production capture guarantees.

The API requires an exact local Origin (when present) plus the per-run app
token. Status and image stay local. No screenshots are persisted by the UI.

## Verification and rollback

### Calibration/result reader increment

- Catch Lab now includes a 120–600ms swipe-duration control (default remains
  350ms). Points are still manually selected on a fresh preview for every test.
- `CatchScreenReader.swift` uses local Apple Vision on WDA-provided PNGs. No
  iPhone Mirroring dependency, no cloud OCR, no screenshot persistence in app.
- `catch_screen.py` recognizes an English encounter via AR + CP at expected
  screen positions, active displayed cooldown, corroborated catch phrases or
  reward panel, and flee messages. Top notification banners cannot prove catch.
- Before throwing, reread the foreground screen; unknown/changed CP, active
  displayed cooldown, invalid calibration and non-encounter previews block.
- Following a successful gesture request, observe up to 24 seconds. Require
  two matching frames and at least five seconds elapsed for a result. A still
  visible encounter does NOT distinguish a miss from an escape. Errors and
  ambiguous animations are uncertain, never authorization for a retry.
- The UI displays the last attempt's CP, duration, samples, outcome and text
  evidence. A confirmed catch screen does not verify shiny/IV identity. No
  production hunt statistics or auto-catching behavior are changed.
- 139 tests passed, including cooldown/changed-screen guards, duration bounds,
  OCR banner exclusion, corroborating catch evidence and two-frame results.
- Before-calibration app backup:
  `build/shundo-hunter/backup-before-catch-result-reader-20260928.app`.
- Live calibration completed: all THREE authorized ordinary regular-ball
  throws have been used. No further throws without new user approval.
- First calibration throw (240ms) left Golett CP135 in encounter; observer
  interrupted and correctly reported uncertain, not caught.
- Recorded second throw (240ms, normalized start .50/.85, end .50/.40)
  fell short at Golett's feet; iPogo displayed Missed around 7–8 seconds.
  Hunter independently reported still-in-encounter, not a verified capture.
  Video: `build/catch-lab-recordings/test-2-retry/throw.mp4`.
- The watch skill's frame review identified the shortfall. Final throw used
  a faster/higher swipe: 150ms, normalized start .50/.85, end .50/.30.
  It landed Nice and caught Golett CP135 over Wi-Fi with USB disconnected.
  Video: `build/catch-lab-recordings/test-3/throw.mp4`.
- Hunter independently confirmed the catch after four observations, including
  two matching reward panels: POKÉMON CAUGHT, NICE THROW, TOTAL 1,620 XP, OK.
  Attempt `d59b3913d0bd3870`: result=caught, captureVerified=true.
  This is one successful Golett calibration, NOT a universal throw profile
  or proof of shiny/IV identity. No production hunt statistics changed.
- Two preflight requests blocked before any gesture because OCR was uncertain;
  these consumed no balls. Fresh-screen validation now allows up to two extra
  read-only observations for uncertain OCR, never a gesture retry.
- Controller stopped after the third approved throw; last caught result is
  retained in the running app. Hunt idle, automatic Shundo catching OFF.

- 124 unit tests passed (existing suite + wireless selection/native routing + Catch Lab guards).
- Python compilation and JS syntax checks passed.
- Signed helper installed; its `/status` returned ready on iOS 26.7.
- Updated Mac app installed and opened; Settings and Start controller verified.
- Managed helper started successfully from Hunter and returned ready.
- Final installed build's native Wi-Fi helper also returned ready, with USB
  disconnected and no manually started bridge. Stopped it after verification;
  Hunter left open in Settings, hunt idle and phone connected over Wi-Fi.
- Live wireless test: Golett CP135, regular balls158 before and157 after one
  W3C gesture through Hunter's guarded throw endpoint. Golett remained on the
  encounter screen: remote throw demonstrated, capture NOT demonstrated.
- Test initially hit stale helper status after failed Bonjour matching. iOS
  uses opaque supportsRP service names; do not assume MAC@hostname. Discovery
  now tries private IPv4 advertisements, deduplicates/bounds candidates, and
  requires paired UDID authentication. Up to three bounded discovery passes.
- Previous Mac app saved at
  `build/shundo-hunter/backup-before-wifi-catch-lab-20260928.app`.
- Latest build installed at `/Applications/Shundo Hunter.app`.

Before expanding to unattended Shundo catching, prove same-network Wi-Fi
operation end-to-end, demonstrate ordinary catches and catch-outcome detection,
then integrate reliable encounter identity. Keep existing Shundo stop/alarm
as the fallback on every uncertain condition.
