#!/usr/bin/env python3
"""Patch iPogo 4.3.3 so CLLocationSourceInformation reports non-simulated.

The original IPA is never modified. The script verifies the complete IPA and
framework hashes plus every original byte before producing an unsigned copy.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path


EXPECTED_IPA_SHA256 = "5ff1c7ba5ac79143692823326872714d10a0d7ac3cc033df40a3c88d41382cfb"
EXPECTED_BINARY_SHA256 = "9e3ec66f2bc9a92d68548eb20f8259eac2b80c166957756160362021ce6ea2cf"
BINARY_RELATIVE_PATH = Path("Payload/PokmonGO.app/Frameworks/FBLPromises.framework/FBLPromises")

HOOK_OFFSET = 0x130224
CLASS_STRING_OFFSET = 0x81F820
SELECTOR_STRING_OFFSET = 0x821390
SELECTOR_REFERENCE_OFFSET = 0xD440C0
FALSE_IMPLEMENTATION_OFFSET = 0x12E000
OBSOLETE_SOURCE_NIL_OFFSET = 0x132C3C

EXPECTED_HOOK = bytes.fromhex(
    "8860009001c946f9a8600090156140f9e00313aaa2581b94200100b4f40300aa"
    "e00313aae10315aa9d581b94800000b4e10300aae00314aa89591b94"
)
PATCHED_HOOK = bytes.fromhex(
    "f40313aa603700f000802091c4591b94a8600090016140f9a1581b94e1ffffd0"
    "2100009191591b94f30314aa1f2003d51f2003d51f2003d51f2003d5"
)
EXPECTED_CLASS_STORAGE = b"Coordinates imported successfully.\x00"
PATCHED_CLASS_STRING = b"CLLocationSourceInformation\x00"
EXPECTED_SELECTOR_STORAGE = b"Enter Speed in km/h (ex. 9)\x00"
PATCHED_SELECTOR_STRING = b"isSimulatedBySoftware\x00"
EXPECTED_SELECTOR_REFERENCE = struct.pack("<Q", 0xACB236)
PATCHED_SELECTOR_REFERENCE = struct.pack("<Q", SELECTOR_STRING_OFFSET)
EXPECTED_FALSE_IMPLEMENTATION = bytes.fromhex("00008052c0035fd6")
EXPECTED_SOURCE_INFORMATION_PROLOGUE = bytes.fromhex("fd7bbfa9fd030091")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def replace_exact(blob: bytearray, offset: int, expected: bytes, replacement: bytes) -> None:
    actual = bytes(blob[offset : offset + len(expected)])
    if actual != expected:
        raise RuntimeError(
            f"Refusing patch at 0x{offset:x}: expected {expected.hex()}, found {actual.hex()}"
        )
    if len(replacement) > len(expected):
        raise RuntimeError("Replacement is larger than its verified storage")
    blob[offset : offset + len(replacement)] = replacement


def verify_patched_binary(path: Path) -> None:
    data = path.read_bytes()
    checks = (
        (HOOK_OFFSET, PATCHED_HOOK),
        (CLASS_STRING_OFFSET, PATCHED_CLASS_STRING),
        (SELECTOR_STRING_OFFSET, PATCHED_SELECTOR_STRING),
        (SELECTOR_REFERENCE_OFFSET, PATCHED_SELECTOR_REFERENCE),
        (FALSE_IMPLEMENTATION_OFFSET, EXPECTED_FALSE_IMPLEMENTATION),
        # The older sourceInformation=nil experiment moved the avatar but did
        # not load Pokémon, stops, or gyms. Never accept a layered IPA that
        # still contains that obsolete return-nil implementation.
        (OBSOLETE_SOURCE_NIL_OFFSET, EXPECTED_SOURCE_INFORMATION_PROLOGUE),
    )
    for offset, expected in checks:
        if data[offset : offset + len(expected)] != expected:
            raise RuntimeError(f"Patched binary verification failed at 0x{offset:x}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_ipa", type=Path)
    parser.add_argument("output_ipa", type=Path)
    args = parser.parse_args()

    if sha256(args.source_ipa) != EXPECTED_IPA_SHA256:
        raise RuntimeError("Source IPA hash does not match the inspected iPogo 4.3.3 build")
    if args.output_ipa.exists():
        raise RuntimeError(f"Output already exists: {args.output_ipa}")

    with tempfile.TemporaryDirectory(prefix="ipogo-simulated-flag-") as temporary:
        root = Path(temporary)
        subprocess.run(["ditto", "-x", "-k", str(args.source_ipa), str(root)], check=True)
        binary = root / BINARY_RELATIVE_PATH
        if sha256(binary) != EXPECTED_BINARY_SHA256:
            raise RuntimeError("Injected framework hash does not match the inspected build")

        data = bytearray(binary.read_bytes())
        replace_exact(data, HOOK_OFFSET, EXPECTED_HOOK, PATCHED_HOOK)
        replace_exact(data, CLASS_STRING_OFFSET, EXPECTED_CLASS_STORAGE, PATCHED_CLASS_STRING)
        replace_exact(data, SELECTOR_STRING_OFFSET, EXPECTED_SELECTOR_STORAGE, PATCHED_SELECTOR_STRING)
        replace_exact(data, SELECTOR_REFERENCE_OFFSET, EXPECTED_SELECTOR_REFERENCE, PATCHED_SELECTOR_REFERENCE)
        if data[FALSE_IMPLEMENTATION_OFFSET : FALSE_IMPLEMENTATION_OFFSET + 8] != EXPECTED_FALSE_IMPLEMENTATION:
            raise RuntimeError("Existing false-return implementation is not the expected code")
        binary.write_bytes(data)
        verify_patched_binary(binary)

        args.output_ipa.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(root / "Payload"), str(args.output_ipa)],
            check=True,
        )

    print(f"Created: {args.output_ipa}")
    print(f"SHA-256: {sha256(args.output_ipa)}")
    print("The output is intentionally unsigned and must be signed before installation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
