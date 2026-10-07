"""Local, bounded supervision. No model calls, screen taps, or location owner.

Runs on OvernightGuard's monitor. Repairs are either a paired-controller
reconnection or a request to the existing hunt worker. Manual pauses, unknown
screens, disabled setup, and protected encounters cannot auto-resume.
"""
from collections import deque
from datetime import datetime, timezone
import threading
import time


class HealthWatchdog:
    def __init__(self, guard, clock=time.monotonic):
        self.guard, self.clock = guard, clock
        self.lock = threading.RLock()
        self.state, self.detail = "off", "Inactive until overnight setup and a hunt are running."
        self.checked = self.good = None
        self.progress_at = None
        self.history = []
        self.attempts = 0
        self.hourly = deque()
        self.next_attempt = 0
        self.phase_key = self.progress_key = None
        self.phase_since = self.clock()
        self.connection_since = None
        self.notified = set()

    @staticmethod
    def stamp():
        return datetime.now(timezone.utc).isoformat()

    def status(self):
        with self.lock:
            return {"healthState": self.state, "healthDetail": self.detail,
                    "healthLastCheck": self.checked, "healthLastHealthy": self.good,
                    "healthLastProgress": self.progress_at,
                    "healthHourlyAttempts": sum(self.clock()-t < 3600 for t in self.hourly),
                    "healthRecoveryAttempts": self.attempts,
                    "healthRetryAfterSeconds": max(0, int(self.next_attempt-self.clock())),
                    "healthHistory": list(self.history)}

    def report(self, state, detail, *, action=False):
        with self.lock:
            changed = (state, detail) != (self.state, self.detail)
            self.state, self.detail = state, detail
            self.checked = self.stamp()
            if state == "healthy":
                self.good = self.checked
            if changed:
                self.history.append({"at": self.checked, "state": state, "detail": detail})
                self.history = self.history[-30:]
        if changed and action:
            self.guard.hunt.store.record_hunt_event("Health watchdog: " + detail)

    def attention(self, detail):
        self.report("attention", detail, action=True)
        if detail not in self.notified:
            self.notified.add(detail)
            self.guard.hunt.notifier("Hunter health needs attention", detail)
            self.guard.hunt.shundo_alarm()

    def claim_attempt(self, detail):
        now = self.clock()
        while self.hourly and now-self.hourly[0] >= 3600:
            self.hourly.popleft()
        if self.attempts >= 2 or len(self.hourly) >= 6:
            self.attention("Automatic recovery limit reached (2 per incident / 6 per hour). Hunt remains paused; inspect the phone.")
            return False
        if now < self.next_attempt:
            self.report("backoff", "Waiting before the next bounded recovery attempt.")
            return False
        self.attempts += 1
        self.hourly.append(now)
        self.next_attempt = now + (30 if self.attempts == 1 else 60)
        self.report("recovering", detail, action=True)
        return True

    def tick(self):
        g = self.guard
        if not g.active or g.stop_event.is_set():
            self.report("off", "Hunt health checks are off; no automatic actions.")
            return
        s = g.hunt.status()
        if g.protected or s.get("huntState") == "shundo":
            self.report("protected", "Shundo/encounter protected. Health repairs, restarts and location changes are disabled.")
            return
        phase, state = s.get("huntPhase"), s.get("huntState")
        if state == "paused" and phase not in {"paused-alerts", "paused-world"}:
            self.report("paused", "Operator pause respected; no automatic resume.")
            return
        if state == "error" or (state == "running" and not s.get("huntWorkerAlive")):
            self.attention("Hunt worker stopped unexpectedly. Nothing will restart automatically; inspect the phone and resume manually.")
            return
        if not s.get("ipogoPrepared") or not s.get("huntWorkerAlive"):
            self.report("idle", "Waiting for a prepared, active hunt. Nothing will start automatically.")
            return
        if state not in {"running", "paused"}:
            self.attention("Hunt worker is not running normally. Inspect before restarting.")
            return
        watcher = getattr(g.hunt.detector, "watcher", None)
        if watcher is not None and any(e.is_shundo for e in watcher.events_after(g.hunt.detector.status().get("checkpoint", 0))):
            self.attention("A Shundo alert is pending. All health repairs are blocked; location is preserved for the hunt's Shundo handler or manual inspection.")
            return
        now = self.clock()
        progress = (s.get("huntRunStartedAt"), s.get("huntCheckedThisRun", 0))
        if progress != self.progress_key:
            if s.get("huntCheckedThisRun", 0) > 0:
                self.progress_at = self.stamp()
            self.progress_key = progress
            self.attempts = 0
            self.next_attempt = 0
            self.notified.clear()
        key = (s.get("currentTargetId"), phase)
        if key != self.phase_key:
            self.phase_key, self.phase_since = key, now
        n = s.get("notificationWatcher", {})
        controller_failed = g.controller.status().get("catchLabState") == "unavailable"
        transport_failed = n.get("state") in {"error", "stopped"}
        if controller_failed or transport_failed:
            g.hunt.health_pause("Phone alert transport interrupted; waiting for verified reconnection.", alerts=True)
            self.connection_since = self.connection_since if self.connection_since is not None else now
            if now-self.connection_since < 20:
                self.report("waiting", "Temporary phone connection issue; allowing 20 seconds for transport recovery.")
                return
            if g.vision.busy or g.screen_recovery.busy:
                self.report("waiting", "Waiting for in-flight screen work to stop before reconnecting; no concurrent repair.")
                return
            if self.claim_attempt("Reconnecting the existing paired phone controller; a healthy reader is required before resuming."):
                try:
                    g.reconnect_for_health()
                    # Xcode may take a minute to start. Do not overlap launches.
                    self.next_attempt = self.clock() + 90
                    self.report("waiting", "Controller restarted; waiting for the phone alert reader to reconnect.")
                except RuntimeError as error:
                    self.attention(str(error))
            return
        self.connection_since = None
        if not n.get("huntReady", n.get("unattendedReady")):
            g.hunt.health_pause("Notification reader is not ready; waiting for its connection.", alerts=True)
            self.report("waiting-reader", "The selected notification reader is not ready. Reconnect it; no test Hundo is required.")
            if now-self.phase_since > 60:
                self.attention("The notification reader is still unavailable. Hunt remains paused; check the phone connection.")
            return
        if state == "paused" and phase == "paused-world":
            if not s.get("healthRetryablePause"):
                self.attention("Recovery stopped on an unknown/unsafe screen or uncertain action. No automatic dismissal or restart. " + (s.get("ipogoLastRefreshError") or "Inspect the phone."))
                return
            if g.screen_recovery.busy or g.vision.busy:
                self.report("waiting", "Waiting for current screen work to finish before scheduling a refresh.")
                return
            if self.claim_attempt("Requesting a clean refresh on the existing hunt worker; the current coordinate stays preserved."):
                if not g.hunt.health_retry(s.get("currentTargetId")):
                    self.report("waiting", "Recovery request cancelled because hunt state changed; no new worker was started.")
            return
        if state == "paused":
            self.report("waiting", "Reader is connected again; waiting for the hunt worker to resume its alert pause.")
            return
        limits = {"dwelling": float(s.get("huntDwellSeconds", 120))+25,
                  "verifying-world": float(s.get("ipogoRecoveryDwellSeconds", 75))+25,
                  "cooldown": float(s.get("huntHundoCooldownSeconds", 20))+25,
                  "setting-location": 90, "starting": 90, "selecting": 90, "resuming": 90,
                  "resolving-coordinates": 60,
                  "clearing-screen": 240,
                  "restarting-ipogo": 180, "settling-ipogo": 240, "retrying-world": 240}
        if phase in limits and now-self.phase_since > limits[phase]:
            if g.hunt.health_pause("Progress watchdog: the " + phase + " phase exceeded its expected time; requesting bounded recovery."):
                self.report("stalled", "Progress stopped; hunt paused cooperatively before a worker-owned recovery.", action=True)
            return
        if phase in {"waiting", "refreshing-feed"}:
            self.report("waiting-feed", "No eligible coordinate is queued; existing feed refresh remains in charge. This is not a frozen map.")
        else:
            if n.get("unattendedReady"):
                self.report("healthy", "Hunt is progressing within its phase budget; phone alert transport is verified.")
            else:
                self.report("awaiting-alert", "Phone reader connected; hunting normally. No real Hundo captured yet—alert delivery is not verified.")
