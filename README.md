# NX Recomp Hub

One window for every way this PC can run your Switch games. Double-click **`NX Recomp Hub.bat`**.

Everything it writes stays in this folder: `work\<title ID>\` (decrypted code, lifted C, builds), `.venv\` (Python
packages), `.cache\` (NuGet, pip, temp). Nothing is installed to C:.

## What each column means

| Column | Project | On this PC (i5-14400F, RTX 4070, Windows x64) |
|---|---|---|
| Native on this PC | [UltraTears](https://github.com/kuraeow/ultratears): ARM64 → C → x86-64 static recompilation, NVN → Vulkan | Works, but only for Tears of the Kingdom **1.4.3 (v720896)**. Your copy is 1.2.1 (v393216) |
| Native on Apple | [nxnative](https://github.com/seedds/nxnative): the game's ARM64 code runs directly on Apple chips, NVN → Metal | Cannot run here (needs Apple Silicon). Shown so you know which games have a profile, and for which version |
| Lift test | UltraTears' lifter, run on any game | Translates the game's `main` to C: step one of a port. Not playable: the runtime (system services, graphics) is TotK-specific |
| Emulator | Eden / Ryujinx / Sudachi in `T:\Emulation` | Plays everything today |

## Buttons

- **Play (best available)**: native UltraTears build if one exists, else the chosen emulator.
- **Decrypt game**: `nx_extract` (nxnative's LibHac tool, built for .NET 9 in `nxrecomp\bin`) merges base + newest
  update into `work\<id>\extract\ExeFS` and `RomFS`, with your `prod.keys`.
- **Recompile test**: decrypts the code only, then lifts `main` to C in `work\<id>\lift\main`.
- **Build native PC port**: TotK 1.4.3 only: decrypts the whole game, then runs UltraTears' `tools/setup.py` into
  `work\0100F2C0115B6000\ultratears` (about 35 min, about 32 GB; it downloads UltraTears' build tools once).

## Native ports in progress

A game with a folder under `ports\` (an UltraTears copy adapted to that game, its own git history) shows
"⚙ port in progress" and gets **Run native port (experimental)**: an incremental build, then a windowed boot whose log
is `ports\<name>\run\hub.log`.

- **Pikmin 4** (`ports\pikmin4`): the whole game (main, sdk, subsdk0) recompiles and links; it boots through SDK
  startup, its RomFS, saves, about 20 engine threads and into NVN on Vulkan on the RTX 4070, then stops in the NVN
  translation layer before the first frame. Status, changes and next steps: `ports\pikmin4\PORTING.md`;
  one iteration from a shell: `nxrecomp/port_iter.sh "$PWD/ports/pikmin4" "$PWD/work/0100B7C00933A000" <tag>`.
- **Pikmin 3 Deluxe** (`ports\pikmin3`): 32-bit ARM (A32). The port adds an AArch32 front end to SwitchRecomp
  (translator checked against Unicorn on every instruction shape the game uses, 32-bit loader, SVC32 ABI, 32-bit
  address space). The whole game translates, compiles and links into one exe and boots into its `rtld`; bring-up
  continues from there. Details: `ports\pikmin3\README.md`.

## Layout

```
NX Recomp Hub.bat        start here
nxrecomp\nxrecomp.py     the GUI (tkinter)
nxrecomp\lift_generic.py the lifter without TotK's instruction patches, for other games
nxrecomp\compile_lift.py compiles a lifted game with UltraTears' toolchain (the Compile test)
nxrecomp\port_iter.sh    one build + boot + report iteration of a port
ports\pikmin4\           the Pikmin 4 port (UltraTears copy, own git history, PORTING.md)
ports\pikmin3\           the Pikmin 3 Deluxe port (SwitchRecomp + AArch32 front end, README.md)
nxrecomp\tools\nx_extract  nxnative's extractor source, retargeted to .NET 9 (MIT, LICENSE.nxnative)
refs\                    clones of nxnative and ultratears
work\                    per-game output (made from your files: keep it private)
```

## This repository

Everything above except what comes from your own console or from other projects' checkouts: `work\` (your dumps),
`refs\` (reference clones of nxnative, UltraTears and SwitchRecomp), `.venv\`, `.cache\` and built binaries are
not included (see `.gitignore`). Licenses are per directory: `ports\pikmin4` is GPLv3 (UltraTears),
`ports\pikmin3` is Apache 2.0 (SwitchRecomp by MZ Labs, keep `NOTICE.txt`), `nxrecomp\tools\nx_extract` is MIT (nxnative).
