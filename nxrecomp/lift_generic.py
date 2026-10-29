"""Run UltraTears' ARM64 -> C lifter (refs/ultratears/tools/lifter/gen.py) on any game's code module.

The lifter's patches.py holds hand-written instruction replacements for TOTK 1.4.3 only, and each refuses another
build. For other games this wrapper gives the lifter an empty patch table; the lifting itself is unchanged.
usage: lift_generic.py <name> <nso> <base> <outdir> [gen.py options]
"""
import struct, sys, types
from pathlib import Path

LIFTER = Path(__file__).resolve().parents[1] / 'refs/ultratears/tools/lifter'
sys.path.insert(0, str(LIFTER))
sys.modules['patches'] = types.SimpleNamespace(PATCHES={})
import gen  # noqa: E402

_eh = gen.eh_frame_functions


def eh_frame_functions(n):
    """Older SDK builds (Pikmin 3 Deluxe) have no .eh_frame_hdr where the MOD0 header points: skip that table and
    let the lifter find functions from symbols, relocations and branch targets instead."""
    try:
        return _eh(n)
    except (ValueError, struct.error) as e:
        print(f'note: .eh_frame_hdr unreadable ({e}); discovering functions without it', file=sys.stderr)
        return []


gen.eh_frame_functions = eh_frame_functions
sys.argv[0] = str(LIFTER / 'gen.py')
gen.main()
