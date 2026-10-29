#!/bin/bash
# One porting iteration for a game port under ports/<name>: incremental build, a headless boot, and a short report
# of how far it got (the last log lines before the failure, the failure, the guest call chain).
# usage: nxrecomp/port_iter.sh <port dir> <work/<title id>> <tag> [seconds]
set -u
ROOT="T:/Dev/Switch PC Recomps"; PORT="$1"; WORK="$2"; TAG="$3"; SECS="${4:-120}"
export TEMP="$ROOT/.cache/tmp" TMP="$ROOT/.cache/tmp" PYTHONPYCACHEPREFIX="$ROOT/.cache/pycache" ULTRS_CLANG64="$ROOT/refs/ultratears/deps/clang64/bin"
cd "$PORT" || exit 1
"$ROOT/.venv/Scripts/python" tools/build_game.py --generated "$(realpath --relative-to=. "$WORK/lift")" --target ultratears --cpus 14 -j 14 > build.log 2>&1 \
  || { echo "BUILD FAILED"; grep -E "error" build.log | head -20; exit 1; }
mkdir -p run
TOTK_SHADER_CAPTURE="$WORK/shaders" TOTK_SHADER_DIR="$WORK/shaders/ryujinx" TOTK_HEADLESS=1 TOTK_PROFILE_DIR="$(pwd)/run/saves" TOTK_ROMFS="$WORK/extract/RomFS" timeout "$SECS" ./UltraTears.exe "$WORK/extract/ExeFS" > "run/$TAG.log" 2>&1
echo "exit $? ($(wc -l < "run/$TAG.log") log lines)"
grep -vE "^\s+#[0-9]+ +[0-9a-f]{16} |^\s+x[0-9]|^\s*$" "run/$TAG.log" | grep -vE "^(loaded|relocated) " | tail -n 25 | cut -c1-220
