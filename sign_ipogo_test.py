#!/usr/bin/env python3
"""Sign the patched iPogo test IPA with a local Apple development profile."""

from __future__ import annotations

import argparse
import plistlib
import shutil
import subprocess
import tempfile
from pathlib import Path


TEAM_ID = "H37AFANDDZ"
APP_RELATIVE_PATH = Path("Payload/PokmonGO.app")


def run(*args: str) -> None:
    subprocess.run(args, check=True)


def bundle_identifier(bundle: Path) -> str:
    with (bundle / "Info.plist").open("rb") as source:
        return plistlib.load(source)["CFBundleIdentifier"]


def entitlements_for(bundle_id: str, application_id_suffix: str) -> dict[str, object]:
    suffix = f".{application_id_suffix}" if application_id_suffix else ""
    return {
        "application-identifier": f"{TEAM_ID}.{bundle_id}{suffix}",
        "com.apple.developer.team-identifier": TEAM_ID,
        "get-task-allow": True,
        # Preserve every group granted by the wildcard development profile.
        # iPogo 4.3.5's known-good signed control includes com.apple.token.
        "keychain-access-groups": [f"{TEAM_ID}.*", "com.apple.token"],
    }


def sign(identity: str, target: Path, entitlements: Path | None = None) -> None:
    command = ["codesign", "--force", "--sign", identity, "--timestamp=none", "--generate-entitlement-der"]
    if entitlements is not None:
        command.extend(["--entitlements", str(entitlements)])
    command.append(str(target))
    run(*command)


def verify_ipogo_runtime(root: Path) -> None:
    app = root / APP_RELATIVE_PATH
    with (app / "Info.plist").open("rb") as source:
        info = plistlib.load(source)
    if (
        str(info.get("CFBundleShortVersionString") or "") == "0.423.1"
        and str(info.get("ShundoSpawnRuntimeVersion") or "") == "6"
    ):
        import build_ipogo_435_runtime as runtime

        expected_metadata = {
            "CFBundleIdentifier": "com.nianticlabs.pokemongo",
            "CFBundleShortVersionString": runtime.engine.BASE_SHORT_VERSION,
            "CFBundleVersion": runtime.engine.BUNDLE_VERSION,
            "ShundoSpawnRuntimeVersion": runtime.engine.RUNTIME_VERSION,
            "ShundoSpawnRuntimeBuild": runtime.engine.RUNTIME_BUILD,
            "ShundoWorldScanRuntimeVersion": runtime.engine.WORLD_VERSION,
        }
        for key, expected in expected_metadata.items():
            if str(info.get(key) or "") != expected:
                raise RuntimeError(f"iPogo 4.3.5 metadata {key} is wrong")
        binary = (root / runtime.engine.FBL).read_bytes()
        runtime.engine.verify_patched_binary(binary)
        return

    if (
        str(info.get("CFBundleShortVersionString") or "") == "0.427.0"
        and str(info.get("ShundoSpawnRuntimeVersion") or "") == "7"
    ):
        import build_ipogo_438_runtime as runtime

        expected_metadata = {
            "CFBundleIdentifier": "com.nianticlabs.pokemongo",
            "CFBundleShortVersionString": runtime.engine.BASE_SHORT_VERSION,
            "CFBundleVersion": runtime.engine.BUNDLE_VERSION,
            "ShundoSpawnRuntimeVersion": runtime.engine.RUNTIME_VERSION,
            "ShundoSpawnRuntimeBuild": runtime.engine.RUNTIME_BUILD,
            "ShundoWorldScanRuntimeVersion": runtime.engine.WORLD_VERSION,
        }
        for key, expected in expected_metadata.items():
            if str(info.get(key) or "") != expected:
                raise RuntimeError(f"iPogo 4.3.8 metadata {key} is wrong")
        binary = (root / runtime.engine.FBL).read_bytes()
        runtime.engine.verify_patched_binary(binary)
        return

    if (
        str(info.get("CFBundleShortVersionString") or "") == "0.429.1"
        and str(info.get("ShundoSpawnRuntimeVersion") or "") == "8"
    ):
        import build_ipogo_439_runtime as runtime

        expected_metadata = {
            "CFBundleIdentifier": "com.nianticlabs.pokemongo",
            "CFBundleShortVersionString": runtime.engine.BASE_SHORT_VERSION,
            "CFBundleVersion": runtime.engine.BUNDLE_VERSION,
            "ShundoSpawnRuntimeVersion": runtime.engine.RUNTIME_VERSION,
            "ShundoSpawnRuntimeBuild": runtime.engine.RUNTIME_BUILD,
            "ShundoWorldScanRuntimeVersion": runtime.engine.WORLD_VERSION,
        }
        for key, expected in expected_metadata.items():
            if str(info.get(key) or "") != expected:
                raise RuntimeError(f"iPogo 4.3.9 metadata {key} is wrong")
        binary = (root / runtime.engine.FBL).read_bytes()
        runtime.engine.verify_patched_binary(binary)
        return

    from build_ipogo_spawn_runtime import verify_runtime

    verify_runtime(root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("unsigned_ipa", type=Path)
    parser.add_argument("signed_ipa", type=Path)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--identity", required=True)
    parser.add_argument(
        "--application-id-suffix",
        default="",
        help="Legacy suffix used by the already-installed app's application-identifier entitlement",
    )
    parser.add_argument(
        "--allow-unsafe-ipogo",
        action="store_true",
        help="Permit signing an experimental Pokémon GO IPA that fails the Hunter Runtime invariant",
    )
    args = parser.parse_args()

    if args.signed_ipa.exists():
        raise RuntimeError(f"Output already exists: {args.signed_ipa}")

    with tempfile.TemporaryDirectory(prefix="ipogo-sign-") as temporary:
        root = Path(temporary)
        run("ditto", "-x", "-k", str(args.unsigned_ipa), str(root))
        app = root / APP_RELATIVE_PATH
        if bundle_identifier(app) == "com.nianticlabs.pokemongo" and not args.allow_unsafe_ipogo:
            try:
                verify_ipogo_runtime(root)
            except (ImportError, OSError, RuntimeError) as error:
                raise RuntimeError(
                    "Refusing to sign an unverified iPogo experiment. Only a version-locked "
                    "Hunter Runtime is accepted by default."
                ) from error
        shutil.copy2(args.profile, app / "embedded.mobileprovision")

        frameworks = sorted(app.rglob("*.framework"), key=lambda path: len(path.parts), reverse=True)
        dylibs = sorted(app.rglob("*.dylib"), key=lambda path: len(path.parts), reverse=True)
        for target in [*frameworks, *dylibs]:
            sign(args.identity, target)

        extensions = sorted(app.rglob("*.appex"), key=lambda path: len(path.parts), reverse=True)
        for index, extension in enumerate(extensions):
            shutil.copy2(args.profile, extension / "embedded.mobileprovision")
            entitlement_path = root / f"extension-{index}.xcent"
            entitlement_path.write_bytes(
                plistlib.dumps(entitlements_for(bundle_identifier(extension), args.application_id_suffix))
            )
            sign(args.identity, extension, entitlement_path)

        main_entitlements = root / "main.xcent"
        main_entitlements.write_bytes(
            plistlib.dumps(entitlements_for(bundle_identifier(app), args.application_id_suffix))
        )
        sign(args.identity, app, main_entitlements)
        run("codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app))

        args.signed_ipa.parent.mkdir(parents=True, exist_ok=True)
        run("ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(root / "Payload"), str(args.signed_ipa))

    print(f"Created and verified: {args.signed_ipa}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
