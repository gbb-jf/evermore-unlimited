#!/usr/bin/env python3
"""Build the opening-station NPC experiment from a verified US ROM."""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import zlib

from character_model import Store, ROOT, revision, canonical
from character_rom import install, TALK_OFFSET, SPAWN_OFFSET, TEXT_OFFSET


SOURCE_SHA256 = "17c864a76d498feb6479eee8e7d6807b951c66225033228622bb66754baab1db"
SOURCE_SIZE = 0x300000
TARGET_SIZE = 0x400000
HOOK = 0x1BC446
SCRIPT_TABLE_SLOT = 0x129C3E  # Unreferenced short-script ID $19aa.
TEXT_TABLE_SLOT = 0x11D006  # Unused debug text ID $0006.
SPAWN_OFFSET = 0x308000
TALK_OFFSET = 0x308400
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


def compile_rom(source, scene=None, characters=None, *, gamemaster=False):
    if len(source) != SOURCE_SIZE or sha256(source) != SOURCE_SHA256:
        raise ValueError("Expected the clean, unheadered US Secret of Evermore ROM "
                         f"({SOURCE_SIZE} bytes, SHA-256 {SOURCE_SHA256}).")
    if scene is None:
        scene, characters = Store().project()
    rom = bytearray(source) + bytearray(b"\xff" * (TARGET_SIZE - len(source)))
    layout = install(rom, scene, characters, write_checked, packed_script, packed_text)
    if gamemaster:
        from gamemaster_rom import install as install_gamemaster
        install_gamemaster(rom, source, layout, write_checked, packed_script, packed_text)
    rom[0xFFDC:0xFFE0] = bytes.fromhex("ff ff 00 00")
    checksum = sum(rom) & 0xFFFF
    struct.pack_into("<HH", rom, 0xFFDC, checksum ^ 0xFFFF, checksum)
    return bytes(rom), layout


def build_rom(source, scene=None, characters=None):
    return compile_rom(source, scene, characters)[0]


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
    metadata = b"Evermore Unlimited: character editor NPC scene v3"
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


def build_project(root=ROOT, output_dir=None, source_path=None, *, gamemaster=False):
    from character_model import export_sheet
    root = Path(root).resolve()
    output_dir = Path(output_dir or root / "build").resolve()
    source_path = Path(source_path or root / "roms/original.sfc").resolve()
    output_rom = output_dir / "evermore-npc.sfc"
    if output_rom.resolve() == source_path.resolve():
        raise ValueError("Output must not overwrite the original ROM")
    scene, characters = Store(root).project()
    source = source_path.read_bytes()
    target, layout = compile_rom(source, scene, characters, gamemaster=gamemaster)
    patch = create_bps(source, target)
    manifest = {
        "experiment": "opening-gamemaster-v1" if gamemaster else "character-editor-v3",
        "source": {"region": "USA / NTSC", "revision": "1.0", "header_bytes": 0,
                   "size": len(source), "sha256": sha256(source)},
        "target": {"size": len(target), "sha256": sha256(target),
                   "snes_checksum": f"{int.from_bytes(target[0xFFDE:0xFFE0], 'little'):04X}"},
        "patch": {"format": "BPS", "size": len(patch), "sha256": sha256(patch)},
        "documents": {"scene": revision(canonical(scene)),
                      "characters": {key: revision(canonical(value)) for key, value in characters.items()}},
        **layout,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    output_rom.write_bytes(target)
    (output_dir / "evermore-npc.bps").write_bytes(patch)
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    for ident, character in characters.items():
        for mode in ("idle", "walk"):
            (output_dir / f"{ident}-{mode}.png").write_bytes(export_sheet(character, mode))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=Path("roms/original.sfc"))
    parser.add_argument("--output-dir", type=Path, default=Path("build"))
    parser.add_argument("--gamemaster", action="store_true", help="Build the opening AI gamemaster experiment")
    args = parser.parse_args()
    try:
        manifest = build_project(output_dir=args.output_dir, source_path=args.rom, gamemaster=args.gamemaster)
        print(f"ROM:   {args.output_dir / 'evermore-npc.sfc'}")
        print(f"Patch: {args.output_dir / 'evermore-npc.bps'}")
        print(f"SHA-256: {manifest['target']['sha256']}")
    except (OSError, ValueError) as error:
        parser.exit(1, f"Build failed: {error}\n")


if __name__ == "__main__":
    main()
