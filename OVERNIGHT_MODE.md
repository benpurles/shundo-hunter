# Overnight encounter work — 2026-09-28

## Current status: direct Hundo with Mac display off passed; full-night/Shundo validation pending

### Final revision 2 live test PASSED — 2026-09-29 04:10:45Z

Installed revision 2 returned screenLocked=false and gameActive=true.
Manually tested fresh Treecko CP842 (sighting 24341104); no hunt running.
macOS power log: display OFF at 22:10:13 MDT. Hunter recorded the real alert
at `2026-09-29T04:10:45.713895Z`: sequence 1, `Hundo Treecko appeared`,
is_hundo=true, is_shundo=false, source=iphone-banner, unattendedReady=true.
Only after observing this proof did the test launch caffeinate -u; the power
log records that test process PID76186 creating UserIsActive at 22:10:45,
followed by display ON. Thus delivery preceded the test-driven screen wake.
No detector errors occurred during this test. No Mac mirror event supplied
the proof. No cloud images, throws, berries, catches or IPA changes occurred.

Handoff: updated signed Hunter open, hunt idle/worker stopped, phone prepared,
overnight setup active, direct proof verified. User may start the hunt.
Keep Mac lid open/system awake on power; its display can sleep. Keep the
iPhone unlocked/charging with iPogo open and visible banners/previews enabled.
This proves a short real display-off alert test, not a whole night or a real
Shundo encounter opening. The separate earlier ordinary-map-tap test remains
the only live AI encounter-opening evidence.

### Direct notification repair — 2026-09-29 UTC, live Hundo passed

Installed signed Mac build and packaged-controller startup passed without a
separate terminal controller: backend → phone_helper → xcodebuild + usbmux
forwarder, all owned by Hunter. At `2026-09-29T04:01:01.444395Z`, Hunter itself
recorded sequence 1, `Hundo Treecko appeared`, `is_hundo=true`,
`is_shundo=false`, `source=iphone-banner`. `unattendedReady` became true.
This is a real fresh iPhone banner, not a synthetic injection, replay or Mac
mirror event. Fresh Treecko CP872 was a manual location test, not a hunt.
The full latest rerun passed 197 tests; one earlier rerun hit a timing race
in the pre-existing two-timeout recovery test, which passed in isolation and
in the final full rerun. No change to unrelated hunt recovery logic.

The iPogo syslog connection delivers OS UserNotifications request logs but no
Hunter marker. That does not prove why the IPA hook/log output is absent.
Do not rebuild or modify the working spawn-runtime IPA on that assumption.

Added an iPhone-only WDA accessibility endpoint and `PhoneBannerReader`, wired
to direct mode. It does not depend on Mac mirroring, send screenshots to AI,
open Notification Center or touch the phone. An empty healthy response is
only a connection, never alert proof. Reconnects baseline existing banners;
errors/stale heartbeats revoke direct readiness. Real phone banners/previews
must be visible and iPogo must remain foreground/unlocked.

Observed actual live SpringBoard AX banner during the Nidoking CP423 test:
`POKÉMON GO, now, Pokémon GO, Hundo Nidoking appeared`.
Identifier `NotificationShortLookView`, visible 1, rect x8 y40 w412 h66.
The Python parser mistakenly required `nearby`; fixed with an optional suffix
and an actual-wording regression test. This AX capture alone is NOT proof
that the complete new endpoint → parser → Hunter path has passed.

The lightweight controller startup then stalled. Xcode's attempt reported
`Timed out while enabling automation mode`. Requested the user unlock the
phone and confirm Developer → Enable UI Automation. Packaged the signed
runner and added Hunter-owned Xcode startup, bounded/cleaned up by the existing
supervisor. Do not call startup fixed until that managed path passes live.
197 tests pass; no throws, berries, catches, hunt starts or IPA edits.
A real Shundo-triggered opening remains unverified. Display-asleep delivery
is being tested separately; do not infer it from the awake Hundo result.

Follow-up live testing: the user started a hunt at 04:01:48Z during the first
display-off test. The detector later paused it; no checks were counted. There
were repeated five-second phone-read timeouts. The Mac display also woke after
15 seconds, so that attempt was not a successful display-asleep delivery test.
Stopped preparation and the paused worker to install the next build; did not
use Skip, change hunt thresholds or alter the IPA.

Reader revision 2 uses one SpringBoard snapshot, selects only native
`NotificationShortLookView` nodes, and computes visibility only for candidate
banners. It explicitly disables SpringBoard idle waiting. Foreground game
presence is telemetry, not notification-transport health: planned iPogo
restarts must not revoke an otherwise connected banner reader. Screen lock,
invalid responses and real transport errors still fail closed. Encounter
foreground/stability checks remain separate and unchanged. Added controlled
exception-category logging. The final source test suite passes 198 tests.
Verified revision 2 installed and responding with screenLocked=false over the
Hunter-owned Xcode Wi-Fi helper. Fresh live alert retest follows separately.

### Live supervised tap PASSED (2026-09-29 UTC)

The user explicitly approved proceeding through the tap, including up to
three cropped iPogo images sent to OpenAI. First Beldum attempt at 03:08:39Z
found zero candidates (it was no longer visible), stopped safely, and sent
NO tap. One image used. Released that no-tap test without moving the phone.

Installed a narrower supervised flow: one LOCATE and one IDENTITY request,
with identity corroborated on two local OCR frames. Production remains
LOCATE + two independent Shundo VERIFY requests; no safety guards removed.
Supervised UI states two images, evidence never calls cached identity a
second AI reading. Full suite: 185 tests passed. Signed build installed.

Litten test started 03:13:58Z over Wi-Fi. LOCATE at 03:14:10Z found one
unobstructed Litten. Native-control, geometry, foreground and image-stability
guards passed. Exactly ONE map tap budget consumed at 03:14:15Z. IDENTITY
at 03:14:24Z read Litten CP 346; local frames agreed. State reached holding
at 03:14:33Z. A separate local screenshot visibly confirmed Litten CP 346
on its catch screen. Total for both attempts: three cloud images, one tap.
No throws, berries, catches, dismissals, spoof/runtime changes or hunt stats.

This proves ordinary map selection → physical tap → encounter identity →
short read-only hold. It does NOT prove a Shundo, exact encounter identity
among multiple identical species, real direct Shundo notification handling,
display-asleep delivery, or overnight encounter survival. Those remain live
validation work. Leave this ordinary encounter protected for manual handling;
release explicitly before resuming hunting. Phone screenshot showed 24%
battery without a charging symbol; wall power should be verified before any
overnight run.

### Supervised one-opening test (2026-09-28, earlier setup history)

Installed a dedicated `vision-test-open` action + explicit UI confirmation.
Uses the same native-control, stale-image and single-tap guards as production,
but requires idle/unprepared/unprotected state and never injects a fake Shundo
alert. Test journal is marked `mode=supervised`. A separate identity-only
schema (OpenAI Docs structured-output guidance) checks species/CP twice and
never sets visionShundoEvidenceMatched or updates hunt statistics. Production
still requires visible IV/shiny evidence. Cancellation/uncertainty leaves the
encounter protected. 185 tests pass; JS syntax checked. Installed rollback:
`/private/tmp/shundo-before-open-test.jdi9l7g0/Shundo Hunter.app`.

The user requested the next supervised step. Controller setup was restored,
iPogo foreground verified. The actual test command was rejected BEFORE
execution by tool privacy review: prior approval covered one screenshot,
whereas this flow sends up to three fresh cropped images (locate + two identity
checks) to OpenAI. No test taps or images were sent in this attempt. Do not
work around the rejection; explicit authorization for those three images is
was required before invoking the test. That approval was subsequently given;
see the successful live test above.

### Beldum read-only test and stage separation (2026-09-28)

Retest after installing the split, explicitly approved by the user: completed
2026-09-29T02:58:26Z, about 10 seconds after start. Real API result: map,
Beldum, candidate_count=1, uncertainty="", box x=.283 y=.647 w=.065 h=.041
(cropped-image fractions). Selection evidence described one unobstructed
sprite separate from neighbours and UI. The local species, unique-candidate,
and image-bound checks PASSED. No touch was delivered. This validates the
specific uncertainty-field fix, not live pre-touch stability/native-control
checks, encounter opening, IV/shiny verification, or overnight reliability.
Hunter remained idle, protection false, test complete, overnight setup active.

With explicit user approval, the installed app sent one cropped image to
OpenAI over the configured API. The request completed in about 12 seconds
and identified one Beldum map sprite. No touches occurred. Shiny/IV values
were unavailable on the map, correctly, but the shared schema encouraged
that caveat in the uncertainty field and would have blocked map opening.

Fixed by giving LOCATE its own strict schema and prompt: species, scene,
candidate count, box, selection evidence, and selection-only uncertainty.
VERIFY still requires independent encounter/species/CP/IV/shiny evidence.
No string filtering or automatic dismissal of model uncertainty was added;
any reported selection ambiguity still blocks touching. Old-format or
wrong-stage results are rejected. The no-tap test now reports the outcome
of candidate checks rather than only reporting that the API returned.

Regression tests cover the Beldum box with no IV/shiny fields, wrong-stage
responses, ambiguity, and empty selection evidence. Actual opening and
overnight reliability are still unverified; the first image was not a catch
screen or proof of a Shundo. No IPA or spoofing-runtime changes.

The one-tap AI opener is implemented, disabled by default; the user has since
enabled it and supplied a key through Settings. One approved real OpenAI
map-analysis request succeeded as recorded above. Actual Shundo opening and
overnight hold have NOT been verified. Do not present simulated tests as
phone/AI success. No API key was exposed or inspected by the agent.

### New AI flow

- Settings → Overnight encounter hold: explicit cropped-image-sharing consent,
  separate API billing notice, model, API key stored by signed native helper in
  macOS Keychain, enable switch, read-only Analyze screen, Cancel, evidence log.
- On a fresh real Shundo alert, the existing stationary stop/interlock runs
  first. Actual alert species is parsed; it need not match the queued target.
  Unknown/ambiguous species or stale alert stops without a tap.
- At most three API requests: locate once, verify twice. Images are cropped
  to 16–82% of screen height, excluding the status/banner band and bottom
  controls. Overlays may still contain information; consent warns about this.
  Only species/CP and the crop are sent to the fixed OpenAI Responses endpoint,
  with store=false, strict structured output, no tools, redirects or retries.
- Before the one map tap: validate species, ambiguity, bounds, foreground PID,
  screen geometry, global and target-region pixel stability, local encounter
  classifier, and native dialog/button overlap. Recapture after slow queries.
  Consume/persist the tap budget BEFORE delivery. Timeout never retries.
- Once tapped, observe only. Two frames must match species, CP, explicit shiny
  evidence, and visible numeric 100-IV evidence. Local OCR corroborates name,
  CP and IV. A notification or CP alone is NOT 100-IV proof. AI evidence can
  still be wrong; UI deliberately says visual evidence matched, not certainty.
- Wrong, obscured or unproven encounter is left open with protection locked
  and an attention alarm. Never flee/relaunch/throw/berry/retry automatically.
- Cancellation revokes subsequent actions. It cannot undo a delivered tap.
  No cloud request holds the operator-action lock; delivery is serialized with
  release/cancel. A restart never resumes an AI task or clears a recorded hold.
- No generic remote-touch API was exposed. Existing supervised Catch Lab is
  separate and blocked while overnight protection/setup is active.

### Verification and next setup

177 tests passed after adding 26 vision tests, including a synthetic native
image orientation test, one-tap persistence, timeout, cancellation, wrong
species, stale frames, malformed/refused responses and missing IV evidence.
No test uses an API key or contacts OpenAI. JS syntax checked.

Signed build installed to `/Applications/Shundo Hunter.app` and opened. Its
Settings UI was visually inspected. Live status: idle, phone connected, AI
disabled, consent false, no key configured, no task/protection running.
Rollback copy: `/private/tmp/shundo-before-ai-opener.U1Pj5w/Shundo Hunter.app`.

To enable: stop hunting; set iPhone Auto-Lock Never and wall-charge; start
overnight setup; enter API key and explicitly opt in; save; run Analyze screen
on a known Pokémon (no tap). Then prove a real direct Hundo alert, including
with the Mac display asleep. Live exact-Shundo opening still requires testing.
Keep Mac lid open/on power and use trusted Wi-Fi. Do not modify the working
IPA, turn on internal spoofing, or use notification taps as encounter opening.

OpenAI Docs skill informed the image-input and structured-output integration:
https://developers.openai.com/api/docs/guides/images-vision
https://developers.openai.com/api/docs/guides/structured-outputs

## Earlier foundation evidence (before AI opener)

User wants manual throwing in the morning, no automated throws or berries.
At this earlier stage automatic opening of the exact Shundo was not implemented.
User confirmed notification tapping only changes iPogo's internal coordinates;
it does not open an encounter and does not work with internal spoofing off.
Do not turn internal spoofing on or disturb the verified spawn runtime to
work around that limitation. No IPA changes were made for this preview.

Implemented in Settings → Display-off setup & encounter protection:

- Explicit direct-only phone-log alerts, routed through existing paired Wi-Fi.
  Mac bridge heartbeats cannot stop the listener or inject duplicate proof.
- A running process is not sufficient proof: a real Hundo/Shundo marker must
  arrive on the current direct stream before starting a hunt. Restarting the
  stream clears proof. Default mirrored-alert behavior stays unchanged.
- Bounded 12-hour helper and Mac `caffeinate -i -s` assertion tied to the
  backend PID. No display assertion, global power settings, or lock bypass.
- On Shundo in this mode: stop/lock hunt controls, switch from the walking
  route to stationary location, and report **needs opening**, never “held.”
- Operator-opened encounter protection checks two matching encounter/CP
  frames and reads every 10 seconds. CP is NOT shiny/IV/encounter identity.
  It never taps, throws, uses berries, relaunches, unlocks, or dismisses.
- Server-side action locks and a persistent database-adjacent hold journal.
  After restart, recorded protection remains locked and explicitly unmonitored.
- Lost controller, lost power assertion, or unreadable/changed held screen
  reports attention. Running hunts pause. No blind recovery of held encounters.
- Explicit release only unlocks controls/ends wake protection. It does not
  catch, move location, resume hunting, or dismiss an encounter. Direct source
  remains selected until explicitly switching back while idle/unprepared.

## Live evidence and remaining checks

- Phone was connected over native paired Wi-Fi (no USB) and WDA responded.
- Read-only iPogo settings inspected; shiny scanner enabled, internal spoofing
  off, Nearby Shortcut off, Catch Preview on.
- Tapped a visible ordinary Magnemite, with no throws or berries. This gesture
  alone is NOT evidence that an encounter is held or will survive overnight.
- Direct app-filtered native Wi-Fi syslog process stayed open for eight seconds.
  **No real Hundo marker received in that test**, so display-off notification
  delivery remains unverified. Never treat this as end-to-end proof.
- Automated suite: 151 tests pass (139 existing + 12 new). JS syntax checked.
- Live macOS power test: `pmset -g assertions` showed this test's caffeinate
  process owning PreventUserIdleSystemSleep and PreventSystemSleep, with no
  display assertion. The temporary assertion was explicitly released.
- Signed build installed; API showed idle, phone connected over Network,
  protection off, automatic opening readiness false. UI preview panel inspected.
- Pending user confirmation: iPhone Auto-Lock Never + charging + iPogo open.
- Still required: live ordinary encounter hold, true direct Hundo event with
  Mac display asleep, reconnect/failure checks, and safe exact-Shundo selection.

## Test safely

1. Phone on same trusted Wi-Fi, wall charging, Auto-Lock Never; keep iPogo open.
   Mac on power, lid OPEN. Restore Auto-Lock afterward. Do not disable lock
   security or use repeated dummy taps.
2. Stop/end preparation, start display-off setup. Prepare iPogo. Trigger one
   legitimate Hundo notification through a supervised check; direct proof must
   appear. A synthetic Mac event must not satisfy this.
3. Stop the hunt, open an ordinary catch screen manually, Protect open encounter.
   Verify CP/read timestamps update with display off. No throw authorization.
4. Explicitly release before any changing/refresh/real-location action.
5. Do not claim full overnight operation until an exact-encounter opener and
   identity verification are implemented and tested. An alert species may differ
   from the current queue target; existing detector deliberately accepts this.

Rollback app saved at `/private/tmp/shundo-before-encounter-guard.HvgUIO/Shundo Hunter.app`.
This directory is temporary; source and installed app are the durable artifacts.
# Startup and egg screen recovery (2026-09-28)

Implemented and installed: bounded AI cleanup after normal Hunter refreshes,
local egg/notice OCR checks during dwell, and cleanup before Shundo selection.
See `SCREEN_RECOVERY.md` for the allowlist, budgets, safeguards and exact live
test evidence. Live startup OK dismissal and teleport-speed reminder dismissal
both passed; the post-refresh hunt resumed with a confirmed Hundo. Egg flow is
covered by automated tests but has not yet been exercised with a real hatch.
Keep the existing iPogo spawn runtime and revision-2 direct banner reader intact.
