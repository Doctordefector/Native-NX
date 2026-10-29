"""Compile a game's lifted C (work/<id>/lift/<module>/*.c) to x86-64 objects with UltraTears' toolchain and flags.

This is step two of a port: it shows whether the lifter's output builds for this game. It links nothing (there is
no runtime for games other than TOTK yet). Objects go to work/<id>/build/.
usage: compile_lift.py <work/<id>> [--sample N] [-j N]
"""
import argparse, os, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
UT = ROOT / 'refs/ultratears'
sys.path.insert(0, str(UT / 'tools'))
import build_game  # noqa: E402  (UltraTears' own flags, so this matches its TOTK build)
import toolchain  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('work', type=pathlib.Path)
    ap.add_argument('--sample', type=int, default=0, help='compile only the first N files (a quick check)')
    ap.add_argument('-j', type=int, default=os.cpu_count() or 4)
    a = ap.parse_args()
    work = a.work.resolve()
    build = work / 'build'
    build.mkdir(parents=True, exist_ok=True)
    flags = build_game.GAME_CFLAGS.replace('-Isrc/runtime', f'-I"{(UT / "src/runtime").as_posix()}"')
    flags = flags.replace(' -g -gcodeview', '')   # no debug info: nothing is linked, and it halves the time
    lines = ['ninja_required_version = 1.10', f'gameflags = {flags}',
             'rule gamecc', '  command = clang -MD -MF $out.d $gameflags -c $in -o $out', '  deps = gcc',
             '  depfile = $out.d', '  description = $in', '']
    srcs = []
    for module in sorted(p for p in (work / 'lift').iterdir() if p.is_dir()):
        srcs += sorted(module.glob('*.c'))
    if a.sample:
        srcs = srcs[:a.sample]
    slow = 0
    for c in srcs:
        obj = f'obj/{c.parent.name}/{c.stem}.o'            # relative to build/: ninja paths cannot hold ' ' or ':'
        lines.append(f'build {obj}: gamecc ../lift/{c.parent.name}/{c.name}')
        text = c.read_text(errors='replace')
        if 'L_dispatch:' in text and text.count('\nL_') > 2000:   # same rule as build_game.py: huge switch -> -O0
            lines.append('  gameflags = ' + flags.replace('-O2', '-O0'))
            slow += 1
    (build / 'build.ninja').write_text('\n'.join(lines) + '\n')
    print(f'{len(srcs)} files ({slow} at -O0), {a.j} jobs', flush=True)
    env = toolchain.env()
    r = subprocess.run([str(toolchain.CLANG64 / 'ninja.exe'), '-C', str(build), '-k', '0', '-j', str(a.j)], env=env)
    objs = list((build / 'obj').rglob('*.o'))
    print(f'compiled {len(objs)} / {len(srcs)} objects, {sum(o.stat().st_size for o in objs) / 2**20:.0f} MB', flush=True)
    sys.exit(r.returncode)


if __name__ == '__main__':
    main()
