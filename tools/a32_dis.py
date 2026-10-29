"""Disassemble A32 code of a loaded program at a game address.   python tools/a32_dis.py <ExeFS dir> <hex addr> [count] [before]"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import nxloader
import capstone as cs

mods, _, _ = nxloader.load_program(sys.argv[1])
a = int(sys.argv[2], 16); n = int(sys.argv[3]) if len(sys.argv) > 3 else 40; b = int(sys.argv[4]) if len(sys.argv) > 4 else 0
a -= 4 * b
m = next(m for m in mods if m.base <= a < m.base + len(m.image))
md = cs.Cs(cs.CS_ARCH_ARM, cs.CS_MODE_ARM)
slot = {}                                  # GOT slot -> imported symbol (DT_JMPREL)
for mm in mods:
    d = getattr(mm, 'dyn', {})
    if d.get(0x17) is None: continue
    for o in range(d[0x17], d[0x17] + d.get(2, 0), 8):
        r_off, r_info = struct.unpack_from('<II', mm.image, o)
        if r_info >> 8 < len(mm.symlist): slot[mm.base + r_off] = mm.symlist[r_info >> 8][0]

def plt_name(t):                           # add ip,pc,#a / add ip,ip,#b / ldr pc,[ip,#c]!
    mm = next((x for x in mods if x.base <= t < x.base + len(x.image)), None)
    if not mm: return None
    w = [mm.u32(t - mm.base + 4 * k) for k in range(3)]
    if w[0] & 0xFFFFF000 != 0xE28FC000 or w[1] & 0xFFFFF000 != 0xE28CC000 or w[2] & 0xFFFFF000 != 0xE5BCF000: return None
    rot = lambda x: ((x & 255) >> (2 * (x >> 8 & 15))) | ((x & 255) << (32 - 2 * (x >> 8 & 15))) & 0xFFFFFFFF if x >> 8 & 15 else x & 255
    return slot.get(t + 8 + rot(w[0] & 0xFFF) + rot(w[1] & 0xFFF) + (w[2] & 0xFFF))
for k in range(n):
    o = a - m.base + 4 * k
    w = struct.unpack_from('<I', m.image, o)[0]
    i = next(md.disasm_lite(struct.pack('<I', w), a + 4 * k), None)
    t = ('%s %s' % i[2:]) if i else '.word'
    if i and i[2].startswith('bl') and i[3].startswith('#'):
        nm = plt_name(int(i[3][1:], 16))
        if nm: t += '   ; ' + nm
    print('%08x  %08x  %s' % (a + 4 * k, w, t))
