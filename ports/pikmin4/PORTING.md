# Pikmin 4 → Windows (static recompilation on UltraTears' runtime)

Base: UltraTears `1970c7a` (first commit of this repo). Game: Pikmin 4 `0100B7C00933A000`, base + update v131072
(main build `bb89070f…`). Everything derived from the game lives in `work\0100B7C00933A000\` and must not be shared.

## One iteration

```
nxrecomp/port_iter.sh "$PWD/ports/pikmin4" "$PWD/work/0100B7C00933A000" <tag>
```

Incremental build (about 20 s when only host code changed), a 120 s headless boot, and the log tail. Full log:
`run/<tag>.log`. The crash report prints guest registers, any register pointing at text (asserts), and the guest
call chain; names in `main` are only the nearest export (it is mostly stripped), names in `sdk` are exact.

## How far it boots (boot12)

1. Modules load at Pikmin 4's own layout (`src/runtime/rt.h`: main 166 MB; subsdk0 0x080B000000, sdk 0x080C000000).
2. `nn::init::Start`, SDK startup, all three modules' static constructors.
3. RomFS (plain folder) mounted and listed; local account; save, cache and temporary storage.
4. About 20 engine threads; docked mode; DLC watcher; movie module.
5. NVN on Vulkan: RTX 4070, memory pools imported, translation thread, descriptor buffers, first texture upload.
6. **Stops:** `corrupt command record ... op 0 size 1`: the NVN layer reads a record it did not write from the game's
   command memory. Next: find which NVN call Unreal makes that writes no record (or writes command memory in a way
   TOTK does not: `nvnCommandBufferAddCommandMemory` / out-of-memory callbacks), with `TOTK_ASYNC_REPLAY=0` to keep
   it on the game thread.

## Changes so far (see `git log`)

| Area | Change |
|---|---|
| Layout | `rt.h`, `tools/gen_game.py`: module and host-region bases |
| nn::time | `GetDeviceLocationName`, `LoadTimeZoneRule`, `ToCalendarTime(…, TimeZoneRule)`, `GetDayOfWeek` |
| nn::fs | allocator, global cache, save data ensure/exists/extend/commit, cache storage, AOC mount, delete dir, entry count; RomFS folder listing |
| account | Push/PopOpenUsers, network-service-account calls (offline) |
| services_offline.c | nifm, socket, nsd, ssl, bcat, prepo, ngc, ec, web, swkbd, ldn, oe extras, ro |
| aoc | `GetAddOnContentListChangedEvent` |
| NVN | `nvnTexturePoolRegisterImage`; `nvnCommandBufferFenceSync` (approximation: next submit; TODO) |
| Diagnostics | crash report decodes text in registers |

## Known gaps ahead

- Graphics: the command-record mismatch above; then shaders. TOTK's shaders are translated at build time
  (`tools/export_shaders.py` + Ryujinx' translator); Pikmin 4's are inside Unreal's pak (`ShaderArchive` / NVN
  binaries) and need their own finder. nxnative's profile (`refs/nxnative/dm/games/0100B7C00933A000/`) lists them.
- Texture format 0x34 buffer→texture copies (`[temporary] ... not copied`).
- Audio: 83 `nn::audio` imports are not provided; Wwise uses its own `AudioOut` sink (nxnative notes).
- Input: 49 `nn::hid` imports to check against `overrides_input.c`.
- nxnative's Pikmin 4 patches (Unreal's 62 GB engine region, FMallocBinned3) are for update 1.1.1 (v262144); this dump
  is v131072. They have not been needed so far; if memory trouble appears, dump 1.1.1 and port them.
