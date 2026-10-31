"""Dialogue trust boundary, stale replies, and opt-in ROM integrity."""
import json
from pathlib import Path
import struct
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from gamemaster import Companion, commentary, encode_comment
from gamemaster_rom import actor_read, const, expr, read, BOSS
from build_npc import compile_rom, create_bps, SOURCE_SHA256, sha256
from test_build_npc import apply_bps


def until(predicate, timeout=2):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError('Companion did not respond')


class CommentaryTests(unittest.TestCase):
    def test_ollama_generate_contract(self):
        with patch('gamemaster.request.urlopen') as open_url:
            open_url.return_value.__enter__.return_value.read.return_value = json.dumps(
                {'response': 'Alex has a name fit for a space captain!'}).encode()
            text = commentary('Alex', 'local-test-model', 'http://127.0.0.1:11434')
            req = open_url.call_args.args[0]
            body = json.loads(req.data)
            self.assertEqual(req.full_url, 'http://127.0.0.1:11434/api/generate')
            self.assertEqual(body['model'], 'local-test-model')
            self.assertFalse(body['stream'])
            self.assertIn('"Alex"', body['prompt'])
            self.assertIn(b'Alex has a name', text)
            self.assertEqual(text[-1], 0)

    def test_oversized_ollama_response_is_rejected(self):
        with patch('gamemaster.request.urlopen') as open_url:
            open_url.return_value.__enter__.return_value.read.return_value = b'x' * 16385
            with self.assertRaisesRegex(ValueError, 'response too large'):
                commentary('Alex', 'local-test-model', 'http://127.0.0.1:11434')

    def test_untrusted_prose_has_no_menu_or_script_controls(self):
        result = encode_comment('\x00\x8b\x81 Hello! ' * 1000)
        self.assertLessEqual(len(result), 512)
        self.assertEqual(result[-1], 0)
        self.assertNotIn(0, result[:-1])
        self.assertNotIn(0x8b, result)
        self.assertEqual(result.count(b'\x81'), 1)  # Native current-name substitution.
        for page in result.split(b'\x86')[1:-1]:
            self.assertLessEqual(len(page.splitlines()), 2)
            self.assertTrue(all(len(line) <= 18 for line in page.splitlines()))

    def test_empty_responses_rejected(self):
        for value in ('', '\0\n', None, 1, []):
            with self.subTest(value=value), self.assertRaises(ValueError):
                encode_comment(value)

    def test_reply_identity_and_current_name(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            req = {'session': 'one', 'generation': 0, 'request': 1, 'name': 'Alex'}
            (path / 'request.json').write_text(json.dumps(req))
            calls = []
            def generate(name, *_):
                calls.append(name)
                return encode_comment(name + ', ready for orbit!')
            with Companion(path, 'test', generate=generate) as companion:
                until(lambda: (path / 'reply.json').exists())
                reply = json.loads((path / 'reply.json').read_text())
                self.assertEqual({k: reply[k] for k in ('session', 'generation', 'request')},
                                 {k: req[k] for k in ('session', 'generation', 'request')})
                until(lambda: bool(companion.events))
            self.assertEqual(calls, ['Alex'])

    def test_reset_during_generation_drops_old_reply(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            req = {'session': 'one', 'generation': 0, 'request': 1, 'name': 'Alex'}
            (path / 'request.json').write_text(json.dumps(req))
            def generate(*_):
                req['generation'] = 1
                (path / 'request.json').write_text(json.dumps(req))
                return encode_comment('Hello!')
            with Companion(path, 'test', generate=generate) as companion:
                until(lambda: bool(companion.events))
                self.assertEqual(companion.events[0]['status'], 'stale')
                self.assertFalse((path / 'reply.json').exists())

    def test_failed_model_leaves_rom_fallback_in_control(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'request.json').write_text(json.dumps(
                {'session': 'one', 'generation': 0, 'request': 1, 'name': 'Alex'}))
            def generate(*_):
                raise OSError('model unavailable')
            with Companion(path, 'test', generate=generate) as companion:
                until(lambda: bool(companion.events))
                self.assertEqual(companion.events[0]['status'], 'fallback')
                self.assertFalse((path / 'reply.json').exists())

    def test_late_model_response_leaves_fallback_in_control(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'request.json').write_text(json.dumps(
                {'session': 'one', 'generation': 0, 'request': 1, 'name': 'Alex'}))
            def generate(*_):
                time.sleep(0.03)
                return encode_comment('Ready for orbit!')
            with patch('gamemaster.TIMEOUT', 0.01), Companion(path, 'test', generate=generate) as companion:
                until(lambda: bool(companion.events))
                self.assertEqual(companion.events[0]['status'], 'timeout')
                self.assertFalse((path / 'reply.json').exists())

    def test_compound_hp_condition_terminates_after_comparison(self):
        # Regression: a terminated dereference in this condition made the VM
        # execute the comparison operands as opcodes and halt the SNES CPU.
        condition = expr(actor_read(BOSS, 0x2a), 0x20, const(0))
        self.assertEqual(condition[-1], 0xa0)
        self.assertIn(b'\x55\x29\x04\x00\x00', condition)
        self.assertNotIn(b'\xd5', condition)

    def test_negative_hit_bounds_are_signed(self):
        self.assertEqual(const(-20), b'\x83\xec\xff')
        self.assertEqual(const(20), b'\x84\x14\x00')

    def test_low_wram_uses_absolute_dereference(self):
        self.assertEqual(read(0x0341), b'\x04\x41\x03\xd5')
        self.assertEqual(read(0x0341, False), b'\x04\x41\x03\x55')


@unittest.skipUnless(Path('roms/original.sfc').is_file(), 'Private local ROM required')
class GamemasterRomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path('roms/original.sfc').read_bytes()
        cls.normal, _ = compile_rom(cls.source)
        cls.rom, cls.layout = compile_rom(cls.source, gamemaster=True)

    def test_deterministic_checksum_and_independent_bps(self):
        self.assertEqual(compile_rom(self.source, gamemaster=True)[0], self.rom)
        self.assertEqual(apply_bps(self.source, create_bps(self.source, self.rom)), self.rom)
        inverse, checksum = struct.unpack_from('<HH', self.rom, 0xffdc)
        self.assertEqual(checksum ^ inverse, 0xffff)
        self.assertEqual(sum(self.rom) & 0xffff, checksum)
        self.assertEqual(sha256(Path('roms/original.sfc').read_bytes()), SOURCE_SHA256)

    def test_only_opt_in_hooks_and_allocations_change(self):
        ranges = [(0xffdc, 0xffe0), (0x1bc4dd, 0x1bc4e2), (0xcccf5, 0xcccfa),
                  (0x35fff9, 0x35ffff)]
        ranges += [(a['offset'], a['end']) for a in self.layout['allocations']
                   if a['name'].startswith('gamemaster ')]
        for a, b in zip(sorted(ranges), sorted(ranges)[1:]):
            self.assertLessEqual(a[1], b[0])
        cursor = 0
        for start, end in sorted(ranges):
            self.assertEqual(self.normal[cursor:start], self.rom[cursor:start])
            cursor = end
        self.assertEqual(self.normal[cursor:], self.rom[cursor:])
        self.assertEqual(self.layout['gamemaster']['bosses'], ['Thraxx', 'Salabog', 'Magmar'])


if __name__ == '__main__':
    unittest.main()
