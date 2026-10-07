#!/usr/bin/env python3
"""Strict offline verifier for a signed Hunter Lab v2 artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import plistlib
import shutil
import struct
import subprocess
import tempfile
import zipfile
from pathlib import Path

from build_hunter_lab_v2 import (
    LAB_BUILD,
    LAB_BUNDLE_ID,
    LAB_NOTIFICATION_ID,
    LAB_WIDGET_ID,
    LAB_MARKER_KEY,
    LAB_VERSION,
    verify_unsigned_v2,
)
from hunter_lab_artifact import APP, FBL, sha256_file, verify_gold_ipa, write_report
from sign_hunter_lab_v2 import LAB_KEYCHAIN_GROUP, TEAM_ID


ALLOWED_SIGNING_RESOURCES = ("/_CodeSignature/CodeResources", "/embedded.mobileprovision")
FORBIDDEN_PAYLOAD_TERMS = (
    b"http://", b"https://", b"wss://", b"cookie", b"token", b"authorization",
    b"CLLocation", b"teleport", b"UNNotification", b"ShundoBridge",
)


def _run(*arguments: str, capture: bool = False) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(arguments, check=True, capture_output=capture)


def _macho(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size < 4:
        return False
    return struct.unpack("<I", path.read_bytes()[:4])[0] == 0xFEEDFACF


def _normalized_macho(path: Path, temporary: Path, label: str) -> bytes:
    copy = temporary / (hashlib.sha256(label.encode()).hexdigest() + ".macho")
    shutil.copy2(path, copy)
    result = subprocess.run(["codesign", "--remove-signature", str(copy)], capture_output=True)
    if result.returncode not in (0, 1):
        raise RuntimeError(f"Could not normalize Mach-O signature for {label}")
    return copy.read_bytes()


def _entitlements(bundle: Path) -> dict[str, object]:
    result = _run("codesign", "-d", "--entitlements", ":-", str(bundle), capture=True)
    payload = result.stdout
    if not payload:
        raise RuntimeError(f"No entitlements found for {bundle}")
    return plistlib.loads(payload)


def _bundle_id(bundle: Path) -> str:
    return plistlib.loads((bundle / "Info.plist").read_bytes())["CFBundleIdentifier"]


def verify(base_ipa: Path, unsigned_ipa: Path, signed_ipa: Path) -> dict[str, object]:
    base_report = verify_gold_ipa(base_ipa)
    unsigned_report = verify_unsigned_v2(unsigned_ipa)
    signed_report = verify_unsigned_v2(signed_ipa)

    with zipfile.ZipFile(unsigned_ipa) as unsigned, zipfile.ZipFile(signed_ipa) as signed:
        unsigned_names = {name for name in unsigned.namelist() if not name.endswith("/")}
        signed_names = {name for name in signed.namelist() if not name.endswith("/")}
    if unsigned_names != signed_names:
        added = sorted(signed_names - unsigned_names)
        removed = sorted(unsigned_names - signed_names)
        raise RuntimeError(f"Signing changed archive membership; added={added}, removed={removed}")

    with tempfile.TemporaryDirectory(prefix="hunter-lab-v2-verify-") as temporary_name:
        temporary = Path(temporary_name)
        unsigned_root = temporary / "unsigned"
        signed_root = temporary / "signed"
        unsigned_root.mkdir()
        signed_root.mkdir()
        _run("ditto", "-x", "-k", str(unsigned_ipa.resolve()), str(unsigned_root))
        _run("ditto", "-x", "-k", str(signed_ipa.resolve()), str(signed_root))
        signed_app = signed_root / APP
        _run("codesign", "--verify", "--deep", "--strict", "--verbose=2", str(signed_app))

        bundles = [
            signed_app,
            signed_app / "PlugIns/notification.appex",
            signed_app / "PlugIns/homewidget.appex",
        ]
        expected_ids = [LAB_BUNDLE_ID, LAB_NOTIFICATION_ID, LAB_WIDGET_ID]
        entitlement_report: dict[str, object] = {}
        for bundle, expected_id in zip(bundles, expected_ids, strict=True):
            if _bundle_id(bundle) != expected_id:
                raise RuntimeError(f"Signed bundle ID mismatch for {bundle}")
            values = _entitlements(bundle)
            expected_app_id = TEAM_ID + "." + expected_id
            if values.get("application-identifier") != expected_app_id:
                raise RuntimeError(f"Unexpected application identifier for {expected_id}")
            groups = values.get("keychain-access-groups")
            if groups != [LAB_KEYCHAIN_GROUP]:
                raise RuntimeError(f"Non-isolated keychain groups for {expected_id}: {groups}")
            if any("*" in group for group in groups):
                raise RuntimeError(f"Wildcard keychain group found for {expected_id}")
            entitlement_report[expected_id] = {
                "applicationIdentifier": expected_app_id,
                "keychainAccessGroups": groups,
            }

        unsigned_payload = unsigned_root / "Payload"
        signed_payload = signed_root / "Payload"
        checked_machos = 0
        checked_resources = 0
        for relative in sorted(path.relative_to(unsigned_payload) for path in unsigned_payload.rglob("*") if path.is_file()):
            before = unsigned_payload / relative
            after = signed_payload / relative
            label = relative.as_posix()
            if not after.is_file():
                raise RuntimeError(f"Signed artifact is missing {label}")
            if _macho(before):
                normalized_before = _normalized_macho(before, temporary, "unsigned-" + label)
                normalized_after = _normalized_macho(after, temporary, "signed-" + label)
                if normalized_before != normalized_after:
                    raise RuntimeError(f"Signing changed runtime bytes in {label}")
                checked_machos += 1
            elif label.endswith(ALLOWED_SIGNING_RESOURCES):
                continue
            else:
                if before.read_bytes() != after.read_bytes():
                    raise RuntimeError(f"Signing changed non-signature resource {label}")
                checked_resources += 1

        fbl = (signed_root / FBL).read_bytes()
        layout = signed_report["probeLayout"]
        code_offset = int(str(layout["codeAddress"]), 16)
        format_offset = int(str(layout["formatAddress"]), 16)
        payload = (
            fbl[code_offset:code_offset + int(layout["codeReserved"])]
            + fbl[format_offset:format_offset + int(layout["formatReserved"])]
        )
        lowered = payload.lower()
        found = [term.decode("ascii", "replace") for term in FORBIDDEN_PAYLOAD_TERMS if term.lower() in lowered]
        if found:
            raise RuntimeError(f"Read-only payload contains forbidden capability strings: {found}")

    return {
        "schema": 2,
        "status": "approved-for-lab-only-install",
        "base": base_report,
        "unsigned": unsigned_report,
        "signed": {
            **signed_report,
            "ipaSha256": sha256_file(signed_ipa),
            "deepCodeSignatureValid": True,
            "entitlements": entitlement_report,
            "normalizedMachOsCompared": checked_machos,
            "unchangedResourcesCompared": checked_resources,
            "archiveMembershipIdentical": True,
        },
        "productionBundleAuthorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify signed Hunter Lab v2")
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--unsigned", type=Path, required=True)
    parser.add_argument("--signed", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = verify(args.base, args.unsigned, args.signed)
    if args.report:
        write_report(report, args.report)
    print(json.dumps(report["signed"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
