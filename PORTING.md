# Pikmin 4 → Windows (static recompilation on UltraTears' runtime)

Base: UltraTears `1970c7a` (first commit of this repo). Game: Pikmin 4 `0100B7C00933A000`, base + update v131072
(main build `bb89070f…`). Everything derived from the game lives in `work\0100B7C00933A000\` and must not be shared.

## Status: playable

The owner has played it on an i5-14400F and an RTX 4070 and reports that it runs flawlessly. Verified:
- **Boot to gameplay:** boot, the opening and title movies, the title menu, and the save screen.
- **Tutorials:** the intro, and the Rush, whistle and jump tutorials with their looping video clips.
- **Early play:** early gameplay with a squad of 11 Pikmin over several rooms.
- **Menus:** the Options menu.
- **Performance:** steady 30 fps (frame time p50 34 ms) in 25-minute sessions, with 0 skipped draws and 0 shaders
  missing a translation.
- **Input:** keyboard, controller (SDL3) and the scripted virtual pad.

Areas later in the game are untested. New shaders are captured while the game runs and translated when the `.bat`
exits, so a new area may draw incompletely on its first visit.

## Running and iterating

- Play: `Pikmin 4 native test.bat` in the workspace root. Its log goes to `run\visual.log`.
- One build and headless boot from a shell: `nxrecomp/port_iter.sh "$PWD/ports/pikmin4" "$PWD/work/0100B7C00933A000" <tag>`.
  The full log goes to `run/<tag>.log`.
- The crash report prints the guest registers, any register pointing at text (asserts), and the guest call chain.
  Names in `main` are only the nearest export, because main is mostly stripped. Names in `sdk` are exact.

## Changes, in order (see `git log` for details)

| Area | Change |
|---|---|
| Layout | `rt.h`, `tools/gen_game.py`: module and host-region bases (main is 166 MB) |
| SDK | nn::time zone and calendar, nn::fs save, cache and dir calls, offline services, account open users, RomFS listing, DLC event, ro stubs, hwopus, audout:u, public nn::hid names |
| App | FocusStateChanged queued at launch (without it, Unreal stays inactive) |
| NVN | RegisterImage, fences resolve at their submit, per-stage program binding, separate textures and samplers, ClearBuffer, the BGRA8 family format table (0x99–0x9C) |
| Shaders | Captured at runtime and translated by Ryujinx after the run, plus geometry shaders, 8 buffer textures per stage, the depth mode (NEAR_IS_ZERO), and the compute group size from control +0x748 |
| Rendering | Layered render passes (Unreal's 32-slice colour LUT), 3D texture fit checks, and conversion of RGBA8↔BGRA8 texture copies (the title movie was blue) |
| Movies | VP9 in texture mode, odd sizes (1040x585), BGRA textures, and the Flush/Start loop: inputs held across a flush and no input after end of stream, as in nxnative `md_reset` (a looping tutorial clip went black) |
| Lifter | Jump tables through register copies, and table-relative tables (`ldrsw` + `add table`; ICU `SimpleDateFormat::subFormat` crashed at the save screen) |
| Diagnostics | TOTK_SHOT_EVERY, TOTK_SNAP of compute dispatches, TOTK_CBUF_LOG, TOTK_VPAD_SCRIPT, TOTK_MOVIE_IVF (dumps a movie's VP9 packets for an independent decode with ffmpeg), dumps of volumes, RGB10A2 and RGBA32F |

## How the hard ones were found (reuse these methods)

- **Wrong colours:** decode the movie outside the port and compare the frames, before touching the decoder. The
  frames from ffmpeg (TOTK_MOVIE_IVF) matched ours, so the decoder was right. A one-line log on the texture copy
  then showed R8G8B8A8_SRGB → B8G8R8A8_SRGB.
- **"no function at X":** a jump-table target the lifter missed.
  1. Find the lifted function holding the `lr` address in `work/.../lift/main/*.c` and look at the `switch`
     before the `rt_dispatch`.
  2. Disassemble the table load with capstone.
  3. Decode the table from the image and check that every entry has a `case`.
- **After a re-lift:** compare the function and label sets with the previous lift. No function may be lost. Labels
  may only be lost where a branch that used to fall back to every label now resolves through its table (check that
  table's bounds).

## Known gaps

- Later areas: untested.
- nxnative's Pikmin 4 patches (Unreal's 62 GB engine region, FMallocBinned3) are for update 1.1.1 (v262144), and
  this dump is v131072. They haven't been needed. If memory trouble appears, dump 1.1.1 and port them.
