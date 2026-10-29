"""Translate shaders captured at run time (TOTK_SHADER_CAPTURE=<dir>) with UltraTears' Ryujinx translator.

A port of a game whose shaders cannot be found in its RomFS at build time (Unreal keeps them in its pak) records each
shader it is handed but has no translation for: <dir>/raw/<key>.ctl + <key>.bin, listed in <dir>/captured.tsv. This
writes <dir>/jobs.jsonl in tools/export_shaders.py's format (default bind state) and runs tools/run_ryujinx_xlate.py,
which writes <dir>/ryujinx/<key>.spv. Point the port at them with TOTK_SHADER_DIR=<dir>/ryujinx; boot, capture, repeat.
usage: shaders_from_capture.py <dir> [--workers N]
"""
import argparse, json, os, pathlib, struct, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
UT = ROOT / 'refs/ultratears'
STAGES = {0: 'vs', 1: 'ps', 2: 'gs', 5: 'cs'}   # 2: geometry (Ryujinx takes the stage from the program header)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dir', type=pathlib.Path)
    ap.add_argument('--workers', type=int, default=max(1, (os.cpu_count() or 4) - 2))
    a = ap.parse_args()
    d = a.dir.resolve()
    raw, code_dir = d / 'raw', d / 'ryujinx-code'
    code_dir.mkdir(exist_ok=True)
    # the game's NVN depth mode as the capture recorded it: near=-w (GL) needs z converted to 0..w; near=0 (D3D) does not
    # (Pikmin 4 sets NEAR_IS_ZERO). Without the record: -w, as UltraTears' TotK.
    mode = (d / 'depth_mode.txt').read_text().strip() if (d / 'depth_mode.txt').exists() else 'minus_w'
    print(f'depth mode {mode}', flush=True)
    jobs, skipped = [], 0
    for ctl in sorted(raw.glob('*.ctl')):
        key = ctl.stem
        control, code = ctl.read_bytes(), (raw / f'{key}.bin').read_bytes()
        stage = STAGES.get(struct.unpack_from('<I', control, 0x714)[0])
        c1, length = struct.unpack_from('<II', control, 0x700)
        if not stage or not 0 <= c1 <= length <= len(code):
            skipped += 1
            continue
        path = code_dir / f'{key}.code'
        path.write_bytes(code[0 if stage == 'cs' else 0x30:length])
        job = dict(key=key, stage=stage, code=str(path), c1=code[c1:length].hex(), depth_minus_w=mode == 'minus_w',
                   tex={}, img={}, attr={}, fout={})
        if stage == 'cs':   # thread group and shared memory from the control section, as nxnative's shader_split.py
            x, y, z = struct.unpack_from('<3I', control, 0x748)
            if not x * y * z:
                skipped += 1
                continue
            job['local'] = [x, y, z]
            job['shared'] = (struct.unpack_from('<I', control, 0x754)[0] + 15) // 16 * 16
        jobs.append(json.dumps(dict(job=job, out=str(d / 'ryujinx'))))
    (d / 'jobs.jsonl').write_text('\n'.join(jobs) + '\n' if jobs else '')
    print(f'{len(jobs)} captured shaders to translate ({skipped} skipped)', flush=True)
    if not jobs:
        return
    env = dict(os.environ, PYTHONPYCACHEPREFIX=str(ROOT / '.cache/pycache'))
    sys.exit(subprocess.run([sys.executable, str(UT / 'tools/run_ryujinx_xlate.py'), str(d), '--workers', str(a.workers),
                             '--new-only'], env=env).returncode)


if __name__ == '__main__':
    main()
