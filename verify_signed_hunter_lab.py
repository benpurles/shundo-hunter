#!/usr/bin/env python3
"""Verify that signing changed only signature material in Hunter Lab."""

from __future__ import annotations

import argparse
import json
import plistlib
import zipfile
from pathlib import Path

from build_hunter_lab_v2 import LAB_BUILD, LAB_BUNDLE_ID, LAB_MARKER_KEY, LAB_VERSION
from hunter_lab_artifact import APP, FBL, sha256_file, verify_resigned_fbl, write_report


def verify(unsigned_ipa: Path, signed_ipa: Path) -> dict[str, object]:
    with zipfile.ZipFile(unsigned_ipa) as unsigned, zipfile.ZipFile(signed_ipa) as signed:
        unsigned_fbl = unsigned.read(FBL.as_posix())
        signed_fbl = signed.read(FBL.as_posix())
        info = plistlib.loads(signed.read((APP / "Info.plist").as_posix()))
        names = signed.namelist()
    if info.get("CFBundleIdentifier") != LAB_BUNDLE_ID:
        raise RuntimeError("Signed artifact does not have the isolated Hunter Lab bundle ID")
    if str(info.get("CFBundleVersion") or "") != LAB_BUILD:
        raise RuntimeError("Signed artifact does not have the Hunter Lab build number")
    if info.get(LAB_MARKER_KEY) != LAB_VERSION:
        raise RuntimeError("Signed artifact is missing the Hunter Lab marker")
    if any(name.startswith("Payload/PokmonGO.app/Frameworks/ShundoBridge.framework/") for name in names):
        raise RuntimeError("Signed artifact contains forbidden ShundoBridge.framework")
    binary_report = verify_resigned_fbl(unsigned_fbl, signed_fbl)
    return {
        "schema": 1,
        "status": "verified-signed-lab-shell",
        "artifact": str(signed_ipa.resolve()),
        "ipaSha256": sha256_file(signed_ipa),
        "bundleIdentifier": LAB_BUNDLE_ID,
        "bundleVersion": LAB_BUILD,
        "installed": False,
        "fblPromises": binary_report,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("unsigned_ipa", type=Path)
    parser.add_argument("signed_ipa", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = verify(args.unsigned_ipa, args.signed_ipa)
    if args.report:
        write_report(report, args.report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
