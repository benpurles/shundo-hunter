#!/usr/bin/env python3
"""Create an unsigned, side-by-side iPogo Hunter Lab shell.

The clone contains no Hunter automation yet.  Its purpose is to establish a
separate bundle identity for read-only feed probing while preserving the gold
FBLPromises binary byte-for-byte.  This command never signs or installs.
"""

from __future__ import annotations

import argparse
import json
import plistlib
import subprocess
import tempfile
import zipfile
from pathlib import Path

from hunter_lab_artifact import APP, FBL, verify_fbl, verify_gold_ipa, write_report


LAB_BUNDLE_ID = "com.nianticlabs.pokemongo.hunterlab"
LAB_BUILD = "5001"
LAB_DISPLAY_NAME = "iPogo Hunter Lab"
LAB_MARKER_KEY = "ShundoHunterLabVersion"
LAB_VERSION = "1"


def _update_plist(path: Path, bundle_id: str, display_name: str) -> dict[str, object]:
    with path.open("rb") as source:
        info = plistlib.load(source)
    before = {
        "bundleIdentifier": info.get("CFBundleIdentifier"),
        "bundleVersion": info.get("CFBundleVersion"),
        "displayName": info.get("CFBundleDisplayName"),
    }
    info["CFBundleIdentifier"] = bundle_id
    info["CFBundleVersion"] = LAB_BUILD
    info["CFBundleDisplayName"] = display_name
    info[LAB_MARKER_KEY] = LAB_VERSION
    info["ShundoHunterLabMode"] = "read-only-feed-probe"
    path.write_bytes(plistlib.dumps(info, fmt=plistlib.FMT_BINARY))
    parts = path.parts
    try:
        report_path = str(Path(*parts[parts.index("Payload"):]))
    except ValueError:
        report_path = path.name
    return {
        "path": report_path,
        "before": before,
        "after": {
            "bundleIdentifier": bundle_id,
            "bundleVersion": LAB_BUILD,
            "displayName": display_name,
        },
    }


def verify_lab_archive(path: Path) -> dict[str, object]:
    with zipfile.ZipFile(path) as archive:
        fbl = archive.read(FBL.as_posix())
        main = plistlib.loads(archive.read((APP / "Info.plist").as_posix()))
        notification = plistlib.loads(
            archive.read((APP / "PlugIns/notification.appex/Info.plist").as_posix())
        )
        widget = plistlib.loads(
            archive.read((APP / "PlugIns/homewidget.appex/Info.plist").as_posix())
        )
        if any(name.startswith("Payload/PokmonGO.app/Frameworks/ShundoBridge.framework/") for name in archive.namelist()):
            raise RuntimeError("Lab clone unexpectedly contains ShundoBridge.framework")
    fbl_report = verify_fbl(fbl)
    expected_ids = {
        "main": LAB_BUNDLE_ID,
        "notification": LAB_BUNDLE_ID + ".notification",
        "homewidget": LAB_BUNDLE_ID + ".homewidget",
    }
    actual_ids = {
        "main": main.get("CFBundleIdentifier"),
        "notification": notification.get("CFBundleIdentifier"),
        "homewidget": widget.get("CFBundleIdentifier"),
    }
    if actual_ids != expected_ids:
        raise RuntimeError(f"Lab bundle IDs do not match: {actual_ids}")
    for label, info in (("main", main), ("notification", notification), ("homewidget", widget)):
        if str(info.get("CFBundleVersion") or "") != LAB_BUILD:
            raise RuntimeError(f"{label} does not use lab build {LAB_BUILD}")
        if info.get(LAB_MARKER_KEY) != LAB_VERSION:
            raise RuntimeError(f"{label} is missing the Hunter Lab marker")
    return {
        "status": "verified-unsigned-lab-shell",
        "artifact": str(path.resolve()),
        "bundleIdentifiers": actual_ids,
        "bundleVersion": LAB_BUILD,
        "mode": "read-only-feed-probe",
        "fblPromises": fbl_report,
        "signed": False,
        "installed": False,
    }


def build(source: Path, output: Path, report_path: Path | None) -> dict[str, object]:
    base_report = verify_gold_ipa(source)
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite existing artifact: {output}")
    with tempfile.TemporaryDirectory(prefix="hunter-lab-clone-") as temporary:
        root = Path(temporary)
        subprocess.run(["ditto", "-x", "-k", str(source.resolve()), str(root)], check=True)
        app = root / APP
        changes = [
            _update_plist(app / "Info.plist", LAB_BUNDLE_ID, LAB_DISPLAY_NAME),
            _update_plist(
                app / "PlugIns/notification.appex/Info.plist",
                LAB_BUNDLE_ID + ".notification",
                "Hunter Lab Notifications",
            ),
            _update_plist(
                app / "PlugIns/homewidget.appex/Info.plist",
                LAB_BUNDLE_ID + ".homewidget",
                "Hunter Lab Widget",
            ),
        ]
        # Bundle signatures are intentionally stale after plist edits. Signing
        # is a separate, explicit gate; this builder cannot install anything.
        output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
                str(root / "Payload"), str(output.resolve()),
            ],
            check=True,
        )

    lab_report = verify_lab_archive(output)
    report = {"schema": 1, "base": base_report, "changes": changes, "lab": lab_report}
    if report_path:
        write_report(report, report_path)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an unsigned Hunter Lab side-by-side shell")
    parser.add_argument("source_ipa", type=Path)
    parser.add_argument("output_ipa", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = build(args.source_ipa, args.output_ipa, args.report)
    print(json.dumps(report["lab"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
