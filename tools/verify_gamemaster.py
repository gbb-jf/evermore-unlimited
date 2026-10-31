#!/usr/bin/env python3
"""Fresh-boot station boss acceptance: controller input, read-only observations.

--fixture exercises the actual dialogue bridge with deterministic prose instead
of requiring Ollama. Combat/progression is never changed through the bridge.
"""
import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import tempfile

from build_npc import compile_rom
from emulator_session import open_session
from gamemaster import Companion, encode_comment
from gamemaster_rom import BOSSES, BOSS, STATUS, CHOICE, STEP, CLAW1, CLAW2, PROJECTILE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--choice', type=int, choices=range(3), required=True)
    parser.add_argument('--fixture', action='store_true')
    parser.add_argument('--rom', type=Path, default=Path('build/gamemaster/evermore-npc.sfc'))
    parser.add_argument('--original', type=Path, default=Path('roms/original.sfc'))
    parser.add_argument('--luna', type=Path)
    parser.add_argument('--output-dir', type=Path, default=Path('build/gamemaster/verification'))
    args = parser.parse_args()
    if args.rom.read_bytes() != compile_rom(args.original.read_bytes(), gamemaster=True)[0]:
        parser.error('Rebuild the gamemaster ROM before verification')
    output = args.output_dir / BOSSES[args.choice].lower()
    output.mkdir(parents=True, exist_ok=True)
    with ExitStack() as stack:
        # The environment is consumed by Luna at process creation only.
        old = os.environ.pop('LUNA_EVERMORE_BRIDGE', None)
        companion = None
        if args.fixture:
            directory = stack.enter_context(tempfile.TemporaryDirectory(prefix='evermore-verify-'))
            def fixture(name, *_):
                return encode_comment(f'{name} sounds ready to rule this station!')
            companion = stack.enter_context(Companion(directory, 'fixture', generate=fixture))
            os.environ['LUNA_EVERMORE_BRIDGE'] = directory
        try:
            session, report = open_session(args.rom, luna=args.luna)
        finally:
            os.environ.pop('LUNA_EVERMORE_BRIDGE', None)
            if old is not None:
                os.environ['LUNA_EVERMORE_BRIDGE'] = old
        stack.callback(session.close)
        report.update(rom_sha256=hashlib.sha256(args.rom.read_bytes()).hexdigest(),
                      fresh_boot=True, controller_only_progression=True,
                      dialogue='fixture bridge' if args.fixture else 'offline fallback',
                      choice=BOSSES[args.choice], events=[], screenshots=[])
        def run(frames, *buttons):
            session.run(frames, *buttons)
            report['events'].append(dict(frames=frames, buttons=list(buttons), at_frame=session.frame))
        def screenshot(name):
            path = output / (name + '.png')
            session.screenshot(path)
            from PIL import Image
            with Image.open(path) as im:
                im.resize((im.width*4, im.height*4), Image.Resampling.NEAREST).save(output / (name + '-4x.png'))
            report['screenshots'].append(dict(file=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        def check(condition, message):
            if not condition:
                screenshot('failure')
                raise RuntimeError(message)
        try:
            for frames, buttons in ((1500, ()), (1, ('Start',)), (240, ()), (1, ('Start',)), (120, ())):
                run(frames, *buttons)
            # Enter a nondefault name, "rr", using the native naming screen.
            for button in ('Up', 'B', 'B', 'Start', 'B'):
                run(1, button)
                run(15)
            run(18000)
            report['name'] = session.ram[0x2210:0x2234].split(b'\0')[0].decode('ascii')
            check(report['name'] == 'rr', 'Naming UI did not store the chosen name')
            npc = session.word(0x0341)
            check(session.word(npc+0x66) == 0x19aa, 'Cowboy talk script missing')
            check((session.word(npc+0x1a), session.word(npc+0x1c)) == (544,288), 'Cowboy moved')
            # Exercise the original cowboy interaction before opening the chest.
            run(32, 'Right'); run(9, 'Down'); run(1, 'B'); run(150)
            screenshot('01-cowboy')
            for _ in range(12):
                if not session.word(npc+0x0e) & 0x8000:
                    break
                run(5, 'B'); run(30)
            check(not session.word(npc+0x0e) & 0x8000, 'Cowboy did not return control')
            run(74, 'Up'); run(1, 'B')
            # Wait until the engine opens the gamemaster's native message.
            for _ in range(100):
                run(20)
                if session.word(STATUS) in (2,3):
                    break
            mode = session.word(STATUS)
            check(mode == (2 if args.fixture else 3), 'Dialogue reply/fallback did not arrive')
            run(120)
            screenshot('02-name-comment')
            run(1, 'B'); run(90)
            screenshot('03-comment-page')
            run(1, 'B'); run(90)
            screenshot('04-three-choices')
            for _ in range(args.choice):
                run(1, 'Down'); run(15)
            run(1, 'B')
            for _ in range(100):
                run(5)
                if session.word(BOSS):
                    break
            actor = session.word(BOSS)
            check(actor != 0, 'Selected boss did not spawn')
            check(session.word(CHOICE) == args.choice, 'Menu selected another boss')
            check(session.word(actor+0x2a) == 600, 'Boss did not have station HP')
            # Deallocation clears actor registration; stale script fields in
            # the freed slot intentionally remain until the slot is reused.
            check(session.word(npc+0x10) == 0, 'Cowboy remained during boss palette loading')
            screenshot('05-boss')
            initial_hp = session.word(0x4eb3)
            # Stay still for one signature attack, observing the moving actors.
            for _ in range(100):
                run(2)
                if 10 <= session.word(STEP) <= 16:
                    break
            screenshot('06-attack')
            for _ in range(60):
                run(2)
                if session.word(0x4eb3) < initial_hp:
                    break
            check(session.word(0x4eb3) < initial_hp, 'Signature attack caused no damage')
            report['attack_damage'] = initial_hp - session.word(0x4eb3)
            screenshot('07-hit')
            # On the next windup, leave the captured target before impact.
            run(20)
            for _ in range(100):
                run(2)
                if 1 <= session.word(STEP) <= 6:
                    break
            check(1 <= session.word(STEP) <= 6, 'Next attack did not begin')
            hp_before_dodge = session.word(0x4eb3)
            run(30, 'Left')
            run(15)
            check(session.word(0x4eb3) == hp_before_dodge, 'Moving away did not dodge the attack')
            report['attack_dodged'] = True
            screenshot('07-dodge')
            print(f'{BOSSES[args.choice]}: name/menu/attack passed; fighting', flush=True)
            lowest_hp = session.word(0x4eb3)
            last_shot = -100
            for _ in range(260):
                if session.word(STATUS) == 5:
                    break
                x,y = session.word(0x4ea3), session.word(0x4ea5)
                tx,ty = session.word(actor+0x1a), session.word(actor+0x1c)
                if args.choice == 2:
                    # Dodge the jump rather than chasing the moving sprite.
                    # A 64px shot leaves room for the Bazooka muzzle offset.
                    if 1 <= session.word(STEP) < 32 or (tx,ty) != (496,288):
                        run(8, 'Left' if x > 456 else 'Right')
                    elif abs(y-224) > 4:
                        run(min(8,max(1,abs(y-224)//2)), 'Down' if y < 224 else 'Up')
                    elif abs(x-496) > 4:
                        run(min(8,max(1,abs(x-496)//2)), 'Right' if x < 496 else 'Left')
                    elif session.frame - last_shot >= 70:
                        run(1, 'Down'); run(6, 'B')
                        last_shot = session.frame
                    else:
                        run(4)
                    lowest_hp = min(lowest_hp, session.word(0x4eb3))
                    check(lowest_hp > 0, 'Player died before defeating the boss')
                    continue
                # Align a short vertical Bazooka shot; recoil changes position.
                if abs(x-tx) > 4:
                    run(min(8,max(1,abs(x-tx)//2)), 'Right' if tx>x else 'Left')
                elif abs(y-ty) > 36:
                    run(min(8,max(1,(abs(y-ty)-32)//2)), 'Down' if ty>y else 'Up')
                else:
                    run(1, 'Down' if ty>y else 'Up'); run(6, 'B'); run(65)
                lowest_hp = min(lowest_hp, session.word(0x4eb3))
                check(lowest_hp > 0, 'Player died before defeating the boss')
            check(session.word(STATUS) == 5, 'Boss defeat did not finish')
            check(session.word(0x2865) == 2, 'Original escape trigger not set')
            for variable in (BOSS, CLAW1, CLAW2, PROJECTILE):
                check(session.word(variable) == 0, 'Encounter actor was not cleaned up')
            # Original boss-dead flags must remain available for the adventure.
            check(not(session.ram[0x2260] & 0x50), 'Thraxx/Magmar story flags changed')
            check(not(session.ram[0x225e] & 0x80), 'Salabog story flag changed')
            report['lowest_player_hp'] = lowest_hp
            run(8910)
            check(not(session.ram[0x22ec] & 0x20), 'Opening did not finish')
            check((session.word(0x4ea3), session.word(0x4ea5)) == (536,1080), 'Missing original landing')
            screenshot('08-landing')
            for _ in range(24):
                run(5, 'B'); run(300)
            before = session.word(0x4ea3),session.word(0x4ea5)
            run(12, 'Right')
            check(before != (session.word(0x4ea3),session.word(0x4ea5)), 'Player control not restored')
            check(not(session.ram[0x2261] & 1), 'Dog unavailable after reunion')
            screenshot('09-playable-prehistoria')
            report['status'] = 'passed'
            print(f'{BOSSES[args.choice]}: defeat, escape, landing, dog and control passed', flush=True)
        except Exception as error:
            report.update(status='failed', error=str(error))
            (output / 'research-state.json').write_text(json.dumps(session._call('save_state')))
            raise
        finally:
            report['total_frames'] = session.frame
            report['mailbox'] = session.ram[0x28e0:0x28fc].hex()
            (output / 'final-ram.bin').write_bytes(session.ram)
            if companion:
                report['bridge_events'] = companion.events
            (output / 'report.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
