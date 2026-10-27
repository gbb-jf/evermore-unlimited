#!/usr/bin/env python3
"""Verify an isolated two-character editor scene with native walking and dialogue."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile

from build_npc import build_project
from character_model import ROOT, Store, canonical, rgb_palette
from emulator_session import add_arguments, open_session


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "build/editor-runtime")
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    # Generated fixtures and original-ROM-derived assets stay inside ignored build/.
    fixture = Path(tempfile.mkdtemp(prefix="project-", dir=output))
    cowboy = Store().get("characters", "cowboy")["document"]
    ranger = deepcopy(cowboy)
    ranger.update(id="ranger", name="Ranger")
    ranger["palette"][4] = "#385f98"
    store = Store(fixture)
    for character in (cowboy, ranger):
        store.save("characters", character, None)
    scene = {"version": 1, "id": "opening-station", "name": "Editor runtime fixture", "npcs": [
        {"id": "cowboy", "character": "cowboy", "dialogue": "Looks like the experiment worked!",
         "position": {"x": 544, "y": 288}, "facing": "south",
         "movement": {"mode": "stationary", "waypoints": []}},
        {"id": "ranger", "character": "ranger", "dialogue": "I can walk and talk.",
         "position": {"x": 416, "y": 304}, "facing": "south", "movement": {"mode": "patrol",
         "waypoints": [{"x": 416, "y": 304, "pause": 120}, {"x": 448, "y": 304, "pause": 120}]}}
    ]}
    store.save("scenes", scene, None)
    manifest = build_project(fixture, source_path=ROOT / "roms/original.sfc")
    rom = fixture / "build/evermore-npc.sfc"
    session, report = open_session(rom, luna=args.luna, core=args.core)
    report.update({"fresh_boot": True, "ram_writes": False, "fixture": str(fixture),
                   "rom_sha256": manifest["target"]["sha256"],
                   "events": [], "checks": [], "screenshots": []})

    def run(frames, *buttons):
        session.run(frames, *buttons)
        report["events"].append({"frames": frames, "buttons": list(buttons), "at_frame": session.frame})

    def screenshot(name):
        path = output / f"{name}.png"
        session.screenshot(path)
        report["events"].append({"frames": 1, "buttons": [], "capture": path.name, "at_frame": session.frame})
        report["screenshots"].append(path.name)

    def check(condition, message):
        if not condition:
            screenshot("failure")
            raise RuntimeError(message)

    try:
        run(1500)
        run(1, "Start")
        run(240)
        run(1, "Start")
        run(120)
        for button in ("Up", "B", "Start", "B"):
            run(1, button)
            run(15)
        run(18000)
        actors = [address for address in range(0x3D57, 0x4E89, 0x8E)
                  if session.word(address + 0x66) == 0x19AA]
        check(len(actors) == 2, "Both editor NPC instances must exist")
        by_profile = {session.word(actor + 3) & 0xF000: actor for actor in actors}
        stationary, walker = by_profile[0x8000], by_profile[0x9000]
        for actor, character in ((stationary, cowboy), (walker, ranger)):
            slot = session.ram[actor + 0x0C]
            check(session.word(actor + 8) == 0xF1, "Custom frame bank missing")
            check(session.word(0x1278 + slot) == manifest["palettes"][character["id"]], "Private palette missing")
            check(all(session.word(0x6287 + slot * 16 + i * 2) == color
                      for i, color in enumerate(rgb_palette(character)) if i), "Private palette colors differ")
        professor = session.word(0x285B)
        check(session.ram[professor + 2] == 0xC9 and
              session.word(0x1278 + session.ram[professor + 0x0C]) == 0xBA6B,
              "Original professor graphics or palette changed")
        report["checks"].append("two instances, independent palettes, original professor preserved")
        screenshot("01-two-characters")

        poses, positions, frames = set(), set(), set()
        for _ in range(640):
            run(1)
            x, y = session.word(walker + 0x1A), session.word(walker + 0x1C)
            check(416 <= x <= 448 and y == 304, "Patrol left its authored route")
            check((session.word(stationary + 0x1A), session.word(stationary + 0x1C)) == (544, 288),
                  "Stationary NPC moved with the other actor")
            positions.add(x)
            if session.word(walker + 0x0E) & 0x4000:
                poses.add(session.word(walker + 0x22))
                frames.add(session.word(walker + 6))
        check({4, 12} <= poses, "Patrol did not walk east and west")
        check(len(positions) >= 32 and len(frames) >= 4, "Walking animation or movement did not advance")
        report["checks"].append("bidirectional patrol and multiple native animation frames")
        screenshot("02-patrol")

        # Approach from above while the actor waits at the left endpoint.
        run(53, "Left")
        run(20, "Down")
        for _ in range(400):
            if session.word(walker + 0x1A) == 416 and ((session.word(walker + 0x0E) >> 7) & 0x7F) > 100:
                break
            run(1)
        run(5, "B")
        run(90)
        check(session.word(walker + 0x0E) & 0x8000, "Patrol conversation did not open")
        position = (session.word(walker + 0x1A), session.word(walker + 0x1C))
        route_state = session.word(walker + 0x0E) & 0x3FFF
        run(90)
        check((session.word(walker + 0x1A), session.word(walker + 0x1C)) == position and
              session.word(walker + 0x0E) & 0x3FFF == route_state,
              "Conversation did not preserve the patrol waypoint and pause")
        screenshot("03-patrol-conversation")
        for _ in range(24):
            if not session.word(walker + 0x0E) & 0x8000:
                break
            run(5, "B")
            run(45)
        check(not session.word(walker + 0x0E) & 0x8000, "Patrol conversation did not return control")
        resumed = set()
        for _ in range(320):
            run(1)
            resumed.add(session.word(walker + 0x1A))
        check(len(resumed) >= 32, "Patrol did not resume after talking")
        report["checks"].append("dialogue pauses the route and resumes its saved waypoint")
        screenshot("04-patrol-resumed")
        report["status"] = "passed"
        print("Two-character palettes, walking animation, patrol and dialogue passed", flush=True)
    except Exception as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        report["total_frames"] = session.frame
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        session.close()


if __name__ == "__main__":
    main()
