from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import threading
from typing import Any, Callable


LAB_BUNDLE_ID = "com.nianticlabs.pokemongo.hunterlab"
PRODUCTION_BUNDLE_ID = "com.nianticlabs.pokemongo"
APPLE_REFERENCE_TO_UNIX_SECONDS = 978_307_200.0
LIVE_STALE_AFTER = timedelta(minutes=3)
AUTO_REFRESH_SECONDS = 120
AUTO_REFRESH_RETRY_SECONDS = 20
ITEM_RE = re.compile(
    r"HUNTER_FEED_ITEM_V(?:11|12) "
    r"storage=(?P<storage>[0-9a-f]{16}) index=(?P<index>\d+) count=(?P<count>\d+) "
    r"pokemon=(?P<pokemon>-?\d+) form=(?P<form>-?\d+) weather=(?P<weather>-?\d+) "
    r"cp=(?P<cp>-?\d+) cpnil=(?P<cpnil>\d+) "
    r"iv=(?P<iv>-?\d+) ivnil=(?P<ivnil>\d+) "
    r"level=(?P<level>-?\d+) levelnil=(?P<levelnil>\d+) "
    r"expirybits=(?P<expirybits>[0-9a-f]{16}) "
    r"lonbits=(?P<lonbits>[0-9a-f]{16}) latbits=(?P<latbits>[0-9a-f]{16}) "
    r"replace=(?P<replace>[01])"
)


def _double_from_bits(value: str) -> float:
    return struct.unpack(">d", int(value, 16).to_bytes(8, "big"))[0]


def load_catalog() -> dict[int, str]:
    path = Path(__file__).with_name("pokemon_catalog.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {int(key): str(value) for key, value in payload.items()}


@dataclass(frozen=True)
class InternalFeedItem:
    storage: str
    index: int
    count: int
    pokemon_id: int
    species: str
    form: int
    weather: int
    cp: int | None
    iv: int | None
    level: int | None
    expires_at: str
    latitude: float
    longitude: float
    replace: bool = True

    @property
    def message_id(self) -> str:
        identity = (
            f"{self.pokemon_id}|{self.form}|{self.cp}|{self.level}|{self.expires_at}|"
            f"{self.latitude:.8f}|{self.longitude:.8f}"
        )
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "message_id": self.message_id}


def parse_item(line: str, catalog: dict[int, str] | None = None) -> InternalFeedItem | None:
    match = ITEM_RE.search(line)
    if match is None:
        return None
    values = match.groupdict()
    pokemon_id = int(values["pokemon"])
    names = catalog or load_catalog()
    longitude = _double_from_bits(values["lonbits"])
    latitude = _double_from_bits(values["latbits"])
    expiry = _double_from_bits(values["expirybits"]) + APPLE_REFERENCE_TO_UNIX_SECONDS
    cp = None if int(values["cpnil"]) else int(values["cp"])
    iv = None if int(values["ivnil"]) else int(values["iv"])
    level = None if int(values["levelnil"]) else int(values["level"])
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("Internal iPogo feed returned invalid coordinates")
    if iv is not None and not 0 <= iv <= 100:
        raise ValueError("Internal iPogo feed returned an invalid IV")
    return InternalFeedItem(
        storage=values["storage"],
        index=int(values["index"]),
        count=int(values["count"]),
        pokemon_id=pokemon_id,
        species=names.get(pokemon_id, f"Pokémon #{pokemon_id}"),
        form=int(values["form"]),
        weather=int(values["weather"]),
        cp=cp,
        iv=iv,
        level=level,
        expires_at=datetime.fromtimestamp(expiry, timezone.utc).isoformat(),
        latitude=latitude,
        longitude=longitude,
        replace=bool(int(values["replace"])),
    )


class BatchAssembler:
    def __init__(self, catalog: dict[int, str] | None = None) -> None:
        self.catalog = catalog or load_catalog()
        self.pending: dict[str, dict[int, InternalFeedItem]] = {}
        self.completed: list[str] = []

    def accept(self, line: str) -> tuple[bool, list[InternalFeedItem]] | None:
        item = parse_item(line, self.catalog)
        if item is None:
            return None
        records = self.pending.setdefault(item.storage, {})
        records[item.index] = item
        if len(records) != item.count or any(index not in records for index in range(item.count)):
            return None
        batch = [records[index] for index in range(item.count)]
        fingerprint = hashlib.sha256(
            "|".join(record.message_id for record in batch).encode("utf-8")
        ).hexdigest()
        self.pending.pop(item.storage, None)
        if fingerprint in self.completed:
            return None
        self.completed.append(fingerprint)
        self.completed = self.completed[-16:]
        return batch[0].replace, batch


class InternalFeedService:
    """Launch the isolated Lab and maintain its decoded snapshot/delta stream."""

    def __init__(
        self,
        on_batch: Callable[[list[InternalFeedItem]], int],
        can_refresh: Callable[[], bool] | None = None,
    ) -> None:
        self.on_batch = on_batch
        self.can_refresh = can_refresh or (lambda: True)
        self.xcrun = shutil.which("xcrun")
        self.lock = threading.RLock()
        self.process: subprocess.Popen[str] | None = None
        self.thread: threading.Thread | None = None
        self.timer: threading.Timer | None = None
        self.udid: str | None = None
        self.closed = False
        self.items: dict[str, InternalFeedItem] = {}
        self._status: dict[str, Any] = {
            "internalFeedState": "idle",
            "internalFeedMessage": "Choose Start live iPogo feed to load and keep 100-IV targets fresh.",
            "internalFeedLastSyncAt": None,
            "internalFeedLastCount": 0,
            "internalFeedLastInserted": 0,
            "internalFeedLastError": None,
            "internalFeedConsoleLines": 0,
            "internalFeedProbeLines": 0,
            "internalFeedLastProbeLine": None,
            "internalFeedLastConsoleAt": None,
            "internalFeedAutoRefresh": False,
            "internalFeedNextSyncAt": None,
        }

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def status(self) -> dict[str, Any]:
        with self.lock:
            status = dict(self._status)
        if status.get("internalFeedState") == "live" and status.get("internalFeedLastSyncAt"):
            try:
                last_update = datetime.fromisoformat(str(status["internalFeedLastSyncAt"]))
            except ValueError:
                last_update = None
            if last_update and datetime.now(timezone.utc) - last_update > LIVE_STALE_AFTER:
                status.update({
                    "internalFeedState": "stale",
                    "internalFeedMessage": "Live updates stopped. Restart the iPogo feed before the remaining targets expire.",
                })
        return status

    def start(self, udid: str, *, scheduled: bool = False) -> dict[str, Any]:
        if not self.xcrun:
            raise RuntimeError("Xcode command-line tools are unavailable")
        with self.lock:
            if self.closed:
                raise RuntimeError("The iPogo feed service is closed")
            self.udid = udid
            if not scheduled and self.timer is not None:
                self.timer.cancel()
                self.timer = None
            if scheduled and not self.can_refresh():
                self._schedule_next_locked(AUTO_REFRESH_RETRY_SECONDS)
                self._status.update({
                    "internalFeedAutoRefresh": True,
                    "internalFeedMessage": "Feed refresh is queued for the next safe pause between hunts.",
                })
                return self.status()
            if self.process is not None and self.process.poll() is None:
                current = self.status()
                if current.get("internalFeedState") not in ("stale", "offline", "error"):
                    return current
                self.process.terminate()
            command = [
                self.xcrun, "devicectl", "device", "process", "launch",
                "--device", udid, "--activate", "--terminate-existing", "--console",
                LAB_BUNDLE_ID,
            ]
            try:
                self.process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
            except OSError as error:
                raise RuntimeError(f"Could not launch iPogo Hunter Lab: {error}") from error
            self._status.update({
                "internalFeedState": "waiting",
                "internalFeedMessage": "Hunter Lab is refreshing the 100-IV feed automatically. No taps needed.",
                "internalFeedLastError": None,
                "internalFeedConsoleLines": 0,
                "internalFeedProbeLines": 0,
                "internalFeedLastProbeLine": None,
                "internalFeedLastConsoleAt": None,
                "internalFeedAutoRefresh": True,
                "internalFeedNextSyncAt": None,
            })
            self.thread = threading.Thread(
                target=self._read, args=(udid,), name="ipogo-internal-feed", daemon=True
            )
            self.thread.start()
            return self.status()

    def _schedule_next_locked(self, delay: int = AUTO_REFRESH_SECONDS) -> None:
        if self.closed or self.udid is None:
            return
        if self.timer is not None:
            self.timer.cancel()
        next_sync = datetime.now(timezone.utc) + timedelta(seconds=delay)
        self._status["internalFeedNextSyncAt"] = next_sync.isoformat()
        timer = threading.Timer(delay, self._scheduled_refresh)
        timer.daemon = True
        self.timer = timer
        timer.start()

    def _scheduled_refresh(self) -> None:
        with self.lock:
            self.timer = None
            udid = self.udid
        if udid is None:
            return
        try:
            self.start(udid, scheduled=True)
        except Exception as error:
            with self.lock:
                self._status.update({
                    "internalFeedLastError": str(error),
                    "internalFeedMessage": "Automatic feed refresh will retry shortly.",
                })
                self._schedule_next_locked(AUTO_REFRESH_RETRY_SECONDS)

    def _read(self, udid: str) -> None:
        assembler = BatchAssembler()
        process = self.process
        captured_snapshot = False
        try:
            if process is None or process.stdout is None:
                raise RuntimeError("Hunter Lab console did not open")
            for line in process.stdout:
                with self.lock:
                    self._status["internalFeedConsoleLines"] = int(
                        self._status.get("internalFeedConsoleLines") or 0
                    ) + 1
                    self._status["internalFeedLastConsoleAt"] = self._now()
                    if "HUNTER_FEED" in line:
                        self._status["internalFeedProbeLines"] = int(
                            self._status.get("internalFeedProbeLines") or 0
                        ) + 1
                        self._status["internalFeedLastProbeLine"] = line.strip()[-1000:]
                completed = assembler.accept(line)
                if completed is None:
                    continue
                replace, batch = completed
                now = datetime.now(timezone.utc)
                if replace:
                    self.items = {item.message_id: item for item in batch}
                else:
                    self.items.update({item.message_id: item for item in batch})
                self.items = {
                    message_id: item
                    for message_id, item in self.items.items()
                    if item.iv == 100 and datetime.fromisoformat(item.expires_at) > now
                }
                current = list(self.items.values())
                if replace:
                    self._return_to_production(udid)
                inserted = self.on_batch(current)
                with self.lock:
                    self._status.update({
                        "internalFeedState": "live",
                        "internalFeedMessage": f"Live iPogo feed connected · {len(current)} fresh 100-IV targets.",
                        "internalFeedLastSyncAt": self._now(),
                        "internalFeedLastCount": len(current),
                        "internalFeedLastInserted": inserted,
                        "internalFeedLastError": None,
                    })
                if replace:
                    captured_snapshot = True
                    with self.lock:
                        self._status.update({
                            "internalFeedState": "synced",
                            "internalFeedMessage": (
                                f"Synced {len(current)} fresh 100-IV targets. "
                                "The feed refreshes automatically while the hunter is idle."
                            ),
                        })
                    break
            if not captured_snapshot and self.status()["internalFeedState"] == "waiting":
                raise RuntimeError("Hunter Lab closed before a complete feed was captured")
        except Exception as error:
            with self.lock:
                self._status.update({
                    "internalFeedState": "error",
                    "internalFeedMessage": "The iPogo feed could not be synced.",
                    "internalFeedLastError": str(error),
                })
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
            if captured_snapshot:
                with self.lock:
                    self._schedule_next_locked()

    def _return_to_production(self, udid: str) -> None:
        if self.xcrun is None:
            return
        subprocess.run(
            [
                self.xcrun, "devicectl", "device", "process", "launch",
                "--device", udid, "--activate", PRODUCTION_BUNDLE_ID,
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def close(self) -> None:
        with self.lock:
            self.closed = True
            timer = self.timer
            self.timer = None
            process = self.process
        if timer is not None:
            timer.cancel()
        if process is not None and process.poll() is None:
            process.terminate()
