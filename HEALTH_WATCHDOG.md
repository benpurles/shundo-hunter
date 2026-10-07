# Overnight weather recovery and health supervision — 2026-09-29

## Latest policy: no separate preflight Hundo test

At the user's request, the overnight checklist no longer requires a manual
Hundo test. A fresh, healthy `iphone-banner` transport may start/resume normal
walking checks without prior alert evidence (`huntReady`). `unattendedReady`
continues to mean actual captured proof; it is NOT set true just to enable Start.
The first real Hundo/Shundo verifies delivery automatically during the hunt.
Missing proof alone does not pause hunting or trigger a watchdog reconnect;
stale/error/stopped readers still block/pause. Unverified bad coordinates still
use the existing loading timeout and refresh policy. The older requirement for
fresh proof before reconnect/resume below is superseded by this policy.

Regression coverage: healthy unverified transport starts walking, bad coordinates
time out without fabricating proof, reader failure pauses, and the watchdog does
not interrupt just because the first Hundo has not arrived. 254 Python tests,
8 UI-planner tests and the isolated browser flow passed. No live hunt was started
to validate this change; no spawn runtime or IPA edits.

## Why the weather popup stopped the hunt

At 05:59:46 UTC, recovery correctly identified the weather warning and its
`I AM SAFE` button. The programmatic startup-notice allowlist rejected that
button; this was not a spawn-runtime or notification-reader failure.

The exact button is now allowed only with independently recognized weather
warning text, matching local OCR button bounds, the existing fresh-screen and
native-dialog safeguards, and Hunter's own active simulated-location process.
Unknown dialogs, permissions, purchases and encounter screens remain blocked.

## Health supervision

Runs on the existing overnight monitor, nominally every 10 seconds (serialized
with phone operations), only after overnight setup. Does not start idle hunts
or resume manual pauses. No separate location stream, worker or AI polling loop.

- Tracks phone-controller/reader availability, live notification proof, worker
  state and per-target phase progress.
- Honors configured coordinate/cooldown budgets, with 25 seconds of watchdog
  grace; the ordinary hunt worker still owns the actual coordinate deadline.
- Existing local screen probes during dwell invoke guarded weather/egg/startup
  recovery when recognized. Routine read-only probes do not replenish dwell.
- Empty queues are reported as waiting for a feed, not as a frozen game.
- Retryable read-only capture failures and stuck phases may queue a clean
  refresh on the existing worker. A blocked system call must return before that
  worker can repair; the watchdog never creates a replacement worker beside it.
- Controller reconnection is restricted to a prepared, technically paused hunt
  with no active vision/recovery work. It revokes old reader proof first; a
  fresh real Hundo must verify the restarted reader before hunting resumes.
- Maximum two technical-recovery attempts until completed-check progress or a
  new run, and six per rolling hour for the current backend process. Backoff
  prevents rapid retries; controller launches receive 90 seconds to start.
  These limits do not replace the user's normal bad-coordinate refresh policy.
- Unknown screens, uncertain tap delivery, locked-phone responses, exhausted
  retries and dead workers require attention. No automatic authentication.
- Protected encounters and pending Shundo alerts block repairs. Refresh also
  checks again immediately before execution, preserving pending alert evidence.

UI: a health summary appears in the hunt timeline. Overnight settings show
last check, last completed coordinate, retry/backoff counts and recent history.
Material recovery actions are also written to the existing hunt event log.
Attention uses the existing Mac notification/alarm, deduplicated per incident.
In-memory history and budgets reset when the backend restarts.

## Verification and limits

249 Python tests passed, including last night's weather result/OCR geometry,
strict weather guards, bounded retries, transport reconnection, manual-pause
protection, dead-worker detection, deadlines, and late Shundo refresh blocking.
JavaScript syntax check and signed native app build passed.

No phone taps, location changes, live hunt, IPA rebuild or live weather popup
test were performed for this update. Regression tests are not proof of an
unattended full-night run. Unknown screens still require manual intervention.
The user's 120-second loading wait and three-failure refresh policy are not
changed by this feature. Keep existing overnight prerequisites: Mac awake on
power (display may sleep), iPhone awake/unlocked in iPogo, and verified direct
Hundo alerts. Health monitoring does not guarantee server/game availability.

Deployment is performed with the hunt idle, overnight disabled, phone
unprepared and no simulated location. The prior installed app is backed up
before replacing it. Do not auto-start a hunt during deployment verification.

Previous installed-app backup:
`/Users/benpurles/Library/Application Support/Shundo Hunter/backup-health-watchdog.Y4gavd/Shundo Hunter.app`

Installed and reopened `/Applications/Shundo Hunter.app`. Post-launch API and
served UI verification passed at 15:58 UTC: health state off, hunt idle, worker
stopped, phone unprepared, overnight disabled, no vision/recovery activity, and
simulated location/delivery null. Loading wait remains 120 seconds; refresh
failure threshold remains 3. Exactly one native Hunter process was present.
