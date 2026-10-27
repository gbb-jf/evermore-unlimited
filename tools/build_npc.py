#!/usr/bin/env python3
"""Build the opening-station NPC experiment from a verified US ROM."""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import zlib


SOURCE_SHA256 = "17c864a76d498feb6479eee8e7d6807b951c66225033228622bb66754baab1db"
SOURCE_SIZE = 0x300000
TARGET_SIZE = 0x400000
HOOK = 0x1BC446
SCRIPT_TABLE_SLOT = 0x129C3E  # Unreferenced short-script ID $19aa.
TEXT_TABLE_SLOT = 0x11D006  # Unused debug text ID $0006.
SPAWN_OFFSET = 0x308000
TALK_OFFSET = 0x308040
TEXT_OFFSET = 0x300000
DIALOGUE = "Looks like the experiment worked!"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def packed_script(offset):
    """Pack a HiROM file offset into the game's upper-half-bank script address."""
    if offset & 0x8000 == 0:
        raise ValueError("Scripts must be in the upper half of a ROM bank")
    address = offset + 0x800000
    relative = (address & ~0x8000) - 0x920000
    return ((relative & 0x1FF0000) >> 1) | (relative & 0x7FFF)


def packed_text(offset):
    if offset & 0x8000:
        raise ValueError("Text must be in the lower half of a ROM bank")
    return ((offset & 0xFF0000) >> 1) | (offset & 0x7FFF)


def u24(value):
    return value.to_bytes(3, "little")


def write_checked(rom, offset, expected, replacement):
    actual = bytes(rom[offset:offset + len(expected)])
    if actual != expected:
        raise ValueError(f"Unexpected original bytes at file offset 0x{offset:06x}")
    if len(expected) != len(replacement):
        raise ValueError("A checked write must preserve the allocated length")
    rom[offset:offset + len(replacement)] = replacement


def build_rom(source):
    if len(source) != SOURCE_SIZE or sha256(source) != SOURCE_SHA256:
        raise ValueError("Expected the clean, unheadered US Secret of Evermore ROM "
                         f"({SOURCE_SIZE} bytes, SHA-256 {SOURCE_SHA256}).")
    rom = bytearray(source) + bytearray(b"\xff" * (TARGET_SIZE - len(source)))
    # Call the new initializer in place of clearing $22ea bit 3. The initializer
    # executes the displaced instruction before returning to the original BD/00.
    write_checked(rom, HOOK, bytes.fromhex("0c 93 04 b0"),
                  b"\x29" + u24(packed_script(SPAWN_OFFSET)))
    write_checked(rom, SCRIPT_TABLE_SLOT, bytes.fromhex("da e0 02"),
                  u24(packed_script(TALK_OFFSET)))
    write_checked(rom, TEXT_TABLE_SLOT, bytes.fromhex("2a 00 80"),
                  u24(packed_text(TEXT_OFFSET)))
    spawn = bytes.fromhex(
        "0c 93 04 b0 "  # Original clear of $22ea bit 3.
        "ba 57 44 24 "  # Existing professor sprite, tile coordinates (68, 36).
        "2a ad "        # Disable the sprite's ordinary wandering AI.
        "75 ad "        # Face the last-created entity south.
        "3d ad aa 19 "  # Attach short talk script $19aa to that entity.
        "00"            # Return to the original script.
    )
    talk = bytes.fromhex(
        "a3 32 "        # Standard NPC interaction: freeze player, face each other.
        "a3 02 "        # Open standard dialogue window.
        "51 06 00 "     # Show our uncompressed text via debug text slot $0006.
        "55 "           # Close the dialogue window.
        "a3 33 "        # Standard interaction cleanup and restore player control.
        "2a ae "        # Cleanup restores NPC AI too; keep our test NPC stationary.
        "75 ae "        # Return to the idle south-facing pose.
        "00"
    )
    # Text controls: ordinary dialogue mode, explicit line break, wait for input.
    text = b"\x96Looks like the\x0aexperiment worked!\x86\x00"
    for offset, data in [(SPAWN_OFFSET, spawn), (TALK_OFFSET, talk), (TEXT_OFFSET, text)]:
        write_checked(rom, offset, b"\xff" * len(data), data)
    # The original size field already declares the 4 MiB address space ($0c).
    if rom[0xFFD7] != 0x0C:
        raise ValueError("Unexpected ROM size field")
    rom[0xFFDC:0xFFE0] = bytes.fromhex("ff ff 00 00")
    checksum = sum(rom) & 0xFFFF
    struct.pack_into("<HH", rom, 0xFFDC, checksum ^ 0xFFFF, checksum)
    return bytes(rom)


def bps_number(value):
    result = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if not value:
            result.append(byte | 0x80)
            return result
        result.append(byte)
        value -= 1


def create_bps(source, target):
    """Encode BPS with SourceRead, TargetRead, and RLE TargetCopy records."""
    patch = bytearray(b"BPS1")
    metadata = b"Evermore Unlimited: opening station NPC experiment v1"
    for value in (len(source), len(target), len(metadata)):
        patch.extend(bps_number(value))
    patch.extend(metadata)
    position = 0
    copy_cursor = 0
    while position < len(target):
        if position < len(source) and source[position] == target[position]:
            end = position + 1
            while end < len(source) and end < len(target) and source[end] == target[end]:
                end += 1
            patch.extend(bps_number((end - position - 1) << 2))
        else:
            repeated_end = position + 1
            while repeated_end < len(target) and target[repeated_end] == target[position]:
                repeated_end += 1
            if repeated_end - position >= 16:
                patch.extend(bps_number(1))  # One TargetRead byte.
                patch.append(target[position])
                length = repeated_end - position - 1
                patch.extend(bps_number(((length - 1) << 2) | 3))
                relative = position - copy_cursor
                patch.extend(bps_number((abs(relative) << 1) | int(relative < 0)))
                copy_cursor = position + length
                end = repeated_end
            else:
                end = position + 1
                while end < len(target):
                    if end < len(source) and target[end] == source[end]:
                        break
                    if target[end:end + 16] == target[end:end + 1] * 16:
                        break
                    end += 1
                patch.extend(bps_number(((end - position - 1) << 2) | 1))
                patch.extend(target[position:end])
        position = end
    patch.extend(struct.pack("<II", zlib.crc32(source), zlib.crc32(target)))
    patch.extend(struct.pack("<I", zlib.crc32(patch)))
    return bytes(patch)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=Path("roms/original.sfc"))
    parser.add_argument("--output-dir", type=Path, default=Path("build"))
    args = parser.parse_args()
    try:
        source = args.rom.read_bytes()
        target = build_rom(source)
        output_rom = args.output_dir / "evermore-npc.sfc"
        if output_rom.resolve() == args.rom.resolve():
            raise ValueError("Output must not overwrite the original ROM")
        patch = create_bps(source, target)
        manifest = {
            "experiment": "opening-station-npc-v1",
            "source": {"region": "USA / NTSC", "revision": "1.0", "header_bytes": 0,
                       "size": len(source), "sha256": sha256(source)},
            "target": {"size": len(target), "sha256": sha256(target),
                       "snes_checksum": f"{int.from_bytes(target[0xFFDE:0xFFE0], 'little'):04X}"},
            "patch": {"format": "BPS", "size": len(patch), "sha256": sha256(patch)},
            "npc": {"map": "0x46", "sprite": "0x57", "position_tiles": [68, 36],
                    "dialogue": DIALOGUE},
        }
        args.output_dir.mkdir(parents=True, exist_ok=True)
        output_rom.write_bytes(target)
        (args.output_dir / "evermore-npc.bps").write_bytes(patch)
        (args.output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"ROM:   {output_rom}\nPatch: {args.output_dir / 'evermore-npc.bps'}")
        print(f"SHA-256: {sha256(target)}")
    except (OSError, ValueError) as error:
        parser.exit(1, f"Build failed: {error}\n")


if __name__ == "__main__":
    main()
