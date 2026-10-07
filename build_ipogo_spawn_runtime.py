#!/usr/bin/env python3
"""Build the single supported iPogo runtime for external location hunting.

This reproduces the empirically successful in-place runtime: the persistent
simulated-source mask plus the original setBody notification logger. It adds no
framework or Mach-O load command. The app Info.plist carries a versioned build
number that Shundo Hunter verifies before enabling Start Hunt.
"""

from __future__ import annotations

import argparse
import plistlib
import subprocess
import tempfile
from pathlib import Path

from patch_ipogo_shundo_runtime import patch_original_binary, verify_patched_binary
from patch_ipogo_simulated_flag import BINARY_RELATIVE_PATH, EXPECTED_IPA_SHA256, sha256


APP = Path("Payload/PokmonGO.app")
INFO_PLIST = APP / "Info.plist"
RUNTIME_MARKER_KEY = "ShundoSpawnRuntimeVersion"
RUNTIME_VERSION = "2"
RUNTIME_BUILD_NUMBER = "4002"
FORBIDDEN_LOAD_PATH = b"@rpath/ShundoBridge.framework/ShundoBridge"


def stamp_runtime(app: Path) -> None:
    info_path = app.parent.parent / INFO_PLIST
    with info_path.open("rb") as source:
        info = plistlib.load(source)
    info[RUNTIME_MARKER_KEY] = RUNTIME_VERSION
    info["ShundoSpawnRuntimeDescription"] = "In-place spawn compatibility and notification logger"
    # InstallationProxy does not expose arbitrary Info.plist keys in its app
    # listing on every iOS release. Encode the same invariant in the standard,
    # queryable build number so the Mac app can verify the installed runtime.
    info["CFBundleVersion"] = RUNTIME_BUILD_NUMBER
    info_path.write_bytes(plistlib.dumps(info, fmt=plistlib.FMT_BINARY))


def verify_runtime(root: Path) -> None:
    app = root / APP
    binary = root / BINARY_RELATIVE_PATH
    verify_patched_binary(binary)
    if FORBIDDEN_LOAD_PATH in binary.read_bytes():
        raise RuntimeError("Refusing the failed injected-framework design")
    if (app / "Frameworks/ShundoBridge.framework").exists():
        raise RuntimeError("Refusing an IPA containing the failed helper framework")
    with (root / INFO_PLIST).open("rb") as source:
        info = plistlib.load(source)
    if info.get(RUNTIME_MARKER_KEY) != RUNTIME_VERSION:
        raise RuntimeError("Spawn runtime version marker is missing")
    if str(info.get("CFBundleVersion") or "") != RUNTIME_BUILD_NUMBER:
        raise RuntimeError("Spawn runtime build number is incorrect")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_ipa", type=Path)
    parser.add_argument("output_ipa", type=Path)
    args = parser.parse_args()
    if sha256(args.source_ipa) != EXPECTED_IPA_SHA256:
        raise RuntimeError("Source IPA hash does not match the inspected iPogo 4.3.3 build")
    if args.output_ipa.exists():
        raise RuntimeError(f"Output already exists: {args.output_ipa}")
    with tempfile.TemporaryDirectory(prefix="ipogo-spawn-runtime-") as temporary:
        root = Path(temporary)
        subprocess.run(["ditto", "-x", "-k", str(args.source_ipa), str(root)], check=True)
        binary = root / BINARY_RELATIVE_PATH
        patch_original_binary(binary)
        stamp_runtime(root / APP)
        verify_runtime(root)
        args.output_ipa.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
                str(root / "Payload"), str(args.output_ipa),
            ],
            check=True,
        )

    print(f"Created verified spawn runtime: {args.output_ipa}")
    print(f"SHA-256: {sha256(args.output_ipa)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
