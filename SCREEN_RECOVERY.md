# iPogo screen recovery — 2026-09-28

## Purpose and triggers

Startup notices and egg-hatch screens obstruct the map without stopping spawn
notifications. Clear those screens before choosing a Shundo; never interpret a
notification or an egg reveal as proof of a wild Shundo encounter.

Recovery is enabled by the existing overnight setup + AI opt-in/configuration.
It runs after Hunter's normal iPogo refresh/settle, on a local egg/known-notice OCR
hint during target dwell (at most every 15 seconds), and before production
Shundo map selection. Ordinary local map checks do not send cloud images.
Settings → overnight AI → Screen recovery shows status and the last 20 steps.
The manual Clear blocking screens button requires an idle, unprepared hunt.

## Allowed actions

- Acknowledge a locally corroborated surroundings/weather notice at its visible
  OK/close control.
- Acknowledge the exact “You're going too fast / I'M A PASSENGER” game notice
  only while Hunter owns a live simulated-location process. Never infer actual
  driver/passenger status, or dismiss a system safety/permission dialog.
- Tap the central, full-screen hatch egg with the locally recognized “Oh?” prompt.
- Wait through the animation/reveal, or press an explicit visible continuation
  control. Close the bottom-center X on the hatched Pokémon details only after
  observing a hatch sequence and corroborating Weight/Height text.
- Require two separate map inspections before completing recovery.

No catch/berry/throw/flee controls, inventory actions, purchases, permissions,
terms, login, or unknown dialogs are allowed. No generic “dismiss everything.”
Existing encounters/results remain untouched. Multiple-egg batches can exceed
the bounded budget and require manual help.

## Limits and cancellation

Each recovery: up to 8 AI images, 6 recovery touches, 180 seconds. The running
backend additionally limits recovery to 60 images in a rolling hour; this count
resets on app restart. Uses the configured OpenAI model/key, strict structured
output, no model tools, no response storage requested. Recovery crops extend
to bottom close controls but exclude the top status/notification band.

Before each tap: recheck hunt/protection/cancellation, iPogo process, geometry,
native dialogs, screenshot stability, and local OCR. If the screen changed,
reobserve without tapping. If touch delivery is uncertain, stop—never resend.
Cancel AI inspection pauses a running hunt before cancelling recovery.
Pending Hundo and Shundo alerts preempt ordinary recovery and are processed by
the hunt; recovery only peeks at alerts and never consumes them. Screen probes
and cleanup do NOT extend the coordinate loading deadline. Deadline expiry
cancels further recovery taps, polls any pending alert first, then completes an
unconfirmed coordinate and advances. Slow in-flight read/API calls may return
after the deadline, but cannot authorize a late touch or replenish the timer.
If a Shundo interrupts an already observed hatch, its protected preflight can
carry that same-process hatch history for 180 seconds. It cannot carry history
across an iPogo restart or use old history to close an unrelated details page.

The Shundo encounter opener keeps its separate one-map-tap limit and subsequent
read-only verification/hold. Read-only/supervised encounter tests do not run
automatic screen recovery.

## Preserve the proven spawn and alert paths

Do not patch/reinstall iPogo for this feature. Do not replace the existing
DeviceService restart or create another location-stream owner. The existing
refresh path preserves the spoof stream, and recovery begins after it settles.
The direct iPhone banner reader remains revision 2; Mac mirroring is not needed.

## Verification

227 automated tests passed, including notice → map, egg → animation → hatched
details → map, bounds, unknown/system screens, caught/encounter refusal,
cancelled and stale requests, uncertain touch delivery, rate budgets, refresh
integration and Shundo preemption. JavaScript syntax and signed macOS build pass.
These simulated sequences are not evidence of a live egg-hatch run.

First live inspection correctly identified the game's speed reminder and sent
no touch because it was not yet allowlisted. Added the exact, stream-guarded
speed-notice case based on the observed phone screenshot/OCR, not a generic
dialog dismissal rule.

Live phone test passed at 2026-09-29 04:47 UTC: model classified the exact speed
notice, local OCR independently matched its text/button, and the active Hunter
stream guard passed. One recovery tap was delivered at 04:47:30.537 UTC. Separate
AI image inspections at 04:47:41 and 04:47:51 confirmed the unobstructed map.
No map Pokémon was tapped, and no berry/throw/catch action occurred.

Full live refresh integration also passed at 04:49–04:50 UTC. After verifying a
fresh direct `iphone-banner` Hundo Treecko alert at 04:48:55, the normal hunt was
restarted. Its existing clean-restart path preserved the location stream.
Automatic recovery recognized “Stay Aware of Your Surroundings” and the visible
OK button, delivered one guarded tap at 04:49:57, and confirmed maps containing
Pokémon/PokéStops at 04:50:10 and 04:50:21. The hunt then reached cooldown with
one confirmed check, no refresh error, and recovery state `map-ready`.
The hunt was left running; iPogo itself was not reinstalled or patched.

## Follow-up: avoid pausing before processing a real Hundo

At 05:18:16 UTC a speed-notice tap succeeded. The direct reader captured a real
Hundo Treecko at 05:18:19.895, but recovery failed its next read at 05:18:21.136
and paused the hunt before its normal poll could handle that alert. This was
not evidence of bad coordinates. The old generic exception hid the read error.

Routine recovery now yields to Hundo as well as Shundo, including when an alert
and a read failure arrive together. Read-only captures retry transient failures
up to 8 attempts within a nominal 10-second retry window (individual transport
requests retain their own timeout), with cancellation/alerts checked between
attempts. Touch delivery is never retried. Persistent failure retains a useful
error type/message and still pauses safely. The WDA foreground selection may
temporarily select SpringBoard for NotificationShortLookView, so a banner is a
plausible cause; the old generic error did not prove the exact exception.

Added regressions for Hundo preemption without consumption, read-only retries,
bounded persistent failure, deadline cancellation of slow cleanup, and repeated
screen probes not replenishing either of two bad-coordinate timers. Both
coordinates time out and the worker stays running. No timeout-counting, spawn
runtime, notification-readiness, or protected-Shundo checks were removed.

Installed backup before this follow-up:
`/Users/benpurles/Library/Application Support/Shundo Hunter/backup-alert-handoff.pyJ96t/Shundo Hunter.app`

Live follow-up passed: the direct reader verified a fresh Hundo Marshtomp at
05:34:59 UTC. The hunt resumed and confirmed Marshtomp after its startup
refresh. On the next coordinate, recovery identified and tapped a blocking
notice, then a real Hundo interrupted cleanup and the hunt entered cooldown
with two confirmed checks and no error. This exercises the same alert-after-
dismissal ordering that previously paused the hunt. The hunt remains running,
with the original 120-second loading setting and three-failure refresh threshold.
The hard bad-coordinate deadline is regression-tested with simulated timeouts;
no fake coordinates or artificial live alerts were inserted to claim proof.

Installed-app backup before this update:
`/Users/benpurles/Library/Application Support/Shundo Hunter/backup-screen-recovery.sgWTlB/Shundo Hunter.app`

## Weather warning and health watchdog follow-up

The `I AM SAFE` weather warning was correctly identified at 05:59:46 UTC but
rejected by the startup-button allowlist. The weather-specific, OCR-corroborated,
active-stream-guarded button is now supported. See [HEALTH_WATCHDOG.md](HEALTH_WATCHDOG.md)
for the new bounded health supervision, regression evidence and deployment
limits. No live weather-popup test was performed; hunt remains off for this update.

The OpenAI docs skill informed the separate strict recovery evidence schema and
programmatic action allowlist. Reference:
https://developers.openai.com/api/docs/guides/structured-outputs

## Announcement cards and resumable cleanup — September 29, 2026

Observed a GO Pass: September news card behind the speed reminder. A successful
speed acknowledgment at 04:56:35 UTC was followed by a Hundo cancellation, which
let the hunt advance without clearing the remaining news card. Its DISMISS text
spans approximately y=0.9506–0.9680, partly outside the former 0.96 crop.

Added explicit `announcement` / `dismiss_announcement` classification. Local
OCR must find both SEE DETAILS and DISMISS; only the bounded bottom-center
DISMISS control can be tapped. Recovery crop ends at 0.98; all other scene edge
limits and encounter-selection crops stay unchanged. The AI only classifies;
strict structured output does not replace local bounds/text/scene validation.

Hundo is retained while interrupted cleanup resumes at the same coordinate,
without counting it twice. The detector stays armed and is polled again before
advancement: a newer Shundo wins. Repeated Hundos cannot repeatedly interrupt
this post-Hundo cleanup. Same-process hatch history and the last delivered
action survive cancellation; a repeated identical action is rejected. New UI
phase: Hundo received · clearing the screen. Existing bad-coordinate deadlines,
action/image budgets, pause/skip controls, and protected-encounter rules remain.

Live news dismissal passed at 2026-09-30 05:08:49 UTC: exactly one guarded
`dismiss_announcement` tap removed the GO Pass card. An actual Oh? egg appeared
under it and the existing egg tap ran at 05:09:00. The resulting Grookey details
had a bottom checkmark instead of X, so the old rule safely stopped. Added that
specific checkmark with the same recent-hatch/process/bottom-center guards.
Weight-record pages say LIGHTEST/HEAVIEST rather than WEIGHT; they require a
visible kg measurement plus HEIGHT. User dismissed Grookey and confirmed the
next screen was egg inventory requiring a second, bottom-center X.

Added `egg_inventory` / `close_hatch_inventory`, authorized ONLY after the
observed hatch's details were successfully dismissed. Local distance counters
and egg-inventory text corroborate the screen; settings prompts, incubators,
arbitrary inventory, and other X buttons remain off limits. Same-process,
180-second history is required. Regression flow covers egg → details → egg
inventory → two maps, plus changed-process and absent-history refusal. Actual
OCR fixtures account for the iPogo logo obscuring part of the inventory title.
The entire new checkmark→inventory sequence is not yet live-verified.

First controller reconnect timed out enabling iOS UI automation; one clean
second setup succeeded. Final signed build installed with 266 passing Python
tests, eight setup tests, and the isolated browser workflow passing. One existing
subsecond timeout test raced its injected alert on one run; its isolated rerun
and the complete suite then passed. The exact “Log in tomorrow to get another
Daily” egg-caption phrase is excluded from the login warning, but genuine log-in
controls still block recovery (regression-tested).

Final app and direct phone reader reconnected successfully. Prepared but did
NOT restart the hunt: the final screenshot showed the map behind an iOS Low
Battery (20%) alert. Asked the user to connect power and close that system
alert. No system-alert bypass or low-power-mode change was attempted. The new
announcement dismissal is live-proven; full checkmark→inventory-X recovery
is automated-test coverage only until another real hatch occurs.

User closed the battery alert and confirmed power setup. Resumed overnight hunt.
Fresh direct Hundo Treecko arrived at 2026-09-30 05:17:44 UTC. Cleanup confirmed
the unobstructed map twice at 05:17:58 and 05:18:10; the Hundo was counted once,
its configured 20-second cooldown completed, and the worker advanced to the
next coordinate. State running, direct reader verified, no refresh error.
Preserved settings: 120-second loading wait, three-failure refresh threshold,
20-second Hundo cooldown. Left the updated overnight hunt running.
No IPA, location-stream, notification-reader, feed, or timing-setting change.

Installed-app backup:
`/Users/benpurles/Library/Application Support/Shundo Hunter/backup-announcement-recovery.1eZ4dW/Shundo Hunter.app`
