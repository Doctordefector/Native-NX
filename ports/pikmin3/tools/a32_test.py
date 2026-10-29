"""Differential test of a32.py against Unicorn: every distinct instruction shape the game uses, run from random
states in both, compared on r0-r14, NZCVQ/GE, D0-D31, FPSCR flags and data memory.

  python tools/a32_test.py <ExeFS dir> [per-mnemonic samples=12] [states=6]
"""
import ctypes, os, random, re, struct, subprocess, sys, collections
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import nxloader, a32
import capstone as cs
import unicorn as uc
from unicorn import arm_const as A

CLANG = os.path.join(ROOT, '..', '..', 'refs', 'ultratears', 'deps', 'clang64', 'bin', 'clang.exe')
OUT = os.path.join(ROOT, 'build', 'a32test')
MEMSZ = 0x4000000
DATA = 0x3800000; DATASZ = 0x10000
TPID = 0x3810000


def collect(exefs, per):
    mods, npdm, _ = nxloader.load_program(exefs)
    md = cs.Cs(cs.CS_ARCH_ARM, cs.CS_MODE_ARM)
    seen = set(); groups = collections.defaultdict(list)
    for m in mods:
        img = m.image; t0 = m.text[0]
        for o in range(t0, t0 + m.text[1], 4):
            w = struct.unpack_from('<I', img, o)[0]
            if w in seen: continue
            seen.add(w)
            pc = m.base + o
            r = a32.emit(w, pc)
            if not isinstance(r, str) or 'UNDEF' in r or not r: continue
            if 'c->rt->' in r: continue
            ins = next(md.disasm_lite(struct.pack('<I', w), pc), None)
            if not ins: continue
            key = re.sub(r'(eq|ne|hs|lo|mi|pl|vs|vc|hi|ls|ge|lt|gt|le)(\.|$)', r'\2', ins[2]) + ('/q' if re.search(r'\bq\d', ins[3]) else '')
            groups[key].append((pc, w, r, ins[2] + ' ' + ins[3]))
    tests = []
    rnd = random.Random(1)
    for k, lst in sorted(groups.items()):
        rnd.shuffle(lst); tests += lst[:per]
    return mods, tests


def build(mods, tests):
    os.makedirs(OUT, exist_ok=True)
    L = ['#include "cpu32.h"', 'static int g_undef;',
         'static void u_(CPU* c, u64 pc, u32 w){ g_undef=1; }',
         'static const RtAPI rt_={0,u_,0,0,0,0,0,0};', '#define UNDEF() c->rt->undef(c,c->pc,0)']
    for i, (pc, w, r, txt) in enumerate(tests):
        L.append('static void T%d(CPU* RESTRICT c){ u8* const M=c->mem; /* %s */ %s }' % (i, txt.replace('*/', ''), r))
    L.append('int __stdcall DllMain(void* h, unsigned r, void* p){ return 1; }')
    L.append('typedef void (*TF)(CPU*);')
    L.append('static const TF TT[]={%s};' % ','.join('T%d' % i for i in range(len(tests))))
    L.append('''__declspec(dllexport) int run(int i, u32* r, u32* fl, u8* v, u32* fps, u8* mem, u32 tp){
  CPU c; memset(&c,0,sizeof c); c.mem=mem; c.rt=&rt_; c.tpidrro=tp; c.tpidr=tp+0x100; g_undef=0;
  for(int k=0;k<16;k++) c.x[k]=r[k]; set_nzcv(&c,fl[0]>>28); c.user[0]=(fl[0]>>27)&1; c.user[1]=(fl[0]>>16)&15;
  memcpy(c.v,v,256); a32_set_fpscr(&c,fps[0]);
  TT[i](&c);
  for(int k=0;k<16;k++) r[k]=(u32)c.x[k]; fl[0]=a32_apsr(&c); memcpy(v,c.v,256); fps[0]=a32_fpscr(&c);
  return g_undef; }''')
    src = os.path.join(OUT, 't.c')
    open(src, 'w').write('\n'.join(L))
    rt = os.path.join(ROOT, 'runtime')
    dll = os.path.join(OUT, 't.dll')
    cmd = [CLANG, '-O1', '-shared', '-fno-strict-aliasing', '-ffp-contract=off', '-fwrapv', '-w', '-I', rt, src,
           os.path.join(rt, 'cpu32_helpers.c'), os.path.join(rt, 'cpu_helpers.c'), '-nostartfiles', '-Wl,-e,DllMain', '-o', dll]
    env = dict(os.environ, PATH=os.path.dirname(CLANG) + os.pathsep + os.environ['PATH'])
    p = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if p.returncode: print(p.stderr[-6000:]); sys.exit(1)
    return ctypes.CDLL(dll)


def rand_state(rnd):
    regs = []
    for k in range(16):
        x = rnd.random()
        if x < 0.45: regs.append(DATA + 0x4000 + (rnd.randrange(0x400) * 4 if rnd.random() < .8 else rnd.randrange(0x1000)))
        elif x < 0.7: regs.append(rnd.randrange(64))
        else: regs.append(rnd.getrandbits(32))
    regs[13] = DATA + 0x8000 - rnd.randrange(64) * 4
    vf = bytearray()
    for k in range(32):
        x = rnd.random()
        if x < 0.4: vf += struct.pack('<ff', rnd.uniform(-1000, 1000), rnd.choice([0.0, 1.0, -2.5, rnd.uniform(-3, 3)]))
        elif x < 0.7: vf += struct.pack('<d', rnd.uniform(-1e6, 1e6))
        else: vf += struct.pack('<Q', rnd.getrandbits(64))
    flags = rnd.getrandbits(4) << 28 | rnd.getrandbits(1) << 27 | rnd.getrandbits(4) << 16
    fps = rnd.getrandbits(4) << 28
    mem = bytes(rnd.getrandbits(8) for _ in range(DATASZ))
    return regs, flags, bytes(vf), fps, mem


def main():
    exefs = sys.argv[1]; per = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    nstates = int(sys.argv[3]) if len(sys.argv) > 3 else 6
    mods, tests = collect(exefs, per)
    print('tests:', len(tests))
    lib = build(mods, tests)
    lib.run.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32]
    hostmem = (ctypes.c_uint8 * MEMSZ)()
    for m in mods: ctypes.memmove(ctypes.addressof(hostmem) + m.base, m.image, len(m.image))
    mu = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_ARM)
    try: mu.ctl_set_cpu_model(A.UC_CPU_ARM_MAX)
    except Exception: pass
    mu.mem_map(0, MEMSZ)
    for m in mods: mu.mem_write(m.base, bytes(m.image))
    mu.reg_write(A.UC_ARM_REG_C1_C0_2, mu.reg_read(A.UC_ARM_REG_C1_C0_2) | (0xF << 20))
    mu.reg_write(A.UC_ARM_REG_FPEXC, 0x40000000)
    rnd = random.Random(7)
    bad = collections.defaultdict(list); ran = 0; skipped = 0
    RR = [getattr(A, 'UC_ARM_REG_R%d' % i) for i in range(13)] + [A.UC_ARM_REG_SP, A.UC_ARM_REG_LR, A.UC_ARM_REG_PC]
    DR = [getattr(A, 'UC_ARM_REG_D%d' % i) for i in range(32)]
    for ti, (pc, w, r, txt) in enumerate(tests):
        for s in range(nstates):
            regs, flags, vf, fps, mem = rand_state(rnd)
            regs[15] = pc
            # unicorn
            mu.mem_write(DATA, mem)
            for k in range(15): mu.reg_write(RR[k], regs[k])
            mu.reg_write(A.UC_ARM_REG_CPSR, 0x10 | flags)
            for k in range(32): mu.reg_write(DR[k], struct.unpack_from('<Q', vf, k * 8)[0])
            mu.reg_write(A.UC_ARM_REG_FPSCR, fps)
            mu.reg_write(A.UC_ARM_REG_C13_C0_3, TPID)
            try:
                mu.emu_start(pc, pc + 4, count=1)
            except uc.UcError:
                skipped += 1; continue
            ur = [mu.reg_read(RR[k]) for k in range(15)]
            ufl = mu.reg_read(A.UC_ARM_REG_CPSR) & 0xF80F0000
            uv = b''.join(struct.pack('<Q', mu.reg_read(DR[k])) for k in range(32))
            ufps = mu.reg_read(A.UC_ARM_REG_FPSCR) & 0xF8000000
            umem = bytes(mu.mem_read(DATA, DATASZ))
            # ours
            ctypes.memmove(ctypes.addressof(hostmem) + DATA, mem, DATASZ)
            rr = (ctypes.c_uint32 * 16)(*regs); fl = (ctypes.c_uint32 * 1)(flags)
            vv = (ctypes.c_uint8 * 256)(*vf); ff = (ctypes.c_uint32 * 1)(fps)
            if lib.run(ti, rr, fl, vv, ff, hostmem, TPID): skipped += 1; continue
            ran += 1
            diffs = []
            for k in range(15):
                if rr[k] != ur[k]: diffs.append('r%d %08x vs %08x' % (k, rr[k], ur[k]))
            if (fl[0] & 0xF80F0000) != ufl: diffs.append('apsr %08x vs %08x' % (fl[0] & 0xF80F0000, ufl))
            if (ff[0] & 0xF8000000) != ufps: diffs.append('fpscr %08x vs %08x' % (ff[0] & 0xF8000000, ufps))
            ov = bytes(vv)
            for k in range(64):
                a_ = ov[k * 4:k * 4 + 4]; b_ = uv[k * 4:k * 4 + 4]
                if a_ != b_:
                    fa, fb = struct.unpack('<f', a_)[0], struct.unpack('<f', b_)[0]
                    if fa != fa and fb != fb: continue        # both NaN: payloads differ between x86 and ARM
                    da = struct.unpack_from('<d', ov, (k // 2) * 8)[0]; db = struct.unpack_from('<d', uv, (k // 2) * 8)[0]
                    if da != da and db != db: continue
                    diffs.append('s%d %s vs %s' % (k, a_.hex(), b_.hex()))
            omem = bytes(hostmem[DATA:DATA + DATASZ])
            if omem != umem:
                i = next(j for j in range(DATASZ) if omem[j] != umem[j]); diffs.append('mem +%x' % i)
            if diffs:
                bad[txt.split()[0]].append((txt, '%08x' % w, diffs[:4]))
                break
    print('ran %d states, %d skipped (fault/undef)' % (ran, skipped))
    nbad = sum(len(v) for v in bad.values())
    print('failing encodings: %d' % nbad)
    for k, v in sorted(bad.items(), key=lambda kv: -len(kv[1])):
        for e in v[:3]: print('  %-40s %s %s' % (e[0], e[1], '; '.join(e[2])))


if __name__ == '__main__':
    main()
