# Character workshop

Run `python3 tools/characters.py serve` and open `http://127.0.0.1:8765`.
The Python/Pillow service listens on loopback only; the browser runs JavaScript
directly, without a bundler or Node runtime dependency.

## Artwork and animation

Create an empty character or duplicate one. A character has a stable lowercase ID,
display name, description, palette, and idle/walk clips for four facings. Canvas:
32×32 pixels; feet anchor `(16, 32)`. Each clip holds 1–16 frames, each lasting
1–120 game ticks (60 ticks/second). ROM speaker names need printable English.

JSON pixels use `.` for transparency and hexadecimal `1`–`f` for opaque colors.
Index zero stays transparent. Previews use SNES 5-bit color channels; JSON retains
the authored `#RRGGBB` values. Flip acts on the selection or whole frame. Undo
histories are independent per character and scene. Timeline controls add,
duplicate, reorder, delete, and time frames; each clip retains at least one frame.

| Shortcut | Action |
| --- | --- |
| B / E / G / I / M | Pencil / eraser / fill / eyedropper / select |
| Ctrl/⌘ Z, Ctrl/⌘ Shift Z | Undo / redo outside text fields |
| Ctrl/⌘ C, Ctrl/⌘ V | Copy selection/full frame; paste at selection/cursor |
| Ctrl/⌘ S | Save changed documents |
| Arrow keys, Enter, Delete on canvas | Move cursor, paint, erase |
| Right mouse button | Erase while drawing |

PNG sheets have four rows (north/east/south/west), one 32×32 cell per column.
Exports embed clip lengths/durations and preserve duplicate palette indices on
reimport. PNG import affects the selected idle/walk animation and is undoable.
Unmatched colors are rejected unless nearest-color mapping is explicitly selected.
Export saves the selected character. JSON import validates and saves the supplied
character or opening scene.

## Scene and builds

Only `opening-station` is supported. Add an instance, choose its character, write
dialogue, select facing, and place it on the 8-pixel grid. The authoring region is
world X `400–592`, Y `248–320`. Up to eight instances can use two distinct custom
characters. Instances reuse their character's graphics/palette but keep independent
dialogue, facing, and movement.

Stationary actors face the player during dialogue, then return to their configured
facing. Patrols use 2–16 waypoints, each with a 0–120 tick pause. Drag points, edit
coordinates/pauses, reorder/remove them, or use **Place waypoint** to add points.
Movement starts at the placed actor and visits waypoints with horizontal-then-vertical
segments, looping at one pixel per tick. The simulation previews these routes and
authored animation timing; it does not emulate CPU bookkeeping or collision.

Talking pauses only the speaking actor, retaining its next waypoint and remaining
pause. Other patrols continue. Dialogue accepts up to 1,000 printable English
characters and line breaks, wraps at 18 characters, and paginates in the native
window with the character name. Advance pages with B.

The placement region is guidance, not a complete collision map. Keep cutscene
paths/exits clear. Native patrols follow coordinates directly without pathfinding
or avoidance; playtest new arrangements from a fresh game.

**Save & build ROM** saves documents, then runs the CLI compiler. Jobs serialize
build/capture operations and release controls on failure. You can edit while a job
runs; later unsaved edits need another save/build. The manifest records the actual
document revisions compiled. **Capture ROM reference** boots the original ROM
with Luna and writes its station viewport/origin to ignored `build/editor/`;
without Luna, the scene editor still displays its placement grid. **Open Luna**
launches the separate `luna-gui` desktop app from the vendor build or PATH.
See [Luna setup](luna.md) for CLI and desktop build instructions.

## Agent/CLI workflow

The browser and CLI use the same files and validation. Global options precede
commands:

```sh
python3 tools/characters.py --json list
python3 tools/characters.py --json get cowboy
python3 tools/characters.py clone cowboy ranger --name Ranger
python3 tools/characters.py create friend --name Friend
python3 tools/characters.py --json get opening-station --kind scenes
python3 tools/characters.py --json validate
python3 tools/characters.py preview ranger --mode walk --output build/ranger.png
python3 tools/characters.py build
```

`get` returns `{document, revision}`. Edit/export the document, then update with
the revision you read:

```sh
python3 tools/characters.py --json update ranger \
  --input ranger.json --revision <revision-from-get>
python3 tools/characters.py import-png ranger build/ranger.png \
  --mode walk --mapping exact --revision <revision-from-get>
```

Scene updates use `--kind scenes`. Structured errors include field paths; failures
exit with status 2. Schemas are in `schemas/character.schema.json` and
`schemas/scene.schema.json`; runtime validation additionally enforces reference,
unique-instance-ID, and character-budget rules.

Saves use a project lock and atomic replacement, rejecting stale revisions. The
browser polls external changes: clean documents refresh visibly; unsaved documents
show a conflict while retaining local work. Export local JSON if needed, then
explicitly reload and reconcile. Other direct file writers should use atomic
replacement too.

## Verification

Browser tests use isolated copies; runtime tests build a separate two-character
fixture under `build/editor-runtime/`. They do not add characters to the user's
default scene. Acceptance checks start fresh and use real inputs; read-only RAM
assertions inspect bindings, palettes, frames, patrols, and original progression.
Reports contain current ROM and emulator executable hashes and input logs. They do not establish
full-campaign, arbitrary-scene, other-patch/region, hardware, or old-state compatibility.
