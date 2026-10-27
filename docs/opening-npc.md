# Opening-station NPC experiment

## Supported ROM and allocation

Only the clean, unheadered USA revision 1.0 is supported. The builder validates
the complete SHA-256 before allocating output or touching any patch site. It
also checks the original bytes at each hook and pointer-table entry.

All offsets below are **file offsets in an unheadered ROM**. Script addresses
in the game's terminology add `$800000`; native HiROM addresses add `$C00000`.

| File offset | Purpose |
| --- | --- |
| `$1BC446` | Replace the four-byte clear of `$22EA` bit 3 with a script CALL. |
| `$129C3E` | Short-script pointer `$19AA`, redirected to the new conversation. |
| `$11D006` | Debug text pointer `$0006`, redirected to our uncompressed text. |
| `$300000` | New dialogue text in the expanded ROM. |
| `$308000` | NPC creation script, including the displaced flag-clear instruction. |
| `$308040` | Conversation script. |
| `$00FFDC` | Recomputed SNES checksum and complement. |

The original header's ROM-size field is already `$0C` (4 MiB); expansion fills
the previously absent megabyte with `$FF`, apart from the new payloads. This
keeps all new allocations separate from the original code, graphics, and maps.

The hook is in script `$9BBCD9` (opening arrival cutscene), immediately before
`$9BC44A` returns control to the boy. It is not a general map-enter hook: the
character is created for this opening sequence, not later station visits.

## Actor and conversation

- Map `$46`: professor's laboratory and ship area, also used by the opening.
- Existing sprite `$57`; spawn coordinates `(68, 36)` in eight-pixel units,
  resulting in world position `(544, 288)`.
- The actor is additional; existing characters and map objects are retained.
- Creation disables ordinary wandering, faces the actor south, and assigns the
  talk event. It does not store its pointer in the original cutscene's variables.
- The talk script uses the existing NPC interaction helpers `$32`/`$33`, message
  window helper `$02`, and a text string with a line break and wait-for-input.
- The normal end-of-conversation helper re-enables the actor's AI, so the script
  explicitly freezes the NPC again after cleanup and restores its idle facing.
- No inventory, quest, save-format, balance, or progression changes are added.

The script dumper's complete static discovery reports `$19AA` as the sole unused
short/NPC/map script entry. Its original destination is retained elsewhere in the
ROM; only this pointer is repurposed. Static discovery cannot rule out every
possible indirect reference in the whole engine. This slot and the debug text
slot are prototype allocations, not a general allocator or a compatibility promise
for other hacks.

## References inspected

These tools were inspected and built separately; none are bundled into the patch:

- [SoEScriptDumper](https://github.com/black-sliver/SoEScriptDumper), commit
  `d5ac6f390a50e6aa8c59a1c410e6affe49feb8f2`: map IDs, opening event flow,
  script/text pointer formats, actor creation and talk opcodes, unused script scan.
- [Evermizer](https://github.com/black-sliver/evermizer), commit
  `b0401d9b6576004c8640886719510d39340bed57`: examples of expanded-ROM script
  calls and uncompressed text insertion.
- [Snes9x libretro](https://github.com/libretro/snes9x), commit
  `fae2fea08f74180759ef540ee94259213f503480`: headless execution and screenshots.

The project's Python builder generates the patch directly from explicit bytecode.
It does not require a full disassembly, a decompiler, or these external tools to
build. The BPS encoder uses SourceRead, TargetRead, and overlapping TargetCopy
records; checksums cover the source ROM, target ROM, and patch.

## Verification and limits

Verified on 2026-10-27: all 12 unit tests passed, and the complete fresh-boot
Snes9x recipe passed across 40,112 emulated frames. The dialogue and final
Prehistoria screenshots were also visually inspected. The tested output SHA-256
is `399fedd132d277f22cb28d527fa6bc3d230607c96f54fcc02ddabdd96f94bd8d`;
the corresponding BPS is 208 bytes.

`tools/verify_npc.py` runs from a fresh boot and writes a JSON report containing
the core version/hash, ROM hash, frame-by-frame input segments, and screenshot
hashes. It never changes game RAM or bypasses progression. Screenshots show the
NPC in the station, three repeated conversations, the original robot encounter,
arrival in Prehistoria, and resumed play with the dog.

The verification recipe reads vanilla USA WRAM locations for actor position,
talk-script attachment, robot encounter pointers, robot kill count, opening state,
and dog availability. Those reads are observations only, and are specific to
this ROM and emulator recipe.

Automated unit tests independently decode the generated BPS, check its CRCs,
exercise overlapping copies, verify the SNES checksum, reject modified/headered
input, compare repeated builds, and restrict changes within the original 3 MiB
to the listed hook, pointer entries, and checksum fields.

Not yet verified: a complete campaign, old save states made with the unmodified
ROM, compatibility with other patches, other language/region ROMs, physical SNES
hardware, and other emulator cores. Use a fresh game for this experiment.
