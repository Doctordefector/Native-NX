# Workspace notes: Switch PC Recomps

A guide for any agent starting a new port here, such as Pikmin 3 Deluxe. Read it before you touch anything.

## Ground rules from the owner (non-negotiable)

1. **Keep everything in `T:\Dev\Switch PC Recomps`. Never write to C:.** Temp files, caches, pip, NuGet, pycache and
   downloads all go under `.cache\`. Before you run any tool, set
   `TEMP=TMP=T:\Dev\Switch PC Recomps\.cache\tmp` and `PYTHONPYCACHEPREFIX=...\.cache\pycache`.
2. **Don't guess.** Check how `refs\nxnative` (the iOS/macOS Switch-to-native project) solves a problem and port that
   to Windows. Failing that, get facts from real diagnostics: logs, dumps, disassembly and the game's own data. No
   trial-and-error fixes.
3. Treat the files in `work\` as private, because they come from the owner's own game dumps.

## Top-level layout

| Path | What it is |
|---|---|
| `NX Recomp Hub.bat` | Starts the GUI (`nxrecomp\nxrecomp.py`, tkinter). It decrypts, lifts and builds games and runs ports or emulators. |
| `Pikmin 4 native test.bat` | Windowed run of the Pikmin 4 port. Its log goes to `ports\pikmin4\run\visual.log`. When the run ends, it translates any newly seen shaders. Copy it for a new port. |
| `README.md` | What the Hub is, with its columns and buttons. |
| `nxrecomp\` | The Hub's own tooling. This folder is **not** a git repo. |
| `ports\<game>\` | One port per game: a full copy of UltraTears adapted to that game, with **its own git repo**. |
| `work\<titleID>\` | Per-game output: decrypted code, lifted C and captured shaders. Large, private and not in git. |
| `refs\` | Reference sources. Read them, don't edit them, except for the note on `refs\ultratears` below. |
| `.venv\` | Python venv with capstone, lz4 and similar. It has **no PIL**: use the system python for image work. |
| `.cache\` | `dl` (downloads), `dotnet`, `nuget`, `pip`, `pycache`, `tmp`, and `vklayers` (Vulkan validation layers). |
| `SwitchRecomp_v153.zip`, `gcc_v149.7z.*` | Zips the owner dropped in. The SwitchRecomp zip is extracted to `refs\switchrecomp_v153` as reference only. The gcc archives were left alone (untrusted binaries that weren't needed). |

### External paths, read only (`nxrecomp\config.json`)

- Keys: `T:\Emulation\Switch Keys\prod.keys`
- ROMs: `T:\Emulation\Roms\Switch`
- Switch filesystem: `T:\Emulation\Switch file system`
- Emulators for comparison and reference: Eden, Ryujinx and Sudachi under `T:\Emulation\`

## `refs\`: what each reference is for

- **`refs\ultratears`**: UltraTears, a static recompiler built for Zelda TotK that lifts ARM64 to C, builds it as
  x86-64, and replaces NVN with Vulkan. The pieces you'll use:
  - `tools\lifter\`: the lifter. The Hub and the ports use **this copy**.
    - Lifter fixes are made in `ports\pikmin4\tools\lifter\gen.py` and copied here with CRLF line endings.
  - `tools\build_game.py`: the build script, using ninja and clang.
  - `deps\clang64\bin`: clang, ninja and `libc++.dll`.
    - Set `ULTRS_CLANG64` to this folder.
    - Put it on PATH to run `spirv-dis`.
  - `deps\shaders`: holds the shader translator `ultrs-shaders.exe`, which is Ryujinx's NVN→SPIR-V path and is run
    with `--serve`.
- **`refs\nxnative`**: nxnative, which runs Switch games natively on Apple chips (NVN→Metal). It is the
  reference for *how* to solve problems: HLE of SDK and services, the movie decoder, shader splitting
  (`shader_split.py`) and NVN semantics. Start with its `docs\` and `AGENTS.md`.
- **`refs\switchrecomp_v153`**: the owner's SwitchRecomp zip. Reference only.

## `nxrecomp\`

- `nxrecomp.py`: the Hub GUI. Its "Build native PC port" and "Run native port" show how a port is built and run.
  See the `job()` function near line 600.
- `lift_generic.py`: the lifter without TotK's instruction patches, for other games.
- `compile_lift.py`: compiles a lifted game with UltraTears' flags (the "compile test").
- `port_iter.sh`: one build, boot and report iteration:
  `nxrecomp/port_iter.sh "$PWD/ports/<game>" "$PWD/work/<titleID>" <tag>`.
- `shaders_from_capture.py`: turns the shaders a run captured (`work\<id>\shaders\raw`) into SPIR-V
  (`shaders\ryujinx`). It handles VS, FS, GS and CS, plus `depth_mode.txt`.
- `tools\nx_extract` (source) and `bin\nx_extract` (build): nxnative's LibHac extractor, retargeted to .NET 9.
  - It merges the base game with the newest update.
  - It writes `work\<id>\extract\ExeFS` and `RomFS`.

## `work\<titleID>\` (example: Pikmin 4, `0100B7C00933A000`)

```
extract\ExeFS\      main, main.npdm, rtld, sdk, subsdk0   (decrypted NSOs)
extract\RomFS\      game data; romfs_manifest.tsv, control.nacp, icon.jpg sit beside them
lift\main, lift\sdk, lift\subsdk0   lifted C (one file per function group); lift\main_old = previous lift
shaders\raw\        shaders captured at runtime (TOTK_SHADER_CAPTURE)
shaders\ryujinx\    translated .spv the port loads (TOTK_SHADER_DIR)
shaders\depth_mode.txt   "zero" for Pikmin 4 (NVN depth mode NEAR_IS_ZERO)
```

- `work\0100F4C009322000\` is **Pikmin 3 Deluxe**. Only the ExeFS has been extracted, plus a lift attempt in
  `lift_main.log`.
- That lift found 864 functions and **538,261 unsupported instructions**. Pikmin 3 Deluxe is **32-bit ARM
  (AArch32)**, and the UltraTears lifter only handles AArch64.
- So the first big job for a Pikmin 3 port is an AArch32 front end for the lifter, or another way of translating
  32-bit code. Check whether nxnative or SwitchRecomp does anything for 32-bit games before you design one.

## `ports\pikmin4\`: a template for a new port

This is a git repo. Read its `PORTING.md` for status and history, and `git log` for each fix.

```
src\runtime\    CPU/runtime glue for the lifted code
src\host\       host-side HLE: window_sdl.c (SDL3 window/input), overrides_input.c (keyboard map, input scripts),
                movie_host.c (VP9 via libvpx, replaces the SDK's movie decoder), audio, fs, saves...
src\gfx\nvn\    NVN HLE (hle_nvn.c) - records the game's NVN calls
src\gfx\        Vulkan replay: backend_vk.c, vkb_draw.c, vkb_tex.c (NVN format table), vkb_shader.c, vkb_desc.c
tools\          build_game.py, lifter\gen.py (jump-table fixes live here)
build\          ninja files, obj\, the game's generated sources
run\            logs from test runs (visual.log, hub.log, ...) and run\saves\ (TOTK_PROFILE_DIR)
UltraTears.exe  the built game - it must be closed before relinking, or the link fails with "Permission denied"
```

### Building a port

Run this from `ports\<game>`, with TEMP and TMP set as above:

```
set ULTRS_CLANG64=T:\Dev\Switch PC Recomps\refs\ultratears\deps\clang64\bin
..\..\.venv\Scripts\python.exe tools\build_game.py --generated ..\..\work\<titleID>\lift --target ultratears --cpus 10
```

### Running a port

Copy `Pikmin 4 native test.bat`. It sets `TOTK_SHADER_CAPTURE`, `TOTK_SHADER_DIR`, `TOTK_PROFILE_DIR` and
`TOTK_ROMFS`, runs `UltraTears.exe <work>\extract\ExeFS`, and then runs `shaders_from_capture.py`.

### Diagnostic environment variables

The `TOTK_` prefix comes from UltraTears' TotK origins.

| Variable | What it does |
|---|---|
| `TOTK_SHOT` / `TOTK_SHOT_EVERY=<n>` | Saves screenshots (`.bmp`). |
| `TOTK_SNAP` | Saves the textures of a draw or compute dispatch. |
| `TOTK_DUMP` | Dumps a single frame. |
| `TOTK_VK_DRAWTRACE=<frame>:<count>` | Traces the draws of a frame. |
| `TOTK_AUDIT` | Runs an audit. |
| `TOTK_CBUF_LOG=<present>:<key prefix>` | Logs constant buffers. |
| `TOTK_VPAD_SCRIPT` | Runs a virtual SDL gamepad from a script. Other pads, including the Steam Controller virtual device, are ignored. |
| Input scripts (`overrides_input.c`) | Scripted keyboard input for headless runs. |

Keyboard controls in game: W/A/S/D move, J=A, K=B, I=X, U=Y, Enter=+, Tab or Esc=−.

## Gotchas learned the hard way

- Python heredocs in bash turn `\n` inside C string literals into real newlines. Edit C files with the Edit tool.
- `spirv-dis` needs `refs\ultratears\deps\clang64\bin` on PATH, because it depends on `libc++.dll`.
- NVN formats 0x99 and 0x9A are BGRX8 and BGRA8; 0x9B and 0x9C are their SRGB versions. Byte order matters whenever
  the CPU writes texels, for example movie frames.
- Unreal Engine games (Pikmin 4) keep their shaders in the pak. They're captured at runtime and translated after the
  run, so each session fills in more of the game. Pikmin 3 Deluxe isn't Unreal, so check how it stores shaders.
- Compute shaders need the thread-group size from the NVN shader control (+0x748, three u32 values) and the shared
  memory size from +0x754, as nxnative's `shader_split.py` reads them.

## Publishing (github.com/Doctordefector/Native-NX)

The public repo is assembled in `publish\Native-NX\` (its own git repo, branch `main`). It holds the root files (README,
notes, launchers, `nxrecomp\` sources without `bin\` or `config.json`) plus every port under `ports\<game>\`, merged
with its history by `git subtree`. Nothing from `work\`, `refs\`, `.venv\`, `.cache\` or any game build goes in.

- Update a port: `git -C publish/Native-NX subtree pull --prefix=ports/<game> "T:/Dev/Switch PC Recomps/ports/<game>" master`
- Add a new port: the same with `subtree add`.
- Root files: copy them over, then commit and push from `publish\Native-NX`.
- **Never put AI attribution in commits** (no `Co-Authored-By: Claude`, no "Generated with" lines). That's the owner's rule.
