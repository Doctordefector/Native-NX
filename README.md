# Native-NX

Static recompilation of Nintendo Switch games to native Windows x86-64, extended to **32-bit (AArch32) games**.
The first target is Pikmin 3 Deluxe, which is entirely A32 code.

Based on [SwitchRecomp](README.txt) v153 by MZ Labs (Apache 2.0, see `LICENSE.txt` and `NOTICE.txt`): its lifter
pipeline and its low-level runtime (kernel, IPC services, nvdrv, Maxwell GPU to OpenGL), which runs the game's own
SDK and NVN driver.

No game code, keys or data are included. Use your own dump.

## What this adds for 32-bit games

| File | What it does |
|---|---|
| `a32.py`, `a32_neon.py` | A32 instruction to C: integer, VFP and Advanced SIMD (NEON) |
| `codegen32.py` | Function discovery (symbols, `R_ARM_RELATIVE` targets, BL/B targets, clang jump tables) and C emission |
| `nxloader.py` | ELF32 dynamic section, REL relocations, the 32-bit load address (0x200000) |
| `runtime/cpu32.h`, `runtime/cpu32_helpers.c` | Register file and helpers used by the generated code |
| `runtime/kernel.c`, `runtime/svc32_tab.h` | AArch32 SVC calling convention, mapped onto the existing 64-bit SVC code |
| `runtime/mem.c`, `runtime/rt.h` | Address-space layout under 4 GB for 32-bit processes |
| `tools/svc32_abi.py` | Generates `svc32_tab.h` from Atmosphere's SVC definitions (`tools/svc_definition_macro.hpp`, GPLv2), using its layout algorithm |
| `tools/a32_test.py` | Differential test: every instruction shape a game uses, run in the generated C and in Unicorn, compared |
| `tools/build.sh`, `tools/run.sh` | Translate, compile with clang, link one exe; boot it with an extracted RomFS (`SWR_ROMFS`) |

## Status

- The A32 translator matches Unicorn on all 8,555 instruction shapes in Pikmin 3 Deluxe (46,000 random states).
- Pikmin 3 Deluxe translates (118,521 functions, 5.9M instructions), compiles and links into one exe.
- It boots into the game's `rtld` and is being brought up from there. Not playable yet.

## Build (Windows)

Needs a clang for x86_64-w64-windows-gnu and Python with `capstone` (and `unicorn` for the tests).

```
python tools/a32_test.py <game>/ExeFS          # translator vs Unicorn
sh tools/build.sh gen                          # out/Pikmin3.exe (headless backend for now)
sh tools/run.sh 60                             # log: out/Pikmin3.log
```

`tools/build.sh` expects the game extracted under `../../work/<title id>/extract` (`ExeFS`, `RomFS`); adjust `GAME`.
