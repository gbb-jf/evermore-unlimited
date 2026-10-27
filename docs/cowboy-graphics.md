# Independent cowboy graphics (v2)

The opening NPC keeps template `$57` for its existing actor behavior, but its
graphics are now independent. Template `$57` maps to actor definition `$C252`
in bank `$8E` (character index `$29`, the professor); template and character
indices are different tables. No professor definition, original frame, tile,
animation pointer, or palette is overwritten.

## Native behavior

`tools/cowboy_graphics.py` compiles original indexed artwork from
`assets/cowboy.json` to SNES 4bpp tiles. Each facing has four 16×16 chunks in a
32×32 canvas. The descriptors retain the original per-facing bounding rectangles
so the padded art canvas does not change the actor's interaction geometry.

The initializer attaches talk script `$19AA` before setting the actor's facing.
The animation hook recognizes exactly that talk script, talk type `$0040`, and
actor definition `$C252`. Only this actor receives a private idle sequence and
frame references in bank `$F1`. Native direction values select north, east,
south, or west. Other actors execute the displaced table lookup and resume the
original animation routine. The cowboy remains stationary and still turns to
face the player during conversations.

The normal palette allocator assigns a separate slot using identifier `$FF00`.
Two palette hooks load those colors from `$F4FF00` into the normal palette buffer
and select bank `$F4` for uploads of that palette. Other identifiers retain their
original palette source bank `$90`. The relocated vanilla prologue explicitly
loads bank `$90`; copying its original PHK instruction would select `$F4` and
produce incorrect colors for unrelated actors.

The 16×16 tile-pointer bank is copied intact from `$EC0000` to `$F20000` and the
three native decoder reads are redirected to that copy. Only private block IDs
`$1800`–`$180F` differ in the copy; all other pointer entries are byte-identical.
New block pointers retain the engine's format relative to `$D90000`, with the
compression bit clear. There is no emulator-specific graphics overlay.

## Allocations and hooks

All addresses here are unheadered ROM **file offsets**; add `$C00000` for native
HiROM addresses. These graphics allocations are separate from the v1 text and
scripts.

| Offset | Purpose |
| --- | --- |
| `$310000` | Four private frame descriptors (26 bytes each). |
| `$318000` | Private native idle sequence. |
| `$320000` | Relocated 64 KiB tile-pointer bank. |
| `$330000` | Sixteen uncompressed 16×16 SNES 4bpp blocks. |
| `$340000` | Conditional animation initializer. |
| `$340100` | Conditional palette-buffer loader. |
| `$340200` | Direction-to-frame lookup. |
| `$340220` | Conditional palette-upload source bank. |
| `$34FF00` | Private 16-color palette (32 bytes). |
| `$108124` | Four-byte animation lookup replaced by JML. |
| `$10CF3A` | Four-byte palette-loader prologue replaced by JML. |
| `$10CFD2` | Palette-upload bank setup replaced by JSL/NOP. |
| `$009745`, `$009754`, `$00A2E9` | Tile-pointer bank operands changed to `$F2`. |

The native hooks target the verified US ROM and native 16-bit A/X entry
conventions. Conditional fallbacks preserve processor flags before executing
displaced instructions. Both palette loading and native VRAM upload use the
same private color source. The builder checks hook bytes, verifies new allocation
space, and recomputes the ROM checksum and BPS CRCs.

## Verification

Verified on 2026-10-27 using the existing Snes9x libretro core:

- All 17 unit tests passed, including independent decoding of authored tile
  pixels, original-art preservation, pointer-bank identity, BPS reconstruction,
  supported-input validation, and deterministic builds.
- `verify_cowboy.py` passed from a fresh boot over 20,974 frames. It checked all
  four conversation facings, the private palette buffer, station position, and
  the original professor's actor definition, animation bank and palette.
- `verify_npc.py` passed from a fresh boot over 40,213 frames, through repeated
  conversations, the original robot fight, escape, landing, and playable dog
  reunion in Prehistoria. The input recipe now aims in additional directions if
  a robot survives the initial shots, instead of requiring an exact next hit.
- The sprite-sheet preview and station conversation screenshots were visually
  inspected. Reports record ROM/core hashes, input segments and screenshot hashes.

The tested ROM SHA-256 is
`fa51ff6acae7091e641a8ad454764ade068349f03cc1ef2ccdda3ead0984395b`;
the BPS is 67,399 bytes. The larger patch includes the relocated pointer bank.
Use the generated manifest for current hashes after editing the artwork.

This is a stationary NPC prototype. Custom walking/combat animations, a complete
campaign, physical SNES hardware, other regions, other hacks, and old save-state
compatibility have not been verified.

Graphics format reference: [SoETilesViewer](https://github.com/black-sliver/SoETilesViewer),
especially `characterdata.h`, `spriteinfo.h` and `spriteblock.h`. Runtime read and
instruction traces were gathered with a separately instrumented Snes9x build in
temporary storage. That debug core is not required to build or play the patch.
