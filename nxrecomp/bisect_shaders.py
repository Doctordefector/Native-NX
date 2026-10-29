"""Find the translated shader that loses the Vulkan device: hides halves of a candidate set (renames <key>.spv to
<key>.spv.off) and runs a headless boot for each half until one shader is left.
usage: bisect_shaders.py <port dir> <work dir> <keys file: one key prefix per line> [seconds]
The port is run as nxrecomp/port_iter.sh runs it (TOTK_HEADLESS, the work folder's RomFS and shaders); a run counts as
failing when its log has "failed (-4)" (VK_ERROR_DEVICE_LOST). Everything is renamed back at the end."""
import os, pathlib, shutil, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def run(port, work, secs):
    saves = port / 'run/saves_bisect'
    shutil.rmtree(saves, ignore_errors=True)
    if (port / 'run/saves').exists():
        shutil.copytree(port / 'run/saves', saves)
    tmp = str(ROOT / '.cache/tmp')
    env = dict(os.environ, TEMP=tmp, TMP=tmp, TOTK_HEADLESS='1', TOTK_SHADER_DIR=str(work / 'shaders/ryujinx'),
               TOTK_PROFILE_DIR=str(saves), TOTK_ROMFS=str(work / 'extract/RomFS'))
    try:
        out = subprocess.run([str(port / 'UltraTears.exe'), str(work / 'extract/ExeFS')], cwd=port, env=env,
                             capture_output=True, timeout=secs).stderr
    except subprocess.TimeoutExpired as e:
        out = e.stderr or b''
    return b'failed (-4)' in out


def main():
    port, work = pathlib.Path(sys.argv[1]).resolve(), pathlib.Path(sys.argv[2]).resolve()
    secs = int(sys.argv[4]) if len(sys.argv) > 4 else 40
    d = work / 'shaders/ryujinx'
    keys = [k.strip() for k in open(sys.argv[3]) if k.strip()]
    files = {k: next(d.glob(k + '*.spv')) for k in keys if any(d.glob(k + '*.spv'))}
    cand = sorted(files)
    try:
        if not run(port, work, secs):
            print('no device loss with every shader: nothing to bisect'); return
        while len(cand) > 1:
            half = cand[:len(cand) // 2]
            for k in half: files[k].rename(files[k].with_suffix('.spv.off'))
            lost = run(port, work, secs)
            for k in half: files[k].with_suffix('.spv.off').rename(files[k])
            cand = cand[len(cand) // 2:] if lost else half   # still lost without the half: the culprit is in the rest
            print(f'{len(cand)} candidates left ({"lost" if lost else "fine"} without the half)', flush=True)
        print('culprit:', cand[0])
    finally:
        for p in d.glob('*.spv.off'): p.rename(p.with_suffix(''))


if __name__ == '__main__':
    main()
