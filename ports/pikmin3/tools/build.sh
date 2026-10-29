#!/bin/sh
# Pikmin 3 Deluxe: translate (if needed), compile and link into out/Pikmin3.exe (runtime + recompiled code, one exe).
#   tools/build.sh [gen] [headless|win32]
set -e
cd "$(dirname "$0")/.."
ROOT="$PWD/../.."
export PATH="$ROOT/refs/ultratears/deps/clang64/bin:$PATH" TEMP="$ROOT/.cache/tmp" TMP="$ROOT/.cache/tmp" PYTHONPYCACHEPREFIX="$ROOT/.cache/pycache" SWR_ROMFS=1 PYTHONUNBUFFERED=1
GAME="$ROOT/work/0100F4C009322000/extract"
B=out/Pikmin3_build
BACKEND=headless
for a in "$@"; do case $a in gen) GEN=1;; headless|win32) BACKEND=$a;; esac; done
if [ -n "$GEN" ] || [ ! -f $B/module.c ]; then "$ROOT/.venv/Scripts/python.exe" -I switchrecomp.py "$GAME" -o Pikmin3 --outdir out --no-build; fi
FL="-O2 -fno-strict-aliasing -ffp-contract=off -fwrapv -w -I runtime -foptimize-sibling-calls"
# generated code: rebuild a .o when its .c (or the A32 headers) is newer
ls $B/*.c | while read c; do o="${c%.c}.o"; if [ ! -f "$o" ] || [ "$c" -nt "$o" ] || [ runtime/cpu32.h -nt "$o" ]; then echo "$c"; fi; done > $B/todo.txt
n=$(wc -l < $B/todo.txt); echo "compiling $n generated files"
xargs -a $B/todo.txt -P 12 -I{} sh -c 'clang '"$FL"' -c "{}" -o "$(echo {} | sed "s/\.c$/.o/")" || echo FAIL {}' | tee $B/compile.log
grep -q FAIL $B/compile.log && exit 1
# runtime
RT="plat mem kernel ipc svc_core svc_hid svc_fs svc_vi nvdrv gpu gpu_engines gpu_3d main loader svc_launcher entry host1x"
if [ $BACKEND = headless ]; then RT="$RT gpu_nogl backend_headless"; LIBS="-lgdi32 -lwinmm -luser32 -lshell32 -mconsole"
else RT="$RT gpu_gl gl_load shader astc glq glq_gen lsfg_stub backend_win32"; LIBS="-lgdi32 -lwinmm -luser32 -lshell32 -lopengl32 -lcomdlg32 -mwindows"; fi
mkdir -p build/rt_$BACKEND
for s in $RT; do o=build/rt_$BACKEND/$s.o; if [ ! -f $o ] || [ runtime/$s.c -nt $o ] || [ runtime/rt.h -nt $o ]; then clang -O2 -w -fno-strict-aliasing -DSWR_NO_H264 -I runtime -c runtime/$s.c -o $o; fi; done
ls $B/*.o > $B/objects.rsp; ls build/rt_$BACKEND/*.o >> $B/objects.rsp
clang -fuse-ld=lld -o out/Pikmin3.exe @$B/objects.rsp -static $LIBS
echo "built out/Pikmin3.exe ($BACKEND)"
