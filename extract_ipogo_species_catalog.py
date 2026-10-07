#!/usr/bin/env python3
"""Reconstruct iPogo's Pokémon-ID/name table from its own Swift initializer.

The initializer builds a flat array of 1,008 ``(String, String)`` pairs before
turning it into the dictionary used by the feed model's ``title`` property.
It is straight-line ARM64 code, so this tool emulates only the small set of
integer and memory instructions used while that array is populated.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess


START = 0x1CB59C
END = 0x1D4724
ENTRY_COUNT = 1008
BASE = 0x100000000
STACK = 0x200000000
LINE_RE = re.compile(
    r"^\s*([0-9a-f]+):\s+[0-9a-f]{8}\s+([a-z]+)\s+(.+?)(?:\s+;.*)?$"
)
MEMORY_RE = re.compile(r"\[(x\d+|sp)(?:,\s*#(-?0x[0-9a-f]+|-?\d+))?\]")


def _immediate(value: str) -> int:
    token = value.strip().removeprefix("#").split()[0]
    return int(token, 0)


class Emulator:
    def __init__(self) -> None:
        self.registers = {f"x{index}": 0 for index in range(31)}
        self.registers.update({"x0": BASE, "sp": STACK, "x29": STACK + 0x110})
        self.memory: dict[int, int] = {}

    def read_register(self, name: str) -> int:
        if name in ("xzr", "wzr"):
            return 0
        if name.startswith("w"):
            return self.registers[f"x{name[1:]}"] & 0xFFFFFFFF
        return self.registers[name] & 0xFFFFFFFFFFFFFFFF

    def write_register(self, name: str, value: int) -> None:
        if name in ("xzr", "wzr"):
            return
        mask = 0xFFFFFFFF if name.startswith("w") else 0xFFFFFFFFFFFFFFFF
        target = f"x{name[1:]}" if name.startswith("w") else name
        self.registers[target] = value & mask

    def address(self, operand: str) -> int:
        match = MEMORY_RE.fullmatch(operand.strip())
        if not match:
            raise RuntimeError(f"Unsupported memory operand: {operand}")
        return self.read_register(match.group(1)) + int(match.group(2) or "0", 0)

    def store(self, address: int, value: int, size: int = 8) -> None:
        for index in range(size):
            self.memory[address + index] = (value >> (index * 8)) & 0xFF

    def load(self, address: int, size: int = 8) -> int:
        return sum(self.memory.get(address + index, 0) << (index * 8) for index in range(size))

    def execute(self, mnemonic: str, operand_text: str) -> None:
        operands = [item.strip() for item in operand_text.split(",")]
        if mnemonic == "mov":
            destination, source = operands
            value = _immediate(source) if source.startswith("#") else self.read_register(source)
            self.write_register(destination, value)
        elif mnemonic == "movk":
            destination = operands[0]
            shift = _immediate(operands[2].removeprefix("lsl ")) if len(operands) == 3 else 0
            mask = 0xFFFF << shift
            value = (self.read_register(destination) & ~mask) | ((_immediate(operands[1]) & 0xFFFF) << shift)
            self.write_register(destination, value)
        elif mnemonic in ("add", "sub"):
            destination, source = operands[:2]
            value = _immediate(operands[2])
            if len(operands) == 4:
                value <<= _immediate(operands[3].removeprefix("lsl "))
            base = self.read_register(source)
            self.write_register(destination, base + value if mnemonic == "add" else base - value)
        elif mnemonic == "orr":
            destination, left, right = operands
            value = _immediate(right) if right.startswith("#") else self.read_register(right)
            self.write_register(destination, self.read_register(left) | value)
        elif mnemonic in ("str", "stur"):
            source = operands[0]
            if source == "q0":
                return  # Array header; not part of the key/value records.
            self.store(self.address(",".join(operands[1:])), self.read_register(source))
        elif mnemonic == "stp":
            first, second = operands[:2]
            address = self.address(",".join(operands[2:]))
            self.store(address, self.read_register(first))
            self.store(address + 8, self.read_register(second))
        elif mnemonic in ("ldr", "ldur"):
            destination = operands[0]
            if destination == "q0":
                return
            self.write_register(
                destination,
                self.load(self.address(",".join(operands[1:]))),
            )
        elif mnemonic == "ldp":
            first, second = operands[:2]
            address = self.address(",".join(operands[2:]))
            self.write_register(first, self.load(address))
            self.write_register(second, self.load(address + 8))
        elif mnemonic == "adrp":
            self.write_register(operands[0], _immediate(operands[1]))
        else:
            raise RuntimeError(f"Unsupported initializer instruction: {mnemonic} {operand_text}")

    def swift_string(self, address: int) -> str:
        raw = bytes(self.memory.get(address + index, 0) for index in range(16))
        length = raw[15] & 0x0F
        # Swift uses 0xE? for small ASCII and 0xA? for small UTF-8. The low
        # nibble is the byte count in both representations.
        if raw[15] >> 4 not in (0xA, 0xE) or length > 15:
            raise RuntimeError(f"Unsupported non-small Swift.String at 0x{address:x}: {raw.hex()}")
        return raw[:length].decode("utf-8")


def extract(binary: Path) -> dict[str, str]:
    command = [
        "xcrun", "llvm-objdump", "-d", "--arch=arm64",
        f"--start-address=0x{START:x}", f"--stop-address=0x{END:x}",
        str(binary.resolve()),
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    emulator = Emulator()
    executed = 0
    for line in result.stdout.splitlines():
        match = LINE_RE.match(line)
        if not match:
            continue
        address = int(match.group(1), 16)
        if not START <= address < END:
            continue
        emulator.execute(match.group(2), match.group(3))
        executed += 1
    if executed < 5000:
        raise RuntimeError(f"Initializer disassembly was unexpectedly short: {executed} instructions")

    catalog: dict[str, str] = {}
    for index in range(ENTRY_COUNT):
        entry = BASE + 0x20 + index * 0x20
        key = emulator.swift_string(entry)
        name = emulator.swift_string(entry + 0x10)
        expected = str(index + 1)
        if key != expected or not name:
            raise RuntimeError(
                f"Catalog record {index} is invalid: expected key {expected!r}, got {key!r}/{name!r}"
            )
        catalog[key] = name
    return catalog


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("fbl_promises", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    catalog = extract(args.fbl_promises)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Extracted {len(catalog)} iPogo species names to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
