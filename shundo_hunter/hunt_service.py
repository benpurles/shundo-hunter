from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import math
import re
import subprocess
import threading
import time
from typing import Any, Callable, Protocol
import unicodedata

from .notification_service import NotificationWatcher, WorldScanWatcher


# Live iPhone measurements on 2026-08-06 showed iPogo growing from roughly
# 1.44 GB to 1.72 GB and stalling immediately after the fifteenth map load.
# Relaunch between targets before that boundary.  The visit budget deliberately
# includes bad-coordinate timeouts; those attempts still make iPogo load a new
# world.  Operator-directed skips are removed from the visit counter.
IPOGO_MEMORY_SAFE_CONFIRMED_CHECKS = 14
IPOGO_MEMORY_SAFE_MAP_LOADS = 14


class HuntError(RuntimeError):
    """A user-correctable hunt coordinator error."""


def alerts_ready_for_hunt(status):
    return bool(status.get("huntReady", status.get("unattendedReady", False)))


def notify_mac(title: str, message: str) -> None:
    """Deliver the terminal hunt result without invoking a shell."""
    escaped_title = title.replace("\\", "\\\\").replace('"', '\\"')
    escaped_message = message.replace("\\", "\\\\").replace('"', '\\"')
    script = f'display notification "{escaped_message}" with title "{escaped_title}" sound name "Glass"'
    try:
        subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            check=False,
            timeout=5,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        # Detection and durable recording are authoritative; a denied macOS
        # notification must never turn a found Shundo into a hunt failure.
        pass


def play_shundo_alarm() -> None:
    """Play a distinct alarm without blocking the hunt's terminal state."""

    def play() -> None:
        try:
            subprocess.run(
                [
                    "/usr/bin/afplay",
                    "-v",
                    "1.4",
                    "/System/Library/Sounds/Hero.aiff",
                ],
                check=False,
                timeout=15,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.TimeoutExpired):
            # The durable Shundo result remains authoritative if audio output
            # is unavailable or the Mac is muted.
            pass

    threading.Thread(target=play, name="shundo-alarm", daemon=True).start()


class HuntStore(Protocol):
    def discard_orphaned_current(self) -> int: ...

    def claim_next_target(
        self,
        max_age_seconds: float,
        minimum_remaining_seconds: float = 0,
    ) -> dict[str, Any] | None: ...

    def complete_hunt_target(
        self,
        sighting_id: int,
        outcome: str,
        message: str | None = None,
        *,
        completion_reason: str | None = None,
        notification_received_at: str | None = None,
    ) -> bool: ...

    def expire_stale_sightings(self, max_age_seconds: float) -> int: ...

    def record_hunt_event(
        self,
        message: str,
        level: str = "info",
        sighting_id: int | None = None,
    ) -> None: ...

    def record_phone_location(self, sighting: dict[str, Any]) -> None: ...

    def get_sighting(self, sighting_id: int) -> dict[str, Any]: ...

    def queue_pokexperience_resolution(self, sighting_id: int) -> dict[str, Any]: ...

    def set_hunt_state(self, state: str) -> None: ...


class HuntDevice(Protocol):
    def refresh(self) -> dict[str, Any]: ...

    def status(self) -> dict[str, Any]: ...

    def set_location(self, latitude: float, longitude: float) -> dict[str, Any]: ...

    def set_hunt_location(self, latitude: float, longitude: float) -> dict[str, Any]: ...

    def restart_ipogo(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class NotificationEvent:
    kind: str
    message: str
    target_id: int | None
    received_at: str

    @property
    def is_shundo(self) -> bool:
        combined = f"{self.kind} {self.message}".casefold()
        return self.kind.casefold() == "shundo" or "shundo" in combined

    @property
    def is_hundo(self) -> bool:
        combined = f"{self.kind} {self.message}".casefold()
        return self.is_shundo or self.kind.casefold() == "hundo" or "hundo" in combined


class NotificationDetector(Protocol):
    def begin_target(self, target: dict[str, Any]) -> None: ...

    def poll(self, target_id: int) -> NotificationEvent | None: ...

    def end_target(self, target_id: int) -> None: ...

    def status(self) -> dict[str, Any]: ...


class ManualNotificationDetector:
    """Thread-safe notification detector used until the phone bridge is enabled.

    Events are deliberately scoped to the active target. Anything injected
    before a target begins is discarded so a delayed test signal cannot mark
    the next Pokémon as a Shundo.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: deque[NotificationEvent] = deque()
        self._active_target_id: int | None = None
        self._state = "manual-ready"
        self._last_event: NotificationEvent | None = None
        self._sequence = 0

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def begin_target(self, target: dict[str, Any]) -> None:
        with self._lock:
            self._events.clear()
            self._active_target_id = int(target["id"])
            self._state = "manual-watching"

    def inject(
        self,
        kind: str = "shundo",
        message: str = "Manual Shundo test signal",
        target_id: int | None = None,
    ) -> NotificationEvent:
        normalized_kind = " ".join(str(kind).strip().split()).lower() or "notification"
        with self._lock:
            resolved_target = self._active_target_id if target_id is None else int(target_id)
            if resolved_target is None:
                raise HuntError("There is no active target receiving notifications.")
            event = NotificationEvent(
                kind=normalized_kind[:40],
                message=" ".join(str(message).strip().split())[:500],
                target_id=resolved_target,
                received_at=self._now(),
            )
            self._sequence += 1
            self._events.append(event)
            self._last_event = event
            self._state = "manual-signal-pending"
            return event

    def poll(self, target_id: int) -> NotificationEvent | None:
        with self._lock:
            while self._events:
                event = self._events.popleft()
                if event.target_id == target_id:
                    self._state = "manual-watching"
                    return event
            return None

    def end_target(self, target_id: int) -> None:
        with self._lock:
            if self._active_target_id == target_id:
                self._active_target_id = None
            self._events.clear()
            self._state = "manual-ready"

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "state": self._state,
                "activeTargetId": self._active_target_id,
                "pendingSignals": len(self._events),
                "lastEvent": asdict(self._last_event) if self._last_event else None,
                "lastObservedAlert": asdict(self._last_event) if self._last_event else None,
                "sequence": self._sequence,
            }


class USBNotificationDetector:
    """Adapts the device-log watcher to the coordinator's target contract."""

    def __init__(
        self,
        watcher: NotificationWatcher | None = None,
        world_watcher: WorldScanWatcher | None = None,
        *,
        world_signal_minimum_delay_seconds: float = 3.0,
        world_notification_grace_seconds: float = 5.0,
    ) -> None:
        self.watcher = watcher or NotificationWatcher()
        # Production creates both watchers. Tests and other explicit detector
        # adapters that supply only a notification watcher retain their old,
        # notification-only behavior unless they also supply a world watcher.
        self.world_watcher = (
            world_watcher
            if world_watcher is not None
            else (WorldScanWatcher() if watcher is None else None)
        )
        self._world_signal_minimum_delay_seconds = max(
            0.0, float(world_signal_minimum_delay_seconds)
        )
        self._world_notification_grace_seconds = max(
            0.0, float(world_notification_grace_seconds)
        )
        self._lock = threading.Lock()
        self._active_target_id: int | None = None
        self._active_species: str | None = None
        self._checkpoint = 0
        self._last_event: NotificationEvent | None = None
        self._last_unmatched_event: NotificationEvent | None = None
        self._accepted_species_mismatch_count = 0
        self._mac_bridge_state = "not-configured"
        self._alert_source = "mac"
        self._source_gate = threading.RLock()
        self._mac_bridge_trusted = False
        self._mac_bridge_last_error: str | None = None
        self._mac_bridge_last_heartbeat_monotonic: float | None = None
        self._mac_bridge_last_heartbeat_at: str | None = None
        self._mac_bridge_last_seen_at: str | None = None
        self._mac_bridge_last_source: str | None = None
        self._world_checkpoint = 0
        self._world_armed_monotonic: float | None = None
        self._world_reset_observed = False
        self._world_positive_events: dict[str, Any] = {}
        self._world_positive_update_counts: dict[str, int] = {}
        self._world_candidate_monotonic: float | None = None
        self._world_ready_delivered = False
        self._world_last_evidence: dict[str, Any] | None = None
        self._world_last_error: str | None = None

    def set_alert_source(self, source: str) -> None:
        with self._source_gate:
            self._set_alert_source(source)

    def _set_alert_source(self, source: str) -> None:
        """Caller must stop/unprepare hunting before changing event ownership."""
        if source not in {"mac", "direct"}:
            raise ValueError("Unknown alert source")
        with self._lock:
            if self._active_target_id is not None:
                raise RuntimeError("Finish the active target before changing alert source")
            self._alert_source = source
            self._checkpoint = self.watcher.checkpoint()
        self.watcher.stop()
        self.watcher.use_phone_banners = source == "direct"

    def start(self, udid: str) -> None:
        with self._source_gate:
            self._start(udid)

    def _start(self, udid: str) -> None:
        if self.world_watcher is not None:
            try:
                self.world_watcher.start(udid)
                with self._lock:
                    self._world_last_error = None
            except RuntimeError as error:
                # World telemetry accelerates definitive bad-coordinate checks,
                # but its absence must never disable the proven notification +
                # timeout path.
                with self._lock:
                    self._world_last_error = str(error)
        if self.status().get("unattendedReady") and (
            self._alert_source == "mac" or self.watcher.status().get("notificationWatcherUdid") == udid
        ):
            return
        try:
            self.watcher.start(udid)
        except RuntimeError:
            # The native Mac detector is the proven alert source. Keep
            # preparation usable when the optional USB syslog fallback is
            # unavailable, but still fail closed if the native bridge is not
            # healthy either.
            if not self.status().get("unattendedReady"):
                raise

    def begin_target(self, target: dict[str, Any]) -> None:
        with self._lock:
            self._active_target_id = int(target["id"])
            self._active_species = str(target.get("species") or "").strip() or None
            self._checkpoint = self.watcher.checkpoint()
            self._world_checkpoint = (
                self.world_watcher.checkpoint() if self.world_watcher is not None else 0
            )
            self._world_armed_monotonic = time.monotonic()
            self._world_reset_observed = False
            self._world_positive_events = {}
            self._world_positive_update_counts = {}
            self._world_candidate_monotonic = None
            self._world_ready_delivered = False

    @staticmethod
    def _normalized_species(value: str) -> str:
        folded = unicodedata.normalize("NFKD", value).casefold()
        return re.sub(r"[^a-z0-9]+", "", folded)

    @classmethod
    def _alert_matches_species(cls, text: str, species: str | None) -> bool:
        if not species:
            return True
        match = re.search(
            r"\b(?:shundo|hundo)\s+(.+?)\s+(?:appeared|nearby|found)\b",
            text,
            re.IGNORECASE,
        )
        if match is None:
            return True
        return cls._normalized_species(match.group(1)) == cls._normalized_species(species)

    def poll(self, target_id: int) -> NotificationEvent | None:
        with self._lock:
            if self._active_target_id != target_id:
                return None
            events = self.watcher.events_after(self._checkpoint)
            if not events:
                return None
            self._checkpoint = max(event.sequence for event in events)
            selected: NotificationEvent | None = None
            for source in events:
                event = NotificationEvent(
                    kind="shundo" if source.is_shundo else ("hundo" if source.is_hundo else "notification"),
                    message=source.text,
                    target_id=target_id,
                    received_at=source.received_at,
                )
                self._last_event = event
                # The notification's Hundo/Shundo tag is the proof. Species
                # labels are diagnostic only because Discord and iPogo do not
                # use one canonical form (for example Nidoran-m vs Nidoran♂,
                # and regional/form suffixes). The per-target checkpoint keeps
                # alerts from an earlier coordinate from being credited here.
                if event.is_hundo and not self._alert_matches_species(event.message, self._active_species):
                    self._last_unmatched_event = event
                    self._accepted_species_mismatch_count += 1
                if event.is_shundo:
                    return event
                if event.is_hundo:
                    selected = event
                elif selected is None:
                    selected = event
            return selected

    def poll_world(self, target_id: int) -> dict[str, Any] | None:
        """Return target-scoped proof that a fresh, populated world was scanned.

        A single array update is insufficient: it can be a late update from the
        previous coordinate. We ignore the first few seconds after arming and
        require either a post-arm reset or corroboration from two decoded world
        arrays. The notification grace begins only after that credible edge.
        """
        watcher = self.world_watcher
        if watcher is None:
            return None
        with self._lock:
            if self._active_target_id != target_id or self._world_ready_delivered:
                return None
            checkpoint = self._world_checkpoint
            armed_at = self._world_armed_monotonic
        events = watcher.events_after(checkpoint)
        now = time.monotonic()
        with self._lock:
            if self._active_target_id != target_id or self._world_ready_delivered:
                return None
            if events:
                self._world_checkpoint = max(event.sequence for event in events)
            minimum_event_time = (
                armed_at + self._world_signal_minimum_delay_seconds
                if armed_at is not None
                else now
            )
            for event in events:
                if event.received_monotonic < minimum_event_time:
                    continue
                if event.count == 0:
                    if event.kind in {"nearby-pokemon", "wild-pokemon"}:
                        self._world_reset_observed = True
                        self._world_positive_events = {}
                        self._world_positive_update_counts = {}
                        self._world_candidate_monotonic = None
                    continue
                self._world_positive_events[event.kind] = event
                self._world_positive_update_counts[event.kind] = (
                    self._world_positive_update_counts.get(event.kind, 0) + 1
                )

            spawn_events = [
                event for kind, event in self._world_positive_events.items()
                if kind in {"nearby-pokemon", "wild-pokemon"} and event.count > 0
            ]
            corroborating_kinds = len(self._world_positive_events)
            repeated_spawn_update = any(
                self._world_positive_update_counts.get(kind, 0) >= 2
                for kind in ("nearby-pokemon", "wild-pokemon")
            )
            credible = bool(spawn_events) and (
                self._world_reset_observed
                or corroborating_kinds >= 2
                or repeated_spawn_update
            )
            if credible and self._world_candidate_monotonic is None:
                self._world_candidate_monotonic = max(
                    event.received_monotonic for event in self._world_positive_events.values()
                )
            if (
                not credible
                or self._world_candidate_monotonic is None
                or now - self._world_candidate_monotonic < self._world_notification_grace_seconds
            ):
                return None

            counts = {
                kind: int(event.count)
                for kind, event in self._world_positive_events.items()
            }
            evidence = {
                "targetId": target_id,
                "receivedAt": datetime.now(timezone.utc).isoformat(),
                "resetObserved": self._world_reset_observed,
                "counts": counts,
                "spawnCount": sum(event.count for event in spawn_events),
                "notificationGraceSeconds": self._world_notification_grace_seconds,
                "action": "world-loaded-no-hundo",
            }
            self._world_ready_delivered = True
            self._world_last_evidence = dict(evidence)
            return evidence

    def end_target(self, target_id: int) -> None:
        with self._lock:
            if self._active_target_id == target_id:
                self._active_target_id = None
                self._active_species = None
                self._checkpoint = self.watcher.checkpoint()
                if self.world_watcher is not None:
                    self._world_checkpoint = self.world_watcher.checkpoint()
                self._world_armed_monotonic = None
                self._world_candidate_monotonic = None
                self._world_ready_delivered = False

    def update_mac_bridge(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._source_gate:
            return self._update_mac_bridge(payload)

    def _update_mac_bridge(self, payload: dict[str, Any]) -> dict[str, Any]:
        # Display-off mode has exactly one source. A mirrored duplicate must
        # neither stop the phone stream nor become proof for the next target.
        with self._lock:
            if self._alert_source == "direct":
                return {"accepted": False, "bridgeState": "ignored-direct-mode", "trusted": False}
        state = " ".join(str(payload.get("state") or "unknown").strip().split())[:80]
        trusted = bool(payload.get("trusted"))
        error = " ".join(str(payload.get("error") or "").strip().split())[:500] or None
        event_text: str | None = None
        source_name: str | None = None
        if str(payload.get("type") or "") == "notification":
            source_name = " ".join(str(payload.get("appName") or "iPhone notification").strip().split())[:120]
            title = " ".join(str(payload.get("title") or "").strip().split())[:300]
            body = " ".join(str(payload.get("body") or "").strip().split())[:700]
            event_text = " · ".join(part for part in (source_name, title, body) if part)
        with self._lock:
            self._mac_bridge_state = state or "unknown"
            self._mac_bridge_trusted = trusted
            self._mac_bridge_last_error = error
            self._mac_bridge_last_heartbeat_monotonic = time.monotonic()
            self._mac_bridge_last_heartbeat_at = datetime.now(timezone.utc).isoformat()
            if event_text:
                self._mac_bridge_last_seen_at = datetime.now(timezone.utc).isoformat()
                self._mac_bridge_last_source = source_name
        # Use one authoritative event stream. When the proven native bridge is
        # live, stop the USB diagnostic stream so the same phone alert cannot
        # arrive twice and be credited to two consecutive targets.
        if state == "listening" and trusted:
            watcher_status = self.watcher.status()
            stopper = getattr(self.watcher, "stop", None)
            if watcher_status.get("notificationWatcherState") == "listening" and callable(stopper):
                stopper()
        source_event = self.watcher.record_external(event_text) if event_text else None
        return {
            "accepted": source_event is not None,
            "bridgeState": self._mac_bridge_state,
            "trusted": self._mac_bridge_trusted,
        }

    def status(self) -> dict[str, Any]:
        watcher_status = self.watcher.status()
        world_status = (
            self.world_watcher.status()
            if self.world_watcher is not None
            else {
                "worldScanWatcherState": "unavailable",
                "worldScanWatcherLastError": None,
                "worldScanSequence": 0,
                "lastWorldScanEvent": None,
                "lastWorldScanSnapshot": None,
            }
        )
        last_observed = watcher_status.get("lastIpogoNotification")
        with self._lock:
            bridge_age = (
                time.monotonic() - self._mac_bridge_last_heartbeat_monotonic
                if self._mac_bridge_last_heartbeat_monotonic is not None
                else None
            )
            mac_bridge_ready = (
                self._mac_bridge_state == "listening"
                and self._mac_bridge_trusted
                and bridge_age is not None
                and bridge_age <= 8.0
            )
            effective_state = "listening" if mac_bridge_ready else watcher_status["notificationWatcherState"]
            direct = self._alert_source == "direct"
            direct_ready = bool(
                watcher_status["notificationWatcherState"] == "listening"
                and watcher_status.get("directAlertProof")
            )
            # A healthy direct banner endpoint can begin a walking hunt before
            # its first alert. Real Hundo evidence remains separate, never faked.
            direct_transport_ready = bool(
                watcher_status["notificationWatcherState"] == "listening"
                and watcher_status.get("directAlertTransport") == "iphone-banner"
            )
            if direct:
                effective_state = watcher_status["notificationWatcherState"]
            return {
                "state": effective_state,
                "alertSource": self._alert_source,
                "directAlertProof": watcher_status.get("directAlertProof"),
                "directAlertTransport": watcher_status.get("directAlertTransport"),
                "requiresAlertReadiness": True,
                "usbWatcherState": watcher_status["notificationWatcherState"],
                "activeTargetId": self._active_target_id,
                "checkpoint": self._checkpoint,
                "lastEvent": asdict(self._last_event) if self._last_event else None,
                "lastUnmatchedEvent": asdict(self._last_unmatched_event) if self._last_unmatched_event else None,
                "lastSpeciesMismatchEvent": asdict(self._last_unmatched_event) if self._last_unmatched_event else None,
                "acceptedSpeciesMismatchCount": self._accepted_species_mismatch_count,
                "lastObservedAlert": last_observed,
                "lastError": watcher_status["notificationWatcherLastError"],
                "sequence": watcher_status["notificationSequence"],
                "macBridgeState": self._mac_bridge_state,
                "macBridgeTrusted": self._mac_bridge_trusted,
                "macBridgeReady": mac_bridge_ready,
                "macBridgeHeartbeatAgeSeconds": round(bridge_age, 3) if bridge_age is not None else None,
                "macBridgeLastHeartbeatAt": self._mac_bridge_last_heartbeat_at,
                "macBridgeLastError": self._mac_bridge_last_error,
                "macBridgeLastSeenAt": self._mac_bridge_last_seen_at,
                "macBridgeLastSource": self._mac_bridge_last_source,
                "requiresMacBridge": not direct,
                "unattendedReady": direct_ready if direct else mac_bridge_ready,
                "huntReady": (direct_transport_ready or direct_ready) if direct else mac_bridge_ready,
                "worldScanWatcherState": world_status.get("worldScanWatcherState"),
                "worldScanWatcherLastError": (
                    self._world_last_error or world_status.get("worldScanWatcherLastError")
                ),
                "worldScanSequence": world_status.get("worldScanSequence", 0),
                "lastWorldScanEvent": world_status.get("lastWorldScanEvent"),
                "lastWorldScanSnapshot": world_status.get("lastWorldScanSnapshot"),
                "worldScanTargetState": (
                    "ready" if self._world_ready_delivered
                    else ("grace" if self._world_candidate_monotonic is not None
                          else ("watching" if self._active_target_id is not None else "idle"))
                ),
                "worldScanResetObserved": self._world_reset_observed,
                "worldScanCurrentCounts": {
                    kind: int(event.count)
                    for kind, event in self._world_positive_events.items()
                },
                "worldScanLastEvidence": (
                    dict(self._world_last_evidence) if self._world_last_evidence else None
                ),
                "worldScanNotificationGraceSeconds": self._world_notification_grace_seconds,
            }

    def close(self) -> None:
        self.watcher.close()
        if self.world_watcher is not None:
            self.world_watcher.close()


class HuntCoordinator:
    """Owns the real hunt lifecycle and its single phone-location worker."""

    def __init__(
        self,
        store: HuntStore,
        device: HuntDevice,
        detector: NotificationDetector | None = None,
        *,
        dwell_seconds: float = 45.0,
        max_sighting_age_seconds: float = 10 * 60,
        idle_poll_seconds: float = 0.5,
        ipogo_refresh_confirmed_interval: int = IPOGO_MEMORY_SAFE_CONFIRMED_CHECKS,
        ipogo_refresh_visit_interval: int = IPOGO_MEMORY_SAFE_MAP_LOADS,
        ipogo_recovery_timeout_threshold: int = 2,
        ipogo_restart_settle_seconds: float = 18.0,
        ipogo_recovery_dwell_seconds: float = 75.0,
        hundo_cooldown_seconds: float = 30.0,
        ipogo_clean_start: bool = True,
        notifier: Callable[[str, str], None] = notify_mac,
        shundo_alarm: Callable[[], None] = play_shundo_alarm,
    ) -> None:
        self.store = store
        self.device = device
        self.detector = detector or ManualNotificationDetector()
        self.default_dwell_seconds = self._validated_dwell(dwell_seconds)
        self.max_sighting_age_seconds = self._validated_max_age(max_sighting_age_seconds)
        self.idle_poll_seconds = max(0.05, float(idle_poll_seconds))
        self.ipogo_refresh_confirmed_interval = max(1, int(ipogo_refresh_confirmed_interval))
        self.ipogo_refresh_visit_interval = max(1, int(ipogo_refresh_visit_interval))
        self.ipogo_recovery_timeout_threshold = max(1, int(ipogo_recovery_timeout_threshold))
        self.ipogo_restart_settle_seconds = max(0.0, float(ipogo_restart_settle_seconds))
        self.ipogo_recovery_dwell_seconds = self._validated_dwell(ipogo_recovery_dwell_seconds)
        self.hundo_cooldown_seconds = self._validated_cooldown(hundo_cooldown_seconds)
        self.ipogo_clean_start = bool(ipogo_clean_start)
        self.notifier = notifier
        self.shundo_alarm = shundo_alarm
        self.encounter_guard = None

        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._worker: threading.Thread | None = None
        self._prepared = False
        self._stop_requested = False
        self._skip_requested = False
        self._hunt_state = "idle"
        self._phase = "unprepared"
        self._paused_phase: str | None = None
        self._message = "Prepare iPogo before starting the hunt."
        self._current_target: dict[str, Any] | None = None
        self._dwell_seconds = self.default_dwell_seconds
        self._deadline_monotonic: float | None = None
        self._seconds_remaining: int | None = None
        self._run_started_at: str | None = None
        self._last_transition_at = self._now()
        self._last_error: str | None = None
        self._checked_this_run = 0
        self._skipped_this_run = 0
        self._notifications_confirmed_this_run = 0
        self._timeouts_this_run = 0
        self._world_ready_skips_this_run = 0
        self._prepare_notification_sequence: int | None = None
        self._last_notification_proof: dict[str, Any] | None = None
        self._last_world_scan_proof: dict[str, Any] | None = None
        self._confirmed_since_ipogo_refresh = 0
        self._visits_since_ipogo_refresh = 0
        self._consecutive_timeouts = 0
        self._ipogo_refreshes_this_run = 0
        self._ipogo_refresh_state = "idle"
        self._ipogo_refresh_reason: str | None = None
        self._last_ipogo_refresh_at: str | None = None
        self._last_ipogo_refresh_error: str | None = None
        self._awaiting_ipogo_refresh_proof = False
        self._retry_world_recovery_requested = False
        self._health_retryable_pause = False
        self._clean_start_ipogo_requested = False
        self._queue_refill_requester: Callable[[], None] | None = None
        self._last_queue_refill_request_monotonic: float | None = None
        self._queue_refill_interval_seconds = 90.0

    def _minimum_target_remaining_seconds(self, dwell_seconds: float | None = None) -> float:
        """Leave enough life for the world to load and the alert check to finish."""
        dwell = self._dwell_seconds if dwell_seconds is None else float(dwell_seconds)
        return max(60.0, dwell + 30.0)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _validated_dwell(value: float) -> float:
        dwell = float(value)
        if not math.isfinite(dwell) or dwell < 0.05 or dwell > 600:
            raise HuntError("Dwell time must be between 0.05 and 600 seconds.")
        return dwell

    @staticmethod
    def _validated_max_age(value: float) -> float:
        maximum_age = float(value)
        if not math.isfinite(maximum_age) or maximum_age < 1 or maximum_age > 24 * 60 * 60:
            raise HuntError("Sighting age limit must be between 1 second and 24 hours.")
        return maximum_age

    @staticmethod
    def _validated_cooldown(value: float) -> float:
        cooldown = float(value)
        if not math.isfinite(cooldown) or cooldown < 0 or cooldown > 600:
            raise HuntError("Hundo cooldown must be between 0 and 600 seconds.")
        return cooldown

    def _set_phase_locked(self, phase: str, message: str) -> None:
        self._phase = phase
        self._message = message
        self._last_transition_at = self._now()

    def set_queue_refill_requester(self, requester: Callable[[], None]) -> None:
        with self._lock:
            self._queue_refill_requester = requester

    def configure_timing(
        self,
        dwell_seconds: float,
        recovery_failure_threshold: int,
        hundo_cooldown_seconds: float,
    ) -> dict[str, Any]:
        dwell = self._validated_dwell(dwell_seconds)
        cooldown = self._validated_cooldown(hundo_cooldown_seconds)
        failures = int(recovery_failure_threshold)
        if failures < 1 or failures > 20:
            raise HuntError("Failed map loads must be between 1 and 20.")
        with self._lock:
            if self._hunt_state in ("running", "paused"):
                raise HuntError("Stop the hunt before changing timing settings.")
            self.default_dwell_seconds = dwell
            self._dwell_seconds = dwell
            self.ipogo_recovery_timeout_threshold = failures
            self.hundo_cooldown_seconds = cooldown
        return self.status()

    def notify_targets_available(self) -> None:
        self._wake.set()

    def configure_alert_source(self, source: str) -> dict[str, Any]:
        with self._lock:
            if self._prepared or (self._worker and self._worker.is_alive()) or self._hunt_state != "idle":
                raise HuntError("Stop and end preparation before changing the alert source.")
            self.detector.set_alert_source(source)
        return self.status()

    def prepare(self) -> dict[str, Any]:
        if self.encounter_guard is not None:
            self.encounter_guard.require_unprotected()
        phone = self.device.refresh()
        if not phone.get("phoneConnected"):
            raise HuntError(str(phone.get("phoneLastError") or "Connect the iPhone before preparing iPogo."))
        runtime_verifier = getattr(self.device, "verify_ipogo_runtime", None)
        if callable(runtime_verifier):
            try:
                phone = runtime_verifier()
            except RuntimeError as error:
                raise HuntError(str(error)) from error
        udid = phone.get("phoneUdid")
        starter = getattr(self.detector, "start", None)
        if callable(starter):
            if not isinstance(udid, str) or not udid:
                raise HuntError("The connected iPhone did not provide a device identifier.")
            try:
                starter(udid)
            except RuntimeError as error:
                raise HuntError(f"Could not start the iPogo alert watcher: {error}") from error
        detector_status = self.detector.status()
        with self._lock:
            self._prepared = True
            self._prepare_notification_sequence = int(detector_status.get("sequence") or 0)
            self._last_error = None
            if self._hunt_state not in ("running", "paused"):
                self._hunt_state = "idle"
                self._set_phase_locked("ready", "iPogo session prepared. Ready to hunt.")
        runtime_version = phone.get("ipogoSpawnRuntimeVersion")
        runtime_detail = f" (spawn runtime v{runtime_version})" if runtime_version else ""
        self.store.record_hunt_event(f"iPogo session marked prepared{runtime_detail}")
        return self.status()

    def unprepare(self) -> dict[str, Any]:
        if self.encounter_guard is not None:
            self.encounter_guard.require_unprotected()
        with self._lock:
            self._prepared = False
            self._prepare_notification_sequence = None
            self._stop_requested = True
            self._hunt_state = "idle"
            self._deadline_monotonic = None
            self._seconds_remaining = None
            self._set_phase_locked("unprepared", "iPogo session is not prepared.")
            self._wake.set()
        self.store.set_hunt_state("idle")
        self.store.record_hunt_event("iPogo session preparation cleared")
        return self.status()

    def start(self, dwell_seconds: float | None = None) -> dict[str, Any]:
        if self.encounter_guard is not None:
            self.encounter_guard.require_hunt_ready()
        dwell = self.default_dwell_seconds if dwell_seconds is None else self._validated_dwell(dwell_seconds)
        phone = self.device.refresh()
        if not phone.get("phoneConnected"):
            raise HuntError(str(phone.get("phoneLastError") or "Connect the iPhone before starting."))
        detector_status = self.detector.status()
        if detector_status.get("requiresAlertReadiness", detector_status.get("requiresMacBridge")) and not alerts_ready_for_hunt(detector_status):
            raise HuntError(
                "The selected alert reader is not connected. For direct phone alerts, prepare iPogo "
                "and wait for the phone reader to connect. For mirrored alerts, enable Mac Accessibility."
            )

        with self._lock:
            if not self._prepared:
                raise HuntError("Prepare the iPogo session before starting the hunt.")
            if self._hunt_state == "running" and self._worker and self._worker.is_alive():
                return self.status()
            if self._hunt_state == "paused" and self._worker and self._worker.is_alive():
                self._hunt_state = "running"
                if self._phase == "paused-world":
                    self._retry_world_recovery_requested = True
                    self._set_phase_locked(
                        "retrying-world",
                        "Retrying recovery on the preserved target. Skip remains locked.",
                    )
                elif self._paused_phase == "cooldown":
                    self._set_phase_locked(
                        "cooldown",
                        "Cooldown resumed. Holding location before the next check.",
                    )
                else:
                    self._set_phase_locked("resuming", "Resuming the current target.")
                self._paused_phase = None
                self.store.set_hunt_state("running")
                self._wake.set()
                return self.status()

            # A database row can remain `current` if the app or its local
            # service was restarted mid-check.  There is no live worker to
            # own that row here, so resuming it would silently resurrect an
            # old coordinate and bypass normal queue ordering.
            self.store.discard_orphaned_current()
            self.store.expire_stale_sightings(self.max_sighting_age_seconds)
            target = self.store.claim_next_target(
                self.max_sighting_age_seconds,
                self._minimum_target_remaining_seconds(dwell),
            )
            if target is None:
                raise HuntError("There are no fresh queued sightings to hunt.")

            self._dwell_seconds = dwell
            self._stop_requested = False
            self._skip_requested = False
            self._paused_phase = None
            self._hunt_state = "running"
            self._current_target = target
            self._deadline_monotonic = None
            self._seconds_remaining = None
            self._last_error = None
            self._checked_this_run = 0
            self._skipped_this_run = 0
            self._notifications_confirmed_this_run = 0
            self._timeouts_this_run = 0
            self._world_ready_skips_this_run = 0
            self._last_notification_proof = None
            self._last_world_scan_proof = None
            self._confirmed_since_ipogo_refresh = 0
            self._visits_since_ipogo_refresh = 0
            self._consecutive_timeouts = 0
            self._ipogo_refreshes_this_run = 0
            self._ipogo_refresh_state = "idle"
            self._ipogo_refresh_reason = None
            self._last_ipogo_refresh_at = None
            self._last_ipogo_refresh_error = None
            self._awaiting_ipogo_refresh_proof = False
            self._retry_world_recovery_requested = False
            self._clean_start_ipogo_requested = self.ipogo_clean_start
            self._run_started_at = self._now()
            label = target.get("species") or "target"
            self._set_phase_locked("starting", f"Starting with {label}.")
            self.store.set_hunt_state("running")
            self._worker = threading.Thread(
                target=self._worker_main,
                args=(target,),
                name="shundo-hunt-coordinator",
                daemon=True,
            )
            self._worker.start()
        return self.status()

    def stop_for_real_location(self, timeout: float = 3.0) -> dict[str, Any]:
        """Stop every hunt action before the device location override is cleared."""
        if self.encounter_guard is not None:
            self.encounter_guard.require_unprotected()
        with self._lock:
            target = dict(self._current_target) if self._current_target else None
            self._prepared = False
            self._prepare_notification_sequence = None
            self._stop_requested = True
            self._skip_requested = False
            self._hunt_state = "idle"
            self._current_target = None
            self._deadline_monotonic = None
            self._seconds_remaining = None
            self._set_phase_locked("unprepared", "Real location requested. Prepare iPogo before hunting again.")
            self._wake.set()
            worker = self._worker

        if worker and worker.is_alive() and worker is not threading.current_thread():
            worker.join(timeout=timeout)
        if target is not None:
            target_id = int(target["id"])
            self.detector.end_target(target_id)
            self.store.complete_hunt_target(
                target_id,
                "expired",
                "Hunt stopped to restore the iPhone's real location",
            )
        self.store.set_hunt_state("idle")
        self.store.record_hunt_event("Hunt stopped before restoring the iPhone's real location")
        return self.status()

    def pause(self) -> dict[str, Any]:
        with self._lock:
            if self._hunt_state != "running" or not self._worker or not self._worker.is_alive():
                raise HuntError("The hunt is not running.")
            self._hunt_state = "paused"
            self._paused_phase = self._phase
            if self._phase == "cooldown":
                self._set_phase_locked(
                    "paused",
                    "Hunt paused during cooldown. The next target has not started.",
                )
            else:
                self._set_phase_locked("paused", "Hunt paused. The current target is preserved.")
            self._wake.set()
        self.store.set_hunt_state("paused")
        return self.status()

    def health_pause(self, message, *, alerts=False):
        """Cooperative pause only; the watchdog never runs location work."""
        with self._lock:
            if (self._hunt_state != "running" or not self._prepared or self._stop_requested
                    or (self.encounter_guard is not None and self.encounter_guard.protected)):
                return False
            if alerts:
                self._hunt_state = "paused"
                self._set_phase_locked("paused-alerts", message)
                self.store.set_hunt_state("paused")
            else:
                self._pause_for_world_recovery(message,
                    self._current_target.get("id") if self._current_target else None, retryable=True)
            self._wake.set()
            return True

    def health_retry(self, target_id):
        """Queue the established refresh on the sole hunt worker, never here."""
        with self._lock:
            watcher = getattr(self.detector, "watcher", None)
            if watcher is not None and any(e.is_shundo for e in watcher.events_after(self.detector.status().get("checkpoint", 0))):
                return False
            if (self._hunt_state != "paused" or self._phase != "paused-world"
                    or not self._health_retryable_pause or not self._prepared or self._stop_requested
                    or not self._worker or not self._worker.is_alive()
                    or (self._current_target.get("id") if self._current_target else None) != target_id
                    or (self.encounter_guard is not None and self.encounter_guard.protected)
                    or not alerts_ready_for_hunt(self.detector.status())):
                return False
            self._health_retryable_pause = False
            self._retry_world_recovery_requested = True
            self._hunt_state = "running"
            self._set_phase_locked("retrying-world", "Health watchdog queued a bounded refresh on the preserved target.")
            self.store.set_hunt_state("running")
            self._wake.set()
            return True

    def skip(self) -> dict[str, Any]:
        if self.encounter_guard is not None:
            self.encounter_guard.require_unprotected()
        with self._lock:
            if self._current_target is None or not self._worker or not self._worker.is_alive():
                raise HuntError("There is no active target to skip.")
            if self._phase in {
                "restarting-ipogo", "settling-ipogo", "verifying-world",
                "paused-world", "retrying-world",
            }:
                raise HuntError("Skip is locked during world recovery so iPogo cannot change coordinates mid-launch.")
            self._skip_requested = True
            label = self._current_target.get("species") or "target"
            self._message = f"Skipping {label}."
            self._last_transition_at = self._now()
            self._wake.set()
        return self.status()

    def inject_notification(
        self,
        *,
        kind: str = "shundo",
        message: str = "Manual Shundo test signal",
    ) -> dict[str, Any]:
        injector = getattr(self.detector, "inject", None)
        if not callable(injector):
            raise HuntError("The active notification watcher does not support manual signals.")
        with self._lock:
            if self._current_target is None or self._hunt_state not in ("running", "paused"):
                raise HuntError("Start a target before injecting a notification.")
            target_id = int(self._current_target["id"])
        event = injector(kind=kind, message=message, target_id=target_id)
        self._wake.set()
        result = self.status()
        result["injectedNotification"] = asdict(event)
        return result

    def update_mac_notification_bridge(self, payload: dict[str, Any]) -> dict[str, Any]:
        updater = getattr(self.detector, "update_mac_bridge", None)
        if not callable(updater):
            raise HuntError("The active alert watcher does not support the Mac notification bridge.")
        result = updater(payload)
        if result.get("accepted"):
            self._wake.set()
        return result

    def _worker_main(self, initial_target: dict[str, Any]) -> None:
        target: dict[str, Any] | None = initial_target
        try:
            while True:
                if not self._wait_until_running():
                    return
                if target is None:
                    with self._lock:
                        retry_world = self._retry_world_recovery_requested
                        self._retry_world_recovery_requested = False
                    if retry_world:
                        if not self._restart_ipogo_session("operator requested a recovery retry"):
                            continue
                    if self._ipogo_refresh_due():
                        if not self._restart_ipogo_session(
                            "14-map-load memory budget reached; clean relaunch before the next coordinate"
                        ):
                            continue
                    target = self.store.claim_next_target(
                        self.max_sighting_age_seconds,
                        self._minimum_target_remaining_seconds(),
                    )
                    if target is None:
                        requester: Callable[[], None] | None = None
                        with self._lock:
                            self._current_target = None
                            self._deadline_monotonic = None
                            self._seconds_remaining = None
                            now = time.monotonic()
                            last = self._last_queue_refill_request_monotonic
                            if (
                                self._queue_refill_requester is not None
                                and (last is None or now - last >= self._queue_refill_interval_seconds)
                            ):
                                requester = self._queue_refill_requester
                                self._last_queue_refill_request_monotonic = now
                                self._set_phase_locked(
                                    "refreshing-feed",
                                    "Queue is empty. Refreshing iPogo’s 100-IV feed automatically.",
                                )
                            else:
                                self._set_phase_locked("waiting", "Waiting for a fresh queued sighting.")
                        if requester is not None:
                            try:
                                requester()
                            except Exception as error:
                                with self._lock:
                                    self._last_error = str(error)
                                    self._set_phase_locked(
                                        "waiting",
                                        f"Feed refresh will retry automatically: {error}",
                                    )
                                self.store.record_hunt_event(
                                    f"Automatic queue refill failed: {error}", "error"
                                )
                        self._wait_for_wake(self.idle_poll_seconds)
                        continue
                    with self._lock:
                        self._current_target = target

                outcome = self._process_target(target)
                if outcome == "stop":
                    return
                target = None
        except Exception as error:  # Keep a worker failure visible instead of silently dying.
            target_id = None
            with self._lock:
                if self._current_target is not None:
                    target_id = int(self._current_target["id"])
                self._hunt_state = "error"
                self._last_error = str(error)
                self._deadline_monotonic = None
                self._seconds_remaining = None
                self._set_phase_locked("error", f"Hunt stopped: {error}")
            if target_id is not None:
                self.store.complete_hunt_target(target_id, "failed", str(error))
            self.store.set_hunt_state("error")

    def _wait_until_running(self) -> bool:
        while True:
            with self._lock:
                if self._stop_requested or not self._prepared:
                    return False
                if self._skip_requested and self._current_target is not None:
                    return True
                if self._hunt_state != "paused":
                    return self._hunt_state == "running"
            self._wait_for_wake(0.1)

    def _ipogo_refresh_due(self) -> bool:
        with self._lock:
            return bool(
                self._confirmed_since_ipogo_refresh >= self.ipogo_refresh_confirmed_interval
                or self._visits_since_ipogo_refresh >= self.ipogo_refresh_visit_interval
            )

    def _wait_interruptibly(self, seconds: float) -> bool:
        remaining = max(0.0, seconds)
        last = time.monotonic()
        while remaining > 0:
            with self._lock:
                if self._stop_requested or not self._prepared:
                    return False
                paused = self._hunt_state == "paused"
            now = time.monotonic()
            if not paused:
                remaining -= now - last
            last = now
            self._wait_for_wake(min(0.1, max(0.0, remaining)))
        return True

    def _wait_for_hundo_cooldown(self, label: str, target_id: int) -> bool:
        remaining = self.hundo_cooldown_seconds
        if remaining <= 0:
            return True
        last = time.monotonic()
        with self._lock:
            self._deadline_monotonic = last + remaining
            self._seconds_remaining = math.ceil(remaining)
            self._set_phase_locked(
                "cooldown",
                f"Hundo confirmed for {label}. Holding location before the next check.",
            )
        self.store.record_hunt_event(
            f"Holding {remaining:g} seconds after {label} before the next check",
            "success",
            target_id,
        )
        while remaining > 0:
            with self._lock:
                if self._stop_requested or not self._prepared:
                    self._deadline_monotonic = None
                    self._seconds_remaining = None
                    return False
                running = self._hunt_state == "running"
            now = time.monotonic()
            if running:
                remaining = max(0.0, remaining - (now - last))
            last = now
            with self._lock:
                self._seconds_remaining = math.ceil(remaining)
                self._deadline_monotonic = now + remaining if running else None
            if remaining <= 0:
                break
            self._wait_for_wake(min(0.1, remaining))
        with self._lock:
            self._deadline_monotonic = None
            self._seconds_remaining = None
        return True

    def _restart_ipogo_session(self, reason: str, target_id: int | None = None) -> bool:
        # A Shundo can arrive after the watchdog queues a retry. Recheck at
        # execution time; never consume its evidence merely to permit repair.
        if self.encounter_guard is not None and self.encounter_guard.protected:
            return False
        watcher = getattr(self.detector, "watcher", None)
        if watcher is not None and any(e.is_shundo for e in watcher.events_after(self.detector.status().get("checkpoint", 0))):
            self._pause_for_world_recovery("Shundo alert pending; refresh blocked. Preserve this location and inspect the phone.", target_id)
            return False
        restarter = getattr(self.device, "restart_ipogo", None)
        if not callable(restarter):
            error = "This iPhone controller cannot refresh iPogo automatically."
            self._pause_for_world_recovery(error, target_id)
            return False
        with self._lock:
            self._ipogo_refresh_state = "restarting"
            self._ipogo_refresh_reason = reason
            self._last_ipogo_refresh_error = None
            self._deadline_monotonic = None
            self._seconds_remaining = math.ceil(self.ipogo_restart_settle_seconds)
            self._set_phase_locked("restarting-ipogo", "Refreshing iPogo while the spoofed location stays active.")
        self.store.record_hunt_event(f"Refreshing iPogo: {reason}", "info", target_id)
        try:
            restarter()
        except Exception as error:
            self._pause_for_world_recovery(f"iPogo refresh failed: {error}", target_id)
            return False
        with self._lock:
            self._ipogo_refresh_state = "settling"
            self._set_phase_locked(
                "settling-ipogo",
                f"iPogo refreshed. Holding the location for {self.ipogo_restart_settle_seconds:g} seconds while the world loads.",
            )
        if not self._wait_interruptibly(self.ipogo_restart_settle_seconds):
            return False
        if not self._recover_screen("After iPogo refresh", target_id):
            return False
        refreshed_at = self._now()
        with self._lock:
            self._confirmed_since_ipogo_refresh = 0
            self._visits_since_ipogo_refresh = 0
            self._consecutive_timeouts = 0
            self._ipogo_refreshes_this_run += 1
            self._ipogo_refresh_state = "verifying"
            self._last_ipogo_refresh_at = refreshed_at
            self._last_ipogo_refresh_error = None
            self._awaiting_ipogo_refresh_proof = True
            self._deadline_monotonic = None
            self._seconds_remaining = None
            self._set_phase_locked("verifying-world", "iPogo refreshed. The next Hundo alert will verify the world load.")
        self.store.record_hunt_event("iPogo refresh completed; awaiting a live Hundo proof", "success", target_id)
        return True

    def _recover_screen(self, reason, target_id, *, probe=False, deadline=None, after_hundo=False):
        if self.encounter_guard is None:
            return True
        from .screen_recovery import RecoveryCancelled, ObservationUnavailable
        def check():
            with self._lock:
                if self._stop_requested or not self._prepared or self._skip_requested or self._hunt_state != "running":
                    raise RecoveryCancelled("Hunt was paused, skipped or stopped; no recovery tap allowed.")
                if deadline is not None and time.monotonic() >= deadline:
                    raise RecoveryCancelled("Coordinate loading time limit reached; no further recovery tap allowed.")
        try:
            self.encounter_guard.recover_hunt_screen(reason, check, probe=probe, after_hundo=after_hundo)
            return True
        except RecoveryCancelled:
            return "interrupted"  # Poll stop/skip/pause/pending Shundo before any world result.
        except Exception as error:
            self._pause_for_world_recovery(f"Screen recovery needs attention: {error}", target_id,
                                          retryable=isinstance(error, ObservationUnavailable))
            return False

    def _pause_for_world_recovery(self, message: str, target_id: int | None, *, retryable=False) -> None:
        with self._lock:
            self._hunt_state = "paused"
            self._health_retryable_pause = retryable
            self._ipogo_refresh_state = "failed"
            self._last_ipogo_refresh_error = message
            self._last_error = message
            self._deadline_monotonic = None
            self._seconds_remaining = None
            self._set_phase_locked(
                "paused-world",
                f"World recovery paused: {message} Choose Retry recovery; do not change targets.",
            )
        self.store.set_hunt_state("paused")
        self.store.record_hunt_event(message, "error", target_id)
        self.notifier("Shundo Hunter paused", message)

    def _resolve_target_coordinates(
        self,
        target: dict[str, Any],
        timeout_seconds: float = 15.0,
    ) -> dict[str, Any] | str | None:
        """Wait briefly for the native PokeX bridge to resolve one imminent target."""
        target_id = int(target["id"])
        label = target.get("species") or "target"
        try:
            self.store.queue_pokexperience_resolution(target_id)
        except (AttributeError, ValueError) as error:
            self.store.complete_hunt_target(
                target_id, "failed", str(error), completion_reason="coordinate-resolution"
            )
            return None
        deadline = time.monotonic() + max(3.0, timeout_seconds)
        with self._lock:
            self._deadline_monotonic = deadline
            self._seconds_remaining = math.ceil(deadline - time.monotonic())
            self._set_phase_locked(
                "resolving-coordinate",
                f"Getting {label}’s coordinates from PokeXperience. The clipboard remains untouched.",
            )
        while time.monotonic() < deadline:
            with self._lock:
                if self._stop_requested or not self._prepared:
                    return "stop"
                if self._skip_requested:
                    self._deadline_monotonic = None
                    self._seconds_remaining = None
                    self._finish_skipped(target_id, label)
                    return None
                paused = self._hunt_state == "paused"
            if paused:
                self._wait_for_wake(0.1)
                deadline += 0.1
                continue
            try:
                refreshed = self.store.get_sighting(target_id)
            except ValueError:
                return None
            if refreshed.get("latitude") is not None and refreshed.get("longitude") is not None:
                with self._lock:
                    self._deadline_monotonic = None
                    self._seconds_remaining = None
                return refreshed
            if refreshed.get("coordinate_state") == "failed":
                message = refreshed.get("coordinate_error") or "PokeXperience could not match this live row."
                self.store.complete_hunt_target(
                    target_id, "failed", message, completion_reason="coordinate-resolution"
                )
                with self._lock:
                    self._deadline_monotonic = None
                    self._seconds_remaining = None
                return None
            with self._lock:
                self._seconds_remaining = max(0, math.ceil(deadline - time.monotonic()))
            self._wait_for_wake(0.1)
        message = "PokeXperience did not return coordinates before the target-resolution timeout."
        self.store.complete_hunt_target(
            target_id, "failed", message, completion_reason="coordinate-resolution-timeout"
        )
        self.store.record_hunt_event(message, "error", target_id)
        with self._lock:
            self._deadline_monotonic = None
            self._seconds_remaining = None
        return None

    def _process_target(self, target: dict[str, Any]) -> str:
        target_id = int(target["id"])
        label = target.get("species") or "target"
        if target.get("latitude") is None or target.get("longitude") is None:
            resolved = self._resolve_target_coordinates(target)
            if resolved is None:
                return "advance"
            if resolved == "stop":
                return "stop"
            target = resolved
            with self._lock:
                self._current_target = target
        with self._lock:
            self._set_phase_locked("setting-location", f"Sending {label} to the iPhone.")

        try:
            hunt_mover = getattr(self.device, "set_hunt_location", self.device.set_location)
            hunt_mover(float(target["latitude"]), float(target["longitude"]))
            self.store.record_phone_location(target)
            # Arm proof only after the new coordinate is active. This rejects
            # a delayed banner from the previous stop without requiring exact
            # agreement between Discord's and iPogo's species labels.
            self.detector.begin_target(target)
            with self._lock:
                self._visits_since_ipogo_refresh += 1
        except Exception as error:
            self.detector.end_target(target_id)
            self.store.complete_hunt_target(target_id, "failed", str(error))
            with self._lock:
                self._hunt_state = "error"
                self._last_error = str(error)
                self._set_phase_locked("error", f"Could not set the phone location: {error}")
            self.store.set_hunt_state("error")
            return "stop"

        with self._lock:
            if self._stop_requested or not self._prepared:
                self.detector.end_target(target_id)
                return "stop"
            if self._skip_requested:
                return self._finish_skipped(target_id, label)
            clean_start_requested = self._clean_start_ipogo_requested
            self._clean_start_ipogo_requested = False

        if clean_start_requested:
            if not self._restart_ipogo_session(
                "new hunt memory baseline; clean relaunch at the first coordinate",
                target_id,
            ):
                # The restart helper leaves the hunt paused with this target
                # preserved, so the normal recovery loop below can resume it.
                pass
            else:
                # The first target is already active after the fresh process
                # launches, so it consumes map-load slot one of the new budget.
                with self._lock:
                    self._visits_since_ipogo_refresh = 1

        remaining = self._dwell_seconds
        deadline = time.monotonic() + remaining
        recovery_attempted_for_target = False
        pending_hundo = None
        hundo_cleanup_done = False
        with self._lock:
            self._deadline_monotonic = deadline
            self._seconds_remaining = max(0, math.ceil(remaining))
            self._set_phase_locked(
                "dwelling",
                f"Walking around {label} while the map loads and watching for a Shundo.",
            )

        while True:
            with self._lock:
                if self._stop_requested or not self._prepared:
                    self.detector.end_target(target_id)
                    self._deadline_monotonic = None
                    self._seconds_remaining = None
                    return "stop"
                if self._skip_requested:
                    return self._finish_skipped(target_id, label)
                paused = self._hunt_state == "paused"
                retry_world_requested = bool(
                    self._retry_world_recovery_requested and not paused
                )
                if retry_world_requested:
                    self._retry_world_recovery_requested = False

            if retry_world_requested:
                pending_hundo = None
                hundo_cleanup_done = False
                if self._restart_ipogo_session(
                    "operator requested a recovery retry",
                    target_id,
                ):
                    recovery_attempted_for_target = True
                    deadline = time.monotonic() + self.ipogo_recovery_dwell_seconds
                    with self._lock:
                        self._deadline_monotonic = deadline
                        self._seconds_remaining = math.ceil(self.ipogo_recovery_dwell_seconds)
                        self._set_phase_locked(
                            "verifying-world",
                            f"Retrying {label} after a clean iPogo restart. Skip remains locked.",
                        )
                continue

            if paused:
                remaining = max(0.0, deadline - time.monotonic())
                perform_world_retry = False
                with self._lock:
                    alert_monitoring_pause = self._phase == "paused-alerts"
                    world_recovery_pause = self._phase in ("paused-world", "retrying-world")
                    if world_recovery_pause:
                        remaining = self.ipogo_recovery_dwell_seconds
                    self._deadline_monotonic = None
                    self._seconds_remaining = math.ceil(remaining)
                    if not alert_monitoring_pause and not world_recovery_pause:
                        self._set_phase_locked("paused", f"Paused on {label}.")
                recovery_started_at: float | None = None
                while True:
                    with self._lock:
                        if self._stop_requested or not self._prepared:
                            self.detector.end_target(target_id)
                            return "stop"
                        if self._skip_requested:
                            return self._finish_skipped(target_id, label)
                        alert_monitoring_pause = self._phase == "paused-alerts"
                        world_recovery_pause = self._phase in ("paused-world", "retrying-world")
                        if self._hunt_state != "paused":
                            if self._retry_world_recovery_requested:
                                self._retry_world_recovery_requested = False
                                perform_world_retry = True
                                break
                            deadline = time.monotonic() + remaining
                            self._deadline_monotonic = deadline
                            self._set_phase_locked(
                                "verifying-world" if world_recovery_pause else "dwelling",
                                (f"Retrying {label} after world recovery."
                                 if world_recovery_pause else
                                 f"Walking around {label} while the map loads and watching for a Shundo."),
                            )
                            break
                    if alert_monitoring_pause:
                        detector_status = self.detector.status()
                        if alerts_ready_for_hunt(detector_status):
                            now = time.monotonic()
                            recovery_started_at = recovery_started_at or now
                            if now - recovery_started_at >= 2.0:
                                with self._lock:
                                    if self._hunt_state == "paused" and self._phase == "paused-alerts":
                                        self._hunt_state = "running"
                                        self._last_error = None
                                        deadline = time.monotonic() + remaining
                                        self._deadline_monotonic = deadline
                                        self._set_phase_locked(
                                            "dwelling",
                                            f"Notification monitoring recovered. Watching {label}.",
                                        )
                                self.store.set_hunt_state("running")
                                self.store.record_hunt_event(
                                    f"Notification monitoring recovered on {label}; hunt resumed",
                                    "success",
                                    target_id,
                                )
                                break
                        else:
                            recovery_started_at = None
                    self._wait_for_wake(0.1)

                if perform_world_retry:
                    pending_hundo = None
                    hundo_cleanup_done = False
                    if self._restart_ipogo_session(
                        "operator requested a recovery retry",
                        target_id,
                    ):
                        recovery_attempted_for_target = True
                        deadline = time.monotonic() + self.ipogo_recovery_dwell_seconds
                        with self._lock:
                            self._deadline_monotonic = deadline
                            self._seconds_remaining = math.ceil(self.ipogo_recovery_dwell_seconds)
                            self._set_phase_locked(
                                "verifying-world",
                                f"Retrying {label} after a clean iPogo restart. Skip remains locked.",
                            )
                    continue

            event = self.detector.poll(target_id)
            # Retain an already captured Hundo across bounded cleanup/pause.
            # Poll again before committing it so a newer Shundo always wins.
            if pending_hundo is not None and not (event is not None and event.is_shundo):
                event = pending_hundo
            detector_status = self.detector.status()
            mismatch_event = detector_status.get("lastSpeciesMismatchEvent") or {}
            species_label_matched = not (
                event is not None
                and mismatch_event.get("target_id") == target_id
                and mismatch_event.get("message") == event.message
                and mismatch_event.get("received_at") == event.received_at
            )
            if event is not None and event.is_shundo:
                self.detector.end_target(target_id)
                self.store.complete_hunt_target(
                    target_id,
                    "shundo",
                    event.message,
                    completion_reason="shundo-notification",
                    notification_received_at=event.received_at,
                )
                self.store.record_hunt_event(
                    f"Shundo notification confirmed for {label}: {event.message}"
                    + (" (iPogo species label differed; accepted as fresh alert)" if not species_label_matched else ""),
                    "success",
                    target_id,
                )
                self.store.set_hunt_state("shundo")
                with self._lock:
                    self._notifications_confirmed_this_run += 1
                    self._confirmed_since_ipogo_refresh += 1
                    self._consecutive_timeouts = 0
                    if self._awaiting_ipogo_refresh_proof:
                        self._awaiting_ipogo_refresh_proof = False
                        self._ipogo_refresh_state = "verified"
                    self._last_notification_proof = {
                        "targetId": target_id,
                        "species": label,
                        "kind": "shundo",
                        "message": event.message,
                        "receivedAt": event.received_at,
                        "action": "hunt-stopped",
                        "speciesLabelMatched": species_label_matched,
                    }
                    self._hunt_state = "shundo"
                    if self.encounter_guard is not None:
                        self.encounter_guard.latch_shundo()
                    self._deadline_monotonic = None
                    self._seconds_remaining = 0
                    self._set_phase_locked("shundo", f"Shundo detected: {label}. Hunt stopped.")
                if self.encounter_guard is not None:
                    self.encounter_guard.on_shundo(target, event)
                self.shundo_alarm()
                self.notifier("Shundo Hunter", f"Shundo {label} detected. The hunt has stopped.")
                return "stop"
            if event is not None and event.is_hundo:
                if not hundo_cleanup_done:
                    pending_hundo = event
                    with self._lock:
                        self._deadline_monotonic = None
                        self._seconds_remaining = None
                        self._set_phase_locked("clearing-screen", f"Hundo received for {label}; checking for blocking notices before moving on.")
                    recovered = self._recover_screen("Resuming screen cleanup after Hundo", target_id,
                                                     probe=True, after_hundo=True)
                    if recovered is True:
                        hundo_cleanup_done = True
                    continue
                self.detector.end_target(target_id)
                self.store.complete_hunt_target(
                    target_id,
                    "checked",
                    event.message,
                    completion_reason="hundo-notification",
                    notification_received_at=event.received_at,
                )
                cooldown = self.hundo_cooldown_seconds
                advance_copy = (
                    f"holding {cooldown:g} seconds before the next check"
                    if cooldown > 0 else "advancing immediately"
                )
                self.store.record_hunt_event(
                    f"Hundo notification confirmed for {label}; {advance_copy}: {event.message}"
                    + (" (iPogo species label differed; accepted as fresh alert)" if not species_label_matched else ""),
                    "success",
                    target_id,
                )
                with self._lock:
                    self._checked_this_run += 1
                    self._notifications_confirmed_this_run += 1
                    self._confirmed_since_ipogo_refresh += 1
                    self._consecutive_timeouts = 0
                    if self._awaiting_ipogo_refresh_proof:
                        self._awaiting_ipogo_refresh_proof = False
                        self._ipogo_refresh_state = "verified"
                    self._last_notification_proof = {
                        "targetId": target_id,
                        "species": label,
                        "kind": "hundo",
                        "message": event.message,
                        "receivedAt": event.received_at,
                        "action": "cooldown" if cooldown > 0 else "advanced",
                        "speciesLabelMatched": species_label_matched,
                    }
                    self._current_target = None
                    self._deadline_monotonic = None
                    self._seconds_remaining = None
                if cooldown > 0:
                    if not self._wait_for_hundo_cooldown(label, target_id):
                        return "stop"
                    with self._lock:
                        if self._last_notification_proof:
                            self._last_notification_proof["action"] = "advanced-after-cooldown"
                with self._lock:
                    self._set_phase_locked(
                        "selecting",
                        f"Hundo confirmed for {label}; selecting the next target.",
                    )
                return "continue"

            # Process a captured alert before acting on the health sample.
            # Otherwise an alert and a transient offline state in the same
            # poll cycle advances the detector checkpoint but drops the alert.
            if detector_status.get("requiresAlertReadiness", detector_status.get("requiresMacBridge")) and not alerts_ready_for_hunt(detector_status):
                remaining = max(0.0, deadline - time.monotonic())
                with self._lock:
                    self._hunt_state = "paused"
                    self._last_error = "The selected notification detector stopped listening."
                    self._deadline_monotonic = None
                    self._seconds_remaining = math.ceil(remaining)
                    self._set_phase_locked(
                        "paused-alerts",
                        "Hunt paused because notification monitoring went offline. The current target was preserved.",
                    )
                self.store.set_hunt_state("paused")
                self.store.record_hunt_event(
                    f"Paused on {label}: notification monitoring went offline",
                    "error",
                    target_id,
                )
                self.notifier(
                    "Shundo Hunter paused",
                    "Notification monitoring went offline. The current target was preserved.",
                )
                continue

            if time.monotonic() < deadline:
                recovery_started = time.monotonic()
                recovered = self._recover_screen("Blocking notice or egg detected while waiting", target_id,
                                                 probe=True, deadline=deadline)
                # Never replenish a coordinate's loading timer for probes or
                # cleanup. Late read/AI results are checked before any touch.
                if not recovered or recovered == "interrupted":
                    continue
                # Process alerts that arrived during cleanup before timeout.
                if time.monotonic() - recovery_started > .5:
                    continue
            world_poller = getattr(self.detector, "poll_world", None)
            world_evidence = world_poller(target_id) if callable(world_poller) else None
            if world_evidence is not None:
                self.detector.end_target(target_id)
                counts = world_evidence.get("counts") or {}
                evidence_summary = ", ".join(
                    f"{kind}={count}" for kind, count in sorted(counts.items())
                ) or f"spawns={world_evidence.get('spawnCount', 0)}"
                message = (
                    "iPogo populated the current world but produced no Hundo alert "
                    f"after its notification grace ({evidence_summary})"
                )
                self.store.complete_hunt_target(
                    target_id,
                    "checked",
                    message,
                    completion_reason="world-loaded-no-hundo",
                )
                self.store.record_hunt_event(
                    f"World loaded for {label} with no Hundo alert; advancing immediately ({evidence_summary})",
                    "success",
                    target_id,
                )
                with self._lock:
                    self._checked_this_run += 1
                    self._world_ready_skips_this_run += 1
                    self._consecutive_timeouts = 0
                    if self._awaiting_ipogo_refresh_proof:
                        self._awaiting_ipogo_refresh_proof = False
                        self._ipogo_refresh_state = "verified"
                    proof = {
                        "targetId": target_id,
                        "species": label,
                        "kind": "world-loaded-no-hundo",
                        "message": message,
                        "receivedAt": world_evidence.get("receivedAt") or self._now(),
                        "action": "advanced-after-world-scan",
                        "counts": dict(counts),
                        "resetObserved": bool(world_evidence.get("resetObserved")),
                    }
                    self._last_world_scan_proof = dict(proof)
                    self._last_notification_proof = proof
                    self._current_target = None
                    self._deadline_monotonic = None
                    self._seconds_remaining = None
                    self._set_phase_locked(
                        "selecting",
                        f"World loaded with no Hundo for {label}; selecting the next target.",
                    )
                return "continue"

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                with self._lock:
                    next_consecutive_timeout = self._consecutive_timeouts + 1
                    self._consecutive_timeouts = next_consecutive_timeout
                self.detector.end_target(target_id)
                self.store.complete_hunt_target(
                    target_id,
                    "checked",
                    f"No iPogo alert received within {self._dwell_seconds:g} seconds; coordinate treated as unconfirmed",
                    completion_reason="timeout-no-alert",
                )
                with self._lock:
                    self._checked_this_run += 1
                    self._timeouts_this_run += 1
                    self._last_notification_proof = {
                        "targetId": target_id,
                        "species": label,
                        "kind": "timeout",
                        "message": f"No iPogo alert received within {self._dwell_seconds:g} seconds; coordinate skipped",
                        "receivedAt": self._now(),
                        "action": "advanced-after-timeout",
                    }
                    self._current_target = None
                    self._deadline_monotonic = None
                    self._seconds_remaining = None
                    self._set_phase_locked("selecting", f"No alert for {label}; moving to a different coordinate.")
                if next_consecutive_timeout >= self.ipogo_recovery_timeout_threshold:
                    # A missing Hundo cannot distinguish a bad coordinate from
                    # a degraded world. Refresh defensively, but never demand
                    # that the same suspect coordinate prove the restart.
                    self.store.record_hunt_event(
                        f"Discarded unconfirmed {label}; refreshing iPogo before a different target",
                        "info",
                        target_id,
                    )
                    self._restart_ipogo_session(
                        f"{next_consecutive_timeout} consecutive coordinates produced no Hundo alert",
                    )
                return "continue"

            with self._lock:
                self._seconds_remaining = max(0, math.ceil(remaining))
            self._wait_for_wake(min(0.1, remaining))

    def _finish_skipped(self, target_id: int, label: str) -> str:
        self.detector.end_target(target_id)
        self.store.complete_hunt_target(target_id, "skipped")
        with self._lock:
            self._skip_requested = False
            self._skipped_this_run += 1
            # The visit counter is incremented as soon as a target's location
            # becomes active. A user-directed Skip is not a completed map-load
            # attempt, so remove that visit from preventive refresh accounting.
            self._visits_since_ipogo_refresh = max(
                0, self._visits_since_ipogo_refresh - 1
            )
            # Manual intervention also breaks a run of consecutive automatic
            # no-alert timeouts; it must never move the failure threshold closer.
            self._consecutive_timeouts = 0
            self._current_target = None
            self._deadline_monotonic = None
            self._seconds_remaining = None
            self._set_phase_locked("selecting", f"Skipped {label}; selecting the next target.")
        return "continue"

    def _wait_for_wake(self, timeout: float) -> None:
        self._wake.wait(timeout=max(0.0, timeout))
        self._wake.clear()

    def status(self) -> dict[str, Any]:
        detector_status = self.detector.status()
        with self._lock:
            notification_sequence = int(detector_status.get("sequence") or 0)
            observed_since_prepare = bool(
                self._prepared
                and self._prepare_notification_sequence is not None
                and notification_sequence > self._prepare_notification_sequence
            )
            seconds_remaining = self._seconds_remaining
            if self._deadline_monotonic is not None and self._phase in {"dwelling", "cooldown"}:
                seconds_remaining = max(0, math.ceil(self._deadline_monotonic - time.monotonic()))
            target = dict(self._current_target) if self._current_target else None
            return {
                "huntState": self._hunt_state,
                "huntPhase": self._phase,
                "huntMessage": self._message,
                "huntSecondsRemaining": seconds_remaining,
                "ipogoPrepared": self._prepared,
                "notificationWatcherState": detector_status.get("state", "unknown"),
                "notificationWatcher": detector_status,
                "currentTargetId": int(target["id"]) if target else None,
                "currentTarget": target,
                "huntDwellSeconds": self._dwell_seconds,
                "huntHundoCooldownSeconds": self.hundo_cooldown_seconds,
                "huntMaxSightingAgeSeconds": self.max_sighting_age_seconds,
                "huntMinimumRemainingSeconds": self._minimum_target_remaining_seconds(),
                "huntWorkerAlive": bool(self._worker and self._worker.is_alive()),
                "huntRunStartedAt": self._run_started_at,
                "huntLastTransitionAt": self._last_transition_at,
                "huntLastError": self._last_error,
                "healthRetryablePause": self._health_retryable_pause and self._phase == "paused-world",
                "huntCheckedThisRun": self._checked_this_run,
                "huntSkippedThisRun": self._skipped_this_run,
                "huntNotificationsConfirmedThisRun": self._notifications_confirmed_this_run,
                "huntTimeoutsThisRun": self._timeouts_this_run,
                "huntWorldReadySkipsThisRun": self._world_ready_skips_this_run,
                "huntLastNotificationProof": dict(self._last_notification_proof) if self._last_notification_proof else None,
                "huntLastWorldScanProof": dict(self._last_world_scan_proof) if self._last_world_scan_proof else None,
                "notificationObservedSincePrepare": observed_since_prepare,
                "ipogoAutoRefreshEnabled": True,
                "ipogoCleanStartEnabled": self.ipogo_clean_start,
                "ipogoRefreshConfirmedInterval": self.ipogo_refresh_confirmed_interval,
                "ipogoRefreshVisitInterval": self.ipogo_refresh_visit_interval,
                "ipogoRecoveryTimeoutThreshold": self.ipogo_recovery_timeout_threshold,
                "ipogoRestartSettleSeconds": self.ipogo_restart_settle_seconds,
                "ipogoRecoveryDwellSeconds": self.ipogo_recovery_dwell_seconds,
                "ipogoConfirmedSinceRefresh": self._confirmed_since_ipogo_refresh,
                "ipogoVisitsSinceRefresh": self._visits_since_ipogo_refresh,
                "ipogoConsecutiveTimeouts": self._consecutive_timeouts,
                "ipogoRefreshesThisRun": self._ipogo_refreshes_this_run,
                "ipogoRefreshState": self._ipogo_refresh_state,
                "ipogoRefreshReason": self._ipogo_refresh_reason,
                "ipogoLastRefreshAt": self._last_ipogo_refresh_at,
                "ipogoLastRefreshError": self._last_ipogo_refresh_error,
                "ipogoAwaitingWorldProof": self._awaiting_ipogo_refresh_proof,
                "ipogoRecoveryTargetLocked": self._phase in {
                    "restarting-ipogo", "settling-ipogo", "verifying-world",
                    "paused-world", "retrying-world",
                },
            }

    def close(self, timeout: float = 3.0) -> None:
        with self._lock:
            self._prepared = False
            self._stop_requested = True
            self._wake.set()
            worker = self._worker
        if worker and worker.is_alive() and worker is not threading.current_thread():
            worker.join(timeout=timeout)
        closer = getattr(self.detector, "close", None)
        if callable(closer):
            closer()
