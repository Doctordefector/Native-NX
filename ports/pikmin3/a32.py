"""
a32: AArch32 A32 (ARMv8-A, ARM state) -> C, for 32-bit Switch games (Pikmin 3 Deluxe).

emit(w, pc) returns
  str                       plain instruction (condition already applied)
  ('b', t)                  unconditional branch
  ('bc', cond, t)           conditional branch
  ('bl', t, cond)           call (cond None = always)
  ('blr', expr, cond)       indirect call
  ('br', expr, cond, pre)   indirect jump (pre: C run first, when the condition holds)
  ('ret', expr, cond, pre)  return
  ('jt', reg, cond, n)      'add pc, pc, reg, lsl #2' branch table: n entries of B at pc+8 (n None = unknown)
  ('svc', imm, cond)
  ('brk', imm, cond)
  None                      undefined: stops analysis
Registers: see runtime/cpu32.h. Instructions this file does not implement (but are valid) emit UNDEF() so a run
names them; tools/a32_test.py checks every form against Unicorn.
"""

COND = ['c->z', '!c->z', 'c->cf', '!c->cf', 'c->n', '!c->n', 'c->vf', '!c->vf',
        '(c->cf&&!c->z)', '(!c->cf||c->z)', '(c->n==c->vf)', '(c->n!=c->vf)',
        '(!c->z&&c->n==c->vf)', '(c->z||c->n!=c->vf)', None, None]


def bits(w, hi, lo): return (w >> lo) & ((1 << (hi - lo + 1)) - 1)
def bit(w, n): return (w >> n) & 1
def h(v): return '0x%Xu' % (v & 0xFFFFFFFF)
def sx(v, n): return v - (1 << n) if v >> (n - 1) else v


class Undef(Exception): pass


def rd(n, pc):
    """read register n as an expression (pc reads as pc+8)"""
    return h(pc + 8) if n == 15 else 'R(%d)' % n


def wrap(cond, body):
    return body if cond is None else 'if(%s){ %s }' % (cond, body)


def ror(v, r): r &= 31; return ((v >> r) | (v << (32 - r))) & 0xFFFFFFFF if r else v


def armexpand(imm12):
    return ror(imm12 & 0xFF, (imm12 >> 8) * 2)


# ---------------------------------------------------------------- shifter operands
SH = ['lsl', 'lsr', 'asr', 'ror']


def shift_imm(w, pc, carry):
    """register shifted by immediate: (setup C, value expr, carry expr or None)"""
    rm = bits(w, 3, 0); t = bits(w, 6, 5); s = bits(w, 11, 7)
    x = rd(rm, pc)
    if t == 0 and s == 0: return '', x, ('c->cf' if carry else None)
    if t == 3 and s == 0:    # RRX
        return '', '((c->cf<<31)|(%s>>1))' % x, ('(%s&1)' % x if carry else None)
    if t in (1, 2) and s == 0: s = 32
    if t == 0: v = '(%s<<%d)' % (x, s); cy = '((%s>>%d)&1)' % (x, 32 - s)
    elif t == 1:
        v = '0u' if s == 32 else '(%s>>%d)' % (x, s); cy = '((%s>>%d)&1)' % (x, s - 1)
    elif t == 2:
        v = '(u32)((i32)%s>>%d)' % (x, min(s, 31)); cy = '((%s>>%d)&1)' % (x, s - 1)
    else:
        v = 'ror32(%s,%d)' % (x, s); cy = '((%s>>%d)&1)' % (x, s - 1)
    return '', v, (cy if carry else None)


def shift_reg(w, pc, carry):
    rm = bits(w, 3, 0); t = bits(w, 6, 5); rs = bits(w, 11, 8)
    if 15 in (rm, rs, bits(w, 15, 12), bits(w, 19, 16)): raise Undef()
    x = 'R(%d)' % rm; s = 'R(%d)' % rs
    if carry:
        return 'u32 sc_; u32 sv_=a32_%s_c(c,%s,%s,&sc_);' % (SH[t], x, s), 'sv_', 'sc_'
    if t == 3: return '', 'ror32(%s,%s&31)' % (x, s), None
    return '', 'a32_%s(%s,%s)' % (SH[t], x, s), None


# ---------------------------------------------------------------- data processing
DP = ['and', 'eor', 'sub', 'rsb', 'add', 'adc', 'sbc', 'rsc', 'tst', 'teq', 'cmp', 'cmn', 'orr', 'mov', 'bic', 'mvn']


def dataproc(w, pc, cond):
    op = bits(w, 24, 21); S = bit(w, 20); rn = bits(w, 19, 16); d = bits(w, 15, 12)
    logical = op in (0, 1, 8, 9, 12, 13, 14, 15)
    if bit(w, 25):
        imm = armexpand(bits(w, 11, 0))
        setup, b = '', h(imm)
        cy = None
        if S and logical:
            cy = 'c->cf' if bits(w, 11, 8) == 0 else str(imm >> 31)
    elif bit(w, 4):
        setup, b, cy = shift_reg(w, pc, S and logical)
    else:
        setup, b, cy = shift_imm(w, pc, S and logical)
    a = rd(rn, pc)
    if bit(w, 4) and not bit(w, 25) and rn == 15: raise Undef()
    name = DP[op]
    if op in (8, 9, 10, 11) and not S: raise Undef()   # misc space, decoded elsewhere
    # value
    if S and not logical:
        f = {2: 'subs32(c,a_,b_)', 3: 'subs32(c,b_,a_)', 4: 'adds32(c,a_,b_,0)', 5: 'adds32(c,a_,b_,c->cf)',
             6: 'adds32(c,a_,~b_,c->cf)', 7: 'adds32(c,b_,~a_,c->cf)', 10: 'subs32(c,a_,b_)', 11: 'adds32(c,a_,b_,0)'}[op]
        val = f
    else:
        val = {0: 'a_&b_', 1: 'a_^b_', 2: 'a_-b_', 3: 'b_-a_', 4: 'a_+b_', 5: 'a_+b_+c->cf', 6: 'a_-b_-(c->cf^1)',
               7: 'b_-a_-(c->cf^1)', 8: 'a_&b_', 9: 'a_^b_', 10: '', 11: '', 12: 'a_|b_', 13: 'b_', 14: 'a_&~b_',
               15: '~b_'}[op]
    pre = setup + ' u32 a_=%s, b_=%s;' % (a if op not in (13, 15) else '0', b)
    if S and logical: pre += ' u32 cy_=%s;' % cy
    body = pre + ' u32 r_=%s;' % val
    if S and logical: body += ' c->n=r_>>31; c->z=r_==0; c->cf=cy_;'
    if op in (8, 9, 10, 11):
        return wrap(cond, '{' + body + ' (void)r_; }')
    if d == 15:
        if S: raise Undef()        # exception return, not in user code
        if op == 13 and not bit(w, 25) and not bit(w, 4) and bits(w, 11, 4) == 0:
            src = bits(w, 3, 0)
            if src == 14: return ('ret', 'R(14)', cond, '')
            return ('br', rd(src, pc), cond, '')
        if op == 4 and rn == 15 and not bit(w, 25) and not bit(w, 4) and bits(w, 6, 5) == 0 and bits(w, 11, 7) == 2:
            return ('jt', bits(w, 3, 0), cond, None)
        return ('br', '({' + body + ' r_;})', cond, '')
    return wrap(cond, '{' + body + ' SR(%d,r_); }' % d)


# ---------------------------------------------------------------- multiplies
def multiply(w, pc, cond):
    op = bits(w, 23, 21); S = bit(w, 20)
    d = bits(w, 19, 16); a = bits(w, 15, 12); m = bits(w, 11, 8); n = bits(w, 3, 0)
    if 15 in (d, m, n): raise Undef()
    if a == 15 and op in (1, 2, 3): raise Undef()
    fl = ' c->n=r_>>31; c->z=r_==0;' if S else ''
    if op == 0: return wrap(cond, '{ u32 r_=R(%d)*R(%d); SR(%d,r_);%s }' % (n, m, d, fl))
    if op == 1: return wrap(cond, '{ u32 r_=R(%d)*R(%d)+R(%d); SR(%d,r_);%s }' % (n, m, a, d, fl))
    if op == 2 and not S:
        return wrap(cond, '{ u64 r_=(u64)R(%d)*R(%d)+R(%d)+R(%d); SR(%d,r_); SR(%d,r_>>32); }' % (n, m, a, d, a, d))
    if op == 3 and not S: return wrap(cond, '{ SR(%d,R(%d)-R(%d)*R(%d)); }' % (d, a, n, m))
    lo, hi = a, d
    fl = ' c->n=(u32)(r_>>63); c->z=r_==0;' if S else ''
    if op == 4: v = '(u64)R(%d)*R(%d)' % (n, m)
    elif op == 5: v = '(u64)R(%d)*R(%d)+(((u64)R(%d)<<32)|R(%d))' % (n, m, hi, lo)
    elif op == 6: v = '(u64)((i64)(i32)R(%d)*(i32)R(%d))' % (n, m)
    elif op == 7: v = '(u64)((i64)(i32)R(%d)*(i32)R(%d))+(((u64)R(%d)<<32)|R(%d))' % (n, m, hi, lo)
    else: raise Undef()
    return wrap(cond, '{ u64 r_=%s; SR(%d,r_); SR(%d,r_>>32);%s }' % (v, lo, hi, fl))


def halfmul(w, pc, cond):
    op = bits(w, 22, 21); d = bits(w, 19, 16); a = bits(w, 15, 12); m = bits(w, 11, 8); n = bits(w, 3, 0)
    if 15 in (d, m, n) or (a == 15 and op != 3): raise Undef()
    xb = bit(w, 5); yb = bit(w, 6)
    hn = '(i32)(i16)(R(%d)>>%d)' % (n, 16 * xb); hm = '(i32)(i16)(R(%d)>>%d)' % (m, 16 * yb)
    if op == 0:   # SMLAxy
        return wrap(cond, '{ i64 r_=(i64)(%s*%s)+(i32)R(%d); if(r_!=(i32)r_) A32Q=1; SR(%d,r_); }' % (hn, hm, a, d))
    if op == 1:
        if xb == 0:   # SMLAWy
            return wrap(cond, '{ i64 r_=(((i64)(i32)R(%d)*%s)>>16)+(i32)R(%d); if(r_!=(i32)r_) A32Q=1; SR(%d,r_); }' % (n, hm, a, d))
        return wrap(cond, '{ SR(%d,(u32)(((i64)(i32)R(%d)*%s)>>16)); }' % (d, n, hm))    # SMULWy
    if op == 2:   # SMLALxy
        return wrap(cond, '{ i64 r_=(i64)(%s*%s)+(i64)(((u64)R(%d)<<32)|R(%d)); SR(%d,r_); SR(%d,(u64)r_>>32); }' % (hn, hm, d, a, a, d))
    return wrap(cond, '{ SR(%d,(u32)(%s*%s)); }' % (d, hn, hm))


# ---------------------------------------------------------------- loads / stores
def addr_mode(rn, off, P, U, W, pc):
    """-> (address expr, writeback C or '')"""
    base = rd(rn, pc) if rn != 15 else h((pc + 8) & ~3)
    sign = '+' if U else '-'
    nb = '(%s%s%s)' % (base, sign, off)
    if P:
        return '(u32)' + nb, ('SR(%d,%s);' % (rn, nb) if W else '')
    return base, 'SR(%d,%s);' % (rn, nb)


def ldst(w, pc, cond):
    I = bit(w, 25); P = bit(w, 24); U = bit(w, 23); B = bit(w, 22); W = bit(w, 21); L = bit(w, 20)
    rn = bits(w, 19, 16); t = bits(w, 15, 12)
    if I:
        if bit(w, 4): raise Undef()
        setup, off, _ = shift_imm(w, pc, False)
    else:
        off = h(bits(w, 11, 0)); setup = ''
    a, wb = addr_mode(rn, off, P, U, W, pc)
    if not P and W: pass        # LDRT/STRT: same thing for us
    if L:
        ld = 'RD8(a_)' if B else 'RD32(a_)'
        if t == 15:
            if B: raise Undef()
            if rn == 13 and not P and U and not I and bits(w, 11, 0) == 4:
                return ('ret', 'v_', cond, '%s u32 a_=%s; u32 v_=%s; %s' % (setup, a, ld, wb))
            return ('br', 'v_', cond, '%s u32 a_=%s; u32 v_=%s; %s' % (setup, a, ld, wb))
        return wrap(cond, '{ %s u32 a_=%s; u32 v_=%s; %s SR(%d,v_); }' % (setup, a, ld, wb, t))
    v = rd(t, pc) if t != 15 else h(pc + 8)
    st = 'WR8(a_,%s);' % v if B else 'WR32(a_,%s);' % v
    return wrap(cond, '{ %s u32 a_=%s; %s %s }' % (setup, a, st, wb))


def ldst_extra(w, pc, cond):
    P = bit(w, 24); U = bit(w, 23); I = bit(w, 22); W = bit(w, 21); L = bit(w, 20)
    rn = bits(w, 19, 16); t = bits(w, 15, 12); op2 = bits(w, 6, 5)
    off = h((bits(w, 11, 8) << 4) | bits(w, 3, 0)) if I else rd(bits(w, 3, 0), pc)
    a, wb = addr_mode(rn, off, P, U, W, pc)
    if op2 == 1:
        if L: return wrap(cond, '{ u32 a_=%s; u32 v_=RD16(a_); %s SR(%d,v_); }' % (a, wb, t))
        return wrap(cond, '{ u32 a_=%s; WR16(a_,%s); %s }' % (a, rd(t, pc), wb))
    if L:
        ld = 'RDS8(a_)' if op2 == 2 else 'RDS16(a_)'
        return wrap(cond, '{ u32 a_=%s; u32 v_=(u32)(i32)%s; %s SR(%d,v_); }' % (a, ld, wb, t))
    if t & 1 or t == 14: raise Undef()
    if op2 == 2:   # LDRD
        return wrap(cond, '{ u32 a_=%s; u32 v0_=RD32(a_), v1_=RD32(a_+4); %s SR(%d,v0_); SR(%d,v1_); }' % (a, wb, t, t + 1))
    return wrap(cond, '{ u32 a_=%s; WR32(a_,%s); WR32(a_+4,%s); %s }' % (a, rd(t, pc), rd(t + 1, pc), wb))


def sync(w, pc, cond):
    """LDREX/STREX family and ARMv8 LDA/STL (cond 0001 1xxx .... 11xx 1001)"""
    sz = bits(w, 22, 21); L = bit(w, 20); n = bits(w, 19, 16); kind = bits(w, 9, 8)
    if bits(w, 11, 10) != 3 or bits(w, 7, 4) != 9: raise Undef()
    nb = {0: 4, 1: 8, 2: 1, 3: 2}[sz]
    if L:
        t = bits(w, 15, 12)
        if kind == 0:     # LDA
            if sz == 1: raise Undef()
            ld = {4: 'RD32', 1: 'RD8', 2: 'RD16'}[nb]
            return wrap(cond, '{ u32 v_=%s(R(%d)); __atomic_thread_fence(__ATOMIC_ACQUIRE); SR(%d,v_); }' % (ld, n, t))
        if kind == 1: raise Undef()
        if nb == 8:
            return wrap(cond, '{ u32 a_=R(%d); a32_ldrex(c,M,a_,8); u64 v_=c->excl_val; SR(%d,v_); SR(%d,v_>>32); }' % (n, t, t + 1))
        return wrap(cond, '{ SR(%d,a32_ldrex(c,M,R(%d),%d)); }' % (t, n, nb))
    d = bits(w, 15, 12); t = bits(w, 3, 0)
    if kind == 0:     # STL
        if sz == 1: raise Undef()
        st = {4: 'WR32', 1: 'WR8', 2: 'WR16'}[nb]
        return wrap(cond, '{ __atomic_thread_fence(__ATOMIC_RELEASE); %s(R(%d),R(%d)); __atomic_thread_fence(__ATOMIC_SEQ_CST); }' % (st, n, t))
    if kind == 1: raise Undef()
    v = '(((u64)R(%d)<<32)|R(%d))' % (t + 1, t) if nb == 8 else 'R(%d)' % t
    return wrap(cond, '{ SR(%d,a32_strex(c,M,R(%d),%s,%d)); }' % (d, n, v, nb))


def ldm_stm(w, pc, cond):
    P = bit(w, 24); U = bit(w, 23); S = bit(w, 22); W = bit(w, 21); L = bit(w, 20)
    n = bits(w, 19, 16); regs = [i for i in range(16) if bit(w, i)]
    if S or not regs or n == 15: raise Undef()
    cnt = len(regs)
    start = {(0, 1): 0, (1, 1): 4, (0, 0): -4 * cnt + 4, (1, 0): -4 * cnt}[(P, U)]
    newb = 4 * cnt if U else -4 * cnt
    body = 'u32 b_=R(%d);' % n
    if L:
        for i, r in enumerate(regs):
            body += ' u32 v%d_=RD32(b_+%d);' % (r, start + 4 * i)
        if W and n not in regs: body += ' SR(%d,b_+%d);' % (n, newb)
        for r in regs:
            if r != 15: body += ' SR(%d,v%d_);' % (r, r)
        if 15 in regs:
            if n == 13 and W and U and not P: return ('ret', 'v15_', cond, body)
            return ('br', 'v15_', cond, body)
        return wrap(cond, '{ ' + body + ' }')
    for i, r in enumerate(regs):
        body += ' WR32(b_+%d,%s);' % (start + 4 * i, rd(r, pc) if r != 15 else h(pc + 8))
    if W: body += ' SR(%d,b_+%d);' % (n, newb)
    return wrap(cond, '{ ' + body + ' }')


# ---------------------------------------------------------------- misc / media
def misc(w, pc, cond):
    op = bits(w, 22, 21); op2 = bits(w, 6, 4)
    if op2 == 0:
        if op in (0, 2) and not bit(w, 9):
            if op == 0: return wrap(cond, 'SR(%d,a32_apsr(c)|0x10);' % bits(w, 15, 12))           # MRS
            raise Undef()
        if op == 1 and not bit(w, 9):                                                      # MSR APSR, reg
            mask = bits(w, 19, 18) << 2
            return wrap(cond, 'a32_set_apsr(c,%s,%d);' % (rd(bits(w, 3, 0), pc), mask))
        raise Undef()
    if op2 == 1:
        if op == 1:
            m = bits(w, 3, 0)
            if m == 14: return ('ret', 'R(14)', cond, '')
            return ('br', rd(m, pc), cond, '')
        if op == 3:
            return wrap(cond, 'SR(%d,clz32(R(%d)));' % (bits(w, 15, 12), bits(w, 3, 0)))
        raise Undef()
    if op2 == 3 and op == 1:
        return ('blr', rd(bits(w, 3, 0), pc), cond)
    if op2 == 5:     # QADD QSUB QDADD QDSUB
        d = bits(w, 15, 12); n = bits(w, 19, 16); m = bits(w, 3, 0)
        f = {0: 'a32_qadd(c,(i32)R(%d),(i32)R(%d))' % (m, n), 1: 'a32_qsub(c,(i32)R(%d),(i32)R(%d))' % (m, n),
             2: 'a32_qadd(c,(i32)R(%d),(i32)a32_qadd(c,(i32)R(%d),(i32)R(%d)))' % (m, n, n),
             3: 'a32_qsub(c,(i32)R(%d),(i32)a32_qadd(c,(i32)R(%d),(i32)R(%d)))' % (m, n, n)}[op]
        return wrap(cond, 'SR(%d,%s);' % (d, f))
    if op2 == 7 and op == 1:
        return ('brk', h((bits(w, 19, 8) << 4) | bits(w, 3, 0)), cond)
    raise Undef()


def extend(w, pc, cond):
    op = bits(w, 22, 20); n = bits(w, 19, 16); d = bits(w, 15, 12); rot = bits(w, 11, 10) * 8; m = bits(w, 3, 0)
    x = 'ror32(R(%d),%d)' % (m, rot) if rot else 'R(%d)' % m
    acc = '' if n == 15 else 'R(%d)+' % n
    if op == 2: v = '(u32)(i32)(i8)%s' % x
    elif op == 3: v = '(u32)(i32)(i16)%s' % x
    elif op == 6: v = '(u32)(u8)%s' % x
    elif op == 7: v = '(u32)(u16)%s' % x
    elif op in (0, 4):     # SXTB16 / UXTB16
        x_ = 'x_'; s = op == 0
        lo = '(u16)(i16)(i8)x_' if s else '(x_&0xFF)'
        hi = '(u16)(i16)(i8)(x_>>16)' if s else '((x_>>16)&0xFF)'
        if n == 15: v = '({ u32 x_=%s; (u32)%s|((u32)%s<<16); })' % (x, lo, hi)
        else: v = '({ u32 x_=%s, n_=R(%d); (u32)(u16)(n_+%s)|((u32)(u16)((n_>>16)+%s)<<16); })' % (x, n, lo, hi)
        return wrap(cond, 'SR(%d,%s);' % (d, v))
    else: raise Undef()
    return wrap(cond, 'SR(%d,%s%s);' % (d, acc, v))


def media(w, pc, cond):
    op1 = bits(w, 24, 20); op2 = bits(w, 7, 5)
    d = bits(w, 15, 12); n = bits(w, 19, 16); m = bits(w, 3, 0)
    if op1 >> 3 == 0:     # parallel add/sub
        k = bits(w, 22, 20)
        if k in (0, 4) or op2 in (5, 6): raise Undef()
        return wrap(cond, 'SR(%d,a32_parallel(c,%d,%d,R(%d),R(%d)));' % (d, k, op2, n, m))
    if op1 >> 3 == 1:
        if op1 == 0b01000 and op2 & 1 == 0:      # PKH
            sh = bits(w, 11, 7)
            if bit(w, 6):
                x = '(u32)((i32)R(%d)>>%d)' % (m, sh if sh else 31)
                return wrap(cond, 'SR(%d,(R(%d)&0xFFFF0000u)|(%s&0xFFFF));' % (d, n, x))
            return wrap(cond, 'SR(%d,(R(%d)&0xFFFF)|((R(%d)<<%d)&0xFFFF0000u));' % (d, n, m, sh))
        if op2 == 3 and bits(w, 9, 8) == 0: return extend(w, pc, cond)
        if op1 == 0b01000 and op2 == 5:          # SEL
            return wrap(cond, '{ u32 r_=0; for(int i=0;i<4;i++) r_|=((A32GE>>i)&1? R(%d) : R(%d))&(0xFFu<<(i*8)); SR(%d,r_); }' % (n, m, d))
        if op1 & 0b11010 == 0b01010 and op2 & 1 == 0:   # SSAT / USAT
            sat = bits(w, 20, 16); sh = bits(w, 11, 7); t = bit(w, 6)
            x = '(i32)(R(%d)<<%d)' % (m, sh) if not t else '((i32)R(%d)>>%d)' % (m, sh if sh else 31)
            if bit(w, 22): return wrap(cond, 'SR(%d,a32_usat(c,%s,%d));' % (d, x, sat))
            return wrap(cond, 'SR(%d,a32_ssat(c,%s,%d));' % (d, x, sat + 1))
        if op1 == 0b01011 and op2 == 1: return wrap(cond, 'SR(%d,__builtin_bswap32(R(%d)));' % (d, m))
        if op1 == 0b01011 and op2 == 5:
            return wrap(cond, '{ u32 x_=R(%d); SR(%d,((x_&0x00FF00FFu)<<8)|((x_>>8)&0x00FF00FFu)); }' % (m, d))
        if op1 == 0b01111 and op2 == 1:
            return wrap(cond, '{ u32 x_=R(%d), r_=0; for(int i=0;i<32;i++) r_|=((x_>>i)&1)<<(31-i); SR(%d,r_); }' % (m, d))
        if op1 == 0b01111 and op2 == 5:
            return wrap(cond, '{ u32 x_=R(%d); SR(%d,(u32)(i32)(i16)(((x_&0xFF)<<8)|((x_>>8)&0xFF))); }' % (m, d))
        raise Undef()
    if op1 >> 3 == 2:     # signed multiplies, divide
        dd = bits(w, 19, 16); a = bits(w, 15, 12); mm = bits(w, 11, 8); nn = bits(w, 3, 0)
        if op1 == 0b10001 and op2 == 0:
            return wrap(cond, '{ i32 n_=(i32)R(%d), m_=(i32)R(%d); SR(%d, m_==0? 0 : (n_==INT32_MIN&&m_==-1)? (u32)INT32_MIN : (u32)(n_/m_)); }' % (nn, mm, dd))
        if op1 == 0b10011 and op2 == 0:
            return wrap(cond, '{ u32 n_=R(%d), m_=R(%d); SR(%d, m_? n_/m_ : 0); }' % (nn, mm, dd))
        if op1 == 0b10101 and op2 >> 1 == 0:      # SMMUL/SMMLA (R rounds)
            r = '+0x80000000ll' if bit(w, 5) else ''
            acc = '' if a == 15 else '((i64)(i32)R(%d)<<32)+' % a
            return wrap(cond, 'SR(%d,(u32)((u64)(%s(i64)(i32)R(%d)*(i32)R(%d)%s)>>32));' % (dd, acc, nn, mm, r))
        if op1 == 0b10101 and op2 >> 1 == 3:      # SMMLS
            r = '+0x80000000ll' if bit(w, 5) else ''
            return wrap(cond, 'SR(%d,(u32)((u64)(((i64)(i32)R(%d)<<32)-(i64)(i32)R(%d)*(i32)R(%d)%s)>>32));' % (dd, a, nn, mm, r))
        if op1 in (0b10000, 0b10100) and op2 >> 2 == 0:   # SMLAD/SMLSD/SMUAD/SMUSD, SMLALD/SMLSLD
            x = bit(w, 5); sub = bit(w, 6)
            mexpr = 'ror32(R(%d),16)' % mm if x else 'R(%d)' % mm
            p = '({ u32 n_=R(%d), m_=%s; i64 p1_=(i64)(i16)n_*(i16)m_, p2_=(i64)(i16)(n_>>16)*(i16)(m_>>16); p1_%sp2_; })' % (nn, mexpr, '-' if sub else '+')
            if op1 == 0b10000:
                acc = '0' if a == 15 else '(i32)R(%d)' % a
                return wrap(cond, '{ i64 r_=%s+%s; if(r_!=(i32)r_) A32Q=1; SR(%d,r_); }' % (p, acc, dd))
            return wrap(cond, '{ i64 r_=%s+(i64)(((u64)R(%d)<<32)|R(%d)); SR(%d,r_); SR(%d,(u64)r_>>32); }' % (p, dd, a, a, dd))
        raise Undef()
    if op1 == 0b11000 and op2 == 0:   # USAD8 / USADA8
        dd = bits(w, 19, 16); a = bits(w, 15, 12); mm = bits(w, 11, 8); nn = bits(w, 3, 0)
        acc = '0' if a == 15 else 'R(%d)' % a
        return wrap(cond, '{ u32 n_=R(%d), m_=R(%d), r_=%s; for(int i=0;i<32;i+=8){ int x_=(int)((n_>>i)&255)-(int)((m_>>i)&255); r_+=x_<0?-x_:x_; } SR(%d,r_); }' % (nn, mm, acc, dd))
    if op1 & 0b11110 == 0b11010 and op2 & 3 == 2:   # SBFX
        lsb = bits(w, 11, 7); wd = bits(w, 20, 16) + 1
        if lsb + wd > 32: raise Undef()
        return wrap(cond, 'SR(%d,(u32)((i32)(R(%d)<<%d)>>%d));' % (d, m, 32 - lsb - wd, 32 - wd))
    if op1 & 0b11110 == 0b11110 and op2 & 3 == 2:   # UBFX
        lsb = bits(w, 11, 7); wd = bits(w, 20, 16) + 1
        if lsb + wd > 32: raise Undef()
        return wrap(cond, 'SR(%d,(R(%d)>>%d)&%s);' % (d, m, lsb, h((1 << wd) - 1)))
    if op1 & 0b11110 == 0b11100 and op2 & 3 == 0:   # BFC / BFI
        lsb = bits(w, 11, 7); msb = bits(w, 20, 16)
        if msb < lsb: raise Undef()
        mask = ((1 << (msb - lsb + 1)) - 1) << lsb
        src = '0' if m == 15 else '(R(%d)<<%d)' % (m, lsb)
        return wrap(cond, 'SR(%d,(R(%d)&%s)|(%s&%s));' % (d, d, h(~mask), src, h(mask)))
    if op1 == 0b11111 and op2 == 7:
        return ('brk', h((bits(w, 19, 8) << 4) | bits(w, 3, 0)), cond)   # UDF
    raise Undef()


# ---------------------------------------------------------------- coprocessor: p15, VFP
def sreg(v, x): return (v << 1) | x      # single: Vx:bit
def dreg(v, x): return (x << 4) | v      # double: bit:Vx


def vfp_dp(w, pc, cond):
    """VFP data processing, cond 1110 .... 101x ...0"""
    dbl = bit(w, 8)
    o1 = (bit(w, 23) << 2) | bits(w, 21, 20); o3 = bits(w, 7, 6)
    Vd = bits(w, 15, 12); Vn = bits(w, 19, 16); Vm = bits(w, 3, 0)
    D, N, M = bit(w, 22), bit(w, 7), bit(w, 5)
    if dbl: d, n, m = dreg(Vd, D), dreg(Vn, N), dreg(Vm, M); F = 'DF'; T = 'f64'
    else: d, n, m = sreg(Vd, D), sreg(Vn, N), sreg(Vm, M); F = 'SF'; T = 'f32'
    Fd, Fn, Fm = '%s(%d)' % (F, d), '%s(%d)' % (F, n), '%s(%d)' % (F, m)
    op = bit(w, 6)
    if o1 == 0:   # VMLA / VMLS (not fused: product rounded first)
        return wrap(cond, '{ %s p_=%s*%s; %s=%s%sp_; }' % (T, Fn, Fm, Fd, Fd, '-' if op else '+'))
    if o1 == 1:   # VNMLS / VNMLA
        return wrap(cond, '{ %s p_=%s*%s; %s=%s; }' % (T, Fn, Fm, Fd, ('-%s-p_' % Fd) if op else ('-%s+p_' % Fd)))
    if o1 == 2:
        return wrap(cond, '{ %s p_=%s*%s; %s=%sp_; }' % (T, Fn, Fm, Fd, '-' if op else ''))
    if o1 == 3:
        return wrap(cond, '%s=%s%s%s;' % (Fd, Fn, '-' if op else '+', Fm))
    if o1 == 4 and not op:
        return wrap(cond, '%s=%s/%s;' % (Fd, Fn, Fm))
    fma = 'fma' if dbl else 'fmaf'
    if o1 == 5:   # VFNMA / VFNMS
        return wrap(cond, '%s=%s(%s%s,%s,-%s);' % (Fd, fma, '-' if op else '', Fn, Fm, Fd))
    if o1 == 6:   # VFMA / VFMS
        return wrap(cond, '%s=%s(%s%s,%s,%s);' % (Fd, fma, '-' if op else '', Fn, Fm, Fd))
    if o1 != 7: raise Undef()
    o2 = bits(w, 19, 16)
    if o3 & 1 == 0:   # VMOV immediate
        imm8 = (bits(w, 19, 16) << 4) | bits(w, 3, 0)
        a = imm8 >> 7; b = (imm8 >> 6) & 1; cdefgh = imm8 & 0x3F
        if dbl:
            v = (a << 63) | ((b ^ 1) << 62) | ((0xFF if b else 0) << 54) | (cdefgh << 48)
            return wrap(cond, 'DU(%d)=0x%016Xull;' % (d, v))
        v = (a << 31) | ((b ^ 1) << 30) | ((0x1F if b else 0) << 25) | (cdefgh << 19)
        return wrap(cond, 'SU(%d)=%s;' % (d, h(v)))
    U = 'DU' if dbl else 'SU'; sb = '0x8000000000000000ull' if dbl else '0x80000000u'
    if o2 == 0 and o3 == 1: return wrap(cond, '%s(%d)=%s(%d);' % (U, d, U, m))
    if o2 == 0 and o3 == 3: return wrap(cond, '%s(%d)=%s(%d)&~%s;' % (U, d, U, m, sb))
    if o2 == 1 and o3 == 1: return wrap(cond, '%s(%d)=%s(%d)^%s;' % (U, d, U, m, sb))
    if o2 == 1 and o3 == 3: return wrap(cond, '%s=%s(%s);' % (Fd, 'sqrt' if dbl else 'sqrtf', Fm))
    if o2 in (4, 5):     # VCMP{E} (exception difference ignored)
        rhs = '0' if o2 == 5 else Fm
        return wrap(cond, 'a32_fcmp%d(c,%s,%s);' % (64 if dbl else 32, Fd, rhs))
    if o2 == 7 and o3 == 3:   # VCVT between f32/f64
        if dbl: return wrap(cond, 'SF(%d)=(f32)DF(%d);' % (sreg(Vd, D), m))
        return wrap(cond, 'DF(%d)=(f64)SF(%d);' % (dreg(Vd, D), m))
    if o2 == 8:          # VCVT int -> float, source is always a single register
        sm = sreg(Vm, M)
        src = '(i32)SU(%d)' % sm if bit(w, 7) else 'SU(%d)' % sm
        return wrap(cond, '%s=(%s)%s;' % (Fd if not dbl else 'DF(%d)' % dreg(Vd, D), T, src))
    if o2 in (12, 13):   # VCVT float -> int, result in a single register
        sd = sreg(Vd, D)
        x = Fm if bit(w, 7) else 'a32_round(c,%s,-1)' % Fm
        f = 'a32_f2s' if o2 == 13 else 'a32_f2u'
        return wrap(cond, 'SU(%d)=(u32)%s(%s);' % (sd, f, x))
    if o2 == 6:          # VRINTR / VRINTZ
        return wrap(cond, '%s=(%s)a32_round(c,%s,%d);' % (Fd, T, Fm, 3 if bit(w, 7) else -1))
    if o2 == 7 and o3 == 1:   # VRINTX
        return wrap(cond, '%s=(%s)a32_round(c,%s,-1);' % (Fd, T, Fm))
    if o2 in (2, 3):     # VCVTB/VCVTT half <-> single
        t = bit(w, 7)
        if o2 == 2 and not dbl:
            return wrap(cond, '{ _Float16 h_; u16 b_=(u16)(SU(%d)>>%d); memcpy(&h_,&b_,2); SF(%d)=(f32)h_; }' % (m, 16 * t, d))
        if o2 == 3 and not dbl:
            return wrap(cond, '{ _Float16 h_=(_Float16)SF(%d); u16 b_; memcpy(&b_,&h_,2); SU(%d)=(SU(%d)&%s)|((u32)b_<<%d); }' % (m, d, d, h(0xFFFF0000 if not t else 0xFFFF), 16 * t))
        raise Undef()
    if o2 in (10, 11, 14, 15):   # VCVT fixed point, in place on Vd: frac = size - imm4:i
        U_ = bit(w, 16); size = 32 if bit(w, 7) else 16
        fb = size - ((bits(w, 3, 0) << 1) | bit(w, 5))
        if fb < 0: raise Undef()
        sc = repr(float(1 << fb))
        raw = '(u32)DU(%d)' % d if dbl else 'SU(%d)' % d
        if o2 in (10, 11):        # fixed -> float
            st = {(16, 0): 'i16', (16, 1): 'u16', (32, 0): 'i32', (32, 1): 'u32'}[(size, U_)]
            return wrap(cond, '%s=(%s)((f64)(%s)%s/%s);' % (Fd, T, st, raw, sc))
        # float -> fixed, round toward zero, saturate to size bits
        lo, hi = ((0, (1 << size) - 1) if U_ else (-(1 << (size - 1)), (1 << (size - 1)) - 1))
        v = '({ f64 x_=(f64)%s*%s; x_!=x_? 0 : x_>=%d.0? %dLL : x_<=%d.0? %dLL : (i64)x_; })' % (Fd, sc, hi, hi, lo, lo)
        if dbl: return wrap(cond, 'DU(%d)=(u64)(u32)%s;' % (d, v)) if size == 32 else wrap(cond, 'DU(%d)=(u64)(u16)%s;' % (d, v))
        return wrap(cond, 'SU(%d)=(u32)%s;' % (d, v) if size == 32 else 'SU(%d)=(u32)(u16)%s;' % (d, v))
    raise Undef()


def vfp_v8(w, pc):
    """cond=1111 VFP: VSEL, VMAXNM/VMINNM, VRINT{A,N,P,M}, VCVT{A,N,P,M}"""
    dbl = bit(w, 8)
    Vd = bits(w, 15, 12); Vn = bits(w, 19, 16); Vm = bits(w, 3, 0)
    D, N, M = bit(w, 22), bit(w, 7), bit(w, 5)
    if dbl: d, n, m = dreg(Vd, D), dreg(Vn, N), dreg(Vm, M); F = 'DF'; T = 'f64'; U = 'DU'
    else: d, n, m = sreg(Vd, D), sreg(Vn, N), sreg(Vm, M); F = 'SF'; T = 'f32'; U = 'SU'
    if bits(w, 27, 23) == 0b11100 and bit(w, 6) == 0 and bit(w, 4) == 0:   # VSEL
        cc = [COND[0], COND[6], COND[10], COND[12]][bits(w, 21, 20)]
        return '%s(%d)=%s? %s(%d) : %s(%d);' % (U, d, cc, U, n, U, m)
    if bits(w, 27, 23) == 0b11101 and bits(w, 21, 20) == 0 and bit(w, 4) == 0:   # VMAXNM/VMINNM
        f = ('fmin' if bit(w, 6) else 'fmax') + ('' if dbl else 'f')
        return '%s(%d)=%s(%s(%d),%s(%d));' % (F, d, f, F, n, F, m)
    if bits(w, 27, 23) == 0b11101 and bits(w, 21, 18) == 0b1110 and bits(w, 7, 6) == 1:   # VRINTA/N/P/M
        mode = [4, 0, 1, 2][bits(w, 17, 16)]
        return '%s(%d)=(%s)a32_round(c,%s(%d),%d);' % (F, d, T, F, m, mode)
    if bits(w, 27, 23) == 0b11101 and bits(w, 21, 18) == 0b1111 and bit(w, 6) == 1:   # VCVTA/N/P/M
        mode = [4, 0, 1, 2][bits(w, 17, 16)]
        f = 'a32_f2s' if bit(w, 7) else 'a32_f2u'
        return 'SU(%d)=(u32)%s(a32_round(c,%s(%d),%d));' % (sreg(Vd, D), f, F, m, mode)
    raise Undef()


def vfp_ldst(w, pc, cond):
    P = bit(w, 24); U = bit(w, 23); D = bit(w, 22); W = bit(w, 21); L = bit(w, 20)
    n = bits(w, 19, 16); Vd = bits(w, 15, 12); dbl = bit(w, 8); imm8 = bits(w, 7, 0)
    if P and not W:       # VLDR / VSTR
        base = h(((pc + 8) & ~3)) if n == 15 else 'R(%d)' % n
        a = '(u32)(%s%s%d)' % (base, '+' if U else '-', imm8 * 4)
        if dbl:
            r = dreg(Vd, D)
            return wrap(cond, ('DU(%d)=RD64(%s);' % (r, a)) if L else ('WR64(%s,DU(%d));' % (a, r)))
        r = sreg(Vd, D)
        return wrap(cond, ('SU(%d)=RD32(%s);' % (r, a)) if L else ('WR32(%s,SU(%d));' % (a, r)))
    if not P and not U and not W: raise Undef()
    if P and U: raise Undef()
    if n == 15: raise Undef()
    first = dreg(Vd, D) if dbl else sreg(Vd, D)
    cnt = imm8 // 2 if dbl else imm8
    if cnt == 0: raise Undef()
    body = 'u32 b_=R(%d)%s;' % (n, '' if U else '-%d' % (imm8 * 4))
    for i in range(cnt):
        if dbl:
            body += (' DU(%d)=RD64(b_+%d);' if L else ' WR64(b_+%d,DU(%d));' ) % ((first + i, 8 * i) if L else (8 * i, first + i))
        else:
            body += (' SU(%d)=RD32(b_+%d);' if L else ' WR32(b_+%d,SU(%d));') % ((first + i, 4 * i) if L else (4 * i, first + i))
    if W: body += ' SR(%d,R(%d)%s%d);' % (n, n, '+' if U else '-', imm8 * 4)
    return wrap(cond, '{ ' + body + ' }')


def coproc(w, pc, cond):
    cp = bits(w, 11, 8); op1 = bits(w, 27, 24)
    if op1 == 0b1110 and bit(w, 4) == 0 and cp in (10, 11):
        return vfp_dp(w, pc, cond)
    if op1 == 0b1110 and bit(w, 4) == 1:
        L = bit(w, 20); t = bits(w, 15, 12)
        if cp == 15:     # MRC / MCR p15
            o1 = bits(w, 23, 21); crn = bits(w, 19, 16); crm = bits(w, 3, 0); o2 = bits(w, 7, 5)
            key = (o1, crn, crm, o2)
            if key == (0, 13, 0, 3) and L: return wrap(cond, 'SR(%d,c->tpidrro);' % t)
            if key == (0, 13, 0, 2): return wrap(cond, 'SR(%d,c->tpidr);' % t if L else 'c->tpidr=R(%d);' % t)
            if key == (0, 14, 0, 0) and L: return wrap(cond, 'SR(%d,19200000u);' % t)
            if crn == 7 and not L and (crm, o2) in ((10, 5), (10, 4), (5, 4)):
                return wrap(cond, '__atomic_thread_fence(__ATOMIC_SEQ_CST);')
            raise Undef()
        if cp == 10 and bits(w, 23, 21) == 0 and bits(w, 6, 5) == 0:   # VMOV core <-> single
            s = sreg(bits(w, 19, 16), bit(w, 7))
            return wrap(cond, ('SR(%d,SU(%d));' % (t, s)) if L else ('SU(%d)=%s;' % (s, rd(t, pc))))
        if cp == 10 and bits(w, 23, 21) == 7:     # VMRS / VMSR
            if bits(w, 19, 16) != 1: raise Undef()
            if L:
                if t == 15: return wrap(cond, 'set_nzcv(c,c->fpsr>>28);')
                return wrap(cond, 'SR(%d,a32_fpscr(c));' % t)
            return wrap(cond, 'a32_set_fpscr(c,R(%d));' % t)
        if cp == 11:     # VMOV scalar <-> core, VDUP core
            o1 = bits(w, 22, 21); o2 = bits(w, 6, 5); Dn = dreg(bits(w, 19, 16), bit(w, 7))
            if not L and bit(w, 23) == 0:   # to scalar
                if o1 & 2: sz, idx = 1, ((o1 & 1) << 2) | o2
                elif o2 & 1: sz, idx = 2, ((o1 & 1) << 1) | (o2 >> 1)
                elif o2 == 0: sz, idx = 4, o1 & 1
                else: raise Undef()
                ty = {1: 'u8', 2: 'u16', 4: 'u32'}[sz]
                return wrap(cond, '*(%s*)(VB+%d)=(%s)%s;' % (ty, Dn * 8 + idx * sz, ty, rd(t, pc)))
            if L:   # from scalar
                U = bit(w, 23)
                if o1 & 2: sz, idx = 1, ((o1 & 1) << 2) | o2
                elif o2 & 1: sz, idx = 2, ((o1 & 1) << 1) | (o2 >> 1)
                elif o2 == 0 and not U: sz, idx = 4, o1 & 1
                else: raise Undef()
                ty = {1: 'i8', 2: 'i16', 4: 'u32'}[sz]
                if U: ty = 'u' + ty[1:]
                return wrap(cond, 'SR(%d,(u32)(i32)*(%s*)(VB+%d));' % (t, ty, Dn * 8 + idx * sz))
            # VDUP core
            B = bit(w, 22); E = bit(w, 5); Q = bit(w, 21)
            sz = 1 if B else 2 if E else 4
            if B and E: raise Undef()
            if Q and Dn & 1: raise Undef()
            ty = {1: 'u8', 2: 'u16', 4: 'u32'}[sz]
            n = (16 if Q else 8) // sz
            return wrap(cond, '{ %s v_=(%s)%s; for(int i=0;i<%d;i++) ((%s*)(VB+%d))[i]=v_; }' % (ty, ty, rd(t, pc), n, ty, Dn * 8))
        raise Undef()
    if op1 in (0b1100, 0b1101) or (op1 & 0b1110 == 0b1100):
        if bits(w, 24, 21) == 0b0010:   # 64-bit transfers (MCRR/MRRC, VMOV 2 core)
            L = bit(w, 20); t = bits(w, 15, 12); t2 = bits(w, 19, 16)
            if cp == 15:
                if L and bits(w, 3, 0) == 14 and bits(w, 7, 4) in (0, 1):   # CNTPCT / CNTVCT
                    return wrap(cond, '{ u64 v_=c->rt->ticks(); SR(%d,v_); SR(%d,v_>>32); }' % (t, t2))
                raise Undef()
            if cp == 11 and bits(w, 7, 6) == 0 and bit(w, 4):
                dm = dreg(bits(w, 3, 0), bit(w, 5))
                if L: return wrap(cond, '{ u64 v_=DU(%d); SR(%d,v_); SR(%d,v_>>32); }' % (dm, t, t2))
                return wrap(cond, 'DU(%d)=((u64)%s<<32)|%s;' % (dm, rd(t2, pc), rd(t, pc)))
            if cp == 10 and bits(w, 7, 6) == 0 and bit(w, 4):
                sm = sreg(bits(w, 3, 0), bit(w, 5))
                if sm == 31: raise Undef()
                if L: return wrap(cond, '{ SR(%d,SU(%d)); SR(%d,SU(%d)); }' % (t, sm, t2, sm + 1))
                return wrap(cond, '{ SU(%d)=%s; SU(%d)=%s; }' % (sm, rd(t, pc), sm + 1, rd(t2, pc)))
            raise Undef()
        if cp in (10, 11): return vfp_ldst(w, pc, cond)
    raise Undef()


# ---------------------------------------------------------------- NEON
import a32_neon


# ---------------------------------------------------------------- top level
def uncond(w, pc):
    """cond = 1111"""
    if w & 0xFE000000 == 0xF2000000: return a32_neon.dp(w, pc)
    if w & 0xFF100000 == 0xF4000000: return a32_neon.ldst(w, pc)
    if w & 0xFE000000 == 0xFA000000:     # BLX imm: switches to Thumb, which this translator does not do
        return 'UNDEF();'
    if w & 0xFFFFFFF0 in (0xF57FF050, 0xF57FF040, 0xF57FF060): return '__atomic_thread_fence(__ATOMIC_SEQ_CST);'
    if w == 0xF57FF01F: return 'c->excl_on=0;'                                     # CLREX
    if w & 0xFD70F000 == 0xF550F000 or w & 0xFF30F000 == 0xF510F000 or w & 0xFF70F000 == 0xF450F000 \
            or w & 0xFE70F010 == 0xF650F000 or w & 0xFF30F010 == 0xF710F000:
        return ''                                                                  # PLD / PLI
    if w & 0x0F000E10 == 0x0E000A00: return vfp_v8(w, pc)
    raise Undef()


def emit(w, pc):
    try:
        return _emit(w, pc)
    except Undef:
        return None


def _emit(w, pc):
    cv = w >> 28
    if cv == 15: return uncond(w, pc)
    cond = COND[cv]
    if cv == 14: cond = None
    op = bits(w, 27, 25)
    if op == 0:
        if bit(w, 4) and bit(w, 7):
            if bits(w, 6, 5) == 0:
                if bits(w, 24, 23) == 0: return multiply(w, pc, cond)
                if bit(w, 24) and bits(w, 11, 10) == 3: return sync(w, pc, cond)
                raise Undef()                      # SWP (deprecated)
            if bit(w, 24) == 0 and bit(w, 21) and False: pass
            return ldst_extra(w, pc, cond)
        if bits(w, 24, 23) == 2 and not bit(w, 20):
            if bit(w, 7) and not bit(w, 4): return halfmul(w, pc, cond)
            return misc(w, pc, cond)
        return dataproc(w, pc, cond)
    if op == 1:
        o = bits(w, 24, 20)
        if o == 0b10000: return wrap(cond, 'SR(%d,%s);' % (bits(w, 15, 12), h((bits(w, 19, 16) << 12) | bits(w, 11, 0))))
        if o == 0b10100:
            d = bits(w, 15, 12)
            return wrap(cond, 'SR(%d,(R(%d)&0xFFFF)|%s);' % (d, d, h(((bits(w, 19, 16) << 12) | bits(w, 11, 0)) << 16)))
        if o in (0b10010, 0b10110):       # MSR imm / hints
            if o == 0b10010 and bits(w, 19, 16) == 0:
                return '' if bits(w, 7, 0) in (0, 1, 2, 3, 4, 5) or bits(w, 7, 4) == 0xF else 'UNDEF();'
            if o == 0b10010:
                return wrap(cond, 'a32_set_apsr(c,%s,%d);' % (h(armexpand(bits(w, 11, 0))), bits(w, 19, 18) << 2))
            raise Undef()
        return dataproc(w, pc, cond)
    if op == 2: return ldst(w, pc, cond)
    if op == 3:
        if bit(w, 4): return media(w, pc, cond)
        return ldst(w, pc, cond)
    if op == 4: return ldm_stm(w, pc, cond)
    if op == 5:
        t = (pc + 8 + (sx(bits(w, 23, 0), 24) << 2)) & 0xFFFFFFFF
        if bit(w, 24): return ('bl', t, cond)
        return ('b', t) if cond is None else ('bc', cond, t)
    if op == 7 and bit(w, 24):
        return ('svc', h(bits(w, 23, 0)), cond)
    return coproc(w, pc, cond)
