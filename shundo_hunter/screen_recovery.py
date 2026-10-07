"""Bounded, allowlisted screen recovery. Never opens/catches a map Pokémon.

Triggers: post-refresh, local egg OCR during dwell, Shundo opening preflight.
No recurring cloud scan. At most 8 images / 6 taps / 180 seconds per recovery,
60 images per rolling hour. Uncertain delivery is NEVER retried.
"""
import base64
from collections import deque
from datetime import datetime, timezone
import math
import re
import threading
import time
import xml.etree.ElementTree as ET

from .catch_screen import read_screen
from .encounter_vision import VisionError, helper, validate_result, frame_unchanged


class RecoveryCancelled(VisionError):
    pass


class ScreenChanged(VisionError):
    pass


class ObservationUnavailable(VisionError):
    """Read-only failure eligible for bounded worker-owned recovery."""


def egg_hint(local):
    return any(re.fullmatch(r"oh\s*\?+|(?:an?\s+)?egg (?:is )?hatching[.!]*", str(line).strip(), re.I)
               for line in local.get("evidence", []))


def notice_hint(local):
    text = " ".join(local.get("evidence", [])).casefold()
    return bool(re.search(r"aware of your surroundings|weather warning|weather conditions|extreme weather|going too fast", text)) or announcement_hint(local)


def announcement_hint(local):
    # News text is not itself authority to touch. Require both of the actual
    # card's controls; recovery_point separately verifies the Dismiss bounds.
    labels = {str(row.get("text", "")).strip().casefold() for row in local.get("lines", [])}
    return {"see details", "dismiss"} <= labels


def recovery_point(result, frame, local, hatch_seen, hatch_details_closed=False):
    validate_result(result, "recover")
    scene, action, box = result["scene"], result["action"], result["target_box"]
    if result["uncertainty"].strip() or not result["evidence"].strip():
        raise VisionError("Recovery screen is ambiguous; no dismissal allowed.")
    if local.get("scene") in {"encounter", "caught", "fled", "blocked-ball"} or scene == "encounter":
        raise VisionError("An encounter/result is open. Recovery will not touch it.")
    if scene == "map" and action == "none" and box is None:
        return None
    if scene in {"egg_animation", "loading", "hatch_reveal"} and action == "wait" and box is None:
        return None
    allowed = {"startup_notice": "dismiss_notice", "announcement": "dismiss_announcement", "egg_prompt": "tap_egg",
               "hatch_reveal": "advance_hatch", "pokemon_details": "close_hatched_details",
               "egg_inventory": "close_hatch_inventory"}
    if allowed.get(scene) != action or box is None:
        raise VisionError("This screen/action is not on the recovery allowlist.")
    text = " ".join(local.get("evidence", [])).casefold()
    # This exact informational egg caption is not a sign-in control. Any
    # other log-in/consent text still blocks, including on egg inventory.
    safety_text = re.sub(r"\blog in tomorrow to get another daily\b", "", text) if scene == "egg_inventory" else text
    if re.search(r"terms of|privacy policy|sign in|log in|permission|allow access|purchase|buy now|delete account", safety_text):
        raise VisionError("Account, consent or purchase dialog needs manual attention.")
    label = result["control_text"].strip().casefold().replace("’", "'")
    if scene == "announcement" and (label != "dismiss" or not announcement_hint(local)):
        raise VisionError("News dismissal requires the visible See Details and Dismiss controls.")
    if scene == "startup_notice":
        ordinary = re.search(r"aware of your surroundings|weather conditions|extreme weather", text) and label in {"ok", "okay", "close", "dismiss"}
        teleport_speed = "going too fast" in text and label == "i'm a passenger"
        weather_safe = bool(re.search(r"weather warning|weather conditions|extreme weather", text)) and label == "i am safe"
        if not (ordinary or teleport_speed or weather_safe):
            raise VisionError("Startup notice is not a recognized surroundings/weather acknowledgment.")
    if scene == "egg_prompt" and not egg_hint(local):
        raise VisionError("Local OCR cannot corroborate the full-screen hatch prompt.")
    if scene in {"hatch_reveal", "pokemon_details"} and not hatch_seen:
        raise VisionError("No observed hatch sequence authorizes closing this Pokémon page.")
    if scene == "hatch_reveal" and label not in {"ok", "okay", "continue", "next"}:
        raise VisionError("Hatch reveal has no explicit continuation control.")
    if scene == "pokemon_details":
        # A new weight record replaces the WEIGHT caption with LIGHTEST or
        # HEAVIEST, but the measured kg value and HEIGHT remain visible.
        weight = "weight" in text or (re.search(r"\b\d+(?:[.,]\d+)?\s*kg\b", text)
                                       and ("lightest" in text or "heaviest" in text))
        if label not in {"x", "close", "×", "✓", "✔", "checkmark"} or not (weight and "height" in text):
            raise VisionError("Newly hatched detail page is not locally corroborated.")
    if scene == "egg_inventory":
        distances = re.findall(r"\b\d+(?:[.,]\d+)?\s*/\s*(?:2|5|7|10|12)\s*km\b", text)
        inventory_copy = ("incubate eggs" in text or "bonus storage" in text
                          or ("pokémon go is closed" in text and "adventure egg" in text))
        if not (hatch_seen and hatch_details_closed and label in {"x", "×", "close"}
                and len(distances) >= 2 and inventory_copy):
            raise VisionError("Egg inventory may close only after this observed hatch's detail page was dismissed.")
    max_width = .85 if scene == "startup_notice" else .7
    if not .018 <= box["width"] <= max_width or not .012 <= box["height"] <= .55:
        raise VisionError("Recovery control dimensions are unsafe.")
    x = box["x"] + box["width"] / 2
    y = frame["cropTop"] + (box["y"] + box["height"] / 2) * frame["cropHeight"]
    if not .08 < x < .92 or not .18 < y < (.975 if scene == "announcement" else .955):
        raise VisionError("Recovery point overlaps protected phone edges.")
    if scene == "announcement" and not (.35 < x < .65 and .90 < y < .975
                                          and box["width"] <= .4 and box["height"] <= .08):
        raise VisionError("Only the bottom-center news Dismiss control is permitted.")
    if scene == "egg_prompt" and not (.2 < x < .8 and .3 < y < .8):
        raise VisionError("The hatch egg is not in the central prompt area.")
    if scene in {"pokemon_details", "egg_inventory"} and not (.35 < x < .65 and .84 < y < .955):
        raise VisionError("Only the bottom-center hatch-detail close control is permitted.")
    if scene in {"startup_notice", "hatch_reveal", "announcement"}:
        # Independently locate the named button in OCR, not just the AI box.
        if not any(str(row.get("text", "")).strip().casefold().replace("’", "'") == label
                   and abs(float(row.get("x", -1)) + float(row.get("width", 0))/2 - x) < .12
                   and abs(float(row.get("y", -1)) + float(row.get("height", 0))/2 - y) < (.02 if scene == "announcement" else .05)
                   for row in local.get("lines", [])):
            raise VisionError("The recovery button is not corroborated by local text/bounds.")
    return x, y


def native_recovery_guard(source):
    try:
        for node in ET.fromstring(source).iter():
            if node.get("visible") == "false":
                continue
            if node.get("type", node.tag) in {"XCUIElementTypeAlert", "XCUIElementTypeSheet", "XCUIElementTypeTextField", "XCUIElementTypeSecureTextField"}:
                raise VisionError("Native system dialog/input is visible; recovery cannot dismiss it.")
    except ET.ParseError:
        raise VisionError("Native dialog inspection failed.") from None


class ScreenRecovery:
    def __init__(self, guard):
        self.guard = guard
        self.lock = threading.RLock()
        self.busy = False
        self.generation = 0
        self.state = "idle"
        self.detail = "Automatic recovery follows refreshes and checks for egg prompts while hunting."
        self.evidence = []
        self.calls = deque()
        self.next_probe = 0
        self.resume_pending = False
        self.resume_action = None
        self.resume_pid = None
        self.hatch_process = None
        self.hatch_details_closed = False
        self.hatch_observed_at = 0

    def status(self):
        with self.lock:
            return {"screenRecoveryBusy": self.busy, "screenRecoveryState": self.state,
                    "screenRecoveryDetail": self.detail, "screenRecoveryEvidence": list(self.evidence)}

    def record(self, state, detail, result=None):
        with self.lock:
            self.state, self.detail = state, detail
            self.evidence.append({"at": datetime.now(timezone.utc).isoformat(), "stage": state,
                                  "detail": detail, **({"result": result} if result else {})})
            self.evidence = self.evidence[-20:]

    def cancel(self):
        with self.lock:
            self.generation += 1

    def _capture(self, check):
        # Notification banners can temporarily change WDA's active-app
        # selection. Only retry read-only observation, never a delivered tap.
        until = time.monotonic() + 10
        for attempt in range(8):
            check()
            try:
                return self._capture_once(check)
            except RecoveryCancelled:
                raise
            except (RuntimeError, ValueError, KeyError, TypeError) as error:
                check()  # Let real alerts/cancellation win over a read failure.
                if attempt == 7 or time.monotonic() >= until:
                    raise ObservationUnavailable(f"Screen observation unavailable ({type(error).__name__}): {str(error)[:200]}") from None
                self.record("waiting", f"Temporary screen observation failure ({type(error).__name__}); retrying observation only.")
                self.guard.stop_event.wait(1)

    def _capture_once(self, check):
        check()
        c = self.guard.controller
        c._foreground()
        before = c._request("GET", "/wda/activeAppInfo")["value"]
        if before.get("bundleId") != c.BUNDLE_ID or not before.get("pid"):
            raise VisionError("Recovery requires iPogo in the foreground.")
        png = base64.b64decode(c._request("GET", "/screenshot")["value"], validate=True)
        frame, local = helper("recovery-frame", png), read_screen(png)
        after = c._request("GET", "/wda/activeAppInfo")["value"]
        if (before.get("bundleId"), before.get("pid")) != (after.get("bundleId"), after.get("pid")):
            raise VisionError("Foreground process changed during recovery capture.")
        frame["pid"] = before["pid"]
        check()
        return frame, local

    def _ask(self, frame, check):
        check()
        now = time.monotonic()
        while self.calls and now - self.calls[0] >= 3600:
            self.calls.popleft()
        if len(self.calls) >= 60:
            raise VisionError("Screen recovery reached its 60-image hourly budget. Inspect manually.")
        self.calls.append(now)
        result = self.guard.vision.client.analyze("recover", frame, {"species": "screen recovery", "cp": None})
        check()
        self.record("inspecting", "Recovery evidence received; checking local safeguards.", result)
        return result

    def _tap(self, first, local, result, hatch_seen, check):
        with self.guard.operation_lock:
            check()
            c = self.guard.controller
            if not c.session_id:
                response = c._request("POST", "/session", {"capabilities": {"alwaysMatch": {
                    "shouldTerminateApp": False, "forceAppLaunch": False,
                    "waitForIdleTimeout": 0, "shouldWaitForQuiescence": False}}})
                c.session_id = response.get("sessionId") or response.get("value", {}).get("sessionId")
            sid = c.session_id
            if not isinstance(sid, str) or not sid:
                raise VisionError("No safe phone-control session.")
            size = c._request("GET", f"/session/{sid}/window/size")["value"]
            w, h = size["width"], size["height"]
            if not 250 <= w <= 1500 or not w < h <= 3000 or abs(w/h - first["pixelWidth"]/first["pixelHeight"]) > .005:
                raise VisionError("Recovery phone geometry changed.")
            native_recovery_guard(c._request("GET", f"/session/{sid}/source")["value"])
            fresh, fresh_local = self._capture(check)
            if fresh_local.get("scene") in {"encounter", "caught", "fled", "blocked-ball"}:
                raise VisionError("Encounter/result appeared before recovery touch. Left untouched.")
            if first["pid"] != fresh["pid"] or not frame_unchanged(first, fresh, result["target_box"]):
                raise ScreenChanged("Recovery screen changed while AI was thinking. No tap sent; observing again.")
            point = recovery_point(result, fresh, fresh_local, hatch_seen, self.hatch_details_closed)
            if result["control_text"].strip().casefold().replace("’", "'") in {"i'm a passenger", "i am safe"}:
                # Only Hunter-generated movement may authorize this game
                # acknowledgment. Never infer actual passenger/driver status.
                device = self.guard.device
                process = device.location_process
                if process is None or process.poll() is not None or not device.status().get("phoneSimulatedLocation"):
                    raise VisionError("Weather/speed acknowledgment requires Hunter's active simulated-location stream.")
            check()
            # Claim the action before delivery. A timeout aborts this run;
            # no retries and no saved action is replayed after app restart.
            self.record("tap", "One allowlisted recovery tap consumed: " + result["action"])
            c._request("POST", f"/session/{sid}/actions", {"actions": [{"type": "pointer", "id": "screen-recovery",
                "parameters": {"pointerType": "touch"}, "actions": [
                    {"type": "pointerMove", "duration": 0, "x": round(point[0]*w), "y": round(point[1]*h), "origin": "viewport"},
                    {"type": "pointerDown", "button": 0}, {"type": "pause", "duration": 60}, {"type": "pointerUp", "button": 0}]}]})

    def run(self, reason, check, *, protected=False):
        with self.lock:
            if self.busy:
                raise VisionError("Screen recovery is already running.")
            self.busy = True
            generation = self.generation
            self.evidence = []
        deadline = time.monotonic() + 180
        def guard_check():
            check()
            if generation != self.generation or self.guard.stop_event.is_set():
                raise RecoveryCancelled("Screen recovery cancelled.")
            if not self.guard.active or not self.guard.vision.client.status()["visionConfigured"]:
                raise RecoveryCancelled("Screen recovery setup/AI permission ended.")
            if self.guard.power is None or self.guard.power.poll() is not None:
                raise RecoveryCancelled("Mac wake protection ended.")
            if self.guard.protected != protected or (protected and (self.guard.state != "opening" or self.guard.event.get("tapConsumed"))):
                raise RecoveryCancelled("Encounter protection changed; recovery stopped.")
            if time.monotonic() > deadline:
                raise VisionError("Screen recovery timed out. Inspect the phone.")
        taps, hatch_seen, map_count = 0, False, 0
        last_action = self.resume_action if self.resume_pending else None
        self.resume_pending = True
        self.record("starting", reason + " · maximum 8 AI images / 6 taps / 180 seconds")
        try:
            for _ in range(8):
                frame, local = self._capture(guard_check)
                if frame.get("pid") != self.resume_pid:
                    last_action = None
                self.resume_pid = frame.get("pid")
                # A Shundo can interrupt ordinary recovery after the egg was
                # opened. Carry only that short-lived, same-process history
                # into its protected preflight; never across app restarts.
                if frame.get("pid") == self.hatch_process and time.monotonic() - self.hatch_observed_at < 180:
                    hatch_seen = True
                else:
                    hatch_seen = False
                    self.hatch_details_closed = False
                if local.get("scene") in {"encounter", "caught", "fled", "blocked-ball"}:
                    raise VisionError("Encounter/result detected. Left untouched.")
                result = self._ask(frame, guard_check)
                point = recovery_point(result, frame, local, hatch_seen, self.hatch_details_closed)
                if result["scene"] == "map":
                    map_count += 1
                    if map_count >= 2:
                        self.hatch_process = None
                        self.hatch_details_closed = False
                        self.resume_pending = False
                        self.resume_action = None
                        self.record("map-ready", "Two independent screen inspections show the unobstructed map.")
                        return
                else:
                    map_count = 0
                if result["scene"] in {"egg_prompt", "egg_animation"}:
                    hatch_seen = True
                    self.hatch_details_closed = False
                    self.hatch_process = frame.get("pid")
                    self.hatch_observed_at = time.monotonic()
                if point is not None:
                    signature = (result["scene"], result["action"])
                    if taps >= 6 or signature == last_action:
                        raise VisionError("Recovery did not visibly progress; repeated taps are blocked.")
                    try:
                        self._tap(frame, local, result, hatch_seen, guard_check)
                    except ScreenChanged as error:
                        self.record("waiting", str(error))
                        continue
                    taps += 1
                    if result["action"] == "close_hatched_details":
                        self.hatch_details_closed = True
                    last_action = signature
                    self.resume_action = signature
                elif result["scene"] != "map":
                    last_action = None
                    self.resume_action = None
                for _ in range(8):
                    guard_check()
                    self.guard.stop_event.wait(.5)
            raise VisionError("Recovery image budget exhausted before map confirmation. Inspect manually.")
        except Exception as error:
            detail = str(error) if isinstance(error, VisionError) else f"Phone recovery failed ({type(error).__name__}); no touch retry. Inspect manually."
            self.record("cancelled" if isinstance(error, RecoveryCancelled) else "attention", detail)
            if isinstance(error, RecoveryCancelled):
                raise
            self.resume_pending = False
            self.hatch_process = None
            if isinstance(error, ObservationUnavailable):
                raise
            raise VisionError(detail) from None
        finally:
            with self.lock:
                self.busy = False
