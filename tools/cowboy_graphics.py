"""Compatibility helpers for the original cowboy experiment.

All current ROM compilation is data-driven in character_rom.py.
"""
import json
from pathlib import Path
import struct
from character_rom import (FRAME_OFFSET, SEQUENCE_OFFSET, TILE_TABLE_OFFSET, TILES_OFFSET,
    CODE_OFFSET, PALETTE_OFFSET, FIRST_BLOCK, ANIMATION_HOOK, PALETTE_HOOK,
    PALETTE_BANK_HOOK, TILE_HOOKS)
from character_model import FACING_ORDER
from snes_graphics import encode_block, u16, u24
PALETTE_ID = 0xff00
ASSET = Path(__file__).resolve().parents[1] / "assets/characters/cowboy.json"

def u16(value):
    return struct.pack("<H", value & 0xffff)

def u24(value):
    return value.to_bytes(3, "little")

def load_art():
    data = json.loads(ASSET.read_text())
    if "animations" in data:
        data["frames"] = {d: data["animations"]["idle"][d][0]["pixels"] for d in FACING_ORDER}
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
