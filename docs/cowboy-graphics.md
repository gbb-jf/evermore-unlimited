# Character graphics and scene compiler (v3)

The original v2 cowboy experiment now uses the character/scene compiler in
`tools/character_rom.py`. Original artwork lives in `assets/characters/`; instances
and dialogue live in `assets/scenes/`. `tools/cowboy_graphics.py` retains legacy
art-check helpers. This compiler adds no larger story or gameplay design.

## Actor and native graphics formats

Custom actors reuse template `$57` for ordinary interaction geometry. This template
maps to definition `$C252` in bank `$8E` (character index `$29`, the professor).
Template IDs, definition indices, animation origins, frame pointers and block IDs
are separate identifiers. Original professor definitions/graphics remain intact.

Each authored frame is a 32×32 indexed canvas with feet anchor `(16,32)`, compiled
as four 16×16 blocks of SNES 4bpp tiles. The frame descriptor copies the original
per-facing bounds, preserving interaction geometry. A private clip starts with a
frame count, then three-byte entries: 16-bit descriptor offset in `$F1`, duration.
Idle/walk clips for N/E/S/W occupy eight 256-byte slots per instance.

Actor animation origin (`+03`) combines instance profile `$8000 + index*$1000`,
direction (`$000/$100/$200/$300`), and walking (`$400`). The initializer assigns
the private animation bank before setting the first facing. Native animation
selection and tick hooks recognize talk script `$19AA`, talk type `$0040`,
definition `$C252`, and animation bank `$F1`. Other actors resume displaced code.

The custom tick changes frames by authored durations and moves patrols one pixel
per tick. Actor word `+0E` retains waypoint index (bits 0–6), pause count (bits
7–13), walking (bit 14), and conversation suspension (bit 15). Patrols move X then
Y, loop authored waypoints, and hold their pause/state while talking. Stationary
actors still turn through the original interaction helpers.

Hooks enter with native 16-bit A/X, DB `$7E`, Y pointing to the actor. Custom paths
save registers and VM direct-page scratch `$00–$5F` around helper calls. Vanilla
fallbacks restore flags before displaced instructions; the tick fallback retains
the original TYX/INC behavior. Native palette allocation's current-actor pointer
is preserved around custom palette selection.

Each distinct character receives a private 32-byte palette, `$FF00` or `$FF20`.
The normal allocator gives it a dynamic slot; load/upload hooks select bank `$F4`
for these palette ranges, retaining original bank `$90` otherwise. The relocated
vanilla prologue explicitly selects `$90`: copying PHK there would select `$F4`
and corrupt unrelated colors.

The tile-pointer bank is copied intact from `$EC0000` to `$F20000`. Three decoder
operands select the copy. Only private block IDs starting at `$1800` differ; all
other entries remain identical. New uncompressed pointers are relative to `$D90000`.
There is no emulator overlay.

## Allocations

These are **unheadered file offsets**. Native HiROM addresses add `$C00000`;
script listings use the separate `$800000` convention and packed addresses.
Actual occupied intervals are listed in every generated manifest.

| File offset / region | Contents |
| --- | --- |
| `$300000–$307FFF` | Speaker-prefixed dialogue, native line/page controls. |
| `$308000` | Spawn script, displaced flag-clear, all actor initializers. |
| `$308400` | Talk dispatcher keyed by profile, shared script ID `$19AA`. |
| `$308800 + instance*$400` | Per-instance conversation and patrol suspension. |
| `$310000–$317FFF` | Private directional frame descriptors. |
| `$318000–$31FFFF` | Eight instance clip sets (idle/walk, four directions). |
| `$320000–$32FFFF` | Relocated 64 KiB tile-pointer bank. |
| `$340000` | Conditional animation selection. |
| `$340400` | Conditional custom actor tick. |
| `$340800` | Private frame/duration loader. |
| `$340A00` | Patrol movement helper. |
| `$341400`, `$341500` | Palette load and upload-bank helpers. |
| `$342000`, `$342100` | Instance profiles and facing lookup. |
| `$343000` | Waypoint coordinates and encoded pauses. |
| `$34FF00`, `$34FF20` | Private 16-color palettes. |
| `$350000–$35FFFF` | Relocated text-pointer table. |
| `$360000` onward | Private uncompressed 4bpp blocks. |

The text table copies original `$11D000–$12CFFF`, then changes only each custom
instance's text entry (`$0006 + index*3`). Original entries remain untouched in
the original ROM; the normal text reader's base/bank operands select `$F50000`.
Script/text packing helpers enforce upper/lower half-bank address requirements.

| Original file offset | Hook |
| --- | --- |
| `$1BC446` | Four-byte script CALL to initializer. |
| `$129C3E` | Unused short-script `$19AA` pointer to talk dispatcher. |
| `$108124` | Animation lookup replaced by JML. |
| `$1080D2` | Animation tick prologue replaced by JML. |
| `$10CF3A` | Palette loader prologue replaced by JML. |
| `$10CFD2` | Palette upload bank replaced by JSL/NOP. |
| `$009745`, `$009754`, `$00A2E9` | Tile-pointer bank operands to `$F2`. |
| `$0CCCF8`, `$0CCCFD` | Text pointer bank/base operands to `$F5:$0000`. |
| `$00FFDC` | Checksum/complement recomputed after compilation. |

Every hook checks expected original bytes. Each new occupied interval must contain
`$FF`, remain inside expanded ROM, and not overlap another allocation. The source
hash is checked first; checksums/BPS CRCs and deterministic manifests are maintained.

## Verification

The v3 checks cover independent tile decoding, exact BPS reconstruction, unrelated
original graphics preservation, disjoint allocations, supported-input rejection,
deterministic output, and compilation of the full eight-instance/two-character
budget. Browser tests cover source editing and a real two-NPC build.

Fresh-boot Snes9x checks verify four cowboy facings, separate palette buffers, the
original professor, repeated conversations and progression through Prehistoria.
`verify_editor.py` builds an isolated two-character fixture and checks native walking
frames, east/west patrols, and dialogue pause/resume. Inputs and ROM/core hashes are
recorded in the generated reports. Screenshots are inspected natively and at 4×
nearest-neighbor scale. See `README.md` for commands and evidence directories.

The original source reference is [SoETilesViewer](https://github.com/black-sliver/SoETilesViewer),
especially `characterdata.h`, `spriteinfo.h`, and `spriteblock.h`. Earlier native
traces used a separately instrumented Snes9x build; it is not a build/play dependency.
Full-campaign, arbitrary routes, physical hardware, other regions/hacks, and old
save states remain unverified.
