from __future__ import annotations

import argparse
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta, timezone
import difflib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import mimetypes
from pathlib import Path
import re
import sqlite3
import threading
from typing import Any, Iterator
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from .device_service import DeviceController, DeviceError
from .catch_lab import CatchLab, CatchLabError
from .overnight import OvernightGuard
from .hunt_service import HuntCoordinator, HuntError, USBNotificationDetector
from .internal_feed import InternalFeedItem, InternalFeedService
from .parser import compact_json, coordinates_from_text, parse_relay_payload


INTERNAL_FEED_SOURCE = "ipogo-internal-100iv"
POKEXPERIENCE_SOURCE = "pokexperience-mac-100iv"
MANUAL_SOURCE = "manual-entry"
FEED_SOURCE_MODES = ("ipogo-internal", "pokexperience", "discord")
DEFAULT_HUNT_DWELL_SECONDS = 45.0
DEFAULT_RECOVERY_FAILURE_THRESHOLD = 2
DEFAULT_HUNDO_COOLDOWN_SECONDS = 30.0
MANUAL_SIGHTING_LIFETIME_SECONDS = 10 * 60
_POKEMON_CATALOG_DATA = json.loads(Path(__file__).with_name("pokemon_catalog.json").read_text())
POKEMON_NAMES = tuple(dict.fromkeys(str(name) for name in _POKEMON_CATALOG_DATA.values()))
POKEMON_NAME_LOOKUP = {name.casefold(): name for name in POKEMON_NAMES}
POKEMON_ALIASES = {
    "magicarp": "Magikarp",
}


SCHEMA = """
CREATE TABLE IF NOT EXISTS sightings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    guild_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    channel_name TEXT NOT NULL,
    message_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    received_at TEXT NOT NULL,
    species TEXT,
    latitude REAL,
    longitude REAL,
    iv INTEGER,
    cp INTEGER,
    level REAL,
    gender TEXT,
    shiny_eligible INTEGER,
    coordinate_url TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    raw_text TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    expires_at TEXT,
    completion_reason TEXT,
    completion_message TEXT,
    completed_at TEXT,
    notification_received_at TEXT,
    queue_position INTEGER,
    source_item_key TEXT,
    coordinate_state TEXT NOT NULL DEFAULT 'ready',
    coordinate_resolved_at TEXT,
    coordinate_error TEXT,
    resolver_attempts INTEGER NOT NULL DEFAULT 0,
    city TEXT,
    country TEXT,
    metadata_scope TEXT,
    metadata_generation TEXT,
    metadata_last_seen_at TEXT,
    UNIQUE(source, channel_id, message_id, latitude, longitude)
);
CREATE INDEX IF NOT EXISTS idx_sightings_queue
ON sightings(status, received_at DESC);
CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    source TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    sighting_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_events_created
ON events(created_at DESC);
CREATE TABLE IF NOT EXISTS species_preferences (
    species TEXT PRIMARY KEY COLLATE NOCASE,
    rank INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_species_preferences_rank
ON species_preferences(rank, species COLLATE NOCASE);
CREATE TABLE IF NOT EXISTS coordinate_resolution_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sighting_id INTEGER NOT NULL UNIQUE,
    state TEXT NOT NULL DEFAULT 'queued',
    lease_token TEXT,
    created_at TEXT NOT NULL,
    leased_at TEXT,
    completed_at TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT
);
CREATE INDEX IF NOT EXISTS idx_coordinate_resolution_jobs_state
ON coordinate_resolution_jobs(state, created_at);
"""


class SightingStore:
    def __init__(self, database_path: Path):
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.database_path = database_path
        self.lock = threading.Lock()
        with self._connect() as connection:
            connection.executescript(SCHEMA)
            table_info = connection.execute("PRAGMA table_info(sightings)").fetchall()
            columns = {row["name"] for row in table_info}
            if "expires_at" not in columns:
                connection.execute("ALTER TABLE sightings ADD COLUMN expires_at TEXT")
            for column_name in (
                "completion_reason",
                "completion_message",
                "completed_at",
                "notification_received_at",
            ):
                if column_name not in columns:
                    connection.execute(f"ALTER TABLE sightings ADD COLUMN {column_name} TEXT")
            if "queue_position" not in columns:
                connection.execute("ALTER TABLE sightings ADD COLUMN queue_position INTEGER")
            additions = {
                "source_item_key": "TEXT",
                "coordinate_state": "TEXT NOT NULL DEFAULT 'ready'",
                "coordinate_resolved_at": "TEXT",
                "coordinate_error": "TEXT",
                "resolver_attempts": "INTEGER NOT NULL DEFAULT 0",
                "city": "TEXT",
                "country": "TEXT",
                "metadata_scope": "TEXT",
                "metadata_generation": "TEXT",
                "metadata_last_seen_at": "TEXT",
            }
            for column_name, definition in additions.items():
                if column_name not in columns:
                    connection.execute(
                        f"ALTER TABLE sightings ADD COLUMN {column_name} {definition}"
                    )
            # Older Hunter databases required coordinates on every row. PokeXperience
            # now imports ranking metadata first and resolves GPS only for imminent
            # checks, so those two columns must allow NULL without using dangerous
            # placeholder coordinates such as 0,0.
            latitude_info = next((row for row in table_info if row["name"] == "latitude"), None)
            longitude_info = next((row for row in table_info if row["name"] == "longitude"), None)
            if (latitude_info and latitude_info["notnull"]) or (
                longitude_info and longitude_info["notnull"]
            ):
                self._migrate_nullable_coordinates(connection)
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_sightings_manual_order "
                "ON sightings(status, queue_position)"
            )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_sightings_source_item_key "
                "ON sightings(source, source_item_key) WHERE source_item_key IS NOT NULL"
            )
            connection.execute(
                "INSERT OR IGNORE INTO app_state(key, value, updated_at) VALUES (?, ?, ?)",
                ("hunt_state", "idle", self._now()),
            )
            connection.execute(
                "INSERT OR IGNORE INTO app_state(key, value, updated_at) VALUES (?, ?, ?)",
                ("selection_mode", "all", self._now()),
            )
            connection.execute(
                "INSERT OR IGNORE INTO app_state(key, value, updated_at) VALUES (?, ?, ?)",
                ("feed_source_mode", "ipogo-internal", self._now()),
            )
            connection.execute(
                "INSERT OR IGNORE INTO app_state(key, value, updated_at) VALUES (?, ?, ?)",
                ("hunt_dwell_seconds", str(DEFAULT_HUNT_DWELL_SECONDS), self._now()),
            )
            connection.execute(
                "INSERT OR IGNORE INTO app_state(key, value, updated_at) VALUES (?, ?, ?)",
                ("recovery_failure_threshold", str(DEFAULT_RECOVERY_FAILURE_THRESHOLD), self._now()),
            )
            connection.execute(
                "INSERT OR IGNORE INTO app_state(key, value, updated_at) VALUES (?, ?, ?)",
                ("hundo_cooldown_seconds", str(DEFAULT_HUNDO_COOLDOWN_SECONDS), self._now()),
            )
            self._repair_species_preferences(connection)

    @staticmethod
    def _canonical_species_name(value: str) -> str:
        species = " ".join(value.strip().split())[:80]
        if not species:
            return ""
        folded = species.casefold()
        if folded in POKEMON_ALIASES:
            return POKEMON_ALIASES[folded]
        if folded in POKEMON_NAME_LOOKUP:
            return POKEMON_NAME_LOOKUP[folded]
        close = difflib.get_close_matches(folded, POKEMON_NAME_LOOKUP.keys(), n=1, cutoff=0.92)
        return POKEMON_NAME_LOOKUP[close[0]] if close else species

    @classmethod
    def _repair_species_preferences(cls, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            "SELECT species FROM species_preferences ORDER BY rank, species COLLATE NOCASE"
        ).fetchall()
        repaired: list[str] = []
        seen: set[str] = set()
        for row in rows:
            species = cls._canonical_species_name(row["species"])
            if species and species.casefold() not in seen:
                seen.add(species.casefold())
                repaired.append(species)
        if [row["species"] for row in rows] == repaired:
            return
        now = cls._now()
        connection.execute("DELETE FROM species_preferences")
        connection.executemany(
            "INSERT INTO species_preferences(species, rank, updated_at) VALUES (?, ?, ?)",
            [(species, rank, now) for rank, species in enumerate(repaired)],
        )

    @staticmethod
    def _migrate_nullable_coordinates(connection: sqlite3.Connection) -> None:
        """Rebuild only the sightings table while preserving IDs and hunt history."""
        columns = [row["name"] for row in connection.execute("PRAGMA table_info(sightings)")]
        connection.execute("DROP INDEX IF EXISTS idx_sightings_queue")
        connection.execute("DROP INDEX IF EXISTS idx_sightings_manual_order")
        connection.execute("DROP INDEX IF EXISTS idx_sightings_source_item_key")
        connection.execute(
            """CREATE TABLE sightings_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL, guild_id TEXT NOT NULL, channel_id TEXT NOT NULL,
                channel_name TEXT NOT NULL, message_id TEXT NOT NULL,
                observed_at TEXT NOT NULL, received_at TEXT NOT NULL, species TEXT,
                latitude REAL, longitude REAL, iv INTEGER, cp INTEGER, level REAL,
                gender TEXT, shiny_eligible INTEGER, coordinate_url TEXT,
                status TEXT NOT NULL DEFAULT 'queued', raw_text TEXT NOT NULL,
                raw_json TEXT NOT NULL, expires_at TEXT, completion_reason TEXT,
                completion_message TEXT, completed_at TEXT, notification_received_at TEXT,
                queue_position INTEGER, source_item_key TEXT,
                coordinate_state TEXT NOT NULL DEFAULT 'ready', coordinate_resolved_at TEXT,
                coordinate_error TEXT, resolver_attempts INTEGER NOT NULL DEFAULT 0,
                city TEXT, country TEXT, metadata_scope TEXT, metadata_generation TEXT,
                metadata_last_seen_at TEXT,
                UNIQUE(source, channel_id, message_id, latitude, longitude)
            )"""
        )
        destination = [
            "id", "source", "guild_id", "channel_id", "channel_name", "message_id",
            "observed_at", "received_at", "species", "latitude", "longitude", "iv",
            "cp", "level", "gender", "shiny_eligible", "coordinate_url", "status",
            "raw_text", "raw_json", "expires_at", "completion_reason",
            "completion_message", "completed_at", "notification_received_at",
            "queue_position", "source_item_key", "coordinate_state",
            "coordinate_resolved_at", "coordinate_error", "resolver_attempts", "city",
            "country", "metadata_scope", "metadata_generation", "metadata_last_seen_at",
        ]
        selected = [name if name in columns else "NULL" for name in destination]
        # Newly introduced non-null fields need explicit defaults for old rows.
        selected[destination.index("coordinate_state")] = (
            "COALESCE(coordinate_state, 'ready')" if "coordinate_state" in columns else "'ready'"
        )
        selected[destination.index("resolver_attempts")] = (
            "COALESCE(resolver_attempts, 0)" if "resolver_attempts" in columns else "0"
        )
        connection.execute(
            f"INSERT INTO sightings_v2 ({','.join(destination)}) "
            f"SELECT {','.join(selected)} FROM sightings"
        )
        connection.execute("DROP TABLE sightings")
        connection.execute("ALTER TABLE sightings_v2 RENAME TO sightings")
        connection.execute(
            "CREATE INDEX idx_sightings_queue ON sightings(status, received_at DESC)"
        )

    def hunt_settings(self) -> dict[str, float | int]:
        with self._connect() as connection:
            try:
                dwell = float(self._state(
                    connection,
                    "hunt_dwell_seconds",
                    str(DEFAULT_HUNT_DWELL_SECONDS),
                ))
            except ValueError:
                dwell = DEFAULT_HUNT_DWELL_SECONDS
            try:
                failures = int(self._state(
                    connection,
                    "recovery_failure_threshold",
                    str(DEFAULT_RECOVERY_FAILURE_THRESHOLD),
                ))
            except ValueError:
                failures = DEFAULT_RECOVERY_FAILURE_THRESHOLD
            try:
                cooldown = float(self._state(
                    connection,
                    "hundo_cooldown_seconds",
                    str(DEFAULT_HUNDO_COOLDOWN_SECONDS),
                ))
            except ValueError:
                cooldown = DEFAULT_HUNDO_COOLDOWN_SECONDS
        if not math.isfinite(dwell) or dwell < 5 or dwell > 600:
            dwell = DEFAULT_HUNT_DWELL_SECONDS
        if failures < 1 or failures > 20:
            failures = DEFAULT_RECOVERY_FAILURE_THRESHOLD
        if not math.isfinite(cooldown) or cooldown < 0 or cooldown > 600:
            cooldown = DEFAULT_HUNDO_COOLDOWN_SECONDS
        return {
            "dwellSeconds": dwell,
            "recoveryFailureThreshold": failures,
            "hundoCooldownSeconds": cooldown,
        }

    def save_hunt_settings(
        self,
        dwell_seconds: Any,
        recovery_failure_threshold: Any,
        hundo_cooldown_seconds: Any,
    ) -> dict[str, float | int]:
        dwell = float(dwell_seconds)
        failure_number = float(recovery_failure_threshold)
        cooldown = float(hundo_cooldown_seconds)
        if not math.isfinite(dwell) or dwell < 5 or dwell > 600:
            raise ValueError("Map loading wait must be between 5 and 600 seconds.")
        if not math.isfinite(failure_number) or not failure_number.is_integer():
            raise ValueError("Failed map loads must be a whole number.")
        failures = int(failure_number)
        if failures < 1 or failures > 20:
            raise ValueError("Failed map loads must be between 1 and 20.")
        if not math.isfinite(cooldown) or cooldown < 0 or cooldown > 600:
            raise ValueError("Hundo cooldown must be between 0 and 600 seconds.")
        with self.lock, self._connect() as connection:
            self._set_state(connection, "hunt_dwell_seconds", str(dwell))
            self._set_state(connection, "recovery_failure_threshold", str(failures))
            self._set_state(connection, "hundo_cooldown_seconds", str(cooldown))
            self._event(
                connection,
                "System",
                f"Hunt timing saved: {dwell:g}s map wait, {cooldown:g}s after each Hundo, "
                f"refresh after {failures} failed map load{'s' if failures != 1 else ''}",
            )
        return {
            "dwellSeconds": dwell,
            "recoveryFailureThreshold": failures,
            "hundoCooldownSeconds": cooldown,
        }

    def feed_source_mode(self) -> str:
        with self._connect() as connection:
            mode = self._state(connection, "feed_source_mode", "ipogo-internal")
        return mode if mode in FEED_SOURCE_MODES else "ipogo-internal"

    def set_feed_source(self, mode: str) -> dict[str, Any]:
        """Select the only coordinate source eligible for the next hunt."""
        if mode not in FEED_SOURCE_MODES:
            raise ValueError("Coordinate source must be iPogo internal, PokeXperience, or Discord.")
        with self.lock, self._connect() as connection:
            current = self._state(connection, "feed_source_mode", "ipogo-internal")
            self._purge_stale_connection(connection, 10 * 60)
            self._set_state(connection, "feed_source_mode", mode)
            if current != mode:
                label = {
                    "ipogo-internal": "iPogo internal feed",
                    "pokexperience": "PokeXperience background feed",
                    "discord": "Discord / Chrome relay",
                }[mode]
                self._event(connection, "System", f"Coordinate source changed to {label}")
            if mode == "pokexperience":
                self._queue_pokexperience_lookahead_connection(connection)
        return self.source_status()

    def accepts_external_feed(self) -> bool:
        return self.feed_source_mode() == "discord"

    @staticmethod
    def _source_clause(mode: str, alias: str = "") -> tuple[str, tuple[str, ...]]:
        prefix = f"{alias}." if alias else ""
        if mode == "discord":
            return (
                f"{prefix}source NOT IN (?, ?)",
                (INTERNAL_FEED_SOURCE, POKEXPERIENCE_SOURCE),
            )
        if mode == "pokexperience":
            return (
                f"{prefix}source IN (?, ?)",
                (POKEXPERIENCE_SOURCE, MANUAL_SOURCE),
            )
        return f"{prefix}source IN (?, ?)", (INTERNAL_FEED_SOURCE, MANUAL_SOURCE)

    @staticmethod
    def _target_order_clause(alias: str = "s", current_first: bool = False) -> str:
        """Return the single authoritative ordering for active hunt targets.

        Ranked species retain their configured species/level/CP order. PokeXperience
        fallback targets use CP first, while Discord fallback targets retain their
        historical level-first behavior and iPogo remains CP-first.
        """
        prefix = f"{alias}." if alias else ""
        internal_source = INTERNAL_FEED_SOURCE.replace("'", "''")
        pokexperience_source = POKEXPERIENCE_SOURCE.replace("'", "''")
        pokexperience_fallback = (
            f"({prefix}source='{pokexperience_source}' "
            f"AND {prefix}status='queued' AND p.species IS NULL)"
        )
        cp_first = (
            f"({prefix}source='{internal_source}' OR {pokexperience_fallback})"
        )
        if current_first:
            priority_bucket = f"""CASE
                WHEN {prefix}status='current' THEN 0
                WHEN {prefix}queue_position IS NOT NULL THEN 1
                WHEN {prefix}status='prioritized' THEN 2
                WHEN p.species IS NOT NULL THEN 3
                ELSE 4
            END"""
        else:
            priority_bucket = f"""CASE
                WHEN {prefix}queue_position IS NOT NULL THEN 0
                WHEN {prefix}status='prioritized' THEN 1
                WHEN p.species IS NOT NULL THEN 2
                ELSE 3
            END"""
        return f"""{priority_bucket},
            {prefix}queue_position ASC,
            CASE WHEN {prefix}status='queued' AND p.species IS NOT NULL THEN p.rank END ASC,
            CASE WHEN {cp_first} AND {prefix}cp IS NULL THEN 1 ELSE 0 END,
            CASE WHEN {cp_first} THEN {prefix}cp END DESC,
            CASE WHEN {pokexperience_fallback} AND {prefix}level IS NULL THEN 1 ELSE 0 END,
            CASE WHEN {pokexperience_fallback} THEN {prefix}level END DESC,
            CASE WHEN NOT {cp_first} AND {prefix}level IS NULL THEN 1 ELSE 0 END,
            CASE WHEN NOT {cp_first} THEN {prefix}level END DESC,
            CASE WHEN NOT {cp_first} AND {prefix}cp IS NULL THEN 1 ELSE 0 END,
            CASE WHEN NOT {cp_first} THEN {prefix}cp END DESC,
            {prefix}received_at DESC"""

    def source_status(self) -> dict[str, Any]:
        with self.lock, self._connect() as connection:
            self._purge_stale_connection(connection, 10 * 60)
            mode = self._state(connection, "feed_source_mode", "ipogo-internal")
            if mode not in FEED_SOURCE_MODES:
                mode = "ipogo-internal"
            source_clause, source_parameters = self._source_clause(mode)
            rows = connection.execute(
                """SELECT
                SUM(CASE WHEN source=? AND status IN ('queued','prioritized','current') THEN 1 ELSE 0 END) AS internal_count,
                SUM(CASE WHEN source=? AND status IN ('queued','prioritized','current') THEN 1 ELSE 0 END) AS pokexperience_count,
                SUM(CASE WHEN source NOT IN (?, ?, ?) AND status IN ('queued','prioritized','current') THEN 1 ELSE 0 END) AS discord_count,
                SUM(CASE WHEN source=? AND status IN ('queued','prioritized','current') THEN 1 ELSE 0 END) AS manual_count
                FROM sightings""",
                (
                    INTERNAL_FEED_SOURCE,
                    POKEXPERIENCE_SOURCE,
                    INTERNAL_FEED_SOURCE,
                    POKEXPERIENCE_SOURCE,
                    MANUAL_SOURCE,
                    MANUAL_SOURCE,
                ),
            ).fetchone()
            active_count = connection.execute(
                f"""SELECT COUNT(*) FROM sightings
                WHERE status IN ('queued','prioritized','current') AND {source_clause}""",
                source_parameters,
            ).fetchone()[0]
        return {
            "feedSourceMode": mode,
            "activeQueueCount": int(active_count or 0),
            "feedSourceCounts": {
                "ipogo-internal": int(rows["internal_count"] or 0),
                "pokexperience": int(rows["pokexperience_count"] or 0),
                "discord": int(rows["discord_count"] or 0),
                "manual": int(rows["manual_count"] or 0),
            },
        }

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _set_state(connection: sqlite3.Connection, key: str, value: str) -> None:
        connection.execute(
            """INSERT INTO app_state(key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
            (key, value, datetime.now(timezone.utc).isoformat()),
        )

    @staticmethod
    def _state(connection: sqlite3.Connection, key: str, default: str = "") -> str:
        row = connection.execute("SELECT value FROM app_state WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    @staticmethod
    def _event(
        connection: sqlite3.Connection,
        source: str,
        message: str,
        level: str = "info",
        sighting_id: int | None = None,
    ) -> None:
        connection.execute(
            "INSERT INTO events(created_at, source, level, message, sighting_id) VALUES (?, ?, ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), source, level, message, sighting_id),
        )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _expires_at(raw_text: str, received_at: datetime) -> str | None:
        match = re.search(
            r"\bDSP\s+in\s+(?:(\d+)h\s*)?(?:(\d+)m\s*)?(?:(\d+)s)?",
            raw_text,
            re.IGNORECASE,
        )
        if not match or not any(match.groups()):
            return None
        hours, minutes, seconds = (int(value or 0) for value in match.groups())
        return (received_at + timedelta(hours=hours, minutes=minutes, seconds=seconds)).isoformat()

    def add(self, payload: dict[str, Any]) -> tuple[dict[str, Any] | None, bool]:
        sighting = parse_relay_payload(payload)
        if sighting is None:
            return None, False
        data = sighting.as_dict()
        received = datetime.now(timezone.utc)
        received_at = received.isoformat()
        expires_at = self._expires_at(data["raw_text"], received)
        with self.lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO sightings (
                    source, guild_id, channel_id, channel_name, message_id,
                    observed_at, received_at, species, latitude, longitude,
                    iv, cp, level, gender, shiny_eligible, coordinate_url,
                    raw_text, raw_json, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["source"], data["guild_id"], data["channel_id"],
                    data["channel_name"], data["message_id"], data["observed_at"],
                    received_at, data["species"], data["latitude"], data["longitude"],
                    data["iv"], data["cp"], data["level"], data["gender"],
                    None if data["shiny_eligible"] is None else int(data["shiny_eligible"]),
                    data["coordinate_url"], data["raw_text"], compact_json(payload), expires_at,
                ),
            )
            inserted = cursor.rowcount == 1
            if inserted:
                data["id"] = cursor.lastrowid
                data["received_at"] = received_at
                data["expires_at"] = expires_at
                data["status"] = "queued"
                label = data["species"] or "Unknown Pokémon"
                self._event(
                    connection,
                    "Discord",
                    f"Queued {label} from #{data['channel_name']}",
                    sighting_id=cursor.lastrowid,
                )
            else:
                row = connection.execute(
                    """SELECT * FROM sightings
                    WHERE source=? AND channel_id=? AND message_id=?
                    AND latitude=? AND longitude=?""",
                    (data["source"], data["channel_id"], data["message_id"],
                     data["latitude"], data["longitude"]),
                ).fetchone()
                data = self._public_row(row) if row else data
        return data, inserted

    def add_manual_sighting(self, species_value: Any, coordinate_value: Any) -> dict[str, Any]:
        """Insert an operator-supplied target as the next upcoming check."""
        if not isinstance(species_value, str):
            raise ValueError("Enter the Pokémon name.")
        species = " ".join(species_value.strip().split())[:80]
        if not species:
            raise ValueError("Enter the Pokémon name.")
        if not isinstance(coordinate_value, str):
            raise ValueError("Paste coordinates as latitude, longitude.")
        coordinate = coordinates_from_text(coordinate_value.strip())
        if coordinate is None:
            raise ValueError("Coordinates must look like 40.760800, -111.891000.")

        received = datetime.now(timezone.utc)
        received_at = received.isoformat()
        expires_at = (
            received + timedelta(seconds=MANUAL_SIGHTING_LIFETIME_SECONDS)
        ).isoformat()
        latitude, longitude = coordinate
        raw_text = f"{species} · IV 100 · {latitude:.8f},{longitude:.8f} · manual entry"
        payload = {
            "species": species,
            "latitude": latitude,
            "longitude": longitude,
            "enteredAt": received_at,
        }
        with self.lock, self._connect() as connection:
            # Existing custom positions retain their order while making room
            # for this explicit "check next" target.
            connection.execute(
                """UPDATE sightings SET queue_position=queue_position + 1
                WHERE status IN ('queued', 'prioritized')
                AND queue_position IS NOT NULL"""
            )
            cursor = connection.execute(
                """
                INSERT INTO sightings (
                    source, guild_id, channel_id, channel_name, message_id,
                    observed_at, received_at, species, latitude, longitude,
                    iv, cp, level, gender, shiny_eligible, coordinate_url,
                    status, raw_text, raw_json, expires_at, queue_position
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    MANUAL_SOURCE, "", MANUAL_SOURCE, "Manual coordinates",
                    f"manual-{uuid4().hex}", received_at, received_at, species,
                    latitude, longitude, 100, None, None, None, None, None,
                    "queued", raw_text, compact_json(payload), expires_at, 0,
                ),
            )
            row = connection.execute(
                "SELECT * FROM sightings WHERE id=?", (cursor.lastrowid,)
            ).fetchone()
            self._event(
                connection,
                "Manual",
                f"Added {species} as the next check",
                "success",
                cursor.lastrowid,
            )
        if row is None:
            raise ValueError("The manual coordinate could not be saved.")
        return self._public_row(row)

    def save_queue_order(self, ordered_values: list[Any]) -> dict[str, Any]:
        """Persist an explicit order for the currently selected source's queue."""
        if len(ordered_values) > 500:
            raise ValueError("At most 500 upcoming targets can be reordered at once.")
        ordered_ids: list[int] = []
        for value in ordered_values:
            if isinstance(value, bool):
                raise ValueError("Queue order contains an invalid target.")
            try:
                sighting_id = int(value)
            except (TypeError, ValueError) as error:
                raise ValueError("Queue order contains an invalid target.") from error
            if sighting_id <= 0 or sighting_id in ordered_ids:
                raise ValueError("Queue order contains a duplicate or invalid target.")
            ordered_ids.append(sighting_id)

        with self.lock, self._connect() as connection:
            mode = self._state(connection, "feed_source_mode", "ipogo-internal")
            source_clause, source_parameters = self._source_clause(mode)
            eligible_rows = connection.execute(
                f"""SELECT id FROM sightings
                WHERE status IN ('queued', 'prioritized') AND {source_clause}""",
                source_parameters,
            ).fetchall()
            eligible_ids = {int(row["id"]) for row in eligible_rows}
            if any(sighting_id not in eligible_ids for sighting_id in ordered_ids):
                raise ValueError("The queue changed. Refresh it and try the reorder again.")
            connection.execute(
                f"""UPDATE sightings SET queue_position=NULL
                WHERE status IN ('queued', 'prioritized') AND {source_clause}""",
                source_parameters,
            )
            connection.executemany(
                "UPDATE sightings SET queue_position=? WHERE id=?",
                [(position, sighting_id) for position, sighting_id in enumerate(ordered_ids)],
            )
            if ordered_ids:
                self._event(
                    connection,
                    "System",
                    f"Saved a custom order for {len(ordered_ids)} upcoming targets",
                )
            else:
                self._event(connection, "System", "Restored automatic queue order")
        return {"orderedIds": ordered_ids, "customOrder": bool(ordered_ids)}

    def add_internal_batch(self, items: list[InternalFeedItem]) -> int:
        """Atomically add one complete snapshot from iPogo's own 100-IV feed."""
        received = datetime.now(timezone.utc)
        received_at = received.isoformat()
        inserted = 0
        with self.lock, self._connect() as connection:
            self._purge_stale_connection(connection, 10 * 60)
            current_ids = {item.message_id for item in items}
            if current_ids:
                placeholders = ",".join("?" for _ in current_ids)
                connection.execute(
                    f"""DELETE FROM sightings
                    WHERE source=?
                    AND status IN ('queued', 'prioritized')
                    AND message_id NOT IN ({placeholders})""",
                    (INTERNAL_FEED_SOURCE, *tuple(sorted(current_ids))),
                )
            else:
                connection.execute(
                    """DELETE FROM sightings
                    WHERE source=? AND status IN ('queued', 'prioritized')""",
                    (INTERNAL_FEED_SOURCE,),
                )
            for item in items:
                try:
                    expiry = datetime.fromisoformat(item.expires_at)
                except ValueError:
                    continue
                if expiry <= received or item.iv != 100:
                    continue
                raw_text = (
                    f"{item.species} · IV 100 · CP {item.cp if item.cp is not None else '?'} · "
                    f"L{item.level if item.level is not None else '?'} · "
                    f"{item.latitude:.8f},{item.longitude:.8f}"
                )
                payload = item.as_dict()
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO sightings (
                        source, guild_id, channel_id, channel_name, message_id,
                        observed_at, received_at, species, latitude, longitude,
                        iv, cp, level, gender, shiny_eligible, coordinate_url,
                        raw_text, raw_json, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        INTERNAL_FEED_SOURCE, "", INTERNAL_FEED_SOURCE, "iPogo 100 IV",
                        item.message_id, received_at, received_at, item.species,
                        item.latitude, item.longitude, item.iv, item.cp, item.level,
                        None, None, None, raw_text, compact_json(payload), item.expires_at,
                    ),
                )
                inserted += int(cursor.rowcount == 1)
            self._set_state(connection, "internal_feed_heartbeat", received_at)
            self._set_state(connection, "internal_feed_visible", str(len(items)))
            self._event(
                connection,
                "iPogo Feed",
                f"Synced {len(items)} current 100-IV targets; {inserted} new",
                "success",
            )
        return inserted

    def update_pokexperience_bridge(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Record native Mac bridge health or replace its complete live snapshot."""
        event_type = str(payload.get("type") or "status")
        bridge_state = " ".join(str(payload.get("state") or "unknown").split())[:80]
        message = " ".join(str(payload.get("message") or "").split())[:500]
        app_running = bool(payload.get("appRunning"))
        trusted = bool(payload.get("trusted"))
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        if event_type == "metadata-snapshot":
            return self._update_pokexperience_metadata_snapshot(payload, now)
        if event_type == "resolve-result":
            return self._complete_pokexperience_resolution(payload, now)
        if event_type == "resolve-failed":
            return self._fail_pokexperience_resolution(payload, now)
        if event_type != "snapshot":
            with self.lock, self._connect() as connection:
                self._set_state(connection, "pokexperience_bridge_heartbeat", now_iso)
                self._set_state(connection, "pokexperience_bridge_state", bridge_state)
                self._set_state(connection, "pokexperience_bridge_message", message)
                self._set_state(connection, "pokexperience_app_running", json.dumps(app_running))
                self._set_state(connection, "pokexperience_bridge_trusted", json.dumps(trusted))
            return self.pokexperience_status()

        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            raise ValueError("PokeXperience snapshot items must be a list.")
        if len(raw_items) > 5_000:
            raise ValueError("PokeXperience snapshot is too large.")

        normalized: list[dict[str, Any]] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            species = " ".join(str(raw.get("species") or "").strip().split())[:80]
            if not species:
                continue
            try:
                latitude = float(raw.get("latitude"))
                longitude = float(raw.get("longitude"))
                expires_at = datetime.fromisoformat(str(raw.get("expiresAt") or ""))
            except (TypeError, ValueError):
                continue
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            expires_at = expires_at.astimezone(timezone.utc)
            if (
                not math.isfinite(latitude)
                or not math.isfinite(longitude)
                or not -90 <= latitude <= 90
                or not -180 <= longitude <= 180
                or expires_at <= now
            ):
                continue
            try:
                cp = int(raw["cp"]) if raw.get("cp") is not None else None
            except (TypeError, ValueError):
                cp = None
            try:
                level = float(raw["level"]) if raw.get("level") is not None else None
            except (TypeError, ValueError):
                level = None
            if cp is not None and cp <= 0:
                cp = None
            if level is not None and (not math.isfinite(level) or level <= 0):
                level = None
            city = " ".join(str(raw.get("city") or "").strip().split())[:120]
            gender = " ".join(str(raw.get("gender") or "").strip().split())[:20] or None
            expiry_bucket = int(expires_at.timestamp() // 60)
            message_id = (
                f"pokex:{species.casefold()}:{latitude:.5f}:{longitude:.5f}:{expiry_bucket}"
            )
            normalized.append({
                "message_id": message_id,
                "species": species,
                "latitude": latitude,
                "longitude": longitude,
                "cp": cp,
                "level": level,
                "city": city,
                "gender": gender,
                "expires_at": expires_at.isoformat(),
            })

        inserted = 0
        with self.lock, self._connect() as connection:
            self._purge_stale_connection(connection, 10 * 60)
            current_ids = {item["message_id"] for item in normalized}
            if current_ids:
                placeholders = ",".join("?" for _ in current_ids)
                connection.execute(
                    f"""DELETE FROM sightings
                    WHERE source=? AND status IN ('queued', 'prioritized')
                    AND message_id NOT IN ({placeholders})""",
                    (POKEXPERIENCE_SOURCE, *tuple(sorted(current_ids))),
                )
            else:
                connection.execute(
                    """DELETE FROM sightings
                    WHERE source=? AND status IN ('queued', 'prioritized')""",
                    (POKEXPERIENCE_SOURCE,),
                )

            for item in normalized:
                raw_text = (
                    f"{item['species']} · IV 100 · CP {item['cp'] if item['cp'] is not None else '?'} · "
                    f"L{item['level'] if item['level'] is not None else '?'} · "
                    f"{item['latitude']:.8f},{item['longitude']:.8f} · "
                    f"{item['city'] or 'PokeXperience'}"
                )
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO sightings (
                        source, guild_id, channel_id, channel_name, message_id,
                        observed_at, received_at, species, latitude, longitude,
                        iv, cp, level, gender, shiny_eligible, coordinate_url,
                        raw_text, raw_json, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        POKEXPERIENCE_SOURCE, "", POKEXPERIENCE_SOURCE,
                        "PokeXperience Mac", item["message_id"], now_iso, now_iso,
                        item["species"], item["latitude"], item["longitude"],
                        100, item["cp"], item["level"], item["gender"], None, None,
                        raw_text, compact_json(item), item["expires_at"],
                    ),
                )
                if cursor.rowcount == 1:
                    inserted += 1
                else:
                    connection.execute(
                        """UPDATE sightings SET received_at=?, cp=?, level=?, gender=?,
                        raw_text=?, raw_json=?, expires_at=?
                        WHERE source=? AND channel_id=? AND message_id=?
                        AND latitude=? AND longitude=?
                        AND status IN ('queued', 'prioritized')""",
                        (
                            now_iso, item["cp"], item["level"], item["gender"],
                            raw_text, compact_json(item), item["expires_at"],
                            POKEXPERIENCE_SOURCE, POKEXPERIENCE_SOURCE,
                            item["message_id"], item["latitude"], item["longitude"],
                        ),
                    )

            self._set_state(connection, "pokexperience_bridge_heartbeat", now_iso)
            self._set_state(connection, "pokexperience_last_sync", now_iso)
            self._set_state(connection, "pokexperience_bridge_state", "synced")
            self._set_state(
                connection,
                "pokexperience_bridge_message",
                message or f"Captured {len(normalized)} live targets.",
            )
            self._set_state(connection, "pokexperience_app_running", json.dumps(app_running))
            self._set_state(connection, "pokexperience_bridge_trusted", json.dumps(trusted))
            self._set_state(connection, "pokexperience_visible", str(len(normalized)))
            self._set_state(connection, "pokexperience_catalog_complete", json.dumps(True))
            self._set_state(connection, "pokexperience_catalog_rows", str(len(normalized)))
            self._set_state(connection, "pokexperience_catalog_pages", "1")
            self._set_state(connection, "pokexperience_catalog_expected", str(len(normalized)))
            self._event(
                connection,
                "PokeXperience",
                f"Synced {len(normalized)} current 100-IV targets; {inserted} new",
                "success" if normalized else "info",
            )
        return {**self.pokexperience_status(), "inserted": inserted}

    @staticmethod
    def _normalize_pokexperience_metadata(
        raw: dict[str, Any],
        now: datetime,
        scope: str,
        source_index: int,
    ) -> dict[str, Any] | None:
        species = " ".join(str(raw.get("species") or "").strip().split())[:80]
        if not species:
            return None
        try:
            expires_at = datetime.fromisoformat(str(raw.get("expiresAt") or ""))
        except ValueError:
            return None
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        expires_at = expires_at.astimezone(timezone.utc)
        if expires_at <= now:
            return None
        try:
            cp = int(raw["cp"]) if raw.get("cp") is not None else None
        except (TypeError, ValueError):
            cp = None
        try:
            level = float(raw["level"]) if raw.get("level") is not None else None
        except (TypeError, ValueError):
            level = None
        if cp is not None and cp <= 0:
            cp = None
        if level is not None and (not math.isfinite(level) or level <= 0):
            level = None
        city = " ".join(str(raw.get("city") or "").strip().split())[:120]
        country = " ".join(str(raw.get("country") or "").strip().split())[:80]
        gender = " ".join(str(raw.get("gender") or "").strip().split())[:20] or None
        # Expiry is reconstructed from the visible countdown. Rounding to a minute
        # keeps the key stable across refreshes while still separating later spawns
        # with otherwise identical metadata.
        expiry_bucket = int(round(expires_at.timestamp() / 60))
        occurrence = max(0, int(raw.get("sourceIndex") or source_index))
        source_key = "|".join(
            (
                scope.casefold(), species.casefold(), str(cp or ""), str(level or ""),
                (gender or "").casefold(), city.casefold(), country.casefold(),
                str(expiry_bucket), str(occurrence),
            )
        )
        return {
            "source_item_key": source_key[:500],
            "species": species,
            "cp": cp,
            "level": level,
            "gender": gender,
            "city": city,
            "country": country,
            "expires_at": expires_at.isoformat(),
        }

    def _update_pokexperience_metadata_snapshot(
        self,
        payload: dict[str, Any],
        now: datetime,
    ) -> dict[str, Any]:
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            raise ValueError("PokeXperience metadata items must be a list.")
        if len(raw_items) > 5_000:
            raise ValueError("PokeXperience metadata snapshot is too large.")
        scope = " ".join(str(payload.get("scope") or "fallback").strip().split())[:160]
        generation = " ".join(str(payload.get("generation") or uuid4()).split())[:120]
        complete_for_scope = bool(payload.get("completeForScope", True))
        complete_catalog = bool(payload.get("completeCatalog", False))
        try:
            catalog_rows = max(0, int(payload.get("catalogRowsInspected") or len(raw_items)))
            catalog_pages = max(0, int(payload.get("catalogPagesScanned") or 0))
            catalog_expected = max(0, int(payload.get("catalogExpectedRows") or 0))
        except (TypeError, ValueError):
            catalog_rows, catalog_pages, catalog_expected = len(raw_items), 0, 0
        message = " ".join(str(payload.get("message") or "").split())[:500]
        app_running = bool(payload.get("appRunning", True))
        trusted = bool(payload.get("trusted", True))
        now_iso = now.isoformat()
        normalized = [
            item
            for index, raw in enumerate(raw_items)
            if isinstance(raw, dict)
            for item in [self._normalize_pokexperience_metadata(raw, now, scope, index)]
            if item is not None
        ]
        inserted = 0
        with self.lock, self._connect() as connection:
            self._purge_stale_connection(connection, 10 * 60)
            seen_keys: set[str] = set()
            for item in normalized:
                key = item["source_item_key"]
                seen_keys.add(key)
                existing = connection.execute(
                    "SELECT id, status, coordinate_state FROM sightings WHERE source=? AND source_item_key=?",
                    (POKEXPERIENCE_SOURCE, key),
                ).fetchone()
                raw_text = (
                    f"{item['species']} · IV 100 · CP {item['cp'] if item['cp'] is not None else '?'} · "
                    f"L{item['level'] if item['level'] is not None else '?'} · "
                    f"{item['city'] or item['country'] or 'PokeXperience'}"
                )
                if existing is None:
                    connection.execute(
                        """INSERT INTO sightings (
                            source, guild_id, channel_id, channel_name, message_id,
                            observed_at, received_at, species, latitude, longitude,
                            iv, cp, level, gender, shiny_eligible, coordinate_url,
                            raw_text, raw_json, expires_at, source_item_key,
                            coordinate_state, city, country, metadata_scope,
                            metadata_generation, metadata_last_seen_at
                        ) VALUES (?, '', ?, 'PokeXperience Mac', ?, ?, ?, ?, NULL, NULL,
                            100, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)""",
                        (
                            POKEXPERIENCE_SOURCE, POKEXPERIENCE_SOURCE,
                            f"pokex-meta:{key}", now_iso, now_iso, item["species"],
                            item["cp"], item["level"], item["gender"], raw_text,
                            compact_json(item), item["expires_at"], key, item["city"],
                            item["country"], scope, generation, now_iso,
                        ),
                    )
                    inserted += 1
                else:
                    connection.execute(
                        """UPDATE sightings SET received_at=?, species=?, cp=?, level=?,
                        gender=?, raw_text=?, raw_json=?, expires_at=?, city=?, country=?,
                        metadata_scope=?, metadata_generation=?, metadata_last_seen_at=?,
                        coordinate_error=CASE WHEN coordinate_state='failed' THEN NULL ELSE coordinate_error END,
                        coordinate_state=CASE WHEN coordinate_state='failed' THEN 'pending' ELSE coordinate_state END
                        WHERE id=?""",
                        (
                            now_iso, item["species"], item["cp"], item["level"], item["gender"],
                            raw_text, compact_json(item), item["expires_at"], item["city"],
                            item["country"], scope, generation, now_iso, existing["id"],
                        ),
                    )

            if complete_catalog:
                connection.execute(
                    """DELETE FROM sightings WHERE source=?
                    AND status IN ('queued','prioritized')
                    AND (metadata_generation IS NULL OR metadata_generation!=?)""",
                    (POKEXPERIENCE_SOURCE, generation),
                )
            elif complete_for_scope:
                if seen_keys:
                    placeholders = ",".join("?" for _ in seen_keys)
                    connection.execute(
                        f"""DELETE FROM sightings WHERE source=? AND metadata_scope=?
                        AND status IN ('queued','prioritized')
                        AND source_item_key NOT IN ({placeholders})""",
                        (POKEXPERIENCE_SOURCE, scope, *sorted(seen_keys)),
                    )
                else:
                    connection.execute(
                        """DELETE FROM sightings WHERE source=? AND metadata_scope=?
                        AND status IN ('queued','prioritized')""",
                        (POKEXPERIENCE_SOURCE, scope),
                    )
            connection.execute(
                "DELETE FROM coordinate_resolution_jobs WHERE sighting_id NOT IN (SELECT id FROM sightings)"
            )
            self._queue_pokexperience_lookahead_connection(connection)
            visible = connection.execute(
                """SELECT COUNT(*) FROM sightings WHERE source=?
                AND status IN ('queued','prioritized','current')""",
                (POKEXPERIENCE_SOURCE,),
            ).fetchone()[0]
            self._set_state(connection, "pokexperience_bridge_heartbeat", now_iso)
            self._set_state(connection, "pokexperience_last_sync", now_iso)
            self._set_state(
                connection, "pokexperience_bridge_state",
                "synced" if complete_catalog else "catalog-incomplete",
            )
            self._set_state(
                connection, "pokexperience_bridge_message",
                message or f"Indexed {len(normalized)} live targets without using the clipboard.",
            )
            self._set_state(connection, "pokexperience_app_running", json.dumps(app_running))
            self._set_state(connection, "pokexperience_bridge_trusted", json.dumps(trusted))
            self._set_state(connection, "pokexperience_visible", str(visible))
            self._set_state(connection, "pokexperience_catalog_complete", json.dumps(complete_catalog))
            self._set_state(connection, "pokexperience_catalog_rows", str(catalog_rows))
            self._set_state(connection, "pokexperience_catalog_pages", str(catalog_pages))
            self._set_state(connection, "pokexperience_catalog_expected", str(catalog_expected))
            self._event(
                connection, "PokeXperience",
                f"Indexed {len(normalized)} live targets from {scope}; {inserted} new",
                "success" if normalized else "info",
            )
        return {**self.pokexperience_status(), "inserted": inserted}

    def _queue_pokexperience_lookahead_connection(
        self,
        connection: sqlite3.Connection,
        limit: int = 2,
    ) -> None:
        if self._state(connection, "feed_source_mode", "ipogo-internal") != "pokexperience":
            return
        rows = connection.execute(
            f"""SELECT s.id, s.coordinate_state FROM sightings s
            LEFT JOIN species_preferences p ON p.species=s.species COLLATE NOCASE
            WHERE s.source=? AND s.status IN ('current','prioritized','queued')
            AND (s.expires_at IS NULL OR s.expires_at>?)
            ORDER BY {self._target_order_clause('s', current_first=True)} LIMIT ?""",
            (POKEXPERIENCE_SOURCE, self._now(), max(1, limit)),
        ).fetchall()
        now = self._now()
        for row in rows:
            if row["coordinate_state"] not in ("pending", "failed"):
                continue
            connection.execute(
                """INSERT INTO coordinate_resolution_jobs(sighting_id,state,created_at)
                VALUES (?,'queued',?) ON CONFLICT(sighting_id) DO UPDATE SET
                state=CASE WHEN coordinate_resolution_jobs.state='failed' THEN 'queued'
                           ELSE coordinate_resolution_jobs.state END,
                last_error=CASE WHEN coordinate_resolution_jobs.state='failed' THEN NULL
                                ELSE coordinate_resolution_jobs.last_error END""",
                (row["id"], now),
            )

    def queue_pokexperience_resolution(self, sighting_id: int) -> dict[str, Any]:
        with self.lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sightings WHERE id=? AND source=?",
                (sighting_id, POKEXPERIENCE_SOURCE),
            ).fetchone()
            if row is None:
                raise ValueError("The PokeXperience target no longer exists.")
            if row["latitude"] is not None and row["longitude"] is not None:
                return self._public_row(row)
            now = self._now()
            connection.execute(
                """INSERT INTO coordinate_resolution_jobs(sighting_id,state,created_at)
                VALUES (?,'queued',?) ON CONFLICT(sighting_id) DO UPDATE SET
                state='queued', lease_token=NULL, leased_at=NULL, last_error=NULL""",
                (sighting_id, now),
            )
            connection.execute(
                "UPDATE sightings SET coordinate_state='pending', coordinate_error=NULL WHERE id=?",
                (sighting_id,),
            )
            return self._public_row(connection.execute(
                "SELECT * FROM sightings WHERE id=?", (sighting_id,)
            ).fetchone())

    def lease_pokexperience_resolution(self) -> dict[str, Any] | None:
        with self.lock, self._connect() as connection:
            self._purge_stale_connection(connection, 10 * 60)
            self._queue_pokexperience_lookahead_connection(connection)
            stale = (datetime.now(timezone.utc) - timedelta(seconds=12)).isoformat()
            row = connection.execute(
                """SELECT j.id AS job_id, j.attempts AS job_attempts, s.*
                FROM coordinate_resolution_jobs j JOIN sightings s ON s.id=j.sighting_id
                WHERE s.source=? AND s.status IN ('current','prioritized','queued')
                AND s.coordinate_state IN ('pending','resolving','failed')
                AND (j.state='queued' OR (j.state='leased' AND j.leased_at<?))
                ORDER BY CASE WHEN s.status='current' THEN 0 ELSE 1 END,
                         j.created_at ASC, j.id ASC LIMIT 1""",
                (POKEXPERIENCE_SOURCE, stale),
            ).fetchone()
            if row is None:
                return None
            lease = str(uuid4())
            now = self._now()
            connection.execute(
                """UPDATE coordinate_resolution_jobs SET state='leased', lease_token=?,
                leased_at=?, attempts=attempts+1 WHERE id=?""",
                (lease, now, row["job_id"]),
            )
            connection.execute(
                """UPDATE sightings SET coordinate_state='resolving',
                resolver_attempts=resolver_attempts+1, coordinate_error=NULL WHERE id=?""",
                (row["id"],),
            )
            return {
                "jobId": row["job_id"], "leaseToken": lease, "sightingId": row["id"],
                "sourceItemKey": row["source_item_key"], "species": row["species"],
                "cp": row["cp"], "level": row["level"], "gender": row["gender"],
                "city": row["city"], "country": row["country"],
                "expiresAt": row["expires_at"],
            }

    def _complete_pokexperience_resolution(
        self,
        payload: dict[str, Any],
        now: datetime,
    ) -> dict[str, Any]:
        try:
            job_id = int(payload.get("jobId"))
            latitude = float(payload.get("latitude"))
            longitude = float(payload.get("longitude"))
        except (TypeError, ValueError):
            raise ValueError("A valid resolution job and coordinates are required.")
        lease = str(payload.get("leaseToken") or "")
        if not lease or not math.isfinite(latitude) or not math.isfinite(longitude):
            raise ValueError("The coordinate resolution result is invalid.")
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError("The resolved coordinates are outside the valid range.")
        with self.lock, self._connect() as connection:
            job = connection.execute(
                "SELECT * FROM coordinate_resolution_jobs WHERE id=? AND state='leased' AND lease_token=?",
                (job_id, lease),
            ).fetchone()
            if job is None:
                raise ValueError("The coordinate-resolution lease is no longer active.")
            now_iso = now.isoformat()
            connection.execute(
                """UPDATE sightings SET latitude=?, longitude=?, coordinate_state='ready',
                coordinate_resolved_at=?, coordinate_error=NULL,
                coordinate_url=? WHERE id=?""",
                (
                    latitude, longitude, now_iso,
                    f"pokemongo://?spprotele={latitude:.8f},{longitude:.8f}", job["sighting_id"],
                ),
            )
            connection.execute(
                """UPDATE coordinate_resolution_jobs SET state='completed', completed_at=?,
                last_error=NULL WHERE id=?""",
                (now_iso, job_id),
            )
            sighting = connection.execute(
                "SELECT species FROM sightings WHERE id=?", (job["sighting_id"],)
            ).fetchone()
            self._event(
                connection, "PokeXperience",
                f"Coordinates ready for {sighting['species'] if sighting else 'target'}",
                "success", job["sighting_id"],
            )
            self._queue_pokexperience_lookahead_connection(connection)
        return self.pokexperience_status()

    def _fail_pokexperience_resolution(
        self,
        payload: dict[str, Any],
        now: datetime,
    ) -> dict[str, Any]:
        try:
            job_id = int(payload.get("jobId"))
        except (TypeError, ValueError):
            raise ValueError("A coordinate-resolution job is required.")
        lease = str(payload.get("leaseToken") or "")
        message = " ".join(str(payload.get("message") or "Could not match the target row.").split())[:300]
        with self.lock, self._connect() as connection:
            job = connection.execute(
                "SELECT * FROM coordinate_resolution_jobs WHERE id=? AND state='leased' AND lease_token=?",
                (job_id, lease),
            ).fetchone()
            if job is None:
                raise ValueError("The coordinate-resolution lease is no longer active.")
            connection.execute(
                "UPDATE coordinate_resolution_jobs SET state='failed', completed_at=?, last_error=? WHERE id=?",
                (now.isoformat(), message, job_id),
            )
            connection.execute(
                "UPDATE sightings SET coordinate_state='failed', coordinate_error=? WHERE id=?",
                (message, job["sighting_id"]),
            )
            self._event(connection, "PokeXperience", message, "error", job["sighting_id"])
        return self.pokexperience_status()

    def pokexperience_status(self) -> dict[str, Any]:
        with self._connect() as connection:
            heartbeat = self._state(connection, "pokexperience_bridge_heartbeat", "")
            last_sync = self._state(connection, "pokexperience_last_sync", "")
            state = self._state(connection, "pokexperience_bridge_state", "not-started")
            message = self._state(connection, "pokexperience_bridge_message", "")
            visible = int(self._state(connection, "pokexperience_visible", "0") or 0)
            app_running = json.loads(
                self._state(connection, "pokexperience_app_running", "false") or "false"
            )
            trusted = json.loads(
                self._state(connection, "pokexperience_bridge_trusted", "false") or "false"
            )
            catalog_complete = json.loads(
                self._state(connection, "pokexperience_catalog_complete", "false") or "false"
            )
            catalog_rows = int(self._state(connection, "pokexperience_catalog_rows", "0") or 0)
            catalog_pages = int(self._state(connection, "pokexperience_catalog_pages", "0") or 0)
            catalog_expected = int(self._state(connection, "pokexperience_catalog_expected", "0") or 0)
            readiness = connection.execute(
                """SELECT
                SUM(CASE WHEN coordinate_state='ready' THEN 1 ELSE 0 END) AS ready,
                SUM(CASE WHEN coordinate_state='resolving' THEN 1 ELSE 0 END) AS resolving,
                SUM(CASE WHEN coordinate_state IN ('pending','failed') THEN 1 ELSE 0 END) AS pending
                FROM sightings WHERE source=?
                AND status IN ('queued','prioritized','current')""",
                (POKEXPERIENCE_SOURCE,),
            ).fetchone()
        connected = False
        if heartbeat:
            try:
                connected = (
                    datetime.now(timezone.utc) - datetime.fromisoformat(heartbeat)
                ).total_seconds() < 90
            except ValueError:
                pass
        return {
            "pokexperienceBridgeConnected": connected,
            "pokexperienceBridgeState": state,
            "pokexperienceBridgeMessage": message or None,
            "pokexperienceAppRunning": bool(app_running),
            "pokexperienceAccessibilityTrusted": bool(trusted),
            "pokexperienceLastSyncAt": last_sync or None,
            "pokexperienceVisibleCount": visible,
            "pokexperienceCatalogComplete": bool(catalog_complete),
            "pokexperienceCatalogRows": catalog_rows,
            "pokexperienceCatalogPages": catalog_pages,
            "pokexperienceCatalogExpectedRows": catalog_expected,
            "pokexperienceCoordinatesReady": int(readiness["ready"] or 0),
            "pokexperienceCoordinatesResolving": int(readiness["resolving"] or 0),
            "pokexperienceCoordinatesPending": int(readiness["pending"] or 0),
        }

    def heartbeat(
        self,
        channel_id: str = "",
        channel_name: str = "",
        visible_message_count: int | None = None,
        new_candidate_count: int = 0,
        control_samples: list[dict[str, Any]] | None = None,
        api_diagnostics: dict[str, Any] | None = None,
    ) -> None:
        with self.lock, self._connect() as connection:
            self._set_state(connection, "relay_heartbeat", self._now())
            if channel_id:
                self._set_state(connection, f"channel:{channel_id}", channel_name or channel_id)
            if visible_message_count is not None:
                self._set_state(connection, "relay_visible_messages", str(max(0, visible_message_count)))
            if new_candidate_count:
                previous = int(self._state(connection, "relay_candidates_seen", "0") or 0)
                self._set_state(
                    connection,
                    "relay_candidates_seen",
                    str(previous + max(0, new_candidate_count)),
                )
            if control_samples is not None:
                self._set_state(
                    connection,
                    "relay_control_samples",
                    compact_json(control_samples[:6])[:12_000],
                )
            if api_diagnostics is not None:
                for key, value in api_diagnostics.items():
                    self._set_state(connection, f"relay_api_{key}", compact_json(value))

    @staticmethod
    def _public_row(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result.pop("raw_json", None)
        if result.get("shiny_eligible") is not None:
            result["shiny_eligible"] = bool(result["shiny_eligible"])
        return result

    def list(self, limit: int = 100, status: str | None = None) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        with self.lock, self._connect() as connection:
            self._purge_stale_connection(connection, 10 * 60)
            mode = self._state(connection, "feed_source_mode", "ipogo-internal")
            source_clause, source_parameters = self._source_clause(mode)
            sql = f"SELECT * FROM sightings WHERE {source_clause}"
            parameters: list[Any] = list(source_parameters)
            if status:
                sql += " AND status=?"
                parameters.append(status)
            sql += " ORDER BY received_at DESC LIMIT ?"
            parameters.append(limit)
            rows = connection.execute(sql, parameters).fetchall()
        return [self._public_row(row) for row in rows]

    def list_queue(self, limit: int = 250) -> list[dict[str, Any]]:
        """List the visible queue in the exact order used by the hunt coordinator."""
        limit = max(1, min(limit, 500))
        with self.lock, self._connect() as connection:
            self._purge_stale_connection(connection, 10 * 60)
            mode = self._state(connection, "feed_source_mode", "ipogo-internal")
            if mode not in FEED_SOURCE_MODES:
                mode = "ipogo-internal"
            source_clause, source_parameters = self._source_clause(mode, "s")
            rows = connection.execute(
                f"""SELECT s.* FROM sightings s
                LEFT JOIN species_preferences p ON p.species=s.species COLLATE NOCASE
                WHERE s.status IN ('current','prioritized','queued') AND {source_clause}
                ORDER BY {self._target_order_clause('s', current_first=True)} LIMIT ?""",
                (*source_parameters, limit),
            ).fetchall()
        return [
            {**self._public_row(row), "queue_rank": rank}
            for rank, row in enumerate(rows)
        ]

    def channels(self) -> list[dict[str, Any]]:
        with self.lock, self._connect() as connection:
            self._purge_stale_connection(connection, 10 * 60)
            mode = self._state(connection, "feed_source_mode", "ipogo-internal")
            source_clause, source_parameters = self._source_clause(mode)
            rows = connection.execute(
                """SELECT channel_id, MAX(channel_name) AS channel_name,
                COUNT(*) AS sightings, MAX(received_at) AS last_seen_at
                FROM sightings WHERE """ + source_clause + """
                GROUP BY channel_id ORDER BY last_seen_at DESC""",
                source_parameters,
            ).fetchall()
        return [dict(row) for row in rows]

    def events(self, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM events ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> dict[str, Any]:
        with self._connect() as connection:
            totals = connection.execute(
                """SELECT COUNT(*) AS received,
                SUM(CASE WHEN status IN ('checked', 'shundo') THEN 1 ELSE 0 END) AS checked,
                SUM(CASE WHEN status='shundo' THEN 1 ELSE 0 END) AS shundos,
                SUM(CASE WHEN status='skipped' THEN 1 ELSE 0 END) AS skipped
                FROM sightings"""
            ).fetchone()
            species = connection.execute(
                """SELECT species,
                COUNT(*) AS received,
                SUM(CASE WHEN status IN ('checked', 'shundo') THEN 1 ELSE 0 END) AS checked,
                SUM(CASE WHEN status='shundo' THEN 1 ELSE 0 END) AS shundos,
                MAX(received_at) AS last_seen_at
                FROM sightings WHERE species IS NOT NULL AND species != ''
                GROUP BY species
                ORDER BY checked DESC, received DESC, species COLLATE NOCASE"""
            ).fetchall()
        return {
            "received": int(totals["received"] or 0),
            "checked": int(totals["checked"] or 0),
            "shundos": int(totals["shundos"] or 0),
            "skipped": int(totals["skipped"] or 0),
            "species": [
                {
                    **dict(row),
                    "received": int(row["received"] or 0),
                    "checked": int(row["checked"] or 0),
                    "shundos": int(row["shundos"] or 0),
                }
                for row in species
            ],
        }

    def preferences(self) -> dict[str, Any]:
        with self._connect() as connection:
            mode = self._state(connection, "selection_mode", "all")
            ranked = connection.execute(
                "SELECT species, rank FROM species_preferences ORDER BY rank, species COLLATE NOCASE"
            ).fetchall()
            available = connection.execute(
                """SELECT species, COUNT(*) AS sightings,
                SUM(CASE WHEN status IN ('queued', 'prioritized', 'current') THEN 1 ELSE 0 END) AS actionable
                FROM sightings WHERE species IS NOT NULL AND species != ''
                GROUP BY species ORDER BY species COLLATE NOCASE"""
            ).fetchall()
        live_by_species = {
            row["species"].casefold(): {
                "species": row["species"],
                "sightings": int(row["sightings"] or 0),
                "actionable": int(row["actionable"] or 0),
            }
            for row in available
        }
        catalog = []
        for species in POKEMON_NAMES:
            live = live_by_species.pop(species.casefold(), None)
            catalog.append(live or {"species": species, "sightings": 0, "actionable": 0})
        catalog.extend(live_by_species.values())
        catalog.sort(key=lambda item: item["species"].casefold())
        return {
            "mode": mode if mode in ("all", "selected") else "all",
            "rankedSpecies": [row["species"] for row in ranked],
            "availableSpecies": catalog,
        }

    def save_preferences(self, mode: str, ranked_species: list[Any]) -> dict[str, Any]:
        if mode not in ("all", "selected"):
            raise ValueError("Selection mode must be all or selected.")
        normalized: list[str] = []
        seen: set[str] = set()
        for value in ranked_species[:200]:
            if not isinstance(value, str):
                continue
            species = self._canonical_species_name(value)
            key = species.casefold()
            if not species or key in seen:
                continue
            seen.add(key)
            normalized.append(species)
        if mode == "selected" and not normalized:
            raise ValueError("Add at least one Pokémon before enabling selected-only hunting.")
        now = self._now()
        with self.lock, self._connect() as connection:
            connection.execute("DELETE FROM species_preferences")
            connection.executemany(
                "INSERT INTO species_preferences(species, rank, updated_at) VALUES (?, ?, ?)",
                [(species, rank, now) for rank, species in enumerate(normalized)],
            )
            self._set_state(connection, "selection_mode", mode)
            behavior = "selected Pokémon only" if mode == "selected" else "all Pokémon"
            self._event(connection, "System", f"Hunt rules updated: {behavior}")
        return self.preferences()

    def get_sighting(self, sighting_id: int) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM sightings WHERE id=?", (sighting_id,)).fetchone()
        if row is None:
            raise ValueError("The selected sighting no longer exists.")
        return self._public_row(row)

    def record_phone_location(self, sighting: dict[str, Any]) -> None:
        with self.lock, self._connect() as connection:
            payload = {
                "sightingId": sighting["id"],
                "species": sighting.get("species"),
                "latitude": sighting["latitude"],
                "longitude": sighting["longitude"],
                "setAt": self._now(),
            }
            self._set_state(connection, "phone_last_location", compact_json(payload))
            self._event(
                connection,
                "Phone",
                f"Sent {sighting.get('species') or 'target'} location to iPhone",
                "success",
                int(sighting["id"]),
            )

    def set_hunt_state(self, state: str) -> None:
        with self.lock, self._connect() as connection:
            self._set_state(connection, "hunt_state", state)

    def record_hunt_event(
        self,
        message: str,
        level: str = "info",
        sighting_id: int | None = None,
    ) -> None:
        with self.lock, self._connect() as connection:
            self._event(connection, "Hunt", message, level, sighting_id)

    @classmethod
    def _purge_stale_connection(
        cls,
        connection: sqlite3.Connection,
        max_age_seconds: float,
        now: datetime | None = None,
    ) -> list[sqlite3.Row]:
        reference = now or datetime.now(timezone.utc)
        cutoff = datetime.fromtimestamp(
            reference.timestamp() - float(max_age_seconds), timezone.utc
        ).isoformat()
        reference_iso = reference.isoformat()
        rows = connection.execute(
            """SELECT id, species FROM sightings
            WHERE status='expired'
            OR (status IN ('queued', 'prioritized')
            AND ((expires_at IS NOT NULL AND expires_at <= ?)
                 OR (expires_at IS NULL AND received_at < ?)))""",
            (reference_iso, cutoff),
        ).fetchall()
        if rows:
            connection.execute(
                """DELETE FROM sightings
                WHERE status='expired'
                OR (status IN ('queued', 'prioritized')
                AND ((expires_at IS NOT NULL AND expires_at <= ?)
                     OR (expires_at IS NULL AND received_at < ?)))""",
                (reference_iso, cutoff),
            )
        return rows

    def expire_stale_sightings(self, max_age_seconds: float) -> int:
        with self.lock, self._connect() as connection:
            rows = self._purge_stale_connection(connection, max_age_seconds)
            if rows:
                self._event(
                    connection,
                    "Hunt",
                    f"Removed {len(rows)} expired coordinate{'s' if len(rows) != 1 else ''}",
                )
            return len(rows)

    @staticmethod
    def _discard_short_lived_connection(
        connection: sqlite3.Connection,
        minimum_remaining_seconds: float,
        now: datetime | None = None,
    ) -> list[sqlite3.Row]:
        minimum = max(0.0, float(minimum_remaining_seconds))
        if minimum <= 0:
            return []
        cutoff = ((now or datetime.now(timezone.utc)) + timedelta(seconds=minimum)).isoformat()
        rows = connection.execute(
            """SELECT id, species FROM sightings
            WHERE status IN ('queued', 'prioritized')
            AND expires_at IS NOT NULL AND expires_at <= ?""",
            (cutoff,),
        ).fetchall()
        if rows:
            connection.execute(
                """DELETE FROM sightings
                WHERE status IN ('queued', 'prioritized')
                AND expires_at IS NOT NULL AND expires_at <= ?""",
                (cutoff,),
            )
        return rows

    def discard_orphaned_current(self) -> int:
        """Delete targets left `current` by an interrupted coordinator process."""
        with self.lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT id, species FROM sightings WHERE status='current'"
            ).fetchall()
            if not rows:
                return 0
            connection.execute("DELETE FROM sightings WHERE status='current'")
            for row in rows:
                self._event(
                    connection,
                    "Hunt",
                    f"Discarded interrupted target {row['species'] or 'target'}",
                    "info",
                    row["id"],
                )
            return len(rows)

    def claim_next_target(
        self,
        max_age_seconds: float,
        minimum_remaining_seconds: float = 0,
    ) -> dict[str, Any] | None:
        """Atomically expire stale sightings and claim the next eligible target."""
        with self.lock, self._connect() as connection:
            expired = self._purge_stale_connection(connection, max_age_seconds)
            if expired:
                self._event(
                    connection,
                    "Hunt",
                    f"Removed {len(expired)} expired coordinate{'s' if len(expired) != 1 else ''}",
                )
            short_lived = self._discard_short_lived_connection(
                connection,
                minimum_remaining_seconds,
            )
            if short_lived:
                threshold = int(math.ceil(float(minimum_remaining_seconds)))
                self._event(
                    connection,
                    "Hunt",
                    f"Skipped {len(short_lived)} coordinate{'s' if len(short_lived) != 1 else ''} with less than {threshold} seconds remaining",
                )
            current = connection.execute(
                "SELECT * FROM sightings WHERE status='current' ORDER BY received_at DESC LIMIT 1"
            ).fetchone()
            if current is not None:
                return self._public_row(current)
            next_row = self._next_target(connection)
            if next_row is None:
                return None
            connection.execute(
                "UPDATE sightings SET status='current' WHERE id=? AND status IN ('queued', 'prioritized')",
                (next_row["id"],),
            )
            claimed = connection.execute(
                "SELECT * FROM sightings WHERE id=? AND status='current'", (next_row["id"],)
            ).fetchone()
            if claimed is None:
                return None
            self._event(
                connection,
                "Hunt",
                f"Selected {claimed['species'] or 'target'}",
                sighting_id=claimed["id"],
            )
            return self._public_row(claimed)

    def complete_hunt_target(
        self,
        sighting_id: int,
        outcome: str,
        message: str | None = None,
        *,
        completion_reason: str | None = None,
        notification_received_at: str | None = None,
    ) -> bool:
        if outcome not in ("checked", "shundo", "skipped", "failed", "expired"):
            raise ValueError("Invalid hunt outcome.")
        with self.lock, self._connect() as connection:
            row = connection.execute(
                "SELECT id, species, status FROM sightings WHERE id=?", (sighting_id,)
            ).fetchone()
            if row is None or row["status"] != "current":
                return False
            completed_at = self._now()
            resolved_reason = completion_reason or {
                "checked": "completed",
                "shundo": "shundo-notification",
                "skipped": "manual-skip",
                "failed": "error",
                "expired": "expired",
            }.get(outcome, outcome)
            connection.execute(
                """UPDATE sightings
                SET status=?, completion_reason=?, completion_message=?, completed_at=?,
                    notification_received_at=?
                WHERE id=? AND status='current'""",
                (
                    outcome,
                    resolved_reason,
                    message,
                    completed_at,
                    notification_received_at,
                    sighting_id,
                ),
            )
            label = row["species"] or "target"
            if outcome == "shundo":
                event_message = f"Shundo detected: {label}"
                level = "success"
            elif outcome == "checked":
                event_message = f"Checked {label}"
                level = "success"
            elif outcome == "skipped":
                event_message = f"Skipped {label}"
                level = "info"
            elif outcome == "expired":
                event_message = f"Expired {label}"
                level = "info"
            else:
                event_message = f"Failed {label}"
                level = "error"
            if message:
                event_message = f"{event_message}: {message}"
            self._event(connection, "Hunt", event_message, level, sighting_id)
            if outcome == "expired":
                connection.execute("DELETE FROM sightings WHERE id=?", (sighting_id,))
            return True

    @classmethod
    def _next_target(cls, connection: sqlite3.Connection) -> sqlite3.Row | None:
        mode = cls._state(connection, "selection_mode", "all")
        source_mode = cls._state(connection, "feed_source_mode", "ipogo-internal")
        if source_mode not in FEED_SOURCE_MODES:
            source_mode = "ipogo-internal"
        source_clause, source_parameters = cls._source_clause(source_mode, "s")
        return connection.execute(
            f"""SELECT s.id FROM sightings s
            LEFT JOIN species_preferences p ON p.species = s.species COLLATE NOCASE
            WHERE s.status IN ('prioritized', 'queued')
            AND {source_clause}
            AND (s.source=? OR s.status='prioritized' OR ?='all' OR p.species IS NOT NULL)
            ORDER BY {cls._target_order_clause('s')} LIMIT 1""",
            (
                *source_parameters,
                MANUAL_SOURCE,
                mode,
            ),
        ).fetchone()

    def action(self, action: str, sighting_id: int | None = None) -> dict[str, Any]:
        with self.lock, self._connect() as connection:
            if action == "start":
                self._set_state(connection, "hunt_state", "running")
                current = connection.execute(
                    "SELECT id FROM sightings WHERE status='current' LIMIT 1"
                ).fetchone()
                if current is None:
                    next_row = self._next_target(connection)
                    if next_row:
                        connection.execute(
                            "UPDATE sightings SET status='current' WHERE id=?", (next_row["id"],)
                        )
                        self._event(connection, "System", "Hunt started", sighting_id=next_row["id"])
                    else:
                        self._set_state(connection, "hunt_state", "idle")
                        raise ValueError("The selected coordinate source has no fresh targets.")
            elif action == "pause":
                self._set_state(connection, "hunt_state", "paused")
                self._event(connection, "System", "Hunt paused")
            elif action == "skip":
                row = connection.execute(
                    "SELECT id, species FROM sightings WHERE status='current' LIMIT 1"
                ).fetchone()
                if row is None:
                    raise ValueError("There is no current target to skip.")
                connection.execute("UPDATE sightings SET status='skipped' WHERE id=?", (row["id"],))
                self._event(connection, "System", f"Skipped {row['species'] or 'target'}", sighting_id=row["id"])
                self._promote_next(connection)
            elif action == "prioritize":
                if sighting_id is None:
                    raise ValueError("Choose a queued sighting to prioritize.")
                row = connection.execute(
                    "SELECT id, species, status FROM sightings WHERE id=?", (sighting_id,)
                ).fetchone()
                if row is None or row["status"] not in ("queued", "prioritized"):
                    raise ValueError("Only queued sightings can be prioritized.")
                connection.execute(
                    "UPDATE sightings SET status='queued' WHERE status='prioritized'"
                )
                connection.execute(
                    """UPDATE sightings SET queue_position=queue_position + 1
                    WHERE status IN ('queued', 'prioritized')
                    AND queue_position IS NOT NULL AND id!=?""",
                    (sighting_id,),
                )
                connection.execute(
                    "UPDATE sightings SET status='prioritized', queue_position=0 WHERE id=?",
                    (sighting_id,),
                )
                self._event(connection, "System", f"Prioritized {row['species'] or 'target'}", sighting_id=sighting_id)
            elif action in ("checked", "shundo"):
                row = connection.execute(
                    "SELECT id, species FROM sightings WHERE status='current' LIMIT 1"
                ).fetchone()
                if row is None:
                    raise ValueError("There is no current target to complete.")
                connection.execute("UPDATE sightings SET status=? WHERE id=?", (action, row["id"]))
                label = row["species"] or "target"
                message = f"Shundo detected: {label}" if action == "shundo" else f"Checked {label}"
                self._event(connection, "Phone", message, "success", row["id"])
                self._promote_next(connection)
            else:
                raise ValueError("Unknown action.")
        return self.status()

    def _promote_next(self, connection: sqlite3.Connection) -> None:
        hunt_state = self._state(connection, "hunt_state", "idle")
        if hunt_state not in ("running", "paused"):
            return
        next_row = self._next_target(connection)
        if next_row:
            connection.execute(
                "UPDATE sightings SET status='current' WHERE id=?", (next_row["id"],)
            )
        else:
            self._set_state(connection, "hunt_state", "idle")

    def status(self) -> dict[str, Any]:
        with self.lock, self._connect() as connection:
            self._purge_stale_connection(connection, 10 * 60)
            source_mode = self._state(connection, "feed_source_mode", "ipogo-internal")
            if source_mode not in FEED_SOURCE_MODES:
                source_mode = "ipogo-internal"
            source_clause, source_parameters = self._source_clause(source_mode)
            total = connection.execute("SELECT COUNT(*) FROM sightings").fetchone()[0]
            queued = connection.execute(
                f"SELECT COUNT(*) FROM sightings WHERE status='queued' AND {source_clause}",
                source_parameters,
            ).fetchone()[0]
            source_counts = connection.execute(
                """SELECT
                SUM(CASE WHEN source=? AND status IN ('queued','prioritized','current') THEN 1 ELSE 0 END) AS internal_count,
                SUM(CASE WHEN source=? AND status IN ('queued','prioritized','current') THEN 1 ELSE 0 END) AS pokexperience_count,
                SUM(CASE WHEN source NOT IN (?, ?, ?) AND status IN ('queued','prioritized','current') THEN 1 ELSE 0 END) AS discord_count,
                SUM(CASE WHEN source=? AND status IN ('queued','prioritized','current') THEN 1 ELSE 0 END) AS manual_count
                FROM sightings""",
                (
                    INTERNAL_FEED_SOURCE,
                    POKEXPERIENCE_SOURCE,
                    INTERNAL_FEED_SOURCE,
                    POKEXPERIENCE_SOURCE,
                    MANUAL_SOURCE,
                    MANUAL_SOURCE,
                ),
            ).fetchone()
            active_queue_count = connection.execute(
                f"""SELECT COUNT(*) FROM sightings
                WHERE status IN ('queued','prioritized','current') AND {source_clause}""",
                source_parameters,
            ).fetchone()[0]
            custom_queue_order = connection.execute(
                f"""SELECT COUNT(*) FROM sightings
                WHERE status IN ('queued','prioritized')
                AND queue_position IS NOT NULL AND {source_clause}""",
                source_parameters,
            ).fetchone()[0]
            channels = connection.execute(
                f"SELECT COUNT(DISTINCT channel_id) FROM sightings WHERE {source_clause}",
                source_parameters,
            ).fetchone()[0]
            latest = connection.execute(
                f"SELECT MAX(received_at) FROM sightings WHERE {source_clause}",
                source_parameters,
            ).fetchone()[0]
            current = connection.execute(
                "SELECT id FROM sightings WHERE status='current' LIMIT 1"
            ).fetchone()
            hunt_state = self._state(connection, "hunt_state", "idle")
            heartbeat = self._state(connection, "relay_heartbeat", "")
            visible_messages = int(self._state(connection, "relay_visible_messages", "0") or 0)
            candidates_seen = int(self._state(connection, "relay_candidates_seen", "0") or 0)
            samples_json = self._state(connection, "relay_control_samples", "[]") or "[]"
            try:
                control_samples = json.loads(samples_json)
            except json.JSONDecodeError:
                control_samples = []
            api_authorized = json.loads(self._state(connection, "relay_api_authorized", "false") or "false")
            api_last_poll_at = json.loads(self._state(connection, "relay_api_last_poll_at", "null") or "null")
            api_message_count = json.loads(self._state(connection, "relay_api_message_count", "0") or "0")
            api_coordinate_link_count = json.loads(self._state(connection, "relay_api_coordinate_link_count", "0") or "0")
            api_link_hosts = json.loads(self._state(connection, "relay_api_link_hosts", "[]") or "[]")
            api_accepted_count = json.loads(self._state(connection, "relay_api_accepted_count", "0") or "0")
            api_last_error = json.loads(self._state(connection, "relay_api_last_error", "null") or "null")
            interaction_ready = json.loads(self._state(connection, "relay_api_interaction_ready", "false") or "false")
            interaction_sent_count = json.loads(self._state(connection, "relay_api_interaction_sent_count", "0") or "0")
            interaction_last_error = json.loads(self._state(connection, "relay_api_interaction_last_error", "null") or "null")
            internal_feed_heartbeat = self._state(connection, "internal_feed_heartbeat", "")
            internal_feed_visible = int(self._state(connection, "internal_feed_visible", "0") or 0)
        pokexperience_status = self.pokexperience_status()
        relay_connected = False
        if heartbeat:
            try:
                age = datetime.now(timezone.utc) - datetime.fromisoformat(heartbeat)
                relay_connected = age.total_seconds() < 45
            except ValueError:
                pass
        return {
            "ok": True,
            "service": "shundo-hunter-feed",
            "totalSightings": total,
            "queuedSightings": queued,
            "activeQueueCount": int(active_queue_count or 0),
            "customQueueOrder": bool(custom_queue_order),
            "feedSourceMode": source_mode,
            "feedSourceCounts": {
                "ipogo-internal": int(source_counts["internal_count"] or 0),
                "pokexperience": int(source_counts["pokexperience_count"] or 0),
                "discord": int(source_counts["discord_count"] or 0),
                "manual": int(source_counts["manual_count"] or 0),
            },
            "internalFeedStoredLastSyncAt": internal_feed_heartbeat or None,
            "internalFeedStoredCount": internal_feed_visible,
            "channelsSeen": channels,
            "lastSightingAt": latest,
            "huntState": hunt_state,
            "currentTargetId": current["id"] if current else None,
            "relayConnected": relay_connected,
            "relayHeartbeatAt": heartbeat or None,
            "visibleMessages": visible_messages,
            "candidatesSeen": candidates_seen,
            "controlSamples": control_samples,
            "apiAuthorized": api_authorized,
            "apiLastPollAt": api_last_poll_at,
            "apiMessageCount": api_message_count,
            "apiCoordinateLinkCount": api_coordinate_link_count,
            "apiLinkHosts": api_link_hosts,
            "apiAcceptedCount": api_accepted_count,
            "apiLastError": api_last_error,
            "interactionReady": interaction_ready,
            "interactionSentCount": interaction_sent_count,
            "interactionLastError": interaction_last_error,
            **pokexperience_status,
            "now": datetime.now(timezone.utc).isoformat(),
        }


class FeedHandler(BaseHTTPRequestHandler):
    server_version = "ShundoHunterFeed/0.1"

    @property
    def store(self) -> SightingStore:
        return self.server.store  # type: ignore[attr-defined]

    @property
    def static_dir(self) -> Path:
        return self.server.static_dir  # type: ignore[attr-defined]

    @property
    def device(self) -> DeviceController:
        return self.server.device  # type: ignore[attr-defined]

    @property
    def hunt(self) -> HuntCoordinator:
        return self.server.hunt  # type: ignore[attr-defined]

    @property
    def internal_feed(self) -> InternalFeedService:
        return self.server.internal_feed  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin", "")
        return (
            not origin
            or origin.startswith("chrome-extension://")
            or origin.startswith("http://127.0.0.1:")
            or origin.startswith("http://localhost:")
        )

    def _send_json(self, value: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        origin = self.headers.get("Origin")
        if origin and self._origin_allowed():
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, relative_path: str) -> bool:
        relative_path = relative_path.lstrip("/") or "index.html"
        candidate = (self.static_dir / relative_path).resolve()
        try:
            candidate.relative_to(self.static_dir.resolve())
        except ValueError:
            return False
        if not candidate.is_file():
            return False
        body = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8" if content_type.startswith("text/") or content_type == "application/javascript" else content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)
        return True

    def do_OPTIONS(self) -> None:
        if not self._origin_allowed():
            self._send_json({"error": "origin not allowed"}, HTTPStatus.FORBIDDEN)
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        origin = self.headers.get("Origin")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/status":
            status = self.store.status()
            status.update(self.device.status())
            status.update(self.hunt.status())
            status.update(self.internal_feed.status())
            status.update(self.server.catch_lab.status())
            status.update(self.server.overnight.status())
            status["instanceToken"] = self.server.instance_token  # type: ignore[attr-defined]
            status["relayPath"] = str(self.server.relay_path)  # type: ignore[attr-defined]
            self._send_json(status)
            return
        if parsed.path == "/api/sightings":
            query = parse_qs(parsed.query)
            try:
                limit = int(query.get("limit", ["100"])[0])
            except ValueError:
                limit = 100
            status = query.get("status", [None])[0]
            self._send_json({"sightings": self.store.list(limit, status)})
            return
        if parsed.path == "/api/queue":
            query = parse_qs(parsed.query)
            try:
                limit = int(query.get("limit", ["250"])[0])
            except ValueError:
                limit = 250
            self._send_json({"sightings": self.store.list_queue(limit)})
            return
        if parsed.path == "/api/channels":
            self._send_json({"channels": self.store.channels()})
            return
        if parsed.path == "/api/events":
            self._send_json({"events": self.store.events()})
            return
        if parsed.path == "/api/stats":
            self._send_json(self.store.stats())
            return
        if parsed.path == "/api/preferences":
            self._send_json(self.store.preferences())
            return
        if parsed.path == "/api/hunt-settings":
            self._send_json(self.store.hunt_settings())
            return
        if parsed.path == "/api/pokexperience/job":
            job = self.store.lease_pokexperience_resolution()
            self._send_json({"job": job})
            return
        if not self._send_static(parsed.path):
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        gate = self.server.overnight.operation_lock if self.path in {
            "/api/action", "/api/device", "/api/catch-lab", "/api/overnight"
        } else nullcontext()
        with gate:
            self._do_POST()

    def _do_POST(self) -> None:
        if self.path not in (
            "/api/ingest", "/api/heartbeat", "/api/action", "/api/preferences", "/api/device",
            "/api/mac-notification", "/api/hunt-settings", "/api/manual-sighting",
            "/api/queue-order", "/api/pokexperience", "/api/catch-lab", "/api/overnight"
        ):
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        if not self._origin_allowed():
            self._send_json({"error": "origin not allowed"}, HTTPStatus.FORBIDDEN)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > 2_000_000:
            self._send_json({"error": "invalid body size"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            payload = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json({"error": "invalid JSON"}, HTTPStatus.BAD_REQUEST)
            return
        if not isinstance(payload, dict):
            self._send_json({"error": "object required"}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/overnight":
            origin = self.headers.get("Origin", "")
            if (origin and origin not in ("http://127.0.0.1:8765", "http://localhost:8765")) or not self.server.instance_token or payload.get("instanceToken") != self.server.instance_token:
                self._send_json({"error": "Local app authorization required"}, HTTPStatus.FORBIDDEN)
                return
            try:
                action = payload.get("action")
                if action == "setup":
                    self.server.catch_lab.close()
                    result = self.server.overnight.begin(payload.get("autoLockConfirmed") is True)
                elif action == "protect":
                    result = self.server.overnight.protect_open_encounter()
                elif action == "release" and payload.get("confirmed") is True:
                    result = self.server.overnight.release()
                elif action == "source-mac":
                    if self.server.overnight.active:
                        raise RuntimeError("End display-off setup first.")
                    self.server.overnight.require_unprotected()
                    result = self.hunt.configure_alert_source("mac")
                elif action in {"vision-save", "vision-forget"}:
                    guard = self.server.overnight
                    if guard.vision.busy or guard.screen_recovery.busy:
                        raise RuntimeError("Cancel AI inspection and wait for it to finish before changing settings.")
                    if self.hunt.status()["huntWorkerAlive"]:
                        raise RuntimeError("Stop hunting before changing AI settings.")
                    result = guard.vision.client.configure(payload) if action == "vision-save" else guard.vision.client.forget_key()
                elif action == "vision-analyze":
                    if self.server.overnight.screen_recovery.busy:
                        raise RuntimeError("Finish or cancel screen recovery first.")
                    result = self.server.overnight.vision.start(species=payload.get("species"))
                elif action == "screen-recover":
                    result = self.server.overnight.start_screen_recovery()
                elif action == "vision-test-open":
                    if self.server.overnight.screen_recovery.busy:
                        raise RuntimeError("Finish or cancel screen recovery first.")
                    result = self.server.overnight.vision.start(species=payload.get("species"), supervised=True, confirmed=payload.get("confirmed") is True)
                elif action == "vision-cancel":
                    if self.server.overnight.screen_recovery.busy and self.hunt.status()["huntState"] == "running":
                        self.hunt.pause()
                    self.server.overnight.vision.cancel()
                    self.server.overnight.screen_recovery.cancel()
                    result = self.server.overnight.status()
                else:
                    raise ValueError("Unknown or unconfirmed overnight action")
            except (RuntimeError, KeyError, ValueError, TypeError, OSError) as error:
                self._send_json({"error": str(error)}, HTTPStatus.CONFLICT)
                return
            self._send_json({"ok": True, "result": result})
            self.store.record_hunt_event(f"Display-off / encounter protection: {action}")
            return
        # Server-side interlocks, not just disabled buttons. A restarted app
        # retains its hold journal and cannot silently resume/change location.
        if self.path in {"/api/action", "/api/device", "/api/catch-lab"}:
            safe_read = self.path == "/api/device" and payload.get("action") == "refresh"
            try:
                if not safe_read:
                    self.server.overnight.require_unprotected()
                    if self.server.overnight.screen_recovery.busy and payload.get("action") not in {"pause", "unprepare"}:
                        raise RuntimeError("Screen recovery is active. Cancel it before changing location or starting another action.")
                if self.path == "/api/catch-lab" and self.server.overnight.active:
                    raise RuntimeError("Catch Lab is disabled during display-off setup and encounter protection.")
            except RuntimeError as error:
                self._send_json({"error": str(error)}, HTTPStatus.CONFLICT)
                return
        if self.path == "/api/catch-lab":
            # This controls physical touches. Require the local app's per-run
            # token as well as an exact local origin (not the relay whitelist).
            origin = self.headers.get("Origin", "")
            if (origin and origin not in ("http://127.0.0.1:8765", "http://localhost:8765")) or not self.server.instance_token or payload.get("instanceToken") != self.server.instance_token:
                self._send_json({"error": "Local app authorization required"}, HTTPStatus.FORBIDDEN)
                return
            try:
                action = payload.get("action")
                if action == "start":
                    result = self.server.catch_lab.start_helper(self.device.executable, self.device._connected_udid(),
                                                               native_wifi=self.device.status().get("phoneNativeWifi", False))
                elif action == "stop":
                    self.server.catch_lab.close()
                    result = self.server.catch_lab.status()
                elif action == "inspect":
                    result = self.server.catch_lab.inspect()
                elif action == "throw_once":
                    result = self.server.catch_lab.throw_once(payload)
                    self.store.record_hunt_event("Catch Lab: one manually confirmed throw requested; capture outcome unverified")
                else:
                    raise CatchLabError("Unknown Catch Lab action")
            except (CatchLabError, DeviceError, KeyError, TypeError, ValueError) as error:
                self._send_json({"error": str(error)}, HTTPStatus.CONFLICT)
                return
            self._send_json({"ok": True, "result": result})
            return
        if self.path == "/api/heartbeat":
            self.store.heartbeat(
                str(payload.get("channelId") or ""),
                str(payload.get("channelName") or ""),
                int(payload["visibleMessageCount"]) if payload.get("visibleMessageCount") is not None else None,
                int(payload.get("newCandidateCount") or 0),
                payload.get("controlSamples") if isinstance(payload.get("controlSamples"), list) else None,
                {
                    "authorized": bool(payload.get("apiAuthorized")),
                    "last_poll_at": payload.get("apiLastPollAt"),
                    "message_count": int(payload.get("apiMessageCount") or 0),
                    "coordinate_link_count": int(payload.get("apiCoordinateLinkCount") or 0),
                    "link_hosts": payload.get("apiLinkHosts") if isinstance(payload.get("apiLinkHosts"), list) else [],
                    "accepted_count": int(payload.get("apiAcceptedCount") or 0),
                    "last_error": payload.get("apiLastError"),
                    "interaction_ready": bool(payload.get("interactionReady")),
                    "interaction_sent_count": int(payload.get("interactionSentCount") or 0),
                    "interaction_last_error": payload.get("interactionLastError"),
                },
            )
            self._send_json({"ok": True})
            return
        if self.path == "/api/mac-notification":
            try:
                result = self.hunt.update_mac_notification_bridge(payload)
            except HuntError as error:
                self._send_json({"error": str(error)}, HTTPStatus.CONFLICT)
                return
            self._send_json({"ok": True, **result})
            return
        if self.path == "/api/pokexperience":
            try:
                result = self.store.update_pokexperience_bridge(payload)
            except ValueError as error:
                self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
                return
            self.hunt.notify_targets_available()
            self._send_json({"ok": True, **result})
            return
        if self.path == "/api/manual-sighting":
            try:
                sighting = self.store.add_manual_sighting(
                    payload.get("species"), payload.get("coordinates")
                )
            except ValueError as error:
                self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
                return
            self._send_json({"ok": True, "sighting": sighting}, HTTPStatus.CREATED)
            return
        if self.path == "/api/queue-order":
            ordered_ids = payload.get("orderedIds")
            if not isinstance(ordered_ids, list):
                self._send_json(
                    {"error": "orderedIds must be a list."}, HTTPStatus.BAD_REQUEST
                )
                return
            try:
                result = self.store.save_queue_order(ordered_ids)
            except ValueError as error:
                self._send_json({"error": str(error)}, HTTPStatus.CONFLICT)
                return
            self._send_json({"ok": True, "queue": result})
            return
        if self.path == "/api/action":
            try:
                sighting_id = payload.get("sightingId")
                action = str(payload.get("action") or "")
                if action == "prepare":
                    result = self.hunt.prepare()
                elif action == "unprepare":
                    result = self.hunt.unprepare()
                elif action == "start":
                    dwell = payload.get("dwellSeconds")
                    result = self.hunt.start(float(dwell) if dwell is not None else None)
                elif action == "pause":
                    result = self.hunt.pause()
                elif action == "skip":
                    result = self.hunt.skip()
                elif action == "sync_internal_feed":
                    hunt_status = self.hunt.status()
                    if hunt_status.get("huntState") in ("running", "paused"):
                        raise HuntError("Pause is not enough—stop the active hunt before syncing a new feed.")
                    if hunt_status.get("ipogoPrepared"):
                        self.hunt.unprepare()
                    phone = self.device.refresh()
                    udid = phone.get("phoneUdid")
                    if not phone.get("phoneConnected") or not isinstance(udid, str) or not udid:
                        raise HuntError(str(phone.get("phoneLastError") or "Connect the iPhone before syncing."))
                    result = self.internal_feed.start(udid)
                elif action == "set_feed_source":
                    hunt_status = self.hunt.status()
                    if hunt_status.get("huntState") in ("running", "paused"):
                        raise HuntError("Stop the active hunt before changing coordinate sources.")
                    result = self.store.set_feed_source(str(payload.get("source") or ""))
                elif action in ("inject_notification", "test_shundo"):
                    result = self.hunt.inject_notification(
                        kind=str(payload.get("kind") or "shundo"),
                        message=str(payload.get("message") or "Manual Shundo test signal"),
                    )
                else:
                    result = self.store.action(
                        action,
                        int(sighting_id) if sighting_id is not None else None,
                    )
            except (RuntimeError, TypeError, ValueError) as error:
                self._send_json({"error": str(error)}, HTTPStatus.CONFLICT)
                return
            self._send_json({"ok": True, "status": result})
            return
        if self.path == "/api/preferences":
            try:
                ranked_species = payload.get("rankedSpecies")
                if not isinstance(ranked_species, list):
                    raise ValueError("rankedSpecies must be a list.")
                result = self.store.save_preferences(
                    str(payload.get("mode") or "all"), ranked_species
                )
            except ValueError as error:
                self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
                return
            self._send_json({"ok": True, "preferences": result})
            return
        if self.path == "/api/hunt-settings":
            try:
                hunt_status = self.hunt.status()
                if hunt_status.get("huntState") in ("running", "paused"):
                    raise HuntError("Pause is not enough. Stop the hunt before changing timing settings.")
                result = self.store.save_hunt_settings(
                    payload.get("dwellSeconds"),
                    payload.get("recoveryFailureThreshold"),
                    payload.get("hundoCooldownSeconds"),
                )
                updated_status = self.hunt.configure_timing(
                    float(result["dwellSeconds"]),
                    int(result["recoveryFailureThreshold"]),
                    float(result["hundoCooldownSeconds"]),
                )
            except (HuntError, TypeError, ValueError) as error:
                self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
                return
            self._send_json({"ok": True, "settings": result, "status": updated_status})
            return
        if self.path == "/api/device":
            action = str(payload.get("action") or "")
            try:
                if action == "refresh":
                    result = self.device.refresh()
                elif action == "enable_wifi":
                    result = self.device.enable_wifi()
                elif action == "set_location":
                    sighting_id = int(payload.get("sightingId"))
                    sighting = self.store.get_sighting(sighting_id)
                    result = self.device.set_location(
                        float(sighting["latitude"]), float(sighting["longitude"])
                    )
                    self.store.record_phone_location(sighting)
                elif action == "clear_location":
                    self.hunt.stop_for_real_location()
                    result = self.device.clear_location()
                    with self.store.lock, self.store._connect() as connection:
                        self.store._event(connection, "Phone", "Restored the iPhone's real location")
                else:
                    raise ValueError("Unknown phone action.")
            except (DeviceError, TypeError, ValueError) as error:
                self._send_json({"error": str(error)}, HTTPStatus.CONFLICT)
                return
            self._send_json({"ok": True, "device": result})
            return
        if not self.store.accepts_external_feed():
            self._send_json({
                "accepted": False,
                "reason": "Discord relay is not the active coordinate source",
            })
            return
        sighting, inserted = self.store.add(payload)
        if sighting is None:
            self._send_json({"accepted": False, "reason": "no 100-IV coordinate found"})
            return
        self._send_json({"accepted": True, "inserted": inserted, "sighting": sighting})


class FeedServer(ThreadingHTTPServer):
    def __init__(
        self,
        address: tuple[str, int],
        store: SightingStore,
        static_dir: Path,
        relay_path: Path,
        device: DeviceController,
        hunt: HuntCoordinator,
        internal_feed: InternalFeedService,
        instance_token: str = "",
    ):
        super().__init__(address, FeedHandler)
        self.store = store
        self.static_dir = static_dir
        self.relay_path = relay_path
        self.device = device
        self.hunt = hunt
        self.internal_feed = internal_feed
        self.instance_token = instance_token
        def can_test_catch():
            status = self.hunt.status()
            return (self.device.status().get("phoneConnected") is True
                    and status.get("huntState") == "idle"
                    and not status.get("huntWorkerAlive")
                    and not status.get("ipogoPrepared"))
        self.catch_lab = CatchLab(can_test_catch)
        self.overnight = OvernightGuard(hunt, device, Path(store.database_path).with_suffix(".encounter-hold.json"))
        hunt.encounter_guard = self.overnight

    def server_close(self):
        if hasattr(self, "overnight"):
            self.overnight.close()
        super().server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local Shundo Hunter feed service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--instance-token", default="")
    parser.add_argument(
        "--database",
        type=Path,
        default=Path(__file__).resolve().parent / "data" / "shundo_hunter.db",
    )
    parser.add_argument(
        "--static",
        type=Path,
        default=Path(__file__).resolve().parent / "web",
    )
    parser.add_argument(
        "--relay-path",
        type=Path,
        default=Path(__file__).resolve().parent / "browser_relay",
    )
    args = parser.parse_args()
    store = SightingStore(args.database)
    store.expire_stale_sightings(10 * 60)
    device = DeviceController()
    hunt_settings = store.hunt_settings()
    hunt = HuntCoordinator(
        store,
        device,
        USBNotificationDetector(),
        dwell_seconds=float(hunt_settings["dwellSeconds"]),
        ipogo_recovery_timeout_threshold=int(hunt_settings["recoveryFailureThreshold"]),
        hundo_cooldown_seconds=float(hunt_settings["hundoCooldownSeconds"]),
    )
    hunt.detector.watcher.command_transform = device.transport_command
    if hunt.detector.world_watcher is not None:
        hunt.detector.world_watcher.command_transform = device.transport_command

    def internal_feed_refresh_is_safe() -> bool:
        status = hunt.status()
        return (
            status.get("huntState") not in ("running", "paused")
            and not bool(status.get("ipogoPrepared"))
        )

    def store_internal_batch(items: list[InternalFeedItem]) -> int:
        inserted = store.add_internal_batch(items)
        hunt.notify_targets_available()
        return inserted

    internal_feed = InternalFeedService(
        store_internal_batch,
        can_refresh=internal_feed_refresh_is_safe,
    )

    def request_internal_queue_refill() -> None:
        phone = device.refresh()
        udid = phone.get("phoneUdid")
        if not phone.get("phoneConnected") or not isinstance(udid, str) or not udid:
            raise RuntimeError(str(phone.get("phoneLastError") or "Connect the iPhone before refreshing."))
        internal_feed.start(udid)

    hunt.set_queue_refill_requester(request_internal_queue_refill)
    server = FeedServer(
        (args.host, args.port),
        store,
        args.static,
        args.relay_path,
        device,
        hunt,
        internal_feed,
        instance_token=args.instance_token,
    )
    print(f"Shundo Hunter feed listening on http://{args.host}:{args.port}")
    print(f"Database: {args.database}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping feed service")
    finally:
        server.server_close()
        server.catch_lab.close()
        hunt.close()
        internal_feed.close()
        device.close()


if __name__ == "__main__":
    main()
