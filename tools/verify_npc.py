#!/usr/bin/env python3
"""Reproduce the NPC and opening escape using controller input from a fresh boot."""

import argparse
import hashlib
import json
from pathlib import Path

from build_npc import build_rom
from emulator_session import add_arguments, open_session


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser)
    parser.add_argument("--rom", type=Path, default=Path("build/evermore-npc.sfc"))
    parser.add_argument("--original", type=Path, default=Path("roms/original.sfc"))
    parser.add_argument("--output-dir", type=Path, default=Path("build/verification"))
    args = parser.parse_args()
    if args.rom.read_bytes() != build_rom(args.original.read_bytes()):
        parser.error("Patched ROM differs from the current build; rebuild before verification")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    session, report = open_session(args.rom, luna=args.luna, core=args.core)
    report.update({"rom_sha256": hashlib.sha256(args.rom.read_bytes()).hexdigest(),
                   "fresh_boot": True, "ram_writes": False,
                   "events": [], "screenshots": []})

    def run(frames, *buttons):
        session.run(frames, *buttons)
        report["events"].append({"frames": frames, "buttons": list(buttons), "at_frame": session.frame})

    def screenshot(name):
        path = args.output_dir / (name + ".png")
        session.screenshot(path)
        report["events"].append({"frames": 1, "buttons": [], "capture": path.name, "at_frame": session.frame})
        report["screenshots"].append({"file": path.name,
                                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})

    def check(condition, message):
        if not condition:
            screenshot("failure")
            raise RuntimeError(message)

    try:
        # Start a new game; enter one placeholder name using the normal naming UI.
        run(1500)
        run(1, "Start")
        run(240)
        run(1, "Start")
        run(120)
        for button in ("Up", "B", "Start", "B"):
            run(1, button)
            run(15)
        run(18000)
        npc = session.word(0x0341)
        check(session.word(npc + 0x66) == 0x19AA, "Opening NPC talk script not attached")
        check((session.word(npc + 0x1A), session.word(npc + 0x1C)) == (544, 288),
              "Opening NPC was not stationary at its expected location")
        check(session.ram[0x22EC] & 0x20, "Not in the opening station sequence")
        screenshot("01-station-npc")
        print("Fresh boot: opening NPC present", flush=True)

        run(32, "Right")
        run(9, "Down")
        for i in range(3):
            run(1, "B")
            run(150)
            screenshot(f"02-dialogue-{i + 1}")
            # User-authored dialogue can contain several native text pages.
            for _ in range(64):
                if not session.word(npc + 0x0E) & 0x8000:
                    break
                run(5, "B")
                run(30)
            check(not session.word(npc + 0x0E) & 0x8000, "Conversation did not return control")
            run(60)
            check((session.word(npc + 0x1A), session.word(npc + 0x1C)) == (544, 288),
                  "NPC wandered after talking")
        print("Three repeat conversations completed; NPC remains stationary", flush=True)

        # Walk to the original Bazooka chest and trigger the ordinary robot fight.
        run(9, "Up")
        run(65, "Up")
        run(1, "B")
        run(1200)
        screenshot("03-original-robot-encounter")
        check(session.word(0x2861) != 0 and session.word(0x2863) != 0,
              "Original robot encounter did not initialize")
        run(1, "Down")
        run(60)
        for _ in range(24):
            run(1, "B")
            run(70)
        # Do not depend on a particular projectile hitting a particular robot;
        # graphics / scene changes can shift their positions at the shot frame.
        run(120, "Down")
        run(10, "B")
        run(90)
        # Aim using observed positions: recoil can move the boy far from the
        # surviving robot, so turning in place is not an encounter test.
        for _ in range(240):
            if session.word(0x2865) == 2:
                break
            robots = [session.word(address) for address in (0x2861, 0x2863)]
            alive = [actor for actor in robots if session.word(actor + 0x2A) > 0]
            if not alive:
                run(10)
                continue
            actor = alive[0]
            x, y = session.word(0x4EA3), session.word(0x4EA5)
            target_x, target_y = session.word(actor + 0x1A), session.word(actor + 0x1C)
            if abs(target_y - y) > 4:
                run(min(12, max(1, abs(target_y - y) // 2)), "Down" if target_y > y else "Up")
            elif abs(target_x - x) > 80:
                run(min(12, max(1, (abs(target_x - x) - 60) // 2)), "Right" if target_x > x else "Left")
            else:
                run(1, "Right" if target_x > x else "Left")
                run(6, "B")
                run(60)
        check(session.word(0x2865) == 2, "Second robot did not trigger the escape cutscene")
        run(8910)
        check(not (session.ram[0x22EC] & 0x20), "Opening sequence did not finish")
        check((session.word(0x4EA3), session.word(0x4EA5)) == (536, 1080),
              "Did not reach the original landing in Prehistoria")
        screenshot("04-prehistoria-arrival")
        # Advance the original multi-page landing / dog reunion / bone sequence.
        for _ in range(24):
            run(5, "B")
            run(300)
        before = (session.word(0x4EA3), session.word(0x4EA5))
        run(12, "Right")
        after = (session.word(0x4EA3), session.word(0x4EA5))
        check(before != after, "Player control not restored in Prehistoria")
        check(not (session.ram[0x2261] & 1), "Dog remained unavailable after landing")
        screenshot("05-prehistoria-playable")
        print("Original robot fight, escape, landing and player control passed", flush=True)
        report["status"] = "passed"
    except Exception as error:
        report["status"] = "failed"
        report["error"] = str(error)
        raise
    finally:
        report["total_frames"] = session.frame
        (args.output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        session.close()


if __name__ == "__main__":
    main()
