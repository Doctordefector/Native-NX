"""Where the build's tools are: the builder package's deps/ first, then the developer's own installs.

CLANG64: a folder with clang, clang++, lld, ninja and the static libraries the port links (SDL3, opus, vpx, zstd,
iconv, libc++): deps/clang64/bin in the builder package (a trimmed MSYS2 CLANG64), else ULTRS_CLANG64, else
C:/msys64/clang64/bin. XLATE: the shader translator ultrs-shaders.exe (tools/build_xlate.py).
"""
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _clang64():
    for c in (ROOT / 'deps/clang64/bin', os.environ.get('ULTRS_CLANG64'), 'C:/msys64/clang64/bin'):
        if c and (pathlib.Path(c) / 'clang.exe').is_file():
            return pathlib.Path(c)
    return None


CLANG64 = _clang64()
XLATE = next((p for p in (ROOT / 'deps/shaders/ultrs-shaders.exe', ROOT / 'dev-local/build/shaders/ultrs-shaders.exe') if p.is_file()),
             None)


def env():
    """The environment for the build's commands: CLANG64 first on PATH."""
    if CLANG64 is None:
        raise SystemExit('clang not found: unpack the builder package (deps/clang64) or install MSYS2 CLANG64 '
                         '(see BUILDING.md), or set ULTRS_CLANG64 to its bin folder')
    return dict(os.environ, PATH=str(CLANG64) + os.pathsep + os.environ.get('PATH', ''))
