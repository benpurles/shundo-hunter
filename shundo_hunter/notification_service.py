from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import re
import logging
import shutil
import subprocess
import threading
import time
from typing import Any


MARKER = "SHUNDO_HUNTER_NOTIFICATION"
WORLD_SCAN_MARKER = "SHUNDO_WORLD_SCAN_V3"
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
WORLD_SCAN_RE = re.compile(
    rf"{re.escape(WORLD_SCAN_MARKER)}\s+"
    r"wild=(?P<wild>\d+)\s+nearby=(?P<nearby>\d+)\s+"
    r"gyms=(?P<gyms>\d+)\s+stops=(?P<stops>\d+)"
)


@dataclass(frozen=True)
class NotificationEvent:
    sequence: int
    received_at: str
    text: str
    is_hundo: bool
    is_shundo: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorldScanEvent:
    sequence: int
    received_at: str
    received_monotonic: float
    kind: str
    kind_code: int
    count: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class NotificationWatcher:
    """Watches the iPogo notification marker in the connected device log."""

    def __init__(self, executable: str | None = None, history_limit: int = 100):
        self.executable = executable or shutil.which("pymobiledevice3")
        self.history: deque[NotificationEvent] = deque(maxlen=history_limit)
        self.lock = threading.Condition()
        self.process: subprocess.Popen[str] | None = None
        self.reader_thread: threading.Thread | None = None
        self.udid: str | None = None
        self.sequence = 0
        self.state = "stopped"
        self.last_error: str | None = None
        self.direct_proof: dict[str, Any] | None = None
        self.use_phone_banners = False
        self.banner_stop: threading.Event | None = None
        self.banner_heartbeat: float | None = None

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def start(self, udid: str) -> dict[str, Any]:
        if self.use_phone_banners:
            return self._start_banners(udid)
        if not self.executable:
            raise RuntimeError("pymobiledevice3 is not installed")
        with self.lock:
            if self.process is not None and self.process.poll() is None and self.udid == udid:
                return self.status()
        self.stop()
        command = [
            self.executable,
            "syslog",
            "live",
            "--udid",
            udid,
            "--process-name",
            "PokmonGO",
            "--match",
            MARKER,
        ]
        command = getattr(self, "command_transform", lambda value: value)(command)
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except (FileNotFoundError, OSError) as error:
            raise RuntimeError(f"Could not start the iPhone alert watcher: {error}") from error

        # A live syslog stream is silent until an event arrives. Remaining alive
        # through this short probe is its readiness signal.
        time.sleep(0.35)
        if process.poll() is not None:
            output = process.stdout.read().strip() if process.stdout else ""
            if process.stdout:
                process.stdout.close()
            raise RuntimeError(output[-800:] or "The iPhone alert watcher stopped during startup")

        with self.lock:
            self.process = process
            self.udid = udid
            self.direct_proof = None
            self.state = "listening"
            self.last_error = None
            self.reader_thread = threading.Thread(
                target=self._read,
                args=(process,),
                name="ipogo-notification-watcher",
                daemon=True,
            )
            self.reader_thread.start()
            self.lock.notify_all()
        return self.status()

    def _start_banners(self, udid):
        with self.lock:
            if self.banner_stop is not None and not self.banner_stop.is_set() and self.reader_thread and self.reader_thread.is_alive() and self.udid == udid:
                return self.status()
        self.stop()
        with self.lock:
            self.udid = udid
            self.state = "starting"
            self.last_error = None
            stop = self.banner_stop = threading.Event()
            self.reader_thread = threading.Thread(target=self._read_banners, args=(stop,), name="iphone-banner-reader", daemon=True)
            self.reader_thread.start()
        return self.status()

    def _read_banners(self, stop):
        from .phone_notifications import PhoneBannerReader
        reader = PhoneBannerReader()
        while not stop.is_set():
            try:
                messages = reader.read()
                with self.lock:
                    if self.banner_stop is not stop or stop.is_set():
                        return
                    self.banner_heartbeat = time.monotonic()
                    self.state, self.last_error = "listening", None
                    for text in messages:
                        event = self.record_external(text)
                        if event is not None and event.is_hundo:
                            self.direct_proof = {**event.as_dict(), "source": "iphone-banner"}
                    self.lock.notify_all()
            except Exception as error:
                logging.getLogger(__name__).warning("Direct phone banner read failed (%s): %s", type(error).__name__, str(error)[:180])
                reader.reset()
                with self.lock:
                    if self.banner_stop is not stop or stop.is_set():
                        return
                    self.direct_proof = None
                    self.state = "error"
                    self.last_error = "Direct iPhone banner reader unavailable. Keep iPogo foreground and restart/update the phone controller if needed. A fresh Hundo must verify reconnection."
                    self.lock.notify_all()
            stop.wait(.5)

    def _read(self, process: subprocess.Popen[str]) -> None:
        try:
            if process.stdout is not None:
                for line in process.stdout:
                    self._handle_line(line, process=process)
        except (OSError, ValueError) as error:
            with self.lock:
                if self.process is process:
                    self.last_error = str(error)
        finally:
            return_code = process.poll()
            with self.lock:
                if self.process is process:
                    self.process = None
                    self.state = "error" if return_code not in (None, 0, -15) else "stopped"
                    if self.state == "error" and not self.last_error:
                        self.last_error = f"The iPhone alert watcher exited with code {return_code}"
                    self.lock.notify_all()

    def _handle_line(self, line: str, process=None) -> NotificationEvent | None:
        clean = ANSI_ESCAPE_RE.sub("", line).strip()
        marker_index = clean.find(MARKER)
        if marker_index < 0:
            return None
        text = clean[marker_index + len(MARKER):].strip()
        with self.lock:
            if process is not None and self.process is not process:
                return None
            event = self.record_external(text)
            if event is not None and event.is_hundo:
                self.direct_proof = event.as_dict()
        return event

    def record_external(self, text: str) -> NotificationEvent | None:
        """Record a notification body supplied by the native Mac bridge."""
        text = " ".join(str(text).strip().split())[:1000]
        if not text:
            return None
        normalized = text.casefold()
        # Never let this utility's own pause/found banners become Pokémon
        # evidence. They can mention both "iPogo" and "No Hundo alert", which
        # otherwise satisfy the same keyword checks as a real mirrored banner.
        if "shundo hunter" in normalized:
            return None
        # The Mac utility itself is named "Shundo Hunter". Accessibility trees
        # may contain that application name alongside a notification, so strip
        # it before classifying the alert text.
        classification_text = re.sub(r"\bshundo\s+hunter\b", "", normalized)
        is_shundo = bool(re.search(r"\bshundo\b", classification_text))
        is_hundo = is_shundo or bool(
            re.search(r"\bhundo\b|\b100\s*iv\b|\biv\s*100\b", classification_text)
        )
        with self.lock:
            self.sequence += 1
            event = NotificationEvent(
                sequence=self.sequence,
                received_at=self._now(),
                text=text,
                is_hundo=is_hundo,
                is_shundo=is_shundo,
            )
            self.history.append(event)
            self.lock.notify_all()
            return event

    def checkpoint(self) -> int:
        with self.lock:
            return self.sequence

    def events_after(self, checkpoint: int) -> list[NotificationEvent]:
        with self.lock:
            return [event for event in self.history if event.sequence > checkpoint]

    def wait_for_shundo(
        self,
        checkpoint: int,
        timeout: float,
        cancel_event: threading.Event | None = None,
    ) -> NotificationEvent | None:
        deadline = time.monotonic() + max(0.0, timeout)
        with self.lock:
            while True:
                for event in self.history:
                    if event.sequence > checkpoint and event.is_shundo:
                        return event
                if cancel_event is not None and cancel_event.is_set():
                    return None
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self.lock.wait(timeout=min(remaining, 0.25))

    def status(self) -> dict[str, Any]:
        with self.lock:
            latest = self.history[-1].as_dict() if self.history else None
            stale = bool(self.use_phone_banners and self.state == "listening" and (self.banner_heartbeat is None or time.monotonic() - self.banner_heartbeat > 8))
            return {
                "notificationWatcherState": "error" if stale else self.state,
                "directAlertTransport": "iphone-banner" if self.use_phone_banners else "device-log",
                "notificationWatcherUdid": self.udid,
                "notificationWatcherLastError": self.last_error,
                "notificationSequence": self.sequence,
                "lastIpogoNotification": latest,
                "directAlertProof": dict(self.direct_proof) if self.direct_proof and not stale else None,
            }

    def stop(self) -> None:
        with self.lock:
            if self.banner_stop is not None:
                self.banner_stop.set()
            self.banner_stop = None
            self.banner_heartbeat = None
            process = self.process
            self.process = None
            self.udid = None
            self.state = "stopped"
            self.direct_proof = None
            self.lock.notify_all()
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        if process is not None and process.stdout:
            process.stdout.close()

    def close(self) -> None:
        self.stop()


class WorldScanWatcher:
    """Watches read-only iPogo world-array telemetry on the device log."""

    KIND_NAMES = {
        1: "nearby-pokemon",
        2: "wild-pokemon",
        3: "gyms",
        4: "pokestops",
    }

    def __init__(self, executable: str | None = None, history_limit: int = 300):
        self.executable = executable or shutil.which("pymobiledevice3")
        self.history: deque[WorldScanEvent] = deque(maxlen=history_limit)
        self.lock = threading.Condition()
        self.process: subprocess.Popen[str] | None = None
        self.reader_thread: threading.Thread | None = None
        self.udid: str | None = None
        self.sequence = 0
        self.state = "stopped"
        self.last_error: str | None = None
        self.last_snapshot: dict[str, Any] | None = None

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def start(self, udid: str) -> dict[str, Any]:
        if not self.executable:
            raise RuntimeError("pymobiledevice3 is not installed")
        with self.lock:
            if self.process is not None and self.process.poll() is None and self.udid == udid:
                return self.status()
        self.stop()
        command = [
            self.executable,
            "syslog",
            "live",
            "--udid",
            udid,
            "--process-name",
            "PokmonGO",
            "--match",
            WORLD_SCAN_MARKER,
        ]
        command = getattr(self, "command_transform", lambda value: value)(command)
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except (FileNotFoundError, OSError) as error:
            raise RuntimeError(f"Could not start the iPogo world watcher: {error}") from error
        time.sleep(0.35)
        if process.poll() is not None:
            output = process.stdout.read().strip() if process.stdout else ""
            if process.stdout:
                process.stdout.close()
            raise RuntimeError(output[-800:] or "The iPogo world watcher stopped during startup")
        with self.lock:
            self.process = process
            self.udid = udid
            self.state = "listening"
            self.last_error = None
            self.reader_thread = threading.Thread(
                target=self._read,
                args=(process,),
                name="ipogo-world-scan-watcher",
                daemon=True,
            )
            self.reader_thread.start()
            self.lock.notify_all()
        return self.status()

    def _read(self, process: subprocess.Popen[str]) -> None:
        try:
            if process.stdout is not None:
                for line in process.stdout:
                    self._handle_line(line)
        except (OSError, ValueError) as error:
            with self.lock:
                if self.process is process:
                    self.last_error = str(error)
        finally:
            return_code = process.poll()
            with self.lock:
                if self.process is process:
                    self.process = None
                    self.state = "error" if return_code not in (None, 0, -15) else "stopped"
                    if self.state == "error" and not self.last_error:
                        self.last_error = f"The iPogo world watcher exited with code {return_code}"
                    self.lock.notify_all()

    def _handle_line(self, line: str) -> WorldScanEvent | None:
        clean = ANSI_ESCAPE_RE.sub("", line).strip()
        match = WORLD_SCAN_RE.search(clean)
        if match is None:
            return None
        counts = {
            "wild-pokemon": int(match.group("wild")),
            "nearby-pokemon": int(match.group("nearby")),
            "gyms": int(match.group("gyms")),
            "pokestops": int(match.group("stops")),
        }
        if any(count < 0 or count > 4096 for count in counts.values()):
            return None
        received_at = self._now()
        received_monotonic = time.monotonic()
        # Feed the existing target-scoped debounce one event per decoded array.
        # Empty spawn arrays go first so a same-cycle populated array is treated
        # as the fresh post-teleport edge, not erased by its sibling's reset.
        spawn_kinds = ["wild-pokemon", "nearby-pokemon"]
        ordered_kinds = (
            [kind for kind in spawn_kinds if counts[kind] == 0]
            + [kind for kind in spawn_kinds if counts[kind] > 0]
            + ["gyms", "pokestops"]
        )
        events: list[WorldScanEvent] = []
        with self.lock:
            code_by_kind = {value: key for key, value in self.KIND_NAMES.items()}
            for kind in ordered_kinds:
                self.sequence += 1
                event = WorldScanEvent(
                    sequence=self.sequence,
                    received_at=received_at,
                    received_monotonic=received_monotonic,
                    kind=kind,
                    kind_code=code_by_kind[kind],
                    count=counts[kind],
                )
                self.history.append(event)
                events.append(event)
            self.last_snapshot = {
                "sequence": self.sequence,
                "received_at": received_at,
                "wild": counts["wild-pokemon"],
                "nearby": counts["nearby-pokemon"],
                "gyms": counts["gyms"],
                "stops": counts["pokestops"],
                "spawnCount": counts["wild-pokemon"] + counts["nearby-pokemon"],
            }
            self.lock.notify_all()
            return events[-1]

    def checkpoint(self) -> int:
        with self.lock:
            return self.sequence

    def events_after(self, checkpoint: int) -> list[WorldScanEvent]:
        with self.lock:
            return [event for event in self.history if event.sequence > checkpoint]

    def status(self) -> dict[str, Any]:
        with self.lock:
            latest = self.history[-1].as_dict() if self.history else None
            return {
                "worldScanWatcherState": self.state,
                "worldScanWatcherUdid": self.udid,
                "worldScanWatcherLastError": self.last_error,
                "worldScanSequence": self.sequence,
                "lastWorldScanEvent": latest,
                "lastWorldScanSnapshot": dict(self.last_snapshot) if self.last_snapshot else None,
            }

    def stop(self) -> None:
        with self.lock:
            process = self.process
            self.process = None
            self.udid = None
            self.state = "stopped"
            self.lock.notify_all()
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        if process is not None and process.stdout:
            process.stdout.close()

    def close(self) -> None:
        self.stop()
