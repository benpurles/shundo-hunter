"""Display-off alert setup, optional one-tap AI opening, read-only holding."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import threading
import time

from .catch_lab import CatchLab
from .catch_screen import read_screen
from .encounter_vision import VisionClient
from .vision_opener import VisionOpener
from .screen_recovery import ScreenRecovery, RecoveryCancelled
from .health_watchdog import HealthWatchdog


class OvernightGuard:
    def __init__(self, hunt, device, journal: Path):
        self.hunt, self.device, self.journal = hunt, device, journal
        self.lock = threading.RLock()
        self.controller = CatchLab(lambda: True)  # private: no throw endpoint
        self.power = None
        self.active = False
        self.protected = False
        self.state = "off"
        self.detail = "Not configured. AI opening is optional and disabled until explicitly enabled."
        self.cp = None
        self.last_checked = None
        self.event = None
        self.deadline = None
        self.stop_event = threading.Event()
        self.operation_lock = threading.RLock()
        self.vision = VisionOpener(self, VisionClient(journal.with_suffix(".vision.json")))
        self.screen_recovery = ScreenRecovery(self)
        self.health = HealthWatchdog(self)
        try:
            saved = json.loads(journal.read_text())
            if not isinstance(saved, dict):
                raise ValueError("Invalid hold journal")
            if saved.get("protected"):
                self.protected = True
                self.state = "attention"
                self.detail = "A protected encounter was recorded before restart. Inspect the phone; monitoring is OFF. Release explicitly before changing location."
                self.event = saved.get("event")
        except FileNotFoundError:
            pass
        except (ValueError, OSError):
            self.protected = True
            self.state = "attention"
            self.detail = "Hold journal could not be read. Inspect the phone and explicitly release protection."
        self.thread = threading.Thread(target=self._monitor, name="encounter-guard", daemon=True)
        self.thread.start()

    def _save(self):
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.journal.with_suffix(".pending")
        temporary.write_text(json.dumps({"protected": self.protected, "event": self.event}))
        os.replace(temporary, self.journal)

    def require_unprotected(self):
        with self.lock:
            if self.protected:
                raise RuntimeError("Encounter protection is locked. Catch manually, then choose Release encounter protection in Settings.")

    def latch_shundo(self):
        # Called while the coordinator marks the target found, closing the
        # gap before the slower stationary-location transition.
        with self.lock:
            if self.active:
                self.protected = True

    def require_hunt_ready(self):
        self.require_unprotected()
        if self.active:
            if self.state != "setup" or self.power is None or self.power.poll() is not None or time.monotonic() >= self.deadline:
                raise RuntimeError("Display-off setup needs attention. End setup and reconnect before hunting.")
            self.controller._foreground()

    def begin(self, auto_lock_confirmed: bool):
        with self.operation_lock:
            self.require_unprotected()
            status = self.hunt.status()
            if status["huntState"] != "idle" or status["huntWorkerAlive"] or status["ipogoPrepared"]:
                raise RuntimeError("Stop and end preparation before starting display-off setup.")
            if not auto_lock_confirmed:
                raise RuntimeError("Confirm iPhone Auto-Lock is Never and it is charging first.")
            if self.active:
                return self.status()
            self.hunt.configure_alert_source("direct")
            try:
                phone = self.device.refresh()
                if not phone.get("phoneConnected"):
                    raise RuntimeError("Connect the paired iPhone over Wi-Fi or USB first.")
                self.controller.start_helper(self.device.executable, phone["phoneUdid"],
                                             native_wifi=phone.get("phoneNativeWifi", False),
                                             session_seconds=43200)
                # No -d or -u: prevent system sleep, not display sleep. Scope to
                # this backend and a maximum 12 hours; do not change pmset prefs.
                self.power = subprocess.Popen(["/usr/bin/caffeinate", "-i", "-s", "-t", "43200", "-w", str(os.getpid())],
                                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                              stderr=subprocess.DEVNULL)
                with self.lock:
                    self.active = True
                    self.deadline = time.monotonic() + 43200
                    self.state = "setup"
                    self.detail = "Direct iPhone banner reader selected. Prepare iPogo, then start the walking hunt—no separate Hundo test. The first real alert verifies delivery. Mac mirroring is not used. AI opening requires its saved opt-in and API key; otherwise open encounters manually."
            except Exception:
                self.controller.close()
                self._stop_power()
                self.hunt.configure_alert_source("mac")
                raise
            return self.status()

    def on_shundo(self, target, event):
        with self.operation_lock:
            with self.lock:
                if not self.active:
                    return
                if self.vision.busy or self.state in {"opening", "holding"} or (self.event and self.event.get("receivedAt") == event.received_at):
                    return  # A duplicate alert must not reset the one-tap journal.
                # Persist the interlock before any location operation.
                self.protected = True
                self.state = "needs-opening"
                self.event = {"target": dict(target), "alert": event.message, "receivedAt": event.received_at}
                self.detail = "Shundo alert received. Hunt locked. Open the correct Pokémon manually, then choose Protect open encounter. No encounter has been automatically opened or verified."
            try:
                self._save()
                if self.hunt.status()["huntState"] == "shundo":
                    self.device.set_location(float(target["latitude"]), float(target["longitude"]))
                else:
                    raise RuntimeError("An operator stop overlapped the alert; location was left unchanged")
                if self.vision.client.status()["visionConfigured"]:
                    self.state = "opening"
                    self.detail = "Shundo alert locked. AI is inspecting the screen; at most one map tap, then observation only."
                    self.vision.start(event=event, target=target)
            except Exception as error:
                with self.lock:
                    self.state = "attention"
                    self.detail = f"Shundo stop protected; automatic opening unavailable: {error}. Inspect the phone."

    def _read(self):
        self.controller._foreground()
        screenshot = self.controller._request("GET", "/screenshot")["value"]
        result = read_screen(base64.b64decode(screenshot, validate=True))
        self.controller._foreground()
        return result

    def recover_hunt_screen(self, reason, check, *, probe=False, after_hundo=False):
        if not self.active or not self.vision.client.status()["visionConfigured"]:
            return
        def current():
            check()
            if self.protected or self.vision.busy or self.stop_event.is_set():
                raise RecoveryCancelled("Shundo/encounter work takes priority over routine recovery.")
            # Observe, never consume, pending alerts. The hunt worker processes
            # a Shundo immediately after recovery yields back to its poll loop.
            detector = self.hunt.detector
            watcher = getattr(detector, "watcher", None)
            if watcher is not None and any(e.is_shundo or (e.is_hundo and not after_hundo)
                                          for e in watcher.events_after(detector.status().get("checkpoint", 0))):
                # Ordinary alerts yield once, then the worker retains that
                # proof and resumes cleanup before changing coordinates.
                self.screen_recovery.next_probe = 0
                raise RecoveryCancelled("A Hundo/Shundo alert is pending; returning it to the hunt immediately.")
        if probe and not self.screen_recovery.resume_pending:
            if time.monotonic() < self.screen_recovery.next_probe:
                return
            self.screen_recovery.next_probe = time.monotonic() + 15
            from .screen_recovery import egg_hint, notice_hint
            _, local = self.screen_recovery._capture(current)
            if local.get("scene") in {"encounter", "caught", "fled", "blocked-ball"}:
                raise RuntimeError("An encounter/result is open. Hunting must remain paused; no recovery touch sent.")
            if not egg_hint(local) and not notice_hint(local):
                return  # Local-only check; no cloud image for ordinary maps.
        self.screen_recovery.run(reason, current)

    def start_screen_recovery(self):
        if self.screen_recovery.busy or self.vision.busy or not self.active:
            raise RuntimeError("Set up the phone controller and finish existing AI work first.")
        self.require_unprotected()
        def check():
            s = self.hunt.status()
            if s["huntState"] != "idle" or s["huntWorkerAlive"] or s["ipogoPrepared"]:
                raise RecoveryCancelled("End hunt preparation before manually recovering the screen.")
        check()
        def work():
            try:
                self.screen_recovery.run("Manual screen recovery", check)
            except RuntimeError:
                pass  # The recovery panel retains the actual failure.
        threading.Thread(target=work, name="manual-screen-recovery", daemon=True).start()
        return self.status()

    def protect_open_encounter(self):
        with self.operation_lock:
            if self.vision.busy or self.screen_recovery.busy:
                raise RuntimeError("Cancel AI inspection and wait for it to finish first.")
            if not self.active:
                raise RuntimeError("Start display-off setup first.")
            status = self.hunt.status()
            if status["huntWorkerAlive"] or status["huntState"] not in {"idle", "shundo"}:
                raise RuntimeError("Stop hunting before protecting an open encounter.")
            first = self._read()
            time.sleep(1)
            second = self._read()
            if first.get("scene") != "encounter" or second.get("scene") != "encounter" or not first.get("cp") or first.get("cp") != second.get("cp"):
                raise RuntimeError("Could not verify two matching encounter frames. No touches were sent.")
            with self.lock:
                self.protected = True
                self.state = "holding"
                self.cp = second["cp"]
                self.vision.verified = False
                self.detail = f"Open encounter observed · CP {self.cp}. Read-only monitoring; shiny/IV identity is NOT verified. No throws, berries, or dismissals."
                self.last_checked = datetime.now(timezone.utc).isoformat()
            self._save()
            location = self.device.status().get("phoneSimulatedLocation")
            if location and self.device.status().get("phoneMovementMode") == "walking-circle":
                try:
                    self.device.set_location(float(location["latitude"]), float(location["longitude"]))
                except Exception as error:
                    with self.lock:
                        self.state = "attention"
                        self.detail = f"Encounter controls locked, but walking could not be stopped: {error}"
            return self.status()

    def release(self):
        with self.operation_lock:
            status = self.hunt.status()
            if status["huntWorkerAlive"] or status["huntState"] in {"running", "paused"}:
                raise RuntimeError("Stop and end preparation before ending display-off setup.")
            # Releasing removes software protection only. It does NOT dismiss
            # the phone encounter, clear location, resume hunting, or catch.
            self.vision.cancel()
            self.screen_recovery.cancel()
            with self.lock:
                self.protected = False
                self.active = False
                self.state = "off"
                self.detail = "Protection released. The phone screen and location were left unchanged."
            self._save()
            self.controller.close()
            self._stop_power()
            return self.status()

    def _stop_power(self):
        if self.power is not None:
            if self.power.poll() is None:
                self.power.terminate()
                try:
                    self.power.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.power.kill()
                    self.power.wait(timeout=3)
            self.power = None

    def _monitor(self):
        while not self.stop_event.wait(10):
            with self.operation_lock:
                if not self.active:
                    self.health.tick()
                    continue
                try:
                    if self.power is None or self.power.poll() is not None or time.monotonic() >= self.deadline:
                        raise RuntimeError("Mac wake protection ended. Inspect the phone; unattended operation is no longer safe.")
                    if self.protected and self.controller.status()["catchLabState"] == "unavailable":
                        raise RuntimeError("Wi-Fi phone controller ended. Inspect the phone.")
                    self.health.tick()
                    if self.state == "holding":
                        sample = self._read()
                        if sample.get("scene") != "encounter" or sample.get("cp") != self.cp:
                            raise RuntimeError("The protected encounter is no longer verifiable. No recovery or taps were attempted.")
                        with self.lock:
                            self.last_checked = datetime.now(timezone.utc).isoformat()
                except Exception as error:
                    with self.lock:
                        newly_failed = self.state != "attention"
                    if newly_failed:
                        self.vision.cancel()
                    with self.lock:
                        self.state = "attention"
                        self.detail = str(error)
                    self.health.report("attention", str(error), action=True)
                    if self.stop_event.is_set():
                        return
                    try:
                        if self.hunt.status()["huntState"] == "running":
                            self.hunt.pause()
                        if newly_failed:
                            self.hunt.shundo_alarm()
                            self.hunt.notifier("Hunter needs attention", self.detail)
                    except RuntimeError:
                        pass  # A concurrent operator stop must not kill monitoring.

    def reconnect_for_health(self):
        """Reconnect only our paired controller while the worker is safely paused."""
        with self.operation_lock:
            def check():
                s = self.hunt.status()
                if (not self.active or self.stop_event.is_set() or self.protected
                        or self.vision.busy or self.screen_recovery.busy
                        or not s.get("ipogoPrepared") or not s.get("huntWorkerAlive")
                        or s.get("huntState") != "paused"
                        or not (s.get("huntPhase") == "paused-alerts" or s.get("healthRetryablePause"))):
                    raise RuntimeError("Controller repair cancelled: hunt state/protection changed.")
                watcher = getattr(self.hunt.detector, "watcher", None)
                if watcher is not None and any(e.is_shundo for e in watcher.events_after(self.hunt.detector.status().get("checkpoint", 0))):
                    raise RuntimeError("Shundo alert pending; controller repair is blocked.")
            check()
            try:
                info = self.controller._request("GET", "/wda/hunter/notifications").get("value", {})
            except RuntimeError:
                info = None
            if info is not None and info.get("screenLocked") is not False:
                raise RuntimeError("iPhone is locked; unlock it manually. No automatic authentication or repair attempted.")
            phone = self.device.refresh()
            check()
            if not phone.get("phoneConnected"):
                raise RuntimeError("Paired iPhone is disconnected. Reconnect it; no location or pairing change attempted.")
            # Revoke transport proof BEFORE closing the controller, so an
            # alert-pause cannot auto-resume during its replacement.
            self.hunt.detector.watcher.stop()
            check()
            self.controller.close()
            check()
            self.controller.start_helper(self.device.executable, phone["phoneUdid"],
                                         native_wifi=phone.get("phoneNativeWifi", False),
                                         session_seconds=max(60, min(43200, int(self.deadline-time.monotonic()))))
            # Explicitly drop previous transport proof. The existing reader
            # must reconnect healthily; the next real banner verifies delivery.
            self.hunt.detector.watcher.start(phone["phoneUdid"])

    def status(self):
        with self.lock:
            return {"overnightActive": self.active, "encounterProtected": self.protected,
                    "overnightState": self.state, "overnightDetail": self.detail,
                    **self.vision.status(),
                    **self.screen_recovery.status(),
                    **self.health.status(),
                    "overnightAutomaticOpeningReady": self.active and self.vision.client.status()["visionConfigured"] and self.state == "setup",
                    "overnightMacAwake": bool(self.power and self.power.poll() is None),
                    "overnightLastScreenCheck": self.last_checked,
                    "overnightEncounterCP": self.cp,
                    "overnightSecondsRemaining": max(0, int(self.deadline - time.monotonic())) if self.active and self.deadline else 0}

    def close(self):
        self.stop_event.set()
        self.screen_recovery.cancel()
        with self.operation_lock:
            self.vision.cancel()
        if self.vision.thread:
            self.vision.thread.join(timeout=35)
        self.thread.join(timeout=35)
        self.controller.close()
        self._stop_power()
        # Keep the protection journal on shutdown; restart must not auto-resume.
