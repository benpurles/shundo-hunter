"""Opt-in, single-gesture catch experiment; never an unattended catch engine.

WDA must already be running through a loopback-only, device-pinned forwarder.
No location, launch/terminate, inventory, or notification code is changed here.
"""
from __future__ import annotations

import base64
import json
import math
import secrets
import socket
import subprocess
import sys
import threading
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler
from .catch_screen import read_screen


class CatchLabError(RuntimeError):
    pass


class CatchLab:
    BUNDLE_ID = "com.nianticlabs.pokemongo"
    PREVIEW_TTL = 30

    def __init__(self, can_test: Callable[[], bool]):
        self.can_test = can_test
        self.lock = threading.Lock()
        self.session_id = None
        self.preview = None
        self.helper_processes = []
        self.observer_stop = threading.Event()
        self.observer_thread = None
        self.attempt = None
        self.screen_reader = read_screen
        self._status = {"catchLabState": "not-connected", "autoCatchEnabled": False,
                        "catchLabDetail": "Experimental. Automatic Shundo catching is not enabled."}
        # Do not send phone-control traffic through environment-configured proxies.
        self.opener = build_opener(ProxyHandler({}))

    def start_helper(self, executable, udid, native_wifi=False, session_seconds=600):
        with self.lock:
            self._guard()
            if self.helper_processes and all(process.poll() is None for process in self.helper_processes):
                return dict(self._status)
            self._stop_helper_locked()
            # Do not attach blindly to another device's or another program's port.
            with socket.socket() as probe:
                try:
                    probe.bind(("127.0.0.1", 18100))
                except OSError as error:
                    raise CatchLabError("Controller port 18100 is already occupied. Stop the existing test controller first.") from error
            if not executable or not isinstance(udid, str) or not udid:
                raise CatchLabError("A paired iPhone and pymobiledevice3 are required")
            commands = [[sys.executable, "-m", "shundo_hunter.phone_helper",
                         "--executable", executable, "--udid", udid,
                         "--session-seconds", str(int(session_seconds))]]
            if native_wifi:
                commands[0].append("--native-wifi")
            try:
                for command in commands:
                    # Inherit the app's log, never create an undrained PIPE.
                    self.helper_processes.append(subprocess.Popen(command, stdin=subprocess.DEVNULL))
            except OSError as error:
                self._stop_helper_locked()
                raise CatchLabError("Could not start the installed phone controller") from error
            self._status.update(catchLabState="starting", catchLabDetail="Controller starting (up to 30 seconds). Keep iPhone unlocked, open an ordinary encounter, then capture a preview. Test session is limited to 10 minutes.")
            return dict(self._status)

    def _stop_helper_locked(self):
        self.observer_stop.set()
        self.preview = None
        self.session_id = None
        for process in reversed(self.helper_processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
        self.helper_processes = []

    def close(self):
        with self.lock:
            if self.session_id:
                try:
                    self._request("DELETE", f"/session/{self.session_id}")
                except CatchLabError:
                    pass
            self._stop_helper_locked()
            self._status.update(catchLabState="not-connected", catchLabDetail="Controller stopped. Automatic Shundo catching remains off.")

    def status(self):
        with self.lock:
            if self.helper_processes and any(process.poll() is not None for process in self.helper_processes):
                self.preview = None
                self._status.update(catchLabState="unavailable", catchLabDetail="Controller session ended. Stop/start the controller with the phone unlocked before testing again.")
            return dict(self._status)

    def _request(self, method, path, payload=None):
        request = Request("http://127.0.0.1:18100" + path, method=method,
                          data=json.dumps(payload).encode() if payload is not None else None,
                          headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(request, timeout=10) as response:
                result = json.loads(response.read(12_000_000))
        except (OSError, HTTPError, URLError, ValueError) as error:
            raise CatchLabError("Phone controller unavailable. Start the signed helper, unlock the iPhone and enable Settings → Developer → Enable UI Automation.") from error
        value = result.get("value") if isinstance(result, dict) else None
        if isinstance(value, dict) and value.get("error"):
            raise CatchLabError(str(value.get("message") or value["error"])[:500])
        return result

    def _foreground(self):
        value = self._request("GET", "/wda/activeAppInfo").get("value", {})
        if value.get("bundleId") != self.BUNDLE_ID:
            raise CatchLabError("Open an ordinary Pokémon encounter in iPogo first. No other app will be controlled.")

    def _guard(self):
        if not self.can_test():
            raise CatchLabError("Stop/unprepare the hunt before testing. Catch Lab is blocked during hunting, recovery, and Shundo stops.")

    def inspect(self):
        with self.lock:
            self.preview = None
            self._guard()
            try:
                self._request("GET", "/status")
                self._foreground()
                if not self.session_id:
                    # No bundleId means no launch; never restart production iPogo.
                    result = self._request("POST", "/session", {"capabilities": {"alwaysMatch": {
                        "shouldTerminateApp": False, "forceAppLaunch": False,
                        "waitForIdleTimeout": 0, "shouldWaitForQuiescence": False,
                    }}})
                    value = result.get("value", {})
                    session_id = result.get("sessionId") or value.get("sessionId")
                    if not isinstance(session_id, str) or not session_id:
                        raise CatchLabError("Phone controller did not return a test session")
                    self.session_id = session_id
                self._foreground()
                size = self._request("GET", f"/session/{self.session_id}/window/size")["value"]
                width, height = float(size["width"]), float(size["height"])
                if not (math.isfinite(width) and math.isfinite(height) and 100 <= width <= 2000 and 100 <= height <= 3000):
                    raise CatchLabError("Invalid phone screen dimensions")
                screenshot = self._request("GET", "/screenshot")["value"]
                raw = base64.b64decode(screenshot, validate=True)
                if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise CatchLabError("Phone controller did not return a PNG screenshot")
                self._foreground()
                try:
                    scene = self.screen_reader(raw)
                except RuntimeError as error:
                    raise CatchLabError(str(error)) from error
                token = secrets.token_urlsafe(24)
                self.preview = {"token": token, "created": time.monotonic(), "width": width, "height": height, "scene": scene}
                self._status.update(catchLabState="preview-ready", catchLabDetail="Preview captured. Choose the ball and throw destination; one confirmed test only.")
                return {"token": token, "image": "data:image/png;base64," + screenshot,
                        "width": width, "height": height, "expiresIn": self.PREVIEW_TTL, "scene": scene}
            except (CatchLabError, KeyError, TypeError, ValueError) as error:
                self.session_id = None
                self._status.update(catchLabState="unavailable", catchLabDetail=str(error))
                raise CatchLabError(str(error)) from error

    @staticmethod
    def _point(value):
        if not isinstance(value, list) or len(value) != 2:
            raise CatchLabError("Select the ball and throw destination on the preview")
        if any(isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item) or not 0 <= item <= 1 for item in value):
            raise CatchLabError("Throw points must be inside the preview")
        return value

    def throw_once(self, payload):
        with self.lock:
            preview, self.preview = self.preview, None  # Consume even on error; no duplicate/retry throws.
            self._guard()
            if payload.get("confirmedOrdinaryRegularBall") is not True:
                raise CatchLabError("Confirm an ordinary Pokémon, non-Master Ball, and that you are ready to catch")
            if not preview or payload.get("token") != preview["token"] or time.monotonic() - preview["created"] > self.PREVIEW_TTL:
                raise CatchLabError("Preview expired or already used. Capture a new preview before any throw.")
            if self.observer_thread and self.observer_thread.is_alive():
                raise CatchLabError("Still observing the last throw. Wait for its result before another test.")
            duration = payload.get("durationMs", 350)
            if isinstance(duration, bool) or not isinstance(duration, int) or not 120 <= duration <= 600:
                raise CatchLabError("Throw duration must be an integer from 120 to 600 milliseconds")
            if preview["scene"].get("scene") != "encounter":
                raise CatchLabError("The preview is not a recognized encounter. No throw was sent.")
            start, end = self._point(payload.get("start")), self._point(payload.get("end"))
            if start[1] < 0.55 or end[1] >= start[1] - 0.1:
                raise CatchLabError("Select the ball in the lower screen, then a destination above it")
            self._foreground()
            size = self._request("GET", f"/session/{self.session_id}/window/size")["value"]
            if size.get("width") != preview["width"] or size.get("height") != preview["height"]:
                raise CatchLabError("Screen orientation changed. Capture a new preview.")
            try:
                fresh = self._read_scene()
                # A low-contrast AR label or animation can make one OCR frame
                # unreadable. Retry observation only, never the gesture. A
                # positively recognized different screen/CP is not retried.
                for _ in range(2):
                    if fresh["scene"] != "uncertain":
                        break
                    self._guard()
                    fresh = self._read_scene()
            except RuntimeError as error:
                raise CatchLabError(str(error)) from error
            if fresh["scene"] != "encounter" or fresh["cp"] != preview["scene"]["cp"]:
                self._status.update(catchLabState="blocked", catchLabDetail="No throw sent: fresh encounter recognition did not match the preview.", catchLabScreen=fresh)
                raise CatchLabError("Encounter changed or could not be recognized. No throw was sent.")
            if fresh.get("cooldownSeconds", 0) > 0:
                raise CatchLabError("iPogo displays an active cooldown. Wait before throwing.")
            self._guard()
            actions = [{"type": "pointerMove", "duration": 0,
                        "x": round(start[0] * (preview["width"] - 1)), "y": round(start[1] * (preview["height"] - 1)), "origin": "viewport"},
                       {"type": "pointerDown", "button": 0},
                       {"type": "pause", "duration": 80},
                       {"type": "pointerMove", "duration": duration,
                        "x": round(end[0] * (preview["width"] - 1)), "y": round(end[1] * (preview["height"] - 1)), "origin": "viewport"},
                       {"type": "pointerUp", "button": 0}]
            self._status.update(catchLabState="attempt-unverified", catchLabDetail="One throw requested. Capture outcome is NOT verified. No hunt statistics changed.")
            self.attempt = {"id": secrets.token_hex(8), "durationMs": duration, "cp": fresh["cp"],
                            "result": "uncertain", "captureVerified": False, "evidence": [], "samples": 0}
            self._status["catchLabAttempt"] = dict(self.attempt)
            try:
                self._request("POST", f"/session/{self.session_id}/actions", {
                    "actions": [{"type": "pointer", "id": "hunter-test-finger", "parameters": {"pointerType": "touch"}, "actions": actions}]})
            except CatchLabError:
                self._status["catchLabDetail"] = "Throw outcome unknown after a connection error. Inspect the phone; do not automatically retry."
                raise
            self._start_observer()
            return dict(self._status)

    def _read_scene(self):
        self._foreground()
        raw = base64.b64decode(self._request("GET", "/screenshot")["value"], validate=True)
        self._foreground()
        return self.screen_reader(raw)

    def _start_observer(self):
        self.observer_stop = threading.Event()
        stop = self.observer_stop
        attempt_id = self.attempt["id"]
        self._status.update(catchLabState="observing", catchLabDetail="Throw sent. Reading the result for about 24 seconds; no automatic retry.")
        self.observer_thread = threading.Thread(target=self._observe_result, args=(stop, attempt_id), daemon=True, name="catch-result-reader")
        self.observer_thread.start()

    def _observe_result(self, stop, attempt_id):
        began = time.monotonic()
        previous = None
        streak = 0
        while not stop.wait(2):
            with self.lock:
                if not self.attempt or self.attempt["id"] != attempt_id or stop.is_set():
                    return
                if time.monotonic() - began >= 24:
                    self._finish_observation("uncertain", "Result uncertain after 24 seconds. Inspect the phone; no automatic retry.")
                    return
                try:
                    self._guard()
                    sample = self._read_scene()
                except (CatchLabError, RuntimeError, ValueError, KeyError, TypeError) as error:
                    self.attempt["interruptionReason"] = str(error)[:300]
                    self._finish_observation("uncertain", "Observation interrupted or unreadable: " + str(error)[:200] + ". No automatic retry.")
                    return
                self.attempt["samples"] += 1
                self.attempt["evidence"] = sample["evidence"]
                scene = sample["scene"]
                # A different CP means the screen changed outside this test.
                if scene == "encounter" and sample["cp"] != self.attempt["cp"]:
                    scene = "uncertain"
                streak = streak + 1 if scene == previous else 1
                previous = scene
                self._status["catchLabAttempt"] = dict(self.attempt)
                if time.monotonic() - began >= 5 and streak >= 2 and scene in ("caught", "encounter", "fled"):
                    detail = {"caught": "Catch confirmation recognized in two frames. This does not verify shiny/IV identity; no hunt stats changed.",
                              "encounter": "Still in the encounter after the throw. Miss versus breakout is unknown. No automatic retry.",
                              "fled": "Flee message recognized in two frames. No automatic retry."}[scene]
                    self._finish_observation(scene, detail)
                    return

    def _finish_observation(self, result, detail):
        self.attempt.update(result=result, captureVerified=result == "caught")
        self._status.update(catchLabState="result-ready", catchLabDetail=detail, catchLabAttempt=dict(self.attempt))
