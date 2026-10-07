#!/usr/bin/env python3
"""Sign only the isolated Hunter Lab v2 artifact.

Unlike the general iPogo test signer, this signer rejects production bundle
identities and wildcard keychain access. It never installs anything.
"""

from __future__ import annotations

import argparse
import plistlib
import shutil
import subprocess
import tempfile
from pathlib import Path

from build_hunter_lab_v2 import (
    LAB_BUNDLE_ID,
    LAB_NOTIFICATION_ID,
    LAB_WIDGET_ID,
    verify_unsigned_v2,
)
from hunter_lab_artifact import APP


TEAM_ID = "H37AFANDDZ"
LAB_KEYCHAIN_GROUP = TEAM_ID + "." + LAB_BUNDLE_ID


def _run(*arguments: str) -> None:
    subprocess.run(arguments, check=True)


def _bundle_id(bundle: Path) -> str:
    return plistlib.loads((bundle / "Info.plist").read_bytes())["CFBundleIdentifier"]


def _entitlements(bundle_id: str) -> dict[str, object]:
    if bundle_id not in {LAB_BUNDLE_ID, LAB_NOTIFICATION_ID, LAB_WIDGET_ID}:
        raise RuntimeError(f"Refusing to sign unexpected bundle identity: {bundle_id}")
    return {
        "application-identifier": TEAM_ID + "." + bundle_id,
        "com.apple.developer.team-identifier": TEAM_ID,
        "get-task-allow": True,
        "keychain-access-groups": [LAB_KEYCHAIN_GROUP],
    }


def _sign(identity: str, target: Path, entitlements: Path | None = None) -> None:
    command = [
        "codesign", "--force", "--sign", identity, "--timestamp=none",
        "--generate-entitlement-der",
    ]
    if entitlements is not None:
        command.extend(["--entitlements", str(entitlements)])
    command.append(str(target))
    _run(*command)


def sign(unsigned_ipa: Path, signed_ipa: Path, profile: Path, identity: str) -> None:
    verify_unsigned_v2(unsigned_ipa)
    if signed_ipa.exists():
        raise RuntimeError(f"Refusing to overwrite existing artifact: {signed_ipa}")
    if not profile.is_file():
        raise RuntimeError(f"Provisioning profile does not exist: {profile}")

    with tempfile.TemporaryDirectory(prefix="hunter-lab-v2-sign-") as temporary_name:
        root = Path(temporary_name)
        _run("ditto", "-x", "-k", str(unsigned_ipa.resolve()), str(root))
        app = root / APP
        if _bundle_id(app) != LAB_BUNDLE_ID:
            raise RuntimeError("Refusing to sign a non-Lab main application")
        shutil.copy2(profile, app / "embedded.mobileprovision")

        frameworks = sorted(app.rglob("*.framework"), key=lambda item: len(item.parts), reverse=True)
        dylibs = sorted(app.rglob("*.dylib"), key=lambda item: len(item.parts), reverse=True)
        for target in [*frameworks, *dylibs]:
            _sign(identity, target)

        extensions = sorted(app.rglob("*.appex"), key=lambda item: len(item.parts), reverse=True)
        extension_ids = {_bundle_id(item) for item in extensions}
        if extension_ids != {LAB_NOTIFICATION_ID, LAB_WIDGET_ID}:
            raise RuntimeError(f"Unexpected Lab extension identities: {sorted(extension_ids)}")
        for index, extension in enumerate(extensions):
            shutil.copy2(profile, extension / "embedded.mobileprovision")
            entitlement_path = root / f"extension-{index}.xcent"
            entitlement_path.write_bytes(plistlib.dumps(_entitlements(_bundle_id(extension))))
            _sign(identity, extension, entitlement_path)

        main_entitlements = root / "main.xcent"
        main_entitlements.write_bytes(plistlib.dumps(_entitlements(LAB_BUNDLE_ID)))
        _sign(identity, app, main_entitlements)
        _run("codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app))

        signed_ipa.parent.mkdir(parents=True, exist_ok=True)
        _run(
            "ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
            str(root / "Payload"), str(signed_ipa.resolve()),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Sign the isolated Hunter Lab v2")
    parser.add_argument("unsigned_ipa", type=Path)
    parser.add_argument("signed_ipa", type=Path)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--identity", required=True)
    args = parser.parse_args()
    sign(args.unsigned_ipa, args.signed_ipa, args.profile, args.identity)
    print(f"Created and deep-verified: {args.signed_ipa}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

