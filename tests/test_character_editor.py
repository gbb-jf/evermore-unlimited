from copy import deepcopy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from character_model import (ROOT, Store, Invalid, Conflict, blank_character, validate,
                             export_sheet, import_sheet, migrate_legacy)
from build_npc import compile_rom


def scene_for(*identifiers):
    return {'version': 1, 'id': 'opening-station', 'name': 'Opening station',
            'npcs': [{'id': f'npc-{i}', 'character': ident, 'dialogue': 'Hello!',
                      'position': {'x': 416 + i * 32, 'y': 304}, 'facing': 'south',
                      'movement': {'mode': 'stationary', 'waypoints': []}} for i, ident in enumerate(identifiers)]}


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.character = Store().get('characters', 'cowboy')['document']

    def test_new_document_has_valid_clips_and_transparency(self):
        character = blank_character('new-friend')
        self.assertEqual(character['palette'][0], 'transparent')
        self.assertEqual(len(character['animations']), 2)
        self.assertEqual(validate(character), character)

    def test_document_validation_reports_precise_pixel_field(self):
        self.character['animations']['walk']['west'][0]['pixels'][7] = 'bad'
        with self.assertRaises(Invalid) as caught:
            validate(self.character)
        self.assertEqual(caught.exception.errors[0]['field'], 'animations.walk.west.0.pixels.7')

    def test_timing_clip_and_palette_limits(self):
        for mutate in (lambda c: c['palette'].pop(),
                       lambda c: c['palette'].__setitem__(0, '#000000'),
                       lambda c: c['animations']['idle']['north'][0].__setitem__('duration', 0),
                       lambda c: c['animations']['idle'].__setitem__('west', []),
                       lambda c: c['animations']['walk'].__setitem__('east', c['animations']['walk']['east'] * 5)):
            changed = deepcopy(self.character)
            mutate(changed)
            with self.assertRaises(Invalid):
                validate(changed)

    def test_scene_limits_and_missing_patrol_points(self):
        for document in (scene_for('one', 'two', 'three'), scene_for(*(['cowboy'] * 9))):
            with self.assertRaises(Invalid):
                validate(document, 'scenes')
        scene = scene_for('cowboy')
        scene['npcs'][0]['movement']['mode'] = 'patrol'
        with self.assertRaises(Invalid) as caught:
            validate(scene, 'scenes')
        self.assertIn('waypoints', str(caught.exception))

    def test_scene_geometry_ids_and_dialogue(self):
        for field, value in [('position', {'x': 417, 'y': 304}),
                             ('position', {'x': 800, 'y': 304}), ('dialogue', 'No\x00'), ('facing', 'up')]:
            scene = scene_for('cowboy')
            scene['npcs'][0][field] = value
            with self.assertRaises(Invalid):
                validate(scene, 'scenes')
        scene = scene_for('cowboy', 'cowboy')
        scene['npcs'][1]['id'] = scene['npcs'][0]['id']
        with self.assertRaises(Invalid):
            validate(scene, 'scenes')

    def test_legacy_migration_preserves_idle_art_and_adds_walking(self):
        legacy = {'palette': self.character['palette'],
                  'frames': {d: f[0]['pixels'] for d, f in self.character['animations']['idle'].items()}}
        migrated = migrate_legacy(legacy)
        self.assertEqual(migrated['animations']['idle']['south'][0]['pixels'], legacy['frames']['south'])
        self.assertEqual(len(migrated['animations']['walk']['south']), 4)
        self.assertNotEqual(migrated['animations']['walk']['south'][0]['pixels'], migrated['animations']['walk']['south'][1]['pixels'])

    def test_png_round_trip_preserves_pixels_counts_and_durations(self):
        self.character['animations']['walk']['west'].pop()
        self.character['animations']['walk']['south'][1]['duration'] = 23
        png = export_sheet(self.character, 'walk')
        result = import_sheet(self.character, png, 'walk')
        self.assertEqual(result, self.character)
        self.assertEqual(export_sheet(self.character, 'walk'), png)

    def test_png_preserves_duplicate_color_indices(self):
        self.character['palette'][2] = self.character['palette'][1]
        result = import_sheet(self.character, export_sheet(self.character), 'idle')
        self.assertEqual(result, self.character)

    def test_png_requires_explicit_color_mapping(self):
        from PIL import Image
        stream = io.BytesIO()
        Image.new('RGBA', (32, 128), (255, 0, 255, 255)).save(stream, format='PNG')
        with self.assertRaises(Invalid):
            import_sheet(self.character, stream.getvalue())
        result = import_sheet(self.character, stream.getvalue(), mapping='nearest')
        self.assertEqual(len(result['animations']['idle']['south'][0]['pixels']), 32)

    def test_schema_matches_current_documents(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest('Optional jsonschema package not installed')
        for kind, file in [('characters', 'character'), ('scenes', 'scene')]:
            schema = json.loads((ROOT / f'schemas/{file}.schema.json').read_text())
            for item in Store().list(kind):
                jsonschema.validate(item['document'], schema)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.initial = self.store.save('characters', blank_character('friend'), None)

    def test_save_is_atomic_and_rejects_lost_updates(self):
        changed = deepcopy(self.initial['document'])
        changed['name'] = 'New friend'
        saved = self.store.save('characters', changed, self.initial['revision'])
        self.assertNotEqual(saved['revision'], self.initial['revision'])
        with self.assertRaises(Conflict):
            self.store.save('characters', self.initial['document'], self.initial['revision'])
        self.assertEqual(self.store.get('characters', 'friend'), saved)
        self.assertEqual(list((Path(self.temp.name) / 'assets/characters').glob('*.tmp')), [])

    def test_new_document_cannot_overwrite_existing(self):
        with self.assertRaises(Conflict):
            self.store.save('characters', blank_character('friend'), None)

    def test_invalid_save_leaves_disk_unchanged(self):
        invalid = deepcopy(self.initial['document'])
        invalid['palette'] = []
        with self.assertRaises(Invalid):
            self.store.save('characters', invalid, self.initial['revision'])
        self.assertEqual(self.store.get('characters', 'friend'), self.initial)

    def test_paths_and_symlinks_are_restricted(self):
        for kind, ident in [('characters', '../../outside'), ('bad', 'friend'), ('characters', '/tmp/oops')]:
            with self.assertRaises(Invalid):
                self.store.path(kind, ident)
        link = Path(self.temp.name) / 'assets/characters/link.json'
        link.symlink_to(Path(self.temp.name) / 'outside.json')
        with self.assertRaises(Invalid):
            self.store.path('characters', 'link')

    def test_filename_must_match_document_identity(self):
        path = self.store.path('characters', 'friend')
        content = json.loads(path.read_text())
        content['id'] = 'other'
        path.write_text(json.dumps(content))
        with self.assertRaises(Invalid):
            self.store.get('characters', 'friend')

    def test_project_resolves_references_and_reports_missing_characters(self):
        self.store.save('scenes', scene_for('friend'), None)
        _, characters = self.store.project()
        self.assertEqual(list(characters), ['friend'])
        current = self.store.get('scenes', 'opening-station')
        self.store.save('scenes', scene_for('missing'), current['revision'])
        with self.assertRaises(Invalid) as caught:
            self.store.project()
        self.assertEqual(caught.exception.errors[0]['field'], 'npcs.0.character')

    def test_cli_uses_the_same_validation_and_revisions(self):
        command = [sys.executable, str(ROOT / 'tools/characters.py'), '--root', self.temp.name, '--json']
        created = subprocess.run(command + ['create', 'second'], capture_output=True, text=True)
        self.assertEqual(created.returncode, 0, created.stdout)
        result = json.loads(created.stdout)
        self.assertEqual(self.store.get('characters', 'second'), result)
        invalid = subprocess.run(command + ['create', '../invalid'], capture_output=True, text=True)
        self.assertEqual(invalid.returncode, 2)
        self.assertEqual(json.loads(invalid.stdout)['errors'][0]['field'], 'id')
        malformed_path = Path(self.temp.name) / 'malformed.json'
        malformed_path.write_text('[]')
        malformed = subprocess.run(command + ['update', 'friend', '--input', str(malformed_path),
                                              '--revision', self.initial['revision']], capture_output=True, text=True)
        self.assertEqual(malformed.returncode, 2)
        self.assertEqual(json.loads(malformed.stdout)['errors'][0]['field'], '$')


class CompilerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = ROOT / 'roms/original.sfc'
        if not path.is_file():
            raise unittest.SkipTest('Private source ROM not present')
        cls.source = path.read_bytes()
        cls.character = Store().get('characters', 'cowboy')['document']

    def test_multiple_instances_have_independent_bindings_and_clips(self):
        scene = scene_for('cowboy', 'cowboy')
        target, layout = compile_rom(self.source, scene, {'cowboy': self.character})
        self.assertEqual(layout['character_ids'], ['cowboy'])
        self.assertEqual(len(layout['scene']['npcs']), 2)
        self.assertEqual(target[0x318000:0x318004], target[0x319000:0x319004])
        self.assertTrue(any(a['name'] == 'npc-1 conversation' for a in layout['allocations']))
        self.assertEqual(compile_rom(self.source, scene, {'cowboy': self.character})[0], target)

    def test_over_budget_scene_is_rejected_before_writing(self):
        scene = scene_for('one', 'two', 'three')
        with self.assertRaises(Invalid):
            compile_rom(self.source, scene, {})

    def test_allocations_are_disjoint_and_fit_expansion(self):
        target, layout = compile_rom(self.source)
        allocations = sorted(layout['allocations'], key=lambda a: a['offset'])
        for previous, current in zip(allocations, allocations[1:]):
            self.assertLessEqual(previous['end'], current['offset'])
        self.assertTrue(all(0x300000 <= a['offset'] < a['end'] <= len(target) for a in allocations))

    def test_full_scene_budget_and_two_characters_compile(self):
        second = deepcopy(self.character)
        second.update(id='ranger', name='Ranger')
        second['palette'][4] = '#385f98'
        scene = scene_for(*(['cowboy', 'ranger'] * 4))
        for i, npc in enumerate(scene['npcs']):
            npc['position'] = {'x': 416 + i % 4 * 32, 'y': 288 + i // 4 * 32}
        target, layout = compile_rom(self.source, scene, {'cowboy': self.character, 'ranger': second})
        self.assertEqual(layout['palettes'], {'cowboy': 0xff00, 'ranger': 0xff20})
        self.assertEqual(len([a for a in layout['allocations'] if a['name'].endswith('conversation')]), 8)
        self.assertEqual(compile_rom(self.source, scene, {'cowboy': self.character, 'ranger': second})[0], target)

    def test_explicit_rom_build_has_manifest_and_previews(self):
        from build_npc import build_project
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            manifest = build_project(output_dir=output, source_path=ROOT / 'roms/original.sfc')
            self.assertEqual(json.loads((output / 'manifest.json').read_text()), manifest)
            self.assertTrue((output / 'cowboy-idle.png').is_file())
            self.assertTrue((output / 'cowboy-walk.png').is_file())


if __name__ == '__main__':
    unittest.main()
