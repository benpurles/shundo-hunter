#!/usr/bin/env python3
"""Preflight, install, and receipt the one released Hunter Runtime IPA."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile

from build_ipogo_439_runtime import (
    RUNTIME_BUILD,
    RUNTIME_VERSION,
    verify_ipa,
    sha256_file,
)


BUNDLE_ID = "com.nianticlabs.pokemongo"
RELEASE_SHA256 = "a728aaca83f64bdb972902f4f1f7ea51446c68539d21d9c00d2c61ec9af9341b"
DEFAULT_RECEIPT = Path.home() / "Library/Application Support/Shundo Hunter/spawn-runtime-receipt.json"


def run_json(command: list[str], timeout: float = 60) -> object:
    result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout)
    return json.loads(result.stdout)


def usb_udid(executable: str) -> str:
    devices = run_json([executable, "usbmux", "list"], timeout=20)
    if not isinstance(devices, list):
        raise RuntimeError("The iPhone device list was invalid")
    for device in devices:
        if isinstance(device, dict) and device.get("ConnectionType") == "USB":
            value = device.get("UniqueDeviceID")
            if isinstance(value, str) and value:
                return value
    raise RuntimeError("No paired USB iPhone was found")


def installed_app(executable: str, udid: str) -> dict[str, object]:
    applications = run_json(
        [executable, "apps", "list", "--type", "User", "--udid", udid],
        timeout=60,
    )
    if not isinstance(applications, dict) or not isinstance(applications.get(BUNDLE_ID), dict):
        raise RuntimeError("iPogo/Pokémon GO was not present after installation")
    return applications[BUNDLE_ID]


def verify_release(ipa: Path) -> None:
    actual_hash = sha256_file(ipa)
    if actual_hash != RELEASE_SHA256:
        raise RuntimeError(
            "Refusing install: IPA hash does not match the empirically verified release"
        )
    verify_ipa(ipa)


def write_receipt(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ipa", type=Path)
    parser.add_argument("--udid")
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--pymobiledevice3", default="pymobiledevice3")
    args = parser.parse_args()

    verify_release(args.ipa)
    udid = args.udid or usb_udid(args.pymobiledevice3)
    subprocess.run(
        [
            args.pymobiledevice3,
            "apps",
            "install",
            "--developer",
            "--udid",
            udid,
            str(args.ipa),
        ],
        check=True,
        timeout=300,
    )
    app = installed_app(args.pymobiledevice3, udid)
    sequence = app.get("SequenceNumber")
    bundle_path = app.get("Path")
    if not isinstance(sequence, int) or not isinstance(bundle_path, str) or not bundle_path:
        raise RuntimeError("iOS did not return a verifiable installation identity")
    receipt = {
        "bundleId": BUNDLE_ID,
        "bundlePath": bundle_path,
        "deviceUdid": udid,
        "installedAt": datetime.now(timezone.utc).isoformat(),
        "ipaSha256": RELEASE_SHA256,
        "runtimeBuild": RUNTIME_BUILD,
        "runtimeVersion": RUNTIME_VERSION,
        "sequenceNumber": sequence,
    }
    write_receipt(args.receipt, receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
