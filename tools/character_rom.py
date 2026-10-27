"""Data-driven opening NPC compiler. Native hooks use only custom actor state."""

import struct
import textwrap

from character_model import FACING_ORDER, rgb_palette, validate, Invalid
from snes_graphics import encode_block, u16, u24

FRAME_OFFSET = 0x310000
SEQUENCE_OFFSET = 0x318000
TILE_TABLE_OFFSET = 0x320000
TILES_OFFSET = 0x360000
TEXT_TABLE_OFFSET = 0x350000
CODE_OFFSET = 0x340000
PALETTE_OFFSET = 0x34FF00
PROFILE_OFFSET = 0x342000
ROUTE_OFFSET = 0x343000
FIRST_BLOCK = 0x1800
ANIMATION_HOOK = 0x108124
TICK_HOOK = 0x1080D2
PALETTE_HOOK = 0x10CF3A
PALETTE_BANK_HOOK = 0x10CFD2
TILE_HOOKS = (0x9745, 0x9754, 0xA2E9)
SPAWN_OFFSET = 0x308000
TALK_OFFSET = 0x308400
TEXT_OFFSET = 0x300000


class Asm:
    def __init__(self, origin):
        self.origin, self.data, self.labels, self.fixups = origin, bytearray(), {}, []

    def emit(self, text):
        self.data.extend(bytes.fromhex(text))

    def label(self, name):
        self.labels[name] = len(self.data)

    def jump(self, name):
        self.data.append(0x5C)
        self.fixups.append((len(self.data), name))
        self.data.extend(b"\0" * 3)

    def when(self, opcode, name):
        self.data.extend((opcode ^ 0x20, 4))  # Inverse condition skips a JML.
        self.jump(name)

    def finish(self):
        for at, name in self.fixups:
            self.data[at:at + 3] = u24(0xC00000 + self.origin + self.labels[name])
        return bytes(self.data)


def recognition(code, fallback):
    code.emit("08 48 b9 66 00 c9 aa 19")
    code.when(0xD0, fallback)
    code.emit("b9 68 00 c9 40 00")
    code.when(0xD0, fallback)
    code.emit("b9 60 00 c9 52 c2")
    code.when(0xD0, fallback)
    code.emit("b9 02 00 29 ff 00 c9 f1 00")
    code.when(0xD0, fallback)
    code.emit("68 28")


def save_scratch(code):
    # Callers of the original animation routines retain VM scratch state here.
    # Our palette and route helpers use more direct-page words than those
    # routines, so keep their scratch effects local to this actor's update.
    code.emit("da 5a 48 08")
    for address in range(0, 0x60, 2):
        code.data.extend(bytes((0xA5, address, 0x48)))


def restore_scratch(code):
    for address in reversed(range(0, 0x60, 2)):
        code.data.extend(bytes((0x68, 0x85, address)))
    code.emit("28 68 7a fa")


def selection_code():
    c = Asm(CODE_OFFSET)
    recognition(c, "vanilla")
    save_scratch(c)
    c.emit("b9 03 00 29 00 70 eb aa 86 14")  # Profile index *16.
    c.emit("b9 03 00 29 00 f0 85 12 b9 22 00 29 0e 00 aa")
    c.emit("bf 00 21 f4 85 16 b9 0e 00 89 00 40")
    c.when(0xF0, "idle")
    c.emit("a5 16 09 04 00 85 16")
    c.label("idle")
    c.emit("a5 16 eb 05 12 85 12 d9 03 00")
    c.when(0xD0, "change")
    c.emit("b9 08 00 c9 f1 00")
    c.when(0xF0, "done")
    c.label("change")
    c.emit("a5 12 99 03 00 7b 99 00 00 a9 f1 00 99 08 00")
    c.emit("22 00 08 f4")
    # Palette helpers use the global current actor. Save it around this call.
    c.emit("da 5a a5 4c 48 98 85 4c a6 14 bf 00 20 f4 22 5c cd 90")
    c.emit("68 85 4c 7a fa")
    c.label("done")
    restore_scratch(c)
    c.emit("6b")
    c.label("vanilla")
    c.emit("68 28 bf 02 00 c4 5c 28 81 90")
    return c.finish()


def load_frame_code():
    c = Asm(CODE_OFFSET + 0x800)
    c.emit("b9 00 00 0a 18 79 00 00 18 79 03 00 1a aa")
    c.emit("bf 00 00 f1 99 06 00 e2 20 bf 02 00 f1 99 05 00 c2 20 6b")
    return c.finish()


def tick_code():
    c = Asm(CODE_OFFSET + 0x400)
    recognition(c, "vanilla")
    save_scratch(c)
    c.emit("22 00 0a f4 22 24 81 90")  # Move, then select idle/walk/facing.
    c.emit("e2 20 b9 05 00 3a 99 05 00 c2 20")
    c.when(0xD0, "done")
    c.emit("b9 00 00 1a 85 12 be 03 00 bf 00 00 f1 29 ff 00 c5 12")
    c.when(0xF0, "restart")
    c.when(0x90, "restart")
    c.emit("a5 12")
    c.jump("frame")
    c.label("restart")
    c.emit("7b")
    c.label("frame")
    c.emit("99 00 00 22 00 08 f4")
    c.label("done")
    restore_scratch(c)
    c.emit("bb 6b")
    c.label("vanilla")
    c.emit("68 28 bb fe 0e 00 5c d6 80 90")
    return c.finish()


def movement_code():
    c = Asm(CODE_OFFSET + 0xA00)
    c.emit("b9 0e 00 89 00 80")
    c.when(0xD0, "done")
    c.emit("b9 03 00 29 00 70 eb aa bf 04 20 f4 85 18")
    c.when(0xF0, "stationary")
    c.emit("b9 0e 00 29 80 3f")
    c.when(0xF0, "route")
    c.emit("b9 0e 00 38 e9 80 00 29 ff bf 99 0e 00 6b")
    c.label("route")
    c.emit("b9 0e 00 29 7f 00 85 1a 0a 18 65 1a 0a 18 7f 06 20 f4 aa")
    c.emit("bf 00 00 f4 85 12 bf 02 00 f4 85 14 bf 04 00 f4 85 16")
    c.emit("b9 1a 00 c5 12")
    c.when(0xF0, "vertical")
    c.when(0x90, "east")
    c.emit("3a 99 1a 00 99 26 00 a9 0c 00 99 22 00")
    c.jump("moving")
    c.label("east")
    c.emit("1a 99 1a 00 99 26 00 a9 04 00 99 22 00")
    c.jump("moving")
    c.label("vertical")
    c.emit("b9 1c 00 c5 14")
    c.when(0xF0, "arrived")
    c.when(0x90, "south")
    c.emit("3a 99 1c 00 99 28 00 7b 99 22 00")
    c.jump("moving")
    c.label("south")
    c.emit("1a 99 1c 00 99 28 00 a9 08 00 99 22 00")
    c.label("moving")
    c.emit("b9 0e 00 09 00 40 99 0e 00 6b")
    c.label("arrived")
    c.emit("a5 1a 1a c5 18")
    c.when(0x90, "index")
    c.emit("7b")
    c.label("index")
    c.emit("05 16 99 0e 00 6b")
    c.label("stationary")
    c.emit("b9 0e 00 29 ff bf 99 0e 00")
    c.label("done")
    c.emit("6b")
    return c.finish()


def palette_code():
    c = Asm(CODE_OFFSET + 0x1400)
    c.emit("08 c9 00 ff")
    c.when(0x90, "vanilla")
    c.emit("c9 40 ff")
    c.when(0xB0, "vanilla")
    c.emit("28 8b f4 f4 f4 ab ab 5a 5c 3e cf 90")
    c.label("vanilla")
    c.emit("28 8b f4 90 90 ab ab 5a 5c 3e cf 90")
    return c.finish()


def palette_bank_code():
    c = Asm(CODE_OFFSET + 0x1500)
    c.emit("08 a5 26 c9 00 ff")
    c.when(0x90, "vanilla")
    c.emit("c9 40 ff")
    c.when(0xB0, "vanilla")
    c.emit("28 a9 f4 00 85 28 6b")
    c.label("vanilla")
    c.emit("28 a9 90 00 85 28 6b")
    return c.finish()


def pointer(field, entity=0x2E, final=True):
    return bytes((entity, 0x29, 0x02, field, 0x9A if final else 0x1A))


def write_actor(field, expression, entity=0x2E):
    return b"\x7a" + pointer(field, entity) + expression


def route_expression(mask, operator):
    return pointer(0x0E, final=False) + bytes.fromhex("55 29 04") + u16(mask) + bytes((operator | 0x80,))


def dialogue_bytes(name, text):
    # Keep text pages within the native window. $86 waits for input at each page.
    lines = []
    for paragraph in (name + ":\n" + text).split("\n"):
        lines.extend(textwrap.wrap(paragraph, width=18, break_long_words=True) or [""])
    pages = [b"\x0a".join(line.encode("ascii") for line in lines[i:i + 2]) for i in range(0, len(lines), 2)]
    return b"\x96" + b"\x86".join(pages) + b"\x86\x00"


def install(rom, scene, characters, checked, packed_script, packed_text):
    validate(scene, 'scenes')
    used = {npc['character'] for npc in scene['npcs']}
    missing = used - characters.keys()
    if missing:
        raise Invalid([{'field': 'npcs', 'message': 'Missing characters: ' + ', '.join(sorted(missing))}])
    characters = {key: validate(characters[key]) for key in sorted(used)}
    for key, document in characters.items():
        if document['id'] != key or any(not 32 <= ord(c) <= 126 for c in document['name']):
            raise Invalid([{'field': f'characters.{key}.name', 'message': 'Use a matching ID and printable English speaker name'}])
    allocations = []

    def put(offset, data, label):
        end = offset + len(data)
        if end > len(rom) or any(offset < a["end"] and end > a["offset"] for a in allocations):
            raise ValueError(f"ROM allocation overlap or overflow: {label}")
        if data:
            checked(rom, offset, b"\xff" * len(data), data)
            allocations.append({"name": label, "offset": offset, "end": end})

    table = bytearray(rom[0x2C0000:0x2D0000])
    text_table = bytearray(rom[0x11D000:0x12D000])
    frames, tiles, frame_records, char_clips = bytearray(), bytearray(), [], {}
    palettes = {}
    old_bounds = (0xE587D, 0xE58BA, 0xE58DE, 0xE5907)
    block_id = FIRST_BLOCK
    for character_id in sorted(characters):
        character = characters[character_id]
        palette_id = 0xFF00 + len(palettes) * 32
        palettes[character_id] = palette_id
        put(0x340000 + palette_id, b"".join(u16(v) for v in rgb_palette(character)), f"{character_id} palette")
        char_clips[character_id] = {}
        for mode in ("idle", "walk"):
            for d, direction in enumerate(FACING_ORDER):
                records = []
                for frame in character["animations"][mode][direction]:
                    frame_address = FRAME_OFFSET + len(frames)
                    frames.extend(bytes((4, 6)) + rom[old_bounds[d] + 2:old_bounds[d] + 6])
                    pixels = [[0 if c == "." else int(c, 16) for c in row] for row in frame["pixels"]]
                    for x, y in ((0, 0), (16, 0), (0, 16), (16, 16)):
                        data = encode_block([row[x:x + 16] for row in pixels[y:y + 16]])
                        table[block_id * 3:block_id * 3 + 3] = u24(TILES_OFFSET + len(tiles) - 0x190000)
                        tiles.extend(data)
                        frames.extend(bytes((0x11, (x - 16) & 255, (y - 32) & 255)) + u16(block_id))
                        block_id += 1
                    records.append((frame_address & 0xFFFF, frame["duration"]))
                    frame_records.append({"character": character_id, "mode": mode, "facing": direction,
                                          "offset": frame_address, "duration": frame["duration"]})
                char_clips[character_id][mode, direction] = records
    if len(frames) > 0x8000 or len(tiles) > 0xA0000 or block_id * 3 > 0x10000:
        raise ValueError("Character graphics exceed the expanded ROM budget")
    put(FRAME_OFFSET, frames, "directional frames")
    put(TILE_TABLE_OFFSET, table, "tile pointers")
    put(TILES_OFFSET, tiles, "graphics")
    spawn = bytearray.fromhex("0c 93 04 b0")
    dispatch, profile, routes, text = bytearray(), bytearray(), bytearray(), bytearray()
    for i, npc in enumerate(scene["npcs"]):
        base = 0x8000 + i * 0x1000
        character = characters[npc["character"]]
        for mode_index, mode in enumerate(("idle", "walk")):
            for d, direction in enumerate(FACING_ORDER):
                records = char_clips[npc["character"]][mode, direction]
                clip = bytes((len(records),)) + b"".join(u16(ptr) + bytes((duration,)) for ptr, duration in records)
                put(0x310000 + base + (mode_index * 4 + d) * 256, clip, f"{npc['id']} {mode} {direction}")
        movement = npc["movement"]
        route = movement["waypoints"] if movement["mode"] == "patrol" else []
        profile.extend(struct.pack("<8H", palettes[npc["character"]], 0, len(route),
                                   (ROUTE_OFFSET + len(routes)) & 0xFFFF, 0, 0, 0, 0))
        for point in route:
            routes.extend(struct.pack("<3H", point["x"], point["y"], point.get("pause", 30) << 7))
        x, y = npc["position"]["x"] // 8, npc["position"]["y"] // 8
        spawn.extend(bytes((0xBA, 0x57, x, y, 0x2A, 0xAD)))
        spawn.extend(write_actor(2, b"\x84\xf1\x00", 0x2D))
        spawn.extend(write_actor(3, b"\x84" + u16(base), 0x2D))
        spawn.extend(write_actor(0x0E, b"\xb0", 0x2D))
        spawn.extend(bytes.fromhex("3d ad aa 19"))
        spawn.extend(bytes((dict(north=0x74, south=0x75, west=0x76, east=0x77)[npc["facing"]], 0xAD)))
        talk_at = 0x308800 + i * 0x400
        condition = pointer(3, final=False) + bytes.fromhex("55 29 04 00 f0 24 29 04") + u16(base) + b"\xa2"
        dispatch.extend(b"\x09" + condition + u16(5) + b"\x29" + u24(packed_script(talk_at)) + b"\x00")
        # Pause only this actor, retaining its next waypoint and remaining pause.
        talk = write_actor(0x0E, route_expression(0x3FFF, 0x24))
        talk += write_actor(0x0E, route_expression(0x8000, 0x25))
        talk += bytes.fromhex("a3 32 a3 02 51") + u16(6 + i * 3)
        talk += bytes.fromhex("55 a3 33 2a ae")
        talk += write_actor(0x0E, route_expression(0x7FFF, 0x24))
        if not route:
            talk += bytes((dict(north=0x74, south=0x75, west=0x76, east=0x77)[npc["facing"]], 0xAE))
        talk += b"\x00"
        put(talk_at, talk, f"{npc['id']} conversation")
        text_table[6 + i * 3:9 + i * 3] = u24(packed_text(TEXT_OFFSET + len(text)))
        text.extend(dialogue_bytes(character["name"], npc["dialogue"]))
    spawn.append(0)
    dispatch.append(0)
    if len(spawn) > 0x400 or len(dispatch) > 0x400 or len(text) > 0x8000:
        raise ValueError("Scene scripts or dialogue exceed their ROM budget")
    put(SPAWN_OFFSET, spawn, "spawn script")
    put(TALK_OFFSET, dispatch, "conversation dispatcher")
    put(TEXT_OFFSET, text, "dialogue")
    put(TEXT_TABLE_OFFSET, text_table, "relocated text pointers")
    for offset, data, name in ((CODE_OFFSET, selection_code(), "animation selection"),
                               (CODE_OFFSET + 0x400, tick_code(), "custom actor tick"),
                               (CODE_OFFSET + 0x800, load_frame_code(), "frame loading"),
                               (CODE_OFFSET + 0xA00, movement_code(), "patrol movement"),
                               (CODE_OFFSET + 0x1400, palette_code(), "palette loader"),
                               (CODE_OFFSET + 0x1500, palette_bank_code(), "palette upload"),
                               (PROFILE_OFFSET, profile, "NPC profiles"),
                               (CODE_OFFSET + 0x2100, b"".join(u16(v) for v in (0, 1, 1, 1, 2, 3, 3, 3)), "facing lookup"),
                               (ROUTE_OFFSET, routes, "patrol waypoints")):
        put(offset, data, name)
    checked(rom, 0x1BC446, bytes.fromhex("0c 93 04 b0"), b"\x29" + u24(packed_script(SPAWN_OFFSET)))
    checked(rom, 0x129C3E, bytes.fromhex("da e0 02"), u24(packed_script(TALK_OFFSET)))
    for at, expected, target in ((ANIMATION_HOOK, "bf 02 00 c4", CODE_OFFSET),
                                  (TICK_HOOK, "bb fe 0e 00", CODE_OFFSET + 0x400),
                                  (PALETTE_HOOK, "8b 4b ab 5a", CODE_OFFSET + 0x1400)):
        checked(rom, at, bytes.fromhex(expected), b"\x5c" + u24(target + 0xC00000))
    checked(rom, PALETTE_BANK_HOOK, bytes.fromhex("a9 90 00 85 28"), b"\x22" + u24(CODE_OFFSET + 0x1500 + 0xC00000) + b"\xea")
    for at in TILE_HOOKS:
        checked(rom, at, b"\xec", b"\xf2")
    checked(rom, 0xCCCF8, b"\x91", b"\xf5")
    checked(rom, 0xCCCFD, bytes.fromhex("00 d0"), bytes.fromhex("00 00"))
    return {"scene": scene, "allocations": allocations, "frames": frame_records,
            "palettes": palettes, "character_ids": sorted(characters)}
