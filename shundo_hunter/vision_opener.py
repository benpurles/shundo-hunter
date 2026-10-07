"""One map tap, at most three encounter vision requests, then read-only observation.

Production Shundo selection first uses the separately bounded screen-recovery
preflight. No encounter retries, escape taps, throws, berries, or app launches. Cancellation revokes
future actions, but cannot recall a touch already delivered to the phone.
"""
import base64
from datetime import datetime, timezone
import math
import threading
import time
import xml.etree.ElementTree as ET

from .catch_screen import read_screen
from .encounter_vision import (VisionError, alert_identity, helper, tap_candidate,
                               frame_unchanged, verify_encounter, canonical, CATALOG)


def safe_native_target(source, x, y):
    """Reject native dialogs and UI controls that overlap the proposed sprite."""
    try:
        root = ET.fromstring(source)
        for item in root.iter():
            if item.get("visible") == "false":
                continue
            kind = item.get("type", item.tag)
            if kind in {"XCUIElementTypeAlert", "XCUIElementTypeSheet", "XCUIElementTypeTextField", "XCUIElementTypeSecureTextField"}:
                raise VisionError("A native dialog or input is visible. No map tap sent.")
            if kind in {"XCUIElementTypeButton", "XCUIElementTypeImage", "XCUIElementTypeSwitch"}:
                a, b, w, h = (float(item.get(k, "nan")) for k in ("x", "y", "width", "height"))
                if not all(math.isfinite(n) for n in (a, b, w, h)):
                    raise VisionError("Native control bounds could not be checked.")
                if a - 12 <= x <= a + w + 12 and b - 12 <= y <= b + h + 12:
                    raise VisionError("Candidate overlaps a native iPogo control. No tap sent.")
    except (ET.ParseError, TypeError, ValueError):
        raise VisionError("Could not inspect native controls. No tap sent.") from None


class VisionOpener:
    def __init__(self, guard, client):
        self.guard, self.client = guard, client
        self.generation = 0
        self.busy = False
        self.stage = "off"
        self.evidence = []
        self.verified = False
        self.thread = None
        self.deadline = 0
        self.supervised = False

    def status(self):
        with self.guard.lock:
            return {**self.client.status(), "visionBusy": self.busy, "visionStage": self.stage,
                    "visionEvidence": list(self.evidence), "visionShundoEvidenceMatched": self.verified}

    def _record(self, stage, detail, result=None):
        with self.guard.lock:
            self.stage = stage
            self.evidence.append({"at": datetime.now(timezone.utc).isoformat(), "stage": stage,
                                  "detail": detail, **({"result": result} if result is not None else {})})
            self.evidence = self.evidence[-12:]

    def cancel(self):
        # Caller holds operation_lock: serialized with the final touch guard.
        with self.guard.lock:
            self.generation += 1
            self.verified = False
        self._record("cancelled", "No further taps will be sent. An already delivered tap cannot be recalled.")
        if self.guard.protected:
            self.guard.state = "attention"
            self.guard.detail = "AI opening cancelled. Encounter protection remains locked; inspect the phone."

    def _check(self, generation):
        if generation != self.generation or self.guard.stop_event.is_set():
            raise VisionError("AI task cancelled.")
        if not self.guard.active or time.monotonic() >= self.deadline:
            raise VisionError("AI opening deadline or display-off setup ended.")
        if self.guard.power is None or self.guard.power.poll() is not None:
            raise VisionError("Mac wake protection ended.")
        if not self.client.status()["visionConfigured"]:
            raise VisionError("AI permission or configuration was revoked.")

    def start(self, *, event=None, target=None, species=None, supervised=False, confirmed=False):
        # All entry points hold operation_lock. No cloud I/O on caller thread.
        if self.busy:
            raise VisionError("An AI inspection is still finishing. Cancel and wait before starting another.")
        if not self.guard.active or not self.client.status()["visionConfigured"]:
            raise VisionError("Set up direct alerts and enable AI with an API key first.")
        readonly = event is None and not supervised
        if event is None:
            status = self.guard.hunt.status()
            if status["huntWorkerAlive"] or status["huntState"] not in {"idle", "shundo"}:
                raise VisionError("Stop hunting before a read-only AI screen test.")
            names = [name for name in CATALOG if canonical(name) == canonical(species)]
            if len(names) != 1:
                raise VisionError("Enter a recognized Pokémon species for the screen test.")
            expected = {"species": names[0], "cp": None}
            if supervised:
                if confirmed is not True or status["huntState"] != "idle" or status.get("ipogoPrepared") or self.guard.protected:
                    raise VisionError("One-opening test requires explicit confirmation, an idle/unprepared hunt, and no protected encounter.")
                if self.guard.device.status().get("phoneMovementMode") == "walking-circle":
                    raise VisionError("Stop walking before the supervised opening test.")
                self.guard.protected = True
                self.guard.state = "opening"
                self.guard.detail = "Supervised ordinary encounter test. One map tap at most; no Shundo claim, catch, throw or berry."
                self.guard.event = {"mode": "supervised", "species": expected["species"], "tapConsumed": False,
                                    "receivedAt": datetime.now(timezone.utc).isoformat()}
                self.guard._save()
        else:
            if supervised:
                raise VisionError("Production Shundo alerts cannot use supervised verification.")
            expected = alert_identity(event.message, target)
            try:
                received = datetime.fromisoformat(event.received_at.replace("Z", "+00:00"))
                age = (datetime.now(timezone.utc) - received).total_seconds()
            except (ValueError, TypeError, AttributeError):
                raise VisionError("Alert timestamp is invalid; no automatic opening.") from None
            if not 0 <= age <= 30:
                raise VisionError("Shundo alert is stale; no automatic opening.")
            if not self.guard.protected or self.guard.hunt.status()["huntState"] != "shundo":
                raise VisionError("Hunt must be stopped and locked on the Shundo alert.")
            if self.guard.event.get("tapConsumed"):
                raise VisionError("This alert already used its one map tap.")
        self.generation += 1
        self.supervised = supervised
        generation = self.generation
        self.deadline = time.monotonic() + (330 if event is not None else 150)
        self.busy, self.verified, self.evidence = True, False, []
        self._record("starting", f"{'Read-only test' if readonly else 'One-tap opener'} · {expected['species']}. At most {'one' if readonly else 'two' if supervised else 'three'} encounter AI requests." + (" Plus bounded screen recovery: up to 8 images / 6 allowlisted dismissals." if event is not None else ""))
        self.thread = threading.Thread(target=self._run, args=(generation, expected, readonly), name="shundo-vision", daemon=True)
        self.thread.start()
        return self.status()

    def _capture(self, generation):
        self._check(generation)
        controller = self.guard.controller
        controller._foreground()
        info = controller._request("GET", "/wda/activeAppInfo")["value"]
        if info.get("bundleId") != controller.BUNDLE_ID or not info.get("pid"):
            raise VisionError("iPogo is not verifiably in the foreground.")
        raw = controller._request("GET", "/screenshot")["value"]
        png = base64.b64decode(raw, validate=True)
        frame = helper("frame", png)
        local = read_screen(png)
        after = controller._request("GET", "/wda/activeAppInfo")["value"]
        if (info.get("bundleId"), info.get("pid")) != (after.get("bundleId"), after.get("pid")):
            raise VisionError("The foreground app changed during capture.")
        frame["pid"] = info["pid"]
        self._check(generation)
        return frame, local

    def _ask(self, generation, stage, frame, expected):
        self._check(generation)
        result = self.client.analyze(stage, frame, expected)
        self._check(generation)
        self._record(stage, "AI response received. Local safety checks still apply.", result)
        return result

    def _tap(self, generation, first, fresh, result, expected):
        with self.guard.operation_lock:
            self._check(generation)
            status = self.guard.hunt.status()
            correct_hold = (status["huntState"] == "idle" and not status["huntWorkerAlive"] and not status.get("ipogoPrepared") and self.guard.event.get("mode") == "supervised") if self.supervised else status["huntState"] == "shundo"
            if not self.guard.protected or not correct_hold:
                raise VisionError("Shundo hold changed; no tap sent.")
            if self.guard.event.get("tapConsumed"):
                raise VisionError("Map tap budget already consumed.")
            point = tap_candidate(result, expected, first)
            if first["pid"] != fresh["pid"] or not frame_unchanged(first, fresh, result["target_box"]):
                raise VisionError("Screen moved while the AI was thinking. No tap sent; inspect manually.")
            controller = self.guard.controller
            controller._foreground()
            if not controller.session_id:
                response = controller._request("POST", "/session", {"capabilities": {"alwaysMatch": {
                    "shouldTerminateApp": False, "forceAppLaunch": False,
                    "waitForIdleTimeout": 0, "shouldWaitForQuiescence": False}}})
                controller.session_id = response.get("sessionId") or response.get("value", {}).get("sessionId")
            sid = controller.session_id
            if not isinstance(sid, str) or not sid:
                raise VisionError("Could not establish a no-launch phone session.")
            size = controller._request("GET", f"/session/{sid}/window/size")["value"]
            w, h = size["width"], size["height"]
            if not 250 <= w <= 1500 or not w < h <= 3000 or abs(w/h - fresh["pixelWidth"]/fresh["pixelHeight"]) > .005:
                raise VisionError("Phone geometry changed. No tap sent.")
            x, y = round(point[0]*w), round(point[1]*h)
            source = controller._request("GET", f"/session/{sid}/source")["value"]
            safe_native_target(source, x, y)
            # Source/session queries can be slow. Recapture immediately before
            # touching and reject any intervening encounter, app or map change.
            latest, local = self._capture(generation)
            if local.get("scene") in {"encounter", "caught", "fled"} or latest["pid"] != fresh["pid"] or not frame_unchanged(fresh, latest, result["target_box"]):
                raise VisionError("Screen changed before touch delivery. No tap sent.")
            self._check(generation)
            self.guard.event["tapConsumed"] = True
            self.guard._save()  # Durable BEFORE delivery, including a timeout.
            self._record("tap", "One map tap budget consumed. No retries, throws, berries or dismissals.")
            controller._request("POST", f"/session/{sid}/actions", {"actions": [{"type": "pointer", "id": "open-encounter",
                "parameters": {"pointerType": "touch"}, "actions": [
                    {"type": "pointerMove", "duration": 0, "x": x, "y": y, "origin": "viewport"},
                    {"type": "pointerDown", "button": 0}, {"type": "pause", "duration": 60},
                    {"type": "pointerUp", "button": 0}]}]})

    def _run(self, generation, expected, readonly):
        try:
            first, local = self._capture(generation)
            if readonly:
                stage = "verify" if local.get("scene") == "encounter" else "locate"
                result = self._ask(generation, stage, first, expected)
                if stage == "locate":
                    try:
                        tap_candidate(result, expected, first)
                        detail = "Map selection passed species, unique-candidate and image-bound checks. No tap sent; live screen-stability/native-control checks and encounter proof remain separate."
                    except VisionError as error:
                        detail = "Map selection blocked: " + str(error)
                    self._record("selection-check", detail)
                self._record("test-complete", "Read-only test complete. No taps; this does NOT certify a Shundo or overnight reliability.")
                return
            if local.get("scene") != "encounter":
                recovery = getattr(self.guard, "screen_recovery", None)
                if recovery is not None and not self.supervised:
                    self._record("recovering-screen", "Checking for a startup notice or egg before locating the Shundo.")
                    recovery.run("Shundo preflight", lambda: self._check(generation), protected=True)
                    first, local = self._capture(generation)
                    if local.get("scene") == "encounter":
                        raise VisionError("An encounter appeared during recovery. Left untouched.")
                result = self._ask(generation, "locate", first, expected)
                fresh, local = self._capture(generation)
                if local.get("scene") == "encounter":
                    raise VisionError("An encounter appeared before the planned map tap. Left untouched.")
                self._tap(generation, first, fresh, result, expected)
            # Read-only after this point, even if we opened the wrong Pokémon.
            until = time.monotonic() + 15
            while True:
                frame, local = self._capture(generation)
                if local.get("scene") == "encounter":
                    break
                if time.monotonic() >= until:
                    raise VisionError("No readable encounter appeared after the one allowed tap.")
                self.guard.stop_event.wait(1)
            cp = None
            for verification_index in range(2):
                # Ordinary calibration needs one AI identity reading and two
                # local corroborating frames. Production retains two separate
                # AI Shundo verifications. Never describe cached evidence as a
                # second AI reading.
                if not self.supervised or verification_index == 0:
                    result = self._ask(generation, "identity" if self.supervised else "verify", frame, expected)
                current = verify_encounter(result, expected, local, require_shundo=not self.supervised)
                if cp is not None and cp != current:
                    raise VisionError("Encounter changed between verification frames.")
                cp = current
                self.guard.stop_event.wait(1)
                frame, local = self._capture(generation)
            if local.get("scene") != "encounter" or local.get("cp") != cp:
                raise VisionError("Encounter changed after verification.")
            with self.guard.operation_lock:
                self._check(generation)
                with self.guard.lock:
                    self.guard.cp = cp
                    self.guard.state = "holding"
                    self.guard.last_checked = datetime.now(timezone.utc).isoformat()
                    self.guard.detail = (f"Supervised test opened {expected['species']} · CP {cp}. One AI identity reading matched two local frames. Read-only hold; shiny/IV NOT verified. No catch or stats change." if self.supervised else f"Two frames matched visible Shundo evidence for {expected['species']} · CP {cp}. Read-only hold; AI can be wrong. You catch manually.")
                    self.verified = not self.supervised
                self.guard._save()
                self._record("holding", self.guard.detail)
        except Exception as error:
            # Never expose raw transport exceptions, request bodies or secrets.
            detail = str(error) if isinstance(error, VisionError) else "Phone/image inspection failed. No automatic retry; inspect the phone."
            with self.guard.operation_lock:
                if generation == self.generation:
                    self._record("attention", detail)
                    if not readonly:
                        with self.guard.lock:
                            self.guard.state, self.guard.detail = "attention", detail + " Encounter protection remains locked."
                        try:
                            self.guard.hunt.shundo_alarm()
                            self.guard.hunt.notifier("Opening test needs inspection" if self.supervised else "Shundo needs inspection", detail)
                        except Exception:
                            pass
        finally:
            with self.guard.lock:
                self.busy = False
