#!/usr/bin/env python3
"""Offline guardrails for iPogo Hunter Lab experiments.

This module deliberately does not install, launch, or communicate with an
iPhone.  It accepts only the empirically verified spawn-compatible IPA and
checks the byte-level invariants that previously distinguished a working world
from the avatar-only/no-spawns failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import plistlib
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path


GOLD_IPA_SHA256 = "5f49228a0cdd64ddd378b2d4443311a60d7d9dc46ca03a27b4ee9f6198d4d9bf"
GOLD_FBL_SHA256 = "a970779c54893e7fcd12b68583cee9d7c97ab8a3ebec6b49c9f8c521daf3c572"

APP = Path("Payload/PokmonGO.app")
INFO_PLIST = APP / "Info.plist"
FBL = APP / "Frameworks/FBLPromises.framework/FBLPromises"

FORBIDDEN_MEMBERS = (
    "Payload/PokmonGO.app/Frameworks/ShundoBridge.framework/",
)
FORBIDDEN_LOAD_PATH = b"@rpath/ShundoBridge.framework/ShundoBridge"
FAILED_NIL_SOURCE_PATCH = bytes.fromhex("000080d2c0035fd6")


@dataclass(frozen=True)
class SliceInvariant:
    offset: int
    expected: bytes
    label: str


INVARIANTS = (
    SliceInvariant(
        0x130224,
        bytes.fromhex(
            "f40313aa603700f000802091c4591b94a8600090016140f9a1581b94"
            "e1ffffd02100009191591b94f30314aa1f2003d51f2003d51f2003d5"
            "1f2003d5"
        ),
        "simulated-source mask wrapper",
    ),
    SliceInvariant(0x12E000, bytes.fromhex("00008052c0035fd6"), "false getter"),
    SliceInvariant(
        0x132C3C,
        bytes.fromhex("fd7bbfa9fd030091"),
        "original sourceInformation prologue",
    ),
    SliceInvariant(
        0x139E74,
        bytes.fromhex(
            "fd7bbfa9fd030091203700d000802091af321b94000100b4486000f001"
            "6140f98b311b94800000b4a1ffffb0210000917a321b94fd7bc1a850"
            "7d1714"
        ),
        "early startup wrapper",
    ),
    SliceInvariant(0xB9ECD8, bytes.fromhex("749e130000000000"), "startup initializer pointer"),
    SliceInvariant(0x2574DC, bytes.fromhex("8e741094"), "proven notification logger branch"),
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_member(archive: zipfile.ZipFile, relative: Path) -> bytes:
    try:
        return archive.read(relative.as_posix())
    except KeyError as error:
        raise RuntimeError(f"IPA is missing {relative.as_posix()}") from error


def verify_fbl(binary: bytes, *, require_gold_hash: bool = True) -> dict[str, object]:
    binary_hash = sha256_bytes(binary)
    if require_gold_hash and binary_hash != GOLD_FBL_SHA256:
        raise RuntimeError(
            "FBLPromises is not the empirical-gold binary: "
            f"expected {GOLD_FBL_SHA256}, got {binary_hash}"
        )
    if FORBIDDEN_LOAD_PATH in binary:
        raise RuntimeError("Rejected legacy ShundoBridge load command")
    if binary[0x132C3C:0x132C44] == FAILED_NIL_SOURCE_PATCH:
        raise RuntimeError("Rejected failed sourceInformation=nil patch")

    verified: list[dict[str, object]] = []
    for invariant in INVARIANTS:
        actual = binary[invariant.offset:invariant.offset + len(invariant.expected)]
        lab_initializer_redirect = (
            not require_gold_hash
            and invariant.offset == 0xB9ECD8
            and len(actual) == 8
            and 0xB9A000 <= struct.unpack("<Q", actual)[0] < 0xB9A800
        )
        if actual != invariant.expected and not lab_initializer_redirect:
            raise RuntimeError(
                f"{invariant.label} differs at 0x{invariant.offset:x}: "
                f"expected {invariant.expected.hex()}, got {actual.hex()}"
            )
        verified.append(
            {
                "label": invariant.label,
                "offset": f"0x{invariant.offset:x}",
                "sha256": sha256_bytes(actual),
                "length": len(actual),
                "labRedirect": lab_initializer_redirect,
            }
        )
    return {"sha256": binary_hash, "size": len(binary), "invariants": verified}


def macho_code_signature_range(binary: bytes) -> tuple[int, int]:
    if len(binary) < 32 or struct.unpack_from("<I", binary, 0)[0] != 0xFEEDFACF:
        raise RuntimeError("Expected a 64-bit little-endian Mach-O")
    command_count = struct.unpack_from("<I", binary, 16)[0]
    offset = 32
    for _ in range(command_count):
        command, command_size = struct.unpack_from("<II", binary, offset)
        if command_size < 8 or offset + command_size > len(binary):
            raise RuntimeError("Malformed Mach-O load command")
        if command == 0x1D:  # LC_CODE_SIGNATURE
            data_offset, data_size = struct.unpack_from("<II", binary, offset + 8)
            if data_offset + data_size > len(binary):
                raise RuntimeError("Code signature extends beyond the Mach-O")
            return data_offset, data_size
        offset += command_size
    raise RuntimeError("Mach-O has no LC_CODE_SIGNATURE")


def verify_resigned_fbl(gold: bytes, resigned: bytes) -> dict[str, object]:
    # The unsigned input may itself be a verified Lab derivative of the
    # empirical gold. Its runtime invariants must hold, but its whole-file hash
    # is intentionally different because of the read-only probe.
    gold_report = verify_fbl(gold, require_gold_hash=False)
    resigned_report = verify_fbl(resigned, require_gold_hash=False)
    gold_signature = macho_code_signature_range(gold)
    resigned_signature = macho_code_signature_range(resigned)
    signature_start = min(gold_signature[0], resigned_signature[0])
    if gold[:signature_start] != resigned[:signature_start]:
        raise RuntimeError("Re-signing changed FBLPromises outside its code signature")
    differing = [index for index, pair in enumerate(zip(gold, resigned)) if pair[0] != pair[1]]
    if len(gold) != len(resigned):
        raise RuntimeError("Re-signing changed the FBLPromises file size")
    if any(index < signature_start for index in differing):
        raise RuntimeError("FBLPromises has a non-signature byte difference")
    return {
        "goldSha256": gold_report["sha256"],
        "signedSha256": resigned_report["sha256"],
        "fileSize": len(resigned),
        "signatureOffset": signature_start,
        "signatureOnlyDifferenceCount": len(differing),
        "runtimeBytesIdentical": True,
        "invariants": resigned_report["invariants"],
    }


def verify_gold_ipa(path: Path) -> dict[str, object]:
    path = path.resolve()
    if not path.is_file():
        raise RuntimeError(f"IPA does not exist: {path}")
    ipa_hash = sha256_file(path)
    if ipa_hash != GOLD_IPA_SHA256:
        raise RuntimeError(
            "Hunter Lab accepts only the empirical-gold IPA: "
            f"expected {GOLD_IPA_SHA256}, got {ipa_hash}"
        )

    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        for prefix in FORBIDDEN_MEMBERS:
            if any(name.startswith(prefix) for name in names):
                raise RuntimeError(f"Rejected forbidden IPA member: {prefix}")
        info = plistlib.loads(_read_member(archive, INFO_PLIST))
        binary = _read_member(archive, FBL)

    fbl_report = verify_fbl(binary)
    return {
        "schema": 1,
        "status": "verified-gold-base",
        "ipa": str(path),
        "ipaSha256": ipa_hash,
        "bundleIdentifier": info.get("CFBundleIdentifier"),
        "bundleVersion": str(info.get("CFBundleVersion") or ""),
        "fblPromises": fbl_report,
        "forbiddenFrameworkPresent": False,
    }


def write_report(report: dict[str, object], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the immutable Hunter Lab base IPA")
    parser.add_argument("ipa", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = verify_gold_ipa(args.ipa)
    if args.report:
        write_report(report, args.report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
