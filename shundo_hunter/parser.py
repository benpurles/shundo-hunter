from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import re
from typing import Any, Iterable
from urllib.parse import parse_qs, unquote, urlparse


COORDINATE_RE = re.compile(
    r"(?<![\d.])(-?(?:[0-8]?\d\.\d{4,}|90\.0{4,}))\s*[, ]\s*"
    r"(-?(?:1[0-7]\d\.\d{4,}|\d?\d\.\d{4,}|180\.0{4,}))(?![\d.])"
)
CP_RE = re.compile(r"\bCP\s*[:#]?\s*(\d{1,5})\b", re.IGNORECASE)
LEVEL_RE = re.compile(r"\b(?:L|LVL|LEVEL)\s*[:#]?\s*(\d{1,2}(?:\.5)?)\b", re.IGNORECASE)
IV_RE = re.compile(r"\bIV\s*[:#]?\s*(\d{1,3})\s*%?|\b(100)\s*%", re.IGNORECASE)
NAME_RE = re.compile(
    r"\b(?:NAME|POK[EÉ]MON|POKEMON)\s*[:：]\s*([^\n|•]+)", re.IGNORECASE
)
MARKDOWN_NAME_RE = re.compile(r"\*\*\*\s*([^*\n]+?)\s*\*\*\*")
BOT_ROW_NAME_RE = re.compile(
    r"^\s*([A-Za-z][A-Za-z0-9 .:'’()\-]{1,40}?)\s{2,}\d+\s+\d+\s{2,}",
    re.MULTILINE,
)
POKEDEX100_ROW_NAME_RE = re.compile(
    r"^\s*([A-Za-z][A-Za-z0-9 .:'’()\-]{1,40}?)\s{2,}IV\s*100\b",
    re.IGNORECASE | re.MULTILINE,
)
BOT_ROW_DETAILS_RE = re.compile(
    r"^\s*([A-Za-z][A-Za-z0-9 .:'’()\-]{1,40}?)\s{2,}(\d{1,2})\s+(\d{1,5})\s{2,}",
    re.MULTILINE,
)


@dataclass(frozen=True)
class ParsedSighting:
    source: str
    guild_id: str
    channel_id: str
    channel_name: str
    message_id: str
    observed_at: str
    species: str | None
    latitude: float
    longitude: float
    iv: int | None
    cp: int | None
    level: float | None
    gender: str | None
    shiny_eligible: bool | None
    coordinate_url: str | None
    raw_text: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _first_match(pattern: re.Pattern[str], text: str, cast: type = str) -> Any | None:
    match = pattern.search(text)
    if not match:
        return None
    value = next((group for group in match.groups() if group is not None), match.group(0))
    try:
        return cast(value.strip())
    except (TypeError, ValueError):
        return None


def _valid_coordinate(latitude: float, longitude: float) -> bool:
    return -90 <= latitude <= 90 and -180 <= longitude <= 180


def coordinates_from_text(text: str) -> tuple[float, float] | None:
    for match in COORDINATE_RE.finditer(unquote(text)):
        latitude, longitude = float(match.group(1)), float(match.group(2))
        if _valid_coordinate(latitude, longitude):
            return latitude, longitude
    return None


def coordinates_from_url(url: str) -> tuple[float, float] | None:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    for key in ("q", "query", "ll", "center", "destination"):
        for value in query.get(key, []):
            coordinate = coordinates_from_text(value)
            if coordinate:
                return coordinate
    return coordinates_from_text(unquote(url))


def _coordinate_from_payload(payload: dict[str, Any]) -> tuple[float, float, str | None] | None:
    resolved = payload.get("resolvedCoordinate") or payload.get("resolved_coordinate")
    if isinstance(resolved, dict):
        try:
            latitude = float(resolved["latitude"])
            longitude = float(resolved["longitude"])
        except (KeyError, TypeError, ValueError):
            pass
        else:
            if _valid_coordinate(latitude, longitude):
                return latitude, longitude, resolved.get("url")

    links: Iterable[Any] = payload.get("links") or []
    for link in links:
        url = link.get("href") if isinstance(link, dict) else str(link)
        if not url:
            continue
        coordinate = coordinates_from_url(url)
        if coordinate:
            return coordinate[0], coordinate[1], url

    raw_text = str(payload.get("rawText") or payload.get("raw_text") or "")
    coordinate = coordinates_from_text(raw_text)
    if coordinate:
        return coordinate[0], coordinate[1], None
    return None


def _species(text: str, payload: dict[str, Any]) -> str | None:
    explicit = payload.get("species")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()[:80]
    match = (
        NAME_RE.search(text)
        or MARKDOWN_NAME_RE.search(text)
        or POKEDEX100_ROW_NAME_RE.search(text)
        or BOT_ROW_NAME_RE.search(text)
    )
    if match:
        return match.group(1).strip(" *_-•")[:80] or None
    return None


def _bot_row_details(text: str) -> tuple[str, int, int] | None:
    match = BOT_ROW_DETAILS_RE.search(text)
    if not match:
        return None
    return match.group(1).strip(), int(match.group(2)), int(match.group(3))


def _gender(text: str) -> str | None:
    if "♂" in text or re.search(r"\bmale\b", text, re.IGNORECASE):
        return "male"
    if "♀" in text or re.search(r"\bfemale\b", text, re.IGNORECASE):
        return "female"
    return None


def _shiny_eligible(text: str) -> bool | None:
    lowered = text.casefold()
    if any(marker in text for marker in ("✨", "⭐", "🌟")) or "shiny" in lowered:
        return True
    if "not shiny eligible" in lowered or "shiny unavailable" in lowered:
        return False
    return None


def parse_relay_payload(payload: dict[str, Any]) -> ParsedSighting | None:
    coordinate = _coordinate_from_payload(payload)
    if coordinate is None:
        return None

    raw_text = str(payload.get("rawText") or payload.get("raw_text") or "").strip()[:12_000]
    bot_row = _bot_row_details(raw_text)
    channel_name = str(payload.get("channelName") or payload.get("channel_name") or "unknown")[:120]
    iv = _first_match(IV_RE, raw_text, int)
    is_hundo_channel = "💯" in channel_name or "100" in channel_name.casefold()
    is_hundo_message = iv == 100 or "💯" in raw_text
    if iv is not None and iv != 100:
        return None
    if not (is_hundo_channel or is_hundo_message or payload.get("trustedHundoChannel") is True):
        return None

    species = _species(raw_text, payload)
    if species is None:
        return None

    observed = payload.get("observedAt") or payload.get("observed_at")
    if not isinstance(observed, str) or not observed:
        observed = datetime.now(timezone.utc).isoformat()

    return ParsedSighting(
        source="discord-browser-relay",
        guild_id=str(payload.get("guildId") or payload.get("guild_id") or ""),
        channel_id=str(payload.get("channelId") or payload.get("channel_id") or ""),
        channel_name=channel_name,
        message_id=str(payload.get("messageId") or payload.get("message_id") or ""),
        observed_at=observed,
        species=species,
        latitude=coordinate[0],
        longitude=coordinate[1],
        iv=iv or 100,
        cp=_first_match(CP_RE, raw_text, int) or (bot_row[2] if bot_row else None),
        level=_first_match(LEVEL_RE, raw_text, float) or (float(bot_row[1]) if bot_row else None),
        gender=_gender(raw_text),
        shiny_eligible=_shiny_eligible(raw_text),
        coordinate_url=coordinate[2],
        raw_text=raw_text,
    )


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
