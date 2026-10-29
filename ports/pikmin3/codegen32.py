"""
codegen32: analysis -> C for AArch32 (A32) games, the counterpart of codegen.py.
  - functions from dynamic symbols, R_ARM_RELATIVE targets in .text, BL/B targets, run-time hints
  - one C function per guest function, gotos between blocks, switch on entry (every leader is an entry)
  - 'add pc, pc, rX, lsl #2' branch tables: the B entries become leaders, dispatch through the switch
"""
import array, sys
import a32
from codegen import Func


def lit(v): return '0x%Xu' % (v & 0xFFFFFFFF)


class Program32:
    def __init__(self, mods, hints=()):
        self.mods = mods
        self.hints = set(hints)
        self._lastm = None
        self.cache = {}
        for m in mods:
            m._t0 = m.base + m.text[0]; m._t1 = m._t0 + m.text[1]
            o = m.text[0]; n = m.text[1] // 4
            m._words = array.array('I', bytes(m.image[o:o + n * 4]))
            if sys.byteorder != 'little': m._words.byteswap()
        self.jt = {}         # addr of the 'add pc' -> list of entry addresses
        self.undef_count = {}

    def mod_of(self, a):
        m = self._lastm
        if m is not None and m._t0 <= a < m._t1: return m
        for m in self.mods:
            if m._t0 <= a < m._t1:
                self._lastm = m; return m
        return None

    def word(self, a):
        m = self.mod_of(a)
        return None if m is None else m._words[(a - m._t0) >> 2]

    def decode(self, a):
        r = self.cache.get(a)
        if r is not None: return r
        w = self.word(a)
        if w is None: return (None, None)
        r = (w, a32.emit(w, a))
        self.cache[a] = r
        return r

    # -------------------------------------------------------------- analysis
    def jt_entries(self, x, reg):
        """entries of an 'add pc, pc, reg, lsl #2' table: bound from a preceding 'cmp reg, #imm', else the run of B"""
        n = None
        for k in range(1, 6):
            w = self.word(x - 4 * k)
            if w is None: break
            if w & 0x0FFFF000 == 0x03500000 | (reg << 16):          # CMP reg, #imm
                n = a32.armexpand(w & 0xFFF) + 1; break
        ents = []
        y = x + 8
        while len(ents) < (n or 4096):
            w, r = self.decode(y)
            if not (isinstance(r, tuple) and r[0] == 'b'): break
            ents.append(y); y += 4
        return ents

    def table_bound(self, x, reg, back=10):
        for k in range(1, back):
            w = self.word(x - 4 * k)
            if w is None: break
            if w & 0x0FFFF000 == 0x03500000 | (reg << 16):          # CMP reg, #imm
                return a32.armexpand(w & 0xFFF) + 1
        return None

    def reg_tables(self, x):
        """clang's tables through a register: 'add rA, pc, #K; ldr rB, [rA, rX, lsl #2]; add pc, rA, rB' (entries
        relative to the table) or 'ldr pc, [rA, rX, lsl #2]' (absolute, module-relative before relocation)"""
        w = self.word(x); m = self.mod_of(x)
        if w is None: return None
        if w & 0x0FF0FFF0 == 0x0080F000:                               # ADD pc, rA, rB
            ra, rb = (w >> 16) & 15, w & 15
            rx = None
            for k in range(1, 9):                                      # the load may be scheduled earlier
                wl = self.word(x - 4 * k)
                if wl is None: break
                if wl & 0x0FF00FF0 == 0x07900100 and (wl >> 12) & 15 == rb:
                    if (wl >> 16) & 15 != ra: return None
                    rx = wl & 15; break
                if (wl >> 12) & 15 == rb and wl & 0x0C000000 == 0: return None
            if rx is None: return None
            kind = 'rel'
        elif w & 0x0FF0FFF0 == 0x0790F100:                             # LDR pc, [rA, rX, lsl #2]
            ra, rx = (w >> 16) & 15, w & 15; kind = 'abs'
        else:
            return None
        base = None
        for k in range(1, 12):
            wa = self.word(x - 4 * k)
            if wa is not None and wa & 0x0FFFF000 == 0x028F0000 | (ra << 12):   # ADD rA, pc, #K
                base = x - 4 * k + 8 + a32.armexpand(wa & 0xFFF); break
        if base is None: return None
        n = self.table_bound(x, rx, 24)
        if n is not None and n > 4096: return None
        ents = []
        for i in range(n or 1024):
            v = self.word(base + 4 * i)
            if v is None: break
            t = (base + v) & 0xFFFFFFFF if kind == 'rel' else (m.base + v) & 0xFFFFFFFF
            ok = not t & 3 and self.mod_of(t) and (n is not None or abs(t - x) < 0x10000)
            if not ok:
                if n is None and ents: break
                return None
            ents.append(t)
        return ents

    def adr_ladder(self, x):
        """'add rX, pc, #K; (adjust rX); bx rX' into an unrolled ladder ending at the ADR target (__udivsi3):
        every instruction of the run of plain instructions before the target is an entry"""
        w = self.word(x)
        if w is None: return None
        if w & 0x0FFFFFF0 == 0x012FFF10: rx = w & 15                   # BX rX
        elif w & 0x0FFFFFF0 == 0x01A0F000: rx = w & 15                 # MOV pc, rX
        else: return None
        t = None
        for k in range(1, 9):
            wa = self.word(x - 4 * k)
            if wa is None: break
            if wa & 0x0FFFF000 == 0x028F0000 | (rx << 12): t = x - 4 * k + 8 + a32.armexpand(wa & 0xFFF); break
        if t is None or t <= x or t - x > 0x1000 or not self.mod_of(t): return None
        y = t - 4
        while y > x:
            r = self.decode(y)[1]
            if not isinstance(r, str): break
            y -= 4
        return list(range(y + 4, t + 4, 4))

    def pc_rel_target(self, x, w):
        """code addresses built pc-relative (PIC function pointers): 'add/sub rd, pc, #imm' and
        'ldr rm, [pc, #k]; ... add rd, pc, rm'. Only targets inside .text count."""
        t = None
        if w >> 28 == 15: return None
        if w & 0x0FFF0000 == 0x028F0000: t = x + 8 + a32.armexpand(w & 0xFFF)
        elif w & 0x0FFF0000 == 0x024F0000: t = x + 8 - a32.armexpand(w & 0xFFF)
        elif w & 0x0FFF0FF0 == 0x008F0000:
            rm = w & 15
            for k in range(1, 9):
                wl = self.word(x - 4 * k)
                if wl is None: break
                if wl & 0x0F7FF000 == 0x051F0000 | (rm << 12):          # LDR rm, [pc, #+-imm12]
                    la = x - 4 * k + 8 + ((wl & 0xFFF) if wl & (1 << 23) else -(wl & 0xFFF))
                    lv = self.word(la)
                    if lv is None:
                        m = self.mod_of(x); o = la - m.base
                        lv = int.from_bytes(m.image[o:o + 4], 'little') if 0 <= o <= len(m.image) - 4 else None
                    if lv is not None: t = (x + 8 + lv) & 0xFFFFFFFF
                    break
                if (wl >> 12) & 15 == rm and wl & 0x0C000000 == 0: break   # rm overwritten by data processing
        if t is None or t & 3 or not self.mod_of(t): return None
        return t

    def explore(self, a, stops):
        seen = set(); todo = [a]; calls = []; far = []
        while todo and len(seen) <= 300000:
            x = todo.pop()
            while True:
                if x in seen or (x != a and x in stops): break
                w, r = self.decode(x)
                if w is None: break
                seen.add(x)
                if r is None: break
                if isinstance(r, str):
                    t = self.pc_rel_target(x, w)
                    if t is not None: far.append(t)
                    x += 4; continue
                k = r[0]
                if k == 'bc':
                    t = r[2]
                    if self.mod_of(t): todo.append(t)
                elif k == 'b':
                    t = r[1]
                    if self.mod_of(t):
                        if t not in stops and abs(t - a) < 0x40000: todo.append(t)
                        else: far.append(t)
                    break
                elif k == 'bl':
                    if self.mod_of(r[1]): calls.append(r[1])
                    if r[1] == x + 8:     # 'bl over a literal; ldr rN, [lr]; add rN, rN, lr': pointer = &word + word
                        lv = self.word(x + 4)
                        t = (x + 4 + lv) & 0xFFFFFFFF if lv is not None else 1
                        if not t & 3 and self.mod_of(t): far.append(t)
                elif k == 'jt':
                    ents = self.jt_entries(x, r[1]); self.jt[x] = ents
                    todo.extend(ents)
                    if r[2] is None: break
                elif k in ('br', 'ret'):
                    if k == 'br':
                        ents = self.reg_tables(x) or self.adr_ladder(x)
                        if ents:
                            self.jt[x] = ents
                            todo.extend(t for t in ents if t not in stops)
                    if r[2] is None: break
                elif k == 'brk':
                    if r[2] is None: break
                x += 4
        return sorted(seen), calls, far

    def analyze(self, say=print):
        starts = set()
        for m in self.mods:
            for f in m.funcs: starts.add(m.base + f)
            for f in m.relptrs: starts.add(m.base + f)
            starts.add(m._t0)
        for h in self.hints:
            if self.mod_of(h) and not h & 3: starts.add(h)
        funcs = {}
        work = sorted(starts)
        known = set(work)
        rounds = 0
        while work:
            rounds += 1
            nxt = []
            for a in work:
                if a in funcs or a & 3: continue
                addrs, calls, far = self.explore(a, known)
                if not addrs: continue
                funcs[a] = Func(a, addrs, self.mod_of(a))
                for t in calls + far:
                    if t not in known and not t & 3: known.add(t); nxt.append(t)
            work = nxt
        # direct targets that landed inside another function's body become extra entries of that function
        self.funcs = funcs
        self.compute_leaders()
        ni = sum(len(f.addrs) for f in funcs.values())
        und = 0
        for f in funcs.values():
            for x in f.addrs:
                r = self.decode(x)[1]
                if isinstance(r, str) and 'UNDEF' in r:
                    und += 1; w = self.word(x); self.undef_count[w] = self.undef_count.get(w, 0) + 1
        say('Functions: %d  instructions: %d  (%d rounds, %d not translated)' % (len(funcs), ni, rounds, und))
        return funcs

    def compute_leaders(self):
        targets = set()
        for f in self.funcs.values():
            for x in f.addrs:
                r = self.decode(x)[1]
                if isinstance(r, tuple) and r[0] in ('b', 'bc', 'bl'): targets.add(r[-1] if r[0] != 'bl' else r[1])
        for f in self.funcs.values():
            s = f.aset
            L = {f.start}
            prev_term = False
            for x in f.addrs:
                if prev_term: L.add(x)
                r = self.decode(x)[1]
                prev_term = False
                if r is None: prev_term = True
                elif isinstance(r, tuple):
                    k = r[0]
                    if k == 'b': L.add(r[1]); prev_term = True
                    elif k == 'bc': L.add(r[2])
                    elif k in ('bl', 'blr', 'svc'): L.add(x + 4)
                    elif k == 'jt': L.update(self.jt.get(x, ())); L.add(x + 4); f.has_br = True
                    elif k in ('br', 'ret', 'brk'):
                        if k == 'br':
                            f.has_br = True; L.update(self.jt.get(x, ()))
                            # 'add pc, pc, rX, <shift>' computed jump (unrolled ladders: __udivmodsi4): any later
                            # instruction of the function can be the target
                            if (self.word(x) or 0) & 0x0FFFF010 == 0x008FF000: L.update(y for y in f.addrs if y >= x + 8)
                        if r[2] is None: prev_term = True
            L.update(x for x in f.addrs if x in targets or x in self.hints)
            f.leaders = {x for x in L if x in s}


# ======================================================================= emit
def emit_function(prog, f, funcs):
    s = f.addrs; sset = f.aset
    L = f.leaders
    out = ['void %s(CPU* RESTRICT c, u64 e){' % f.name, ' u8* const M=c->mem;']
    need_d = len(L) > 1 or f.has_br
    if need_d: out.append(' if(UNLIKELY(e!=%s)){ c->pc=e; goto D_; }' % lit(f.start))
    else: out.append(' if(UNLIKELY(e!=%s)){ CALLDYN(e); return; }' % lit(f.start))
    if s and s[0] != f.start: out.append(' goto L_%X;' % f.start)

    def tail(t):
        if t in sset: return 'goto L_%X;' % t
        if t in funcs: return '{ %s(c,%s); return; }' % (funcs[t].name, lit(t))
        return '{ CALLDYN(%s); return; }' % lit(t)

    def call(t):
        if t in funcs: return '%s(c,%s);' % (funcs[t].name, lit(t))
        return 'CALLDYN(%s);' % lit(t)

    def jump(expr):
        return ('c->pc=%s; goto D_;' % expr) if need_d else '{ u64 t_=%s; CALLDYN(t_); return; }' % expr

    def cnd(cond, body): return body if cond is None else 'if(%s){ %s }' % (cond, body)

    for i, x in enumerate(s):
        if x in L: out.append('L_%X:' % x)
        w, r = prog.decode(x)
        nxt = x + 4
        if w is None or r is None:
            out.append(' c->pc=%s; c->rt->undef(c,%s,%s); return;' % (lit(x), lit(x), lit(w or 0)))
            continue
        term = False
        if isinstance(r, str):
            if r: out.append(' ' + r.replace('UNDEF()', 'c->pc=%s; c->rt->undef(c,%s,%s)' % (lit(x), lit(x), lit(w))))
        else:
            k = r[0]
            if k == 'b':
                out.append(' ' + tail(r[1])); term = True
            elif k == 'bc':
                out.append(' if(%s) %s' % (r[1], tail(r[2])))
            elif k == 'bl':
                out.append(' ' + cnd(r[2], '{ ABI_SAVE(); c->x[14]=%s; %s if(UNLIKELY(c->pc!=%s)) return; ABI_CHECK(%s,%s); }' % (lit(nxt), call(r[1]), lit(nxt), lit(x), lit(r[1]))))
            elif k == 'blr':
                out.append(' ' + cnd(r[2], '{ u32 t_=%s; ABI_SAVE(); c->x[14]=%s; CALLDYN(t_); if(UNLIKELY(c->pc!=%s)) return; ABI_CHECK(%s,t_); }' % (r[1], lit(nxt), lit(nxt), lit(x))))
            elif k == 'br':
                out.append(' ' + cnd(r[2], '{ %s %s }' % (r[3], jump(r[1]))) if r[3] else ' ' + cnd(r[2], jump(r[1])))
                term = r[2] is None
            elif k == 'ret':
                out.append(' ' + cnd(r[2], '{ %s c->pc=%s; return; }' % (r[3], r[1])))
                term = r[2] is None
            elif k == 'jt':
                out.append(' ' + cnd(r[2], jump('%s+(R(%d)<<2)' % (lit(x + 8), r[1]))))
                term = r[2] is None
            elif k == 'svc':
                out.append(' ' + cnd(r[2], 'c->pc=%s; c->rt->svc(c,%s);' % (lit(nxt), r[1])))
            elif k == 'brk':
                out.append(' ' + cnd(r[2], 'c->pc=%s; c->rt->brk(c,%s,%s); return;' % (lit(x), lit(x), r[1])))
                term = r[2] is None
        if term: continue
        if nxt not in sset or (i + 1 < len(s) and s[i + 1] != nxt):
            out.append(' ' + tail(nxt))
    if need_d:
        out.append('D_: switch((u32)c->pc){')
        for x in sorted(L): out.append('  case %s: goto L_%X;' % (lit(x), x))
        out.append('  default: CALLDYN(c->pc); return; }')
    out.append('}')
    return '\n'.join(out)


INTERP_STUB = '''/* no interpreter for A32: code the analysis did not find is recorded as a hint for the next build */
static void swr_interp(CPU* RESTRICT c, u64 e){ if(c->rt->note_hint) c->rt->note_hint(e); c->pc=e; c->rt->undef(c,e,0xFFFFFFFFu); }'''
