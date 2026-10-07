#!/usr/bin/env python3
"""Install only the approved side-by-side Hunter Lab v2 and prove production unchanged."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from build_hunter_lab_v2 import LAB_BUILD, LAB_BUNDLE_ID, verify_unsigned_v2


PRODUCTION_BUNDLE_ID = "com.nianticlabs.pokemongo"
APPROVED_IPA_SHA256 = "0722c426f03d376dbdddc3736a45ce8730d2e4ed14b035924a1f2211fe367eb9"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _apps(udid: str) -> dict[str, dict[str, object]]:
    result = subprocess.run(
        ["pymobiledevice3", "apps", "list", "--type", "User", "--udid", udid],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError("Installed-app response is not a JSON object")
    return payload


def _identity(apps: dict[str, dict[str, object]], bundle_id: str) -> dict[str, object] | None:
    item = apps.get(bundle_id)
    if item is None:
        return None
    return {
        "bundleIdentifier": item.get("CFBundleIdentifier"),
        "bundleVersion": str(item.get("CFBundleVersion") or ""),
        "path": item.get("Path"),
        "sequenceNumber": item.get("SequenceNumber"),
        "container": item.get("Container"),
        "applicationIdentifier": (item.get("Entitlements") or {}).get("application-identifier"),
        "keychainAccessGroups": (item.get("Entitlements") or {}).get("keychain-access-groups"),
    }


def install(ipa: Path, udid: str) -> dict[str, object]:
    artifact = ipa.resolve()
    if _sha256(artifact) != APPROVED_IPA_SHA256:
        raise RuntimeError("Refusing install: IPA hash is not the approved Hunter Lab v2 build")
    report = verify_unsigned_v2(artifact)
    if report["bundleIdentifiers"]["main"] != LAB_BUNDLE_ID:
        raise RuntimeError("Refusing install: artifact is not the side-by-side Hunter Lab")
    if report["bundleVersion"] != LAB_BUILD:
        raise RuntimeError("Refusing install: artifact build number is not approved")

    before_apps = _apps(udid)
    production_before = _identity(before_apps, PRODUCTION_BUNDLE_ID)
    lab_before = _identity(before_apps, LAB_BUNDLE_ID)
    if production_before is None:
        raise RuntimeError("Production iPogo is not installed; refusing Lab update")

    install_result = subprocess.run(
        [
            "pymobiledevice3", "apps", "install", "--developer", "--udid", udid,
            str(artifact),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    after_apps = _apps(udid)
    production_after = _identity(after_apps, PRODUCTION_BUNDLE_ID)
    lab_after = _identity(after_apps, LAB_BUNDLE_ID)
    if production_after != production_before:
        raise RuntimeError(
            "PRODUCTION IDENTITY CHANGED during Lab install; stop immediately: "
            + json.dumps({"before": production_before, "after": production_after}, sort_keys=True)
        )
    if lab_after is None or lab_after["bundleVersion"] != LAB_BUILD:
        raise RuntimeError(f"Hunter Lab build {LAB_BUILD} was not installed")
    if lab_after["applicationIdentifier"] != "H37AFANDDZ." + LAB_BUNDLE_ID:
        raise RuntimeError("Installed Hunter Lab application identifier is not isolated")
    if lab_after["keychainAccessGroups"] != ["H37AFANDDZ." + LAB_BUNDLE_ID]:
        raise RuntimeError("Installed Hunter Lab keychain group is not isolated")

    return {
        "status": "installed-lab-v2-production-unchanged",
        "deviceUdid": udid,
        "ipa": str(artifact),
        "ipaSha256": APPROVED_IPA_SHA256,
        "production": {"before": production_before, "after": production_after, "unchanged": True},
        "lab": {"before": lab_before, "after": lab_after},
        "installerOutput": install_result.stdout.strip()[-1000:],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Install only approved Hunter Lab v2")
    parser.add_argument("ipa", type=Path)
    parser.add_argument("--udid", required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = install(args.ipa, args.udid)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
