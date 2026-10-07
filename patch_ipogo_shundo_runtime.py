#!/usr/bin/env python3
"""Build the in-place iPogo runtime used by Shundo Hunter.

The patch keeps the known spawn-compatible simulated-source mask, installs it
during framework initialization, and logs the exact local-notification body for
the Mac watcher. It adds no dylib or Mach-O load command.
"""

from __future__ import annotations

import argparse
import struct
import subprocess
import tempfile
from pathlib import Path

from patch_ipogo_simulated_flag import (
    BINARY_RELATIVE_PATH,
    CLASS_STRING_OFFSET,
    EXPECTED_BINARY_SHA256,
    EXPECTED_CLASS_STORAGE,
    EXPECTED_FALSE_IMPLEMENTATION,
    EXPECTED_HOOK,
    EXPECTED_IPA_SHA256,
    EXPECTED_SELECTOR_REFERENCE,
    EXPECTED_SELECTOR_STORAGE,
    FALSE_IMPLEMENTATION_OFFSET,
    HOOK_OFFSET,
    PATCHED_CLASS_STRING,
    PATCHED_HOOK,
    PATCHED_SELECTOR_REFERENCE,
    PATCHED_SELECTOR_STRING,
    SELECTOR_REFERENCE_OFFSET,
    SELECTOR_STRING_OFFSET,
    replace_exact,
    sha256,
)


STARTUP_CAVE_OFFSET = 0x139E74
STARTUP_CAVE_EXPECTED = bytes.fromhex("200020d4" * 17)
STARTUP_WRAPPER = bytes.fromhex(
    "fd7bbfa9fd030091203700d000802091af321b94000100b4486000f0016140f9"
    "8b311b94800000b4a1ffffb0210000917a321b94fd7bc1a8507d1714"
)
MOD_INIT_POINTER_OFFSET = 0xB9ECD8
EXPECTED_MOD_INIT_POINTER = struct.pack("<Q", 0x7193EC)
PATCHED_MOD_INIT_POINTER = struct.pack("<Q", STARTUP_CAVE_OFFSET)

NOTIFICATION_CALL_OFFSET = 0x2574DC
EXPECTED_NOTIFICATION_CALL = bytes.fromhex("28bd1694")
PATCHED_NOTIFICATION_CALL = bytes.fromhex("8e741094")
NOTIFICATION_CAVE_OFFSET = 0x674714
NOTIFICATION_CAVE_EXPECTED = bytes.fromhex("200020d4" * 47)
NOTIFICATION_WRAPPER = bytes.fromhex(
    "ffc300d1fd7b02a9fd830091e00701a9e20f00a90000009000601d9184480694"
    "0200009042a01d91f47b069452460694e00741a9e20f40a9fd7b42a9ffc30091"
    "8a480614"
    "4e53537472696e670000000000000000"
    "5348554e444f5f48554e5445525f4e4f54494649434154494f4e207469746c65"
    "3d3c656d7074793e20626f64793d254000"
)


def patch_original_binary(binary: Path) -> None:
    if sha256(binary) != EXPECTED_BINARY_SHA256:
        raise RuntimeError("Injected framework hash does not match the inspected iPogo 4.3.3 build")
    data = bytearray(binary.read_bytes())

    replace_exact(data, HOOK_OFFSET, EXPECTED_HOOK, PATCHED_HOOK)
    replace_exact(data, CLASS_STRING_OFFSET, EXPECTED_CLASS_STORAGE, PATCHED_CLASS_STRING)
    replace_exact(data, SELECTOR_STRING_OFFSET, EXPECTED_SELECTOR_STORAGE, PATCHED_SELECTOR_STRING)
    replace_exact(data, SELECTOR_REFERENCE_OFFSET, EXPECTED_SELECTOR_REFERENCE, PATCHED_SELECTOR_REFERENCE)
    if data[FALSE_IMPLEMENTATION_OFFSET:FALSE_IMPLEMENTATION_OFFSET + 8] != EXPECTED_FALSE_IMPLEMENTATION:
        raise RuntimeError("Existing false-return implementation is not the expected code")

    replace_exact(data, STARTUP_CAVE_OFFSET, STARTUP_CAVE_EXPECTED, STARTUP_WRAPPER)
    replace_exact(
        data,
        MOD_INIT_POINTER_OFFSET,
        EXPECTED_MOD_INIT_POINTER,
        PATCHED_MOD_INIT_POINTER,
    )
    replace_exact(
        data,
        NOTIFICATION_CALL_OFFSET,
        EXPECTED_NOTIFICATION_CALL,
        PATCHED_NOTIFICATION_CALL,
    )
    replace_exact(
        data,
        NOTIFICATION_CAVE_OFFSET,
        NOTIFICATION_CAVE_EXPECTED,
        NOTIFICATION_WRAPPER,
    )
    binary.write_bytes(data)
    verify_patched_binary(binary)


def verify_patched_binary(binary: Path) -> None:
    data = binary.read_bytes()
    checks = (
        (HOOK_OFFSET, PATCHED_HOOK, "simulated-source hook"),
        (CLASS_STRING_OFFSET, PATCHED_CLASS_STRING, "Core Location class string"),
        (SELECTOR_STRING_OFFSET, PATCHED_SELECTOR_STRING, "Core Location selector string"),
        (SELECTOR_REFERENCE_OFFSET, PATCHED_SELECTOR_REFERENCE, "selector reference"),
        (STARTUP_CAVE_OFFSET, STARTUP_WRAPPER, "startup wrapper"),
        (MOD_INIT_POINTER_OFFSET, PATCHED_MOD_INIT_POINTER, "initializer pointer"),
        (NOTIFICATION_CALL_OFFSET, PATCHED_NOTIFICATION_CALL, "notification branch"),
        (NOTIFICATION_CAVE_OFFSET, NOTIFICATION_WRAPPER, "notification logger"),
    )
    for offset, expected, label in checks:
        if data[offset:offset + len(expected)] != expected:
            raise RuntimeError(f"Patched {label} verification failed at 0x{offset:x}")
    if data[STARTUP_CAVE_OFFSET + len(STARTUP_WRAPPER):STARTUP_CAVE_OFFSET + 68] != STARTUP_CAVE_EXPECTED[len(STARTUP_WRAPPER):]:
        raise RuntimeError("Startup cave boundary was not preserved")
    actual_tail = data[
        NOTIFICATION_CAVE_OFFSET + len(NOTIFICATION_WRAPPER):NOTIFICATION_CAVE_OFFSET + 188
    ]
    if actual_tail != NOTIFICATION_CAVE_EXPECTED[len(NOTIFICATION_WRAPPER):]:
        raise RuntimeError("Notification cave boundary was not preserved")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_ipa", type=Path)
    parser.add_argument("output_ipa", type=Path)
    args = parser.parse_args()
    if sha256(args.source_ipa) != EXPECTED_IPA_SHA256:
        raise RuntimeError("Source IPA hash does not match the inspected iPogo 4.3.3 build")
    if args.output_ipa.exists():
        raise RuntimeError(f"Output already exists: {args.output_ipa}")

    with tempfile.TemporaryDirectory(prefix="ipogo-shundo-runtime-") as temporary:
        root = Path(temporary)
        subprocess.run(["ditto", "-x", "-k", str(args.source_ipa), str(root)], check=True)
        patch_original_binary(root / BINARY_RELATIVE_PATH)
        args.output_ipa.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
                str(root / "Payload"), str(args.output_ipa),
            ],
            check=True,
        )
    print(f"Created unsigned Shundo runtime: {args.output_ipa}")
    print(f"SHA-256: {sha256(args.output_ipa)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
