"""Independent SNES graphics and narrowly scoped native hooks for the test NPC.

Artwork is original indexed pixel data in assets/cowboy.json. No extracted game
art is stored in the repository. Addresses are file offsets in the clean US ROM.
"""

import json
from pathlib import Path
import struct


ASSET = Path(__file__).resolve().parents[1] / "assets" / "cowboy.json"
FRAME_OFFSET = 0x310000
SEQUENCE_OFFSET = 0x318000
TILE_TABLE_OFFSET = 0x320000
TILES_OFFSET = 0x330000
CODE_OFFSET = 0x340000
PALETTE_OFFSET = 0x34FF00
PALETTE_ID = 0xFF00
FIRST_BLOCK = 0x1800
ANIMATION_HOOK = 0x108124
PALETTE_HOOK = 0x10CF3A
PALETTE_BANK_HOOK = 0x10CFD2
TILE_HOOKS = (0x9745, 0x9754, 0xA2E9)
FACING_ORDER = ("north", "east", "south", "west")


def u16(value):
    return struct.pack("<H", value & 0xFFFF)


def u24(value):
    return value.to_bytes(3, "little")


class Code:
    """Tiny label/fixup helper; instructions remain explicit 65816 machine code."""

    def __init__(self):
        self.data = bytearray()
        self.labels = {}
        self.branches = []

    def emit(self, hex_bytes):
        self.data.extend(bytes.fromhex(hex_bytes))

    def label(self, name):
        self.labels[name] = len(self.data)

    def branch(self, opcode, label):
        self.data.extend((opcode, 0))
        self.branches.append((len(self.data) - 1, label))

    def finish(self):
        for offset, label in self.branches:
            delta = self.labels[label] - offset - 1
            if not -128 <= delta <= 127:
                raise ValueError("Native branch exceeds signed byte range")
            self.data[offset] = delta & 255
        return bytes(self.data)


def load_art():
    data = json.loads(ASSET.read_text())
    if len(data["palette"]) != 16 or data["palette"][0] != "transparent":
        raise ValueError("Cowboy requires 16 palette entries, with transparent index 0")
    frames = {}
    for name in FACING_ORDER:
        rows = data["frames"][name]
        if len(rows) != 32 or any(len(row) != 32 for row in rows):
            raise ValueError(f"{name}: expected a 32 by 32 indexed frame")
        if any(c not in ".123456789abcdef" for row in rows for c in row):
            raise ValueError(f"{name}: invalid palette index")
        frames[name] = [[0 if c == "." else int(c, 16) for c in row] for row in rows]
    colors = [0]
    for color in data["palette"][1:]:
        r, g, b = bytes.fromhex(color.removeprefix("#"))
        colors.append((r >> 3) | ((g >> 3) << 5) | ((b >> 3) << 10))
    return frames, b"".join(u16(color) for color in colors)


def encode_block(pixels):
    """Encode a 16x16 block as four standard SNES 4bpp 8x8 tiles."""
    data = bytearray(128)
    for y in range(16):
        for x in range(16):
            value = pixels[y][x]
            tile = x // 8 + 2 * (y // 8)
            for plane in range(4):
                if value & (1 << plane):
                    at = tile * 32 + (y % 8) * 2 + (plane % 2) + (plane // 2) * 16
                    data[at] |= 1 << (7 - x % 8)
    return bytes(data)


def animation_code():
    code = Code()
    # Entry: native mode, M/X=16, DB=$7e, Y=actor, X=animation-table offset.
    # Preserve carry on the vanilla path; the displaced lookup did not change it.
    code.emit("08 48 b9 66 00 c9 aa 19")  # PHP/PHA; actor.talk == $19aa?
    code.branch(0xD0, "vanilla")
    code.emit("b9 68 00 c9 40 00")       # Interaction type must be talk.
    code.branch(0xD0, "vanilla")
    code.emit("b9 60 00 c9 52 c2")       # Original professor actor definition.
    code.branch(0xD0, "vanilla")
    code.emit("68 28")                  # Restore original A/P.
    code.emit("da 5a a9 00 ff 22 5c cd 90 7a fa")  # Allocate a private palette.
    code.emit("b9 22 00 29 0e 00 aa")   # Native facing is an even value 0..14.
    code.emit("bf 00 02 f4 99 06 00")   # Private frame address, by direction.
    code.emit("a9 f1 00 99 08 00")      # Private frame bank; zero render flags.
    code.emit("a9 00 80 99 00 00 99 03 00")  # Private idle loop and loop origin.
    code.emit("7b 99 0e 00 e2 20")      # Reset animation bookkeeping; M=8.
    code.emit("a9 f1 99 02 00 a9 01 99 05 00 c2 20 6b")
    code.label("vanilla")
    code.emit("68 28 bf 02 00 c4 5c 28 81 90")  # Displaced LDA; resume original.
    return code.finish()


def palette_code():
    code = Code()
    code.emit("08 c9 00 ff")  # PHP; A is the requested palette address.
    code.branch(0xF0, "cowboy")
    # PHK must still select the original $90 bank, not this relocated $f4 bank.
    code.emit("28 8b f4 90 90 ab ab 5a 5c 3e cf 90")
    code.label("cowboy")
    code.emit("28 5a da 8a 0a 0a 0a 0a aa")  # Save Y/X, index the palette buffer.
    for i in range(1, 16):
        code.data.extend(b"\xaf" + u24(0xC00000 + PALETTE_OFFSET + i * 2))
        code.data.extend(b"\x9f" + u24(0x7E6287 + i * 2))
    code.emit("fa a9 00 ff 22 b8 cf 90 7a 6b")  # Native upload / fade setup.
    return code.finish()


def palette_bank_code():
    code = Code()
    # Native upload can select a color subrange, so test the whole palette span.
    code.emit("08 a5 26 29 e0 ff c9 00 ff")
    code.branch(0xD0, "vanilla")
    code.emit("28 a9 f4 00 85 28 6b")
    code.label("vanilla")
    code.emit("28 a9 90 00 85 28 6b")
    return code.finish()


def install(rom, write_checked):
    frames, palette = load_art()

    def allocate(offset, data):
        write_checked(rom, offset, b"\xff" * len(data), data)

    # Clone the graphics-pointer bank. Existing indices retain their exact source
    # pointers; private block IDs are installed only in the relocated copy.
    table = bytearray(rom[0x2C0000:0x2D0000])
    blocks = bytearray()
    descriptors = bytearray()
    original_frames = (0xE587D, 0xE58BA, 0xE58DE, 0xE5907)
    for frame_number, name in enumerate(FACING_ORDER):
        # Keep each facing's original bounds so collision / talk range stays
        # independent of the artwork's padded 32x32 tile canvas.
        original = original_frames[frame_number]
        descriptors.extend(bytes((4, 6)) + bytes(rom[original + 2:original + 6]))
        for chunk, (x, y) in enumerate(((0, 0), (16, 0), (0, 16), (16, 16))):
            block_id = FIRST_BLOCK + frame_number * 4 + chunk
            data = encode_block([row[x:x + 16] for row in frames[name][y:y + 16]])
            pointer = TILES_OFFSET + len(blocks) - 0x190000  # Relative to $d90000.
            table[block_id * 3:block_id * 3 + 3] = u24(pointer)
            blocks.extend(data)
            descriptors.extend(bytes((0x11, (x - 16) & 255, (y - 32) & 255)))
            descriptors.extend(u16(block_id))
    allocate(FRAME_OFFSET, descriptors)
    allocate(SEQUENCE_OFFSET, bytes.fromhex("c1 2d"))  # Native wait-one-tick / loop.
    allocate(TILE_TABLE_OFFSET, table)
    allocate(TILES_OFFSET, blocks)
    allocate(CODE_OFFSET, animation_code())
    allocate(CODE_OFFSET + 0x100, palette_code())
    allocate(CODE_OFFSET + 0x200, b"".join(u16(i * 26) for i in (0, 1, 1, 1, 2, 3, 3, 3)))
    allocate(CODE_OFFSET + 0x220, palette_bank_code())
    allocate(PALETTE_OFFSET, palette)
    write_checked(rom, ANIMATION_HOOK, bytes.fromhex("bf 02 00 c4"),
                  b"\x5c" + u24(0xC00000 + CODE_OFFSET))
    write_checked(rom, PALETTE_HOOK, bytes.fromhex("8b 4b ab 5a"),
                  b"\x5c" + u24(0xC00000 + CODE_OFFSET + 0x100))
    write_checked(rom, PALETTE_BANK_HOOK, bytes.fromhex("a9 90 00 85 28"),
                  b"\x22" + u24(0xC00000 + CODE_OFFSET + 0x220) + b"\xea")
    for offset in TILE_HOOKS:
        write_checked(rom, offset, b"\xec", b"\xf2")
    return {"design": "cowboy", "frames": list(FACING_ORDER),
            "frame_offset": FRAME_OFFSET, "tile_table_offset": TILE_TABLE_OFFSET,
            "tiles_offset": TILES_OFFSET, "palette_offset": PALETTE_OFFSET,
            "palette_id": PALETTE_ID, "original_art_preserved": True}


def export_preview(output_dir):
    """Export an indexed PNG sprite sheet and enlarged preview for art editing."""
    from PIL import Image
    frames, snes_palette = load_art()
    colors = []
    for (value,) in struct.iter_unpack("<H", snes_palette):
        colors.extend((((value & 31) * 255 // 31),
                       (((value >> 5) & 31) * 255 // 31),
                       (((value >> 10) & 31) * 255 // 31)))
    sheet = Image.new("P", (128, 32), 0)
    sheet.putpalette(colors + [0] * (768 - len(colors)))
    for i, name in enumerate(FACING_ORDER):
        for y in range(32):
            for x in range(32):
                sheet.putpixel((i * 32 + x, y), frames[name][y][x])
    sheet.info["transparency"] = 0
    output_dir.mkdir(parents=True, exist_ok=True)
    sheet.save(output_dir / "cowboy-sheet.png")
    sheet.resize((768, 192), Image.Resampling.NEAREST).save(output_dir / "cowboy-preview.png")
