"""Conservative, local screen evidence. Never authorizes an automatic throw."""
from pathlib import Path
import json
import re
import subprocess


def classify(lines):
    usable = [item for item in lines if isinstance(item, dict)
              and isinstance(item.get("text"), str)
              and float(item.get("confidence", 0)) >= 0.65]
    # Ignore status bar / mirrored notification banners for outcome evidence.
    body = [item["text"].strip() for item in usable if 0.16 <= float(item.get("y", 0)) <= 0.93]
    text = " ".join(body)
    lower = text.lower().replace("é", "e")
    cooldown = re.search(r"(?:est\.?\s*cd|cooldown)\s*:?\s*(\d{1,2}):(\d{2})(?::(\d{2}))?", " ".join(item["text"] for item in usable), re.I)
    cooldown_seconds = 0
    if cooldown:
        parts = [int(value) for value in cooldown.groups() if value is not None]
        for value in parts:
            cooldown_seconds = cooldown_seconds * 60 + value
    result = {"scene": "uncertain", "evidence": body[:18], "cp": None,
              "lines": [item for item in usable if 0.16 <= float(item.get("y", 0)) <= 0.96],
              "cooldownSeconds": cooldown_seconds, "captureVerified": False}
    # Require both a catch phrase and a corroborating catch cue in the game
    # area. No claim based merely on a disappearing Pokemon or a used ball.
    catch_phrase = re.search(r"\bwas caught[!.]?", lower)
    reward = ("pokemon caught" in lower and "total" in lower
              and re.search(r"\b\d+\s*xp\b", lower) and re.search(r"\bok\b", lower))
    if (catch_phrase and "gotcha" in lower) or reward:
        result["scene"] = "caught"
    elif re.search(r"\b(?:fled|ran away)\b", lower):
        result["scene"] = "fled"
    else:
        cp_rows = [item["text"] for item in usable if 0.18 <= float(item.get("y", 0)) <= 0.55]
        match = re.search(r"\bCP\s*[: ]?\s*(\d{1,5})\b", " ".join(cp_rows), re.I)
        # The AR control distinguishes encounter CP text from Pokemon detail
        # and inventory screens. OCR failure remains uncertain, never a retry.
        has_ar = any(item["text"].strip().upper() == "AR" and float(item.get("y", 1)) < 0.18 for item in usable)
        if match and has_ar:
            result.update(scene="encounter", cp=int(match.group(1)))
    if "master ball" in lower:
        result["scene"] = "blocked-ball"
    return result


def read_screen(png):
    root = Path(__file__).resolve().parent.parent
    candidates = (root.parent / "MacOS/CatchScreenReader", root / "build/shundo-hunter/CatchScreenReader")
    executable = next((path for path in candidates if path.is_file()), None)
    if executable is None:
        raise RuntimeError("The local screen reader is not installed. Rebuild Hunter.")
    try:
        result = subprocess.run([str(executable)], input=png, capture_output=True, timeout=8, check=True)
        lines = json.loads(result.stdout)
        if not isinstance(lines, list):
            raise ValueError("Invalid OCR response")
        return classify(lines)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise RuntimeError("Local screen recognition failed; no automatic action is allowed") from error
