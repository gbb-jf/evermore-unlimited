"""Patch integrity checks; ROM-dependent cases use only the local private dump."""

import hashlib
from pathlib import Path
import random
import struct
import sys
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from build_npc import (HOOK, SOURCE_SHA256, SOURCE_SIZE, SPAWN_OFFSET,
                       TALK_OFFSET, TARGET_SIZE, TEXT_OFFSET, build_rom,
                       create_bps, packed_script, packed_text, write_checked, compile_rom)
from cowboy_graphics import (ANIMATION_HOOK, FIRST_BLOCK, FRAME_OFFSET,
                             PALETTE_BANK_HOOK, PALETTE_HOOK, PALETTE_OFFSET,
                             TILE_HOOKS, TILE_TABLE_OFFSET, TILES_OFFSET,
                             FACING_ORDER, encode_block, load_art)


def apply_bps(source, patch):
    """Independent BPS reader, including checksums and overlapping TargetCopy."""
    if patch[:4] != b"BPS1":
        raise ValueError("Invalid BPS header")
    source_crc, target_crc, patch_crc = struct.unpack("<III", patch[-12:])
    if zlib.crc32(source) != source_crc or zlib.crc32(patch[:-4]) != patch_crc:
        raise ValueError("Checksum mismatch")
    cursor = 4

    def number():
        nonlocal cursor
        value, shift = 0, 1
        while True:
            byte = patch[cursor]
            cursor += 1
            value += (byte & 127) * shift
            if byte & 128:
                return value
            shift <<= 7
            value += shift

    source_size, target_size, metadata_size = number(), number(), number()
    if source_size != len(source):
        raise ValueError("Wrong source size")
    cursor += metadata_size
    output = bytearray()
    source_relative, target_relative = 0, 0
    while len(output) < target_size:
        action = number()
        length, mode = (action >> 2) + 1, action & 3
        if mode == 0:
            output.extend(source[len(output):len(output) + length])
        elif mode == 1:
            output.extend(patch[cursor:cursor + length])
            cursor += length
        else:
            offset = number()
            delta = (offset >> 1) * (-1 if offset & 1 else 1)
            if mode == 2:
                source_relative += delta
                output.extend(source[source_relative:source_relative + length])
                source_relative += length
            else:
                target_relative += delta
                for _ in range(length):
                    output.append(output[target_relative])
                    target_relative += 1
    if cursor != len(patch) - 12 or zlib.crc32(output) != target_crc:
        raise ValueError("Invalid output or trailing data")
    return bytes(output)


class BpsTests(unittest.TestCase):
    def test_round_trip_cases(self):
        for source, target in [(b"", b""), (b"a", b"b"), (b"abc", b"abc"),
                               (b"abc", b"ab"), (b"", b"\xff" * 10000),
                               (b"abcd", b"abXYcd" + b"\xff" * 10000 + b"END"),
                               (b"abcdef", b"x" * 40 + b"yz" + b"q" * 60)]:
            with self.subTest(source=source[:8], size=len(target)):
                self.assertEqual(apply_bps(source, create_bps(source, target)), target)

    def test_randomized_round_trips(self):
        rng = random.Random(42)
        for _ in range(50):
            source = rng.randbytes(rng.randrange(500))
            target = bytearray(source)
            for _ in range(5):
                at = rng.randrange(len(target) + 1)
                target[at:at + rng.randrange(20)] = rng.randbytes(rng.randrange(30))
            self.assertEqual(apply_bps(source, create_bps(source, target)), target)

    def test_patch_rejects_wrong_input_and_corruption(self):
        patch = create_bps(b"abc", b"abd")
        with self.assertRaises(ValueError):
            apply_bps(b"xyz", patch)
        with self.assertRaises(ValueError):
            apply_bps(b"abc", patch[:-1] + bytes([patch[-1] ^ 1]))


class AddressTests(unittest.TestCase):
    def test_script_address_round_trip(self):
        for offset in (0x128000, 0x1BC446, SPAWN_OFFSET, TALK_OFFSET, 0x3FFFFF):
            packed = packed_script(offset)
            unpacked = 0x128000 + (packed & 0x7FFF) + ((packed & 0xFF8000) << 1)
            self.assertEqual(unpacked, offset)

    def test_text_address_round_trip(self):
        for offset in (0x10000, TEXT_OFFSET, 0x3F7FFF):
            packed = packed_text(offset)
            self.assertEqual((packed & 0x7FFF) + ((packed & 0x7F8000) << 1), offset)

    def test_checked_write_rejects_mismatch(self):
        data = bytearray(b"abcd")
        with self.assertRaises(ValueError):
            write_checked(data, 0, b"xx", b"yz")
        self.assertEqual(data, b"abcd")

    def test_unsupported_input_rejected(self):
        with self.assertRaises(ValueError):
            build_rom(b"not a ROM")


class LocalRomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = Path(__file__).resolve().parents[1] / "roms/original.sfc"
        if not cls.path.is_file():
            raise unittest.SkipTest("Private source ROM not present")
        cls.source = cls.path.read_bytes()
        from character_model import Store
        cls.scene, cls.characters = Store().project()
        cls.target, cls.layout = compile_rom(cls.source, cls.scene, cls.characters)

    def test_source_preserved_and_build_reproducible(self):
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), SOURCE_SHA256)
        self.assertEqual(build_rom(self.source), self.target)

    def test_snes_checksum(self):
        self.assertEqual(len(self.target), TARGET_SIZE)
        complement, checksum = struct.unpack("<HH", self.target[0xFFDC:0xFFE0])
        self.assertEqual(complement ^ checksum, 0xFFFF)
        self.assertEqual(sum(self.target) & 0xFFFF, checksum)

    def test_patch_reconstructs_exact_rom(self):
        patch = create_bps(self.source, self.target)
        self.assertEqual(apply_bps(self.source, patch), self.target)
        self.assertLess(len(patch), 250_000)

    def test_only_expected_original_ranges_changed(self):
        allowed = set(range(0xFFDC, 0xFFE0)) | set(range(HOOK, HOOK + 4))
        allowed |= set(range(0x129C3E, 0x129C41))
        for offset, size in ((ANIMATION_HOOK, 4), (PALETTE_HOOK, 4), (PALETTE_BANK_HOOK, 5)):
            allowed.update(range(offset, offset + size))
        allowed.update(TILE_HOOKS)
        allowed.update(range(0x1080D2, 0x1080D6))
        allowed.update((0xCCCF8, 0xCCCFD, 0xCCCFE))
        changes = {i for i in range(SOURCE_SIZE) if self.source[i] != self.target[i]}
        self.assertTrue(changes <= allowed)

    def test_modified_or_headered_rom_rejected(self):
        changed = bytearray(self.source)
        changed[100] ^= 1
        for data in (changed, b"\0" * 512 + self.source):
            with self.assertRaises(ValueError):
                build_rom(data)

    def test_professor_and_original_graphics_are_preserved(self):
        for begin, end in ((0xEC252, 0xEC29C), (0x45372, 0x453A2),
                           (0x932E2, 0x9330A), (0xE587D, 0xE5930),
                           (0x10BA6B, 0x10BA8B), (0x190000, HOOK),
                           (HOOK + 4, 0x300000)):
            self.assertEqual(self.target[begin:end], self.source[begin:end])

    def test_relocated_table_preserves_all_original_entries(self):
        table = self.target[TILE_TABLE_OFFSET:TILE_TABLE_OFFSET + 0x10000]
        from character_model import Store
        _, characters = Store().project()
        frame_count = sum(len(clip) for document in characters.values()
                          for animation in document['animations'].values() for clip in animation.values())
        first, end = FIRST_BLOCK * 3, (FIRST_BLOCK + frame_count * 4) * 3
        original = self.source[0x2C0000:0x2D0000]
        self.assertEqual(table[:first], original[:first])
        self.assertEqual(table[end:], original[end:])

    def test_private_frames_decode_to_authored_pixels(self):
        from collections import Counter
        from character_model import rgb_palette
        for ident, palette_id in self.layout['palettes'].items():
            palette = b''.join(struct.pack('<H', color) for color in rgb_palette(self.characters[ident]))
            self.assertEqual(self.target[0x340000 + palette_id:0x340000 + palette_id + 32], palette)
        seen = Counter()
        for number, record in enumerate(self.layout['frames']):
            key = record['character'], record['mode'], record['facing']
            expected = self.characters[key[0]]['animations'][key[1]][key[2]][seen[key]]['pixels']
            seen[key] += 1
            at = record['offset']
            self.assertEqual(self.target[at:at + 2], bytes((4, 6)))
            rendered = [[0] * 32 for _ in range(32)]
            for chunk in range(4):
                flag, x, y, block = struct.unpack_from('<BbbH', self.target, at + 6 + 5 * chunk)
                self.assertEqual(flag, 0x11)
                self.assertEqual(block, FIRST_BLOCK + number * 4 + chunk)
                pointer = int.from_bytes(self.target[TILE_TABLE_OFFSET + block * 3:
                                                     TILE_TABLE_OFFSET + block * 3 + 3], 'little')
                offset = 0x190000 + pointer
                self.assertGreaterEqual(offset, TILES_OFFSET)
                pixels = decode_block(self.target[offset:offset + 128])
                for row in range(16):
                    rendered[y + 32 + row][x + 16:x + 32] = pixels[row]
            self.assertEqual(rendered, [[0 if c == '.' else int(c, 16) for c in row] for row in expected])


def decode_block(data):
    """Read standard SNES 4bpp planes, independently of the asset encoder."""
    output = [[0] * 16 for _ in range(16)]
    for tile in range(4):
        for y in range(8):
            planes = (data[tile * 32 + y * 2], data[tile * 32 + y * 2 + 1],
                      data[tile * 32 + 16 + y * 2], data[tile * 32 + 17 + y * 2])
            for x in range(8):
                value = sum(((plane >> (7 - x)) & 1) << bit for bit, plane in enumerate(planes))
                output[(tile // 2) * 8 + y][(tile % 2) * 8 + x] = value
    return output


class GraphicsTests(unittest.TestCase):
    def test_bitplane_encoding(self):
        pixels = [[(x + y) % 16 for x in range(16)] for y in range(16)]
        self.assertEqual(decode_block(encode_block(pixels)), pixels)

    def test_artwork_has_distinct_directional_frames(self):
        art, palette = load_art()
        self.assertEqual(len(palette), 32)
        self.assertEqual(len({str(frame) for frame in art.values()}), 4)
        self.assertTrue(all(0 in row for frame in art.values() for row in frame))


if __name__ == "__main__":
    unittest.main()
