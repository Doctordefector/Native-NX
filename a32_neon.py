"""
a32_neon: Advanced SIMD (A32 encodings 1111 001x and 1111 0100 xxx0) -> C.
Vectors are worked on in V128 temporaries (D = low 8 bytes); see runtime/cpu32.h for the register file.
Valid forms that are not implemented emit UNDEF() so a run names them.
"""

UNDEF = 'UNDEF();'


def bits(w, hi, lo): return (w >> lo) & ((1 << (hi - lo + 1)) - 1)
def bit(w, n): return (w >> n) & 1
def dreg(v, x): return (x << 4) | v


def regs(w):
    return dreg(bits(w, 15, 12), bit(w, 22)), dreg(bits(w, 19, 16), bit(w, 7)), dreg(bits(w, 3, 0), bit(w, 5))


def LD(var, r, q): return 'memcpy(&%s,VB+%d,%d);' % (var, r * 8, 16 if q else 8)
def ST(var, r, q): return 'memcpy(VB+%d,&%s,%d);' % (r * 8, var, 16 if q else 8)


ITY = {(0, 0): 'i8', (1, 0): 'i16', (2, 0): 'i32', (3, 0): 'i64', (0, 1): 'u8', (1, 1): 'u16', (2, 1): 'u32', (3, 1): 'u64'}
FLD = {'i8': 'sb', 'u8': 'b', 'i16': 'sh', 'u16': 'h', 'i32': 'ss', 'u32': 's', 'i64': 'sd', 'u64': 'd', 'f32': 'f'}
WIDE = {'i8': 'i16', 'u8': 'u16', 'i16': 'i32', 'u16': 'u32', 'i32': 'i64', 'u32': 'u64'}
MAXV = {'i8': (-128, 127), 'u8': (0, 255), 'i16': (-32768, 32767), 'u16': (0, 65535),
        'i32': (-2147483648, 2147483647), 'u32': (0, 4294967295)}


def lanes(q, sz): return (16 if q else 8) >> sz


def binop(w, q, ty, expr, d, n, m, acc=False):
    """d[i] = expr(n_.x[i], m_.x[i]) per lane; expr uses A and B (and D for the old destination)"""
    f = FLD[ty]; nl = (16 if q else 8) // (8 if ty in ('i64', 'u64') else 4 if ty in ('i32', 'u32', 'f32') else 2 if ty in ('i16', 'u16') else 1)
    if ty == 'f32':     # Advanced SIMD always flushes denormals (standard FPSCR value)
        e = 'a32_fz(%s)' % expr.replace('A', 'a32_fz(n_.f[i])').replace('B', 'a32_fz(m_.f[i])').replace('D', 'a32_fz(d_.f[i])')
    else:
        e = expr.replace('A', 'n_.%s[i]' % f).replace('B', 'm_.%s[i]' % f).replace('D', 'd_.%s[i]' % f)
    return '{ V128 n_,m_,d_; %s %s %s for(int i=0;i<%d;i++) d_.%s[i]=(%s)(%s); %s }' % (
        LD('n_', n, q), LD('m_', m, q), LD('d_', d, q), nl, f, ty, e, ST('d_', d, q))


def unop(q, ty, expr, d, m, tyd=None):
    tyd = tyd or ty
    fs, fd = FLD[ty], FLD[tyd]
    nl = (16 if q else 8) // {'8': 1, '16': 2, '32': 4, '64': 8}[''.join(ch for ch in ty if ch.isdigit())]
    e = expr.replace('A', 'm_.%s[i]' % fs)
    return '{ V128 m_,d_; %s %s for(int i=0;i<%d;i++) d_.%s[i]=(%s)(%s); %s }' % (LD('m_', m, q), LD('d_', d, q), nl, fd, tyd, e, ST('d_', d, q))


def sat(ty, e):
    lo, hi = MAXV[ty]
    return '({ i64 s_=(i64)(%s); s_>%dLL? (c->fpsr|=1u<<27,(%s)%dLL) : s_<%dLL? (c->fpsr|=1u<<27,(%s)%dLL) : (%s)s_; })' % (e, hi, ty, hi, lo, ty, lo, ty)


# ---------------------------------------------------------------- data processing
def dp(w, pc):
    U = bit(w, 24)
    if not bit(w, 23): return three_same(w, U)
    if bit(w, 4):
        if bits(w, 21, 19) == 0 and not bit(w, 7): return modimm(w)
        return shift_imm(w, U)
    if bits(w, 21, 20) != 3:
        if not bit(w, 6): return three_diff(w, U)
        return scalar(w, U)
    if not U: return vext(w)
    if not bit(w, 11): return two_misc(w)
    if bits(w, 11, 10) == 2: return vtbl(w)
    if bits(w, 11, 8) == 0b1100: return vdup_scalar(w)
    return UNDEF


def three_same(w, U):
    A = bits(w, 11, 8); B = bit(w, 4); sz = bits(w, 21, 20); q = bit(w, 6)
    d, n, m = regs(w)
    if q and (d | n | m) & 1: return UNDEF
    ty = ITY[(sz, U)]
    if A == 1 and B == 1:     # logic
        if not U:
            e = ['A&B', 'A&~B', 'A|B', 'A|~B'][sz]
        else:
            e = ['A^B', '(D&A)|(~D&B)', '(A&B)|(D&~B)', '(D&B)|(A&~B)'][sz]   # VEOR VBSL VBIT VBIF
        return binop(w, q, 'u64', e, d, n, m)
    if A == 0 and B == 0:
        if sz == 3: return UNDEF
        return binop(w, q, ty, '((%s)A+(%s)B)>>1' % ('i64', 'i64'), d, n, m)
    if A == 0 and B == 1:
        if sz == 3: return UNDEF
        return binop(w, q, ty, sat(ty, '(i64)A+(i64)B'), d, n, m)
    if A == 1 and B == 0:
        if sz == 3: return UNDEF
        return binop(w, q, ty, '((i64)A+(i64)B+1)>>1', d, n, m)
    if A == 2 and B == 0:
        if sz == 3: return UNDEF
        return binop(w, q, ty, '((i64)A-(i64)B)>>1', d, n, m)
    if A == 2 and B == 1:
        if sz == 3: return UNDEF
        return binop(w, q, ty, sat(ty, '(i64)A-(i64)B'), d, n, m)
    if A == 3:
        if sz == 3: return UNDEF
        return binop(w, q, ty, '(A%sB)? -1 : 0' % ('>=' if B else '>'), d, n, m)
    if A == 4 and B == 0:     # VSHL (register): Vm shifted by the signed low byte of each Vn lane
        es = 8 << sz
        if U: e = '({ int s_=(i8)A; s_>=0? (s_>=%d? 0 : (u64)B<<s_) : (s_<=-%d? 0 : (u64)B>>(-s_)); })' % (es, es)
        else: e = '({ int s_=(i8)A; s_>=0? (s_>=%d? 0 : (i64)((u64)B<<s_)) : (s_<=-%d? (i64)B>>63 : (i64)B>>(-s_)); })' % (es, es)
        return binop(w, q, ty, e, d, n, m)
    if A == 6:
        if sz == 3: return UNDEF
        return binop(w, q, ty, '(A%sB)? A : B' % ('<' if B else '>'), d, n, m)
    if A == 7:
        if sz == 3: return UNDEF
        e = '(A>B? (%s)A-(%s)B : (%s)B-(%s)A)' % (('u64',) * 4)
        return binop(w, q, ty, ('D+' if B else '') + e, d, n, m)
    if A == 8 and B == 0:
        ut = ITY[(sz, 1)]
        return binop(w, q, ut, 'A-B' if U else 'A+B', d, n, m)
    if A == 8 and B == 1:
        if sz == 3: return UNDEF
        ut = ITY[(sz, 1)]
        return binop(w, q, ut, ('(A==B)' if U else '((A&B)!=0)') + '? (%s)-1 : 0' % ut, d, n, m)
    if A == 9:
        if sz == 3: return UNDEF
        ut = ITY[(sz, 1)]
        if B == 0: return binop(w, q, ut, 'D-A*B' if U else 'D+A*B', d, n, m)
        if U: return UNDEF                                        # VMUL.P8
        return binop(w, q, ut, 'A*B', d, n, m)
    if A == 10 or (A == 11 and B == 1 and not U):        # VPMAX/VPMIN, VPADD int (D only)
        if q or sz == 3: return UNDEF
        if A == 11: e, ty = 'a_+b_', ITY[(sz, 1)]
        else: e = '(a_%sb_)? a_ : b_' % ('<' if B else '>')
        return pairwise(ty, e, d, n, m)
    if A == 11 and B == 0:    # VQDMULH / VQRDMULH
        if sz not in (1, 2): return UNDEF
        st = ITY[(sz, 0)]; bitsz = 8 << sz
        r = ' + (1LL<<%d)' % (bitsz - 1) if U else ''
        return binop(w, q, st, sat(st, '((i64)2*(i64)A*(i64)B%s)>>%d' % (r, bitsz)), d, n, m)
    if A == 12 and B == 1:    # VFMA / VFMS
        if bit(w, 20): return UNDEF
        return binop(w, q, 'f32', 'fmaf(%sA,B,D)' % ('-' if bit(w, 21) else ''), d, n, m)
    if A == 13:
        hi = bit(w, 21)
        if bit(w, 20): return UNDEF
        if B == 0:
            if not U: return binop(w, q, 'f32', 'A-B' if hi else 'A+B', d, n, m)
            if not hi: return UNDEF if q else pairwise('f32', 'a_+b_', d, n, m)
            return binop(w, q, 'f32', 'fabsf(A-B)', d, n, m)
        if not U: return binop(w, q, 'f32', ('D-A*B' if hi else 'D+A*B').replace('A*B', 'a32_fz((f32)(A*B))'), d, n, m)
        if not hi: return binop(w, q, 'f32', 'A*B', d, n, m)
        return UNDEF
    if A == 14:
        if bit(w, 20): return UNDEF
        if B == 0:
            hi = bit(w, 21)
            if not U and not hi: return fcmp(q, '==', d, n, m)
            if U: return fcmp(q, '>' if hi else '>=', d, n, m)
            return UNDEF
        if U: return fcmp(q, '>' if bit(w, 21) else '>=', d, n, m, absval=True)
        return UNDEF
    if A == 15:
        hi = bit(w, 21)
        if bit(w, 20): return UNDEF
        if B == 0:
            if not U: return binop(w, q, 'f32', 'a32_fmin(A,B)' if hi else 'a32_fmax(A,B)', d, n, m)
            if q: return UNDEF
            return pairwise('f32', 'a32_fmin(a_,b_)' if hi else 'a32_fmax(a_,b_)', d, n, m)
        if not U: return binop(w, q, 'f32', 'a32_rsqrts(A,B)' if hi else 'a32_recps(A,B)', d, n, m)
        return binop(w, q, 'f32', 'fminf(A,B)' if hi else 'fmaxf(A,B)', d, n, m)
    return UNDEF


def fcmp(q, op, d, n, m, absval=False):
    a, b = ('fabsf(n_.f[i])', 'fabsf(m_.f[i])') if absval else ('n_.f[i]', 'm_.f[i]')
    return '{ V128 n_,m_,d_; %s %s for(int i=0;i<%d;i++) d_.s[i]=(%s%s%s)? 0xFFFFFFFFu : 0; %s }' % (
        LD('n_', n, q), LD('m_', m, q), 4 if q else 2, a, op, b, ST('d_', d, q))


def pairwise(ty, e, d, n, m):
    f = FLD[ty]; nl = 8 // {'8': 1, '16': 2, '32': 4}[''.join(ch for ch in ty if ch.isdigit())]
    return ('{ V128 n_,m_,d_; %s %s for(int i=0;i<%d;i++){ %s a_=n_.%s[2*i], b_=n_.%s[2*i+1]; d_.%s[i]=(%s)(%s); '
            'a_=m_.%s[2*i]; b_=m_.%s[2*i+1]; d_.%s[i+%d]=(%s)(%s); } %s }') % (
        LD('n_', n, 0), LD('m_', m, 0), nl // 2, ty, f, f, f, ty, e, f, f, f, nl // 2, ty, e, ST('d_', d, 0))


def modimm(w):
    q = bit(w, 6); op = bit(w, 5); cmode = bits(w, 11, 8)
    d = dreg(bits(w, 15, 12), bit(w, 22))
    if q and d & 1: return UNDEF
    imm8 = (bit(w, 24) << 7) | (bits(w, 18, 16) << 4) | bits(w, 3, 0)
    c3 = cmode >> 1
    if cmode < 8: v = (imm8 << (8 * c3)); v64 = v | (v << 32); kind = 32
    elif cmode < 12: v = imm8 << (8 * (c3 & 1)); v64 = v | (v << 16) | (v << 32) | (v << 48); kind = 16
    elif cmode < 14:
        v = (imm8 << 8) | 0xFF if cmode == 12 else (imm8 << 16) | 0xFFFF; v64 = v | (v << 32); kind = 32
    elif cmode == 14 and not op: v64 = int.from_bytes(bytes([imm8]) * 8, 'little'); kind = 8
    elif cmode == 14:
        v64 = 0
        for i in range(8):
            if imm8 >> i & 1: v64 |= 0xFF << (8 * i)
        kind = 64
    else:
        if op: return UNDEF
        a = imm8 >> 7; b = (imm8 >> 6) & 1
        v = (a << 31) | ((b ^ 1) << 30) | ((0x1F if b else 0) << 25) | ((imm8 & 0x3F) << 19)
        v64 = v | (v << 32); kind = 32
    v64 &= 0xFFFFFFFFFFFFFFFF
    nw = 2 if q else 1
    if cmode < 12 and cmode & 1:     # VORR / VBIC
        mask = v64 if not op else (~v64) & 0xFFFFFFFFFFFFFFFF
        o = '|' if not op else '&'
        return ' '.join('DU(%d)%s=0x%016Xull;' % (d + i, o, mask) for i in range(nw))
    if op and cmode != 14: v64 = (~v64) & 0xFFFFFFFFFFFFFFFF    # VMVN
    return ' '.join('DU(%d)=0x%016Xull;' % (d + i, v64) for i in range(nw))


def shift_imm(w, U):
    L = bit(w, 7); imm6 = bits(w, 21, 16); A = bits(w, 11, 8); q = bit(w, 6); B = bit(w, 6)
    d = dreg(bits(w, 15, 12), bit(w, 22)); m = dreg(bits(w, 3, 0), bit(w, 5))
    if L: sz = 3
    elif imm6 >> 5: sz = 2
    elif imm6 >> 4: sz = 1
    elif imm6 >> 3: sz = 0
    else: return UNDEF
    es = 8 << sz
    rsh = (64 if L else 2 * es) - imm6
    lsh = imm6 - (0 if L else es)
    ty = ITY[(sz, U)]
    if A in (0, 1, 2, 3):     # VSHR VSRA VRSHR VRSRA
        if q and (d | m) & 1: return UNDEF
        rnd = '+((%s)1<<%d)' % ('i64' if not U else 'u64', rsh - 1) if A in (2, 3) else ''
        if es == 64 and A in (2, 3): return UNDEF
        if rsh == es: e = '(%s)(((%s)A%s)>>%d)' % (ty, 'i64' if not U else 'u64', rnd, rsh) if es < 64 else ('(A<0? -1 : 0)' if not U else '0')
        else: e = '(%s)(((%s)A%s)>>%d)' % (ty, 'i64' if not U else 'u64', rnd, rsh)
        if A in (1, 3): e = 'D+' + e
        return binop_m(q, ty, e, d, m)
    if A == 4 and U:          # VSRI
        if q and (d | m) & 1: return UNDEF
        mask = ((1 << es) - 1) >> rsh if rsh < es else 0
        ut = ITY[(sz, 1)]
        return binop_m(q, ut, '(D&~(%s)0x%Xull)|((%s)(A>>%d)&(%s)0x%Xull)' % (ut, mask, ut, min(rsh, es - 1), ut, mask) if rsh < es else 'D', d, m)
    if A == 5:
        if q and (d | m) & 1: return UNDEF
        ut = ITY[(sz, 1)]
        if not U: return binop_m(q, ut, '(%s)(A<<%d)' % (ut, lsh), d, m)
        mask = (((1 << es) - 1) << lsh) & ((1 << es) - 1)
        return binop_m(q, ut, '(D&~(%s)0x%Xull)|((%s)(A<<%d))' % (ut, mask, ut, lsh), d, m)
    if A in (8, 9) and not L:   # narrowing shifts
        if m & 1: return UNDEF
        src = ITY[(sz + 1, U if A == 9 else 0)] if not (A == 8 and U) else ITY[(sz + 1, 0)]
        dst_signed = (A == 9 and not U)
        dt = ITY[(sz, 0 if dst_signed else 1)]
        es2 = es * 2; rsh = es2 - imm6 if sz < 2 else 64 - imm6
        rsh = {0: 16, 1: 32, 2: 64}[sz] - imm6
        rnd = '+((i64)1<<%d)' % (rsh - 1) if B else ''
        if src in ('u64',): rnd = rnd.replace('i64', 'u64')
        val = '(((%s)A%s)>>%d)' % ('__int128' if src in ('i64', 'u64') else 'i64', rnd, rsh)
        if A == 8 and not U: e = '(%s)%s' % (dt, val)              # VSHRN / VRSHRN
        else: e = sat(dt, val)                                       # VQSHRN VQRSHRN VQSHRUN VQRSHRUN
        nl = 8 >> sz
        fs = FLD[src]; fd = FLD[dt]
        e = e.replace('A', 'm_.%s[i]' % fs)
        return '{ V128 m_,d_; %s for(int i=0;i<%d;i++) d_.%s[i]=(%s)(%s); %s }' % (LD('m_', m, 1), nl, fd, dt, e, ST('d_', d, 0))
    if A == 10 and not B and not L:   # VSHLL / VMOVL
        if d & 1: return UNDEF
        wt = WIDE[ty]; nl = 8 >> sz
        return '{ V128 m_,d_; %s for(int i=0;i<%d;i++) d_.%s[i]=(%s)((%s)m_.%s[i]<<%d); %s }' % (
            LD('m_', m, 0), nl, FLD[wt], wt, wt, FLD[ty], lsh, ST('d_', d, 1))
    if A in (14, 15) and sz == 2 and bit(w, 21):   # VCVT fixed <-> float (32-bit)
        if q and (d | m) & 1: return UNDEF
        fb = 64 - imm6
        if A == 14:
            src = 'm_.%s[i]' % ('s' if U else 'ss')
            return '{ V128 m_,d_; %s for(int i=0;i<%d;i++) d_.f[i]=(f32)((f64)%s/%s); %s }' % (LD('m_', m, q), 4 if q else 2, src, repr(float(1 << fb)), ST('d_', d, q))
        f = 'a32_f2u' if U else 'a32_f2s'
        return '{ V128 m_,d_; %s for(int i=0;i<%d;i++) d_.s[i]=(u32)%s((f64)m_.f[i]*%s); %s }' % (LD('m_', m, q), 4 if q else 2, f, repr(float(1 << fb)), ST('d_', d, q))
    return UNDEF


def binop_m(q, ty, e, d, m):
    f = FLD[ty]; nl = (16 if q else 8) // {'8': 1, '16': 2, '32': 4, '64': 8}[''.join(ch for ch in ty if ch.isdigit())]
    if ty == 'f32': e = 'a32_fz(%s)' % e.replace('A', 'a32_fz(m_.f[i])').replace('D', 'a32_fz(d_.f[i])')
    else: e = e.replace('A', 'm_.%s[i]' % f).replace('D', 'd_.%s[i]' % f)
    return '{ V128 m_,d_; %s %s for(int i=0;i<%d;i++) d_.%s[i]=(%s)(%s); %s }' % (LD('m_', m, q), LD('d_', d, q), nl, f, ty, e, ST('d_', d, q))


def three_diff(w, U):
    A = bits(w, 11, 8); sz = bits(w, 21, 20)
    d, n, m = regs(w)
    ty = ITY[(sz, U)]; wt = WIDE.get(ty)
    if not wt: return UNDEF
    nl = 8 >> sz; fn, fw = FLD[ty], FLD[wt]
    if A in (0, 2, 5, 7, 8, 10, 12):     # long: d(Q) = n(D) op m(D)
        if d & 1: return UNDEF
        e = {0: 'D=(%s)a_+(%s)b_', 2: 'D=(%s)a_-(%s)b_', 5: 'D+=(a_>b_? (%s)a_-(%s)b_ : (%s)b_-(%s)a_)',
             7: 'D=(a_>b_? (%s)a_-(%s)b_ : (%s)b_-(%s)a_)', 8: 'D+=(%s)a_*(%s)b_', 10: 'D-=(%s)a_*(%s)b_',
             12: 'D=(%s)a_*(%s)b_'}[A]
        e = e.replace('%s', wt).replace('D', 'd_.%s[i]' % fw)
        return '{ V128 n_,m_,d_; %s %s %s for(int i=0;i<%d;i++){ %s a_=n_.%s[i], b_=m_.%s[i]; %s; } %s }' % (
            LD('n_', n, 0), LD('m_', m, 0), LD('d_', d, 1), nl, ty, fn, fn, e, ST('d_', d, 1))
    if A in (1, 3):                      # wide: d(Q) = n(Q) op m(D)
        if (d | n) & 1: return UNDEF
        op = '+' if A == 1 else '-'
        return '{ V128 n_,m_,d_; %s %s for(int i=0;i<%d;i++) d_.%s[i]=n_.%s[i]%s(%s)m_.%s[i]; %s }' % (
            LD('n_', n, 1), LD('m_', m, 0), nl, fw, fw, op, wt, fn, ST('d_', d, 1))
    if A in (4, 6):                      # VADDHN / VSUBHN (and rounding forms)
        if (n | m) & 1: return UNDEF
        ut = ITY[(sz, 1)]; uw = WIDE[ut]; es = 8 << sz
        rnd = ' + ((%s)1<<%d)' % (uw, es - 1) if U else ''
        op = '+' if A == 4 else '-'
        return '{ V128 n_,m_,d_; %s %s for(int i=0;i<%d;i++) d_.%s[i]=(%s)((n_.%s[i]%sm_.%s[i]%s)>>%d); %s }' % (
            LD('n_', n, 1), LD('m_', m, 1), nl, FLD[ut], ut, FLD[uw], op, FLD[uw], rnd, es, ST('d_', d, 0))
    if A == 13 and not U and sz in (1, 2):   # VQDMULL
        if d & 1: return UNDEF
        return '{ V128 n_,m_,d_; %s %s for(int i=0;i<%d;i++) d_.%s[i]=%s; %s }' % (
            LD('n_', n, 0), LD('m_', m, 0), nl, fw, ('(%s)' % wt) + '(2*(i64)n_.%s[i]*m_.%s[i])' % (fn, fn), ST('d_', d, 1))
    return UNDEF


def scalar(w, U):
    A = bits(w, 11, 8); sz = bits(w, 21, 20); q = U    # Q is bit 24 for these
    d = dreg(bits(w, 15, 12), bit(w, 22)); n = dreg(bits(w, 19, 16), bit(w, 7))
    if sz == 1: mr = bits(w, 2, 0); idx = (bit(w, 5) << 1) | bit(w, 3); off = mr * 8 + idx * 2; st = 'u16'
    elif sz == 2: mr = bits(w, 3, 0); idx = bit(w, 5); off = mr * 8 + idx * 4; st = 'u32'
    else: return UNDEF
    if A in (0, 1, 4, 5, 8, 9):
        fl = A & 1
        if fl and sz != 2: return UNDEF
        if q and (d | n) & 1: return UNDEF
        ty = 'f32' if fl else ITY[(sz, 1)]
        sv = '(*(%s*)(VB+%d))' % ('f32' if fl else st, off)
        e = {0: 'D+A*S', 4: 'D-A*S', 8: 'A*S'}[A & ~1]
        if fl: e = e.replace('A*S', 'a32_fz((f32)(A*S))')
        f = FLD[ty]; nl = (16 if q else 8) // (4 if sz == 2 else 2)
        if fl: e = 'a32_fz(%s)' % e.replace('A', 'a32_fz(n_.f[i])').replace('D', 'a32_fz(d_.f[i])').replace('S', 'a32_fz(s_)')
        else: e = e.replace('A', 'n_.%s[i]' % f).replace('D', 'd_.%s[i]' % f).replace('S', 's_')
        return '{ V128 n_,d_; %s s_=%s; %s %s for(int i=0;i<%d;i++) d_.%s[i]=(%s)(%s); %s }' % (
            ty, sv, LD('n_', n, q), LD('d_', d, q), nl, f, ty, e, ST('d_', d, q))
    if A in (2, 6, 10):      # VMLAL / VMLSL / VMULL by scalar
        if d & 1: return UNDEF
        ty = ITY[(sz, U)]; wt = WIDE[ty]; nl = 8 >> sz
        e = {2: '+=', 6: '-=', 10: '='}[A]
        sv = '(%s)(*(%s*)(VB+%d))' % (ty, ty, off)
        return '{ V128 n_,d_; %s s_=%s; %s %s for(int i=0;i<%d;i++) d_.%s[i]%s(%s)n_.%s[i]*s_; %s }' % (
            wt, sv, LD('n_', n, 0), LD('d_', d, 1), nl, FLD[wt], e, wt, FLD[ty], ST('d_', d, 1))
    if A in (12, 13):        # VQDMULH / VQRDMULH by scalar
        if q and (d | n) & 1: return UNDEF
        ty = ITY[(sz, 0)]; es = 8 << sz; nl = (16 if q else 8) >> sz
        r = ' + (1LL<<%d)' % (es - 1) if A == 13 else ''
        e = sat(ty, '((i64)2*(i64)n_.%s[i]*(i64)s_%s)>>%d' % (FLD[ty], r, es))
        return '{ V128 n_,d_; i64 s_=*(%s*)(VB+%d); %s %s for(int i=0;i<%d;i++) d_.%s[i]=%s; %s }' % (
            ty, off, LD('n_', n, q), LD('d_', d, q), nl, FLD[ty], e, ST('d_', d, q))
    return UNDEF


def vext(w):
    q = bit(w, 6); imm = bits(w, 11, 8)
    d, n, m = regs(w)
    if q and (d | n | m) & 1: return UNDEF
    if not q and imm > 7: return UNDEF
    nb = 16 if q else 8
    return '{ u8 t_[32]; memcpy(t_,VB+%d,%d); memcpy(t_+%d,VB+%d,%d); memcpy(VB+%d,t_+%d,%d); }' % (n * 8, nb, nb, m * 8, nb, d * 8, imm, nb)


def vtbl(w):
    d, n, m = regs(w); ln = bits(w, 9, 8) + 1; x = bit(w, 6)
    if n + ln > 32: return UNDEF
    dflt = 'd_[i]' if x else '0'
    return '{ u8 t_[32], i_[8], d_[8]; memcpy(t_,VB+%d,%d); memcpy(i_,VB+%d,8); memcpy(d_,VB+%d,8); for(int i=0;i<8;i++) d_[i]= i_[i]<%d? t_[i_[i]] : %s; memcpy(VB+%d,d_,8); }' % (
        n * 8, ln * 8, m * 8, d * 8, ln * 8, dflt, d * 8)


def vdup_scalar(w):
    imm4 = bits(w, 19, 16); q = bit(w, 6)
    d = dreg(bits(w, 15, 12), bit(w, 22)); m = dreg(bits(w, 3, 0), bit(w, 5))
    if q and d & 1: return UNDEF
    if imm4 & 1: sz, idx = 1, imm4 >> 1
    elif imm4 & 2: sz, idx = 2, imm4 >> 2
    elif imm4 & 4: sz, idx = 4, imm4 >> 3
    else: return UNDEF
    ty = {1: 'u8', 2: 'u16', 4: 'u32'}[sz]
    return '{ %s v_=*(%s*)(VB+%d); for(int i=0;i<%d;i++) ((%s*)(VB+%d))[i]=v_; }' % (ty, ty, m * 8 + idx * sz, (16 if q else 8) // sz, ty, d * 8)


def two_misc(w):
    A = bits(w, 17, 16); B = bits(w, 10, 6); sz = bits(w, 19, 18); q = bit(w, 6)
    d = dreg(bits(w, 15, 12), bit(w, 22)); m = dreg(bits(w, 3, 0), bit(w, 5))
    nb = 16 if q else 8
    if A == 0:
        if B >> 1 in (0, 1, 2):     # VREV64/32/16
            grp = {0: 8, 1: 4, 2: 2}[B >> 1]; es = 1 << sz
            if es >= grp: return UNDEF
            if q and (d | m) & 1: return UNDEF
            return '{ u8 s_[16], t_[16]; memcpy(s_,VB+%d,%d); for(int g=0;g<%d;g+=%d) for(int e=0;e<%d;e+=%d) memcpy(t_+g+e,s_+g+%d-%d-e,%d); memcpy(VB+%d,t_,%d); }' % (
                m * 8, nb, nb, grp, grp, es, grp, es, es, d * 8, nb)
        if B >> 1 == 0b1011: return binop_m(q, 'u64', '~A', d, m) if not (q and (d | m) & 1) else UNDEF     # VMVN
        if B >> 1 == 0b1010 and sz == 0: return binop_m(q, 'u8', '__builtin_popcount(A)', d, m)
        if B >> 1 == 0b1001:
            ut = ITY[(sz, 1)]
            if sz == 3: return UNDEF
            return binop_m(q, ut, 'A? __builtin_clz((u32)A)-%d : %d' % (32 - (8 << sz), 8 << sz), d, m)
        if B >> 2 in (0b010, 0b110):    # VPADDL / VPADAL
            U = bit(w, 7); ty = ITY[(sz, U)]; wt = WIDE.get(ty)
            if not wt: return UNDEF
            nl = nb >> (sz + 1); acc = '+' if B >> 2 == 0b110 else ''
            return '{ V128 m_,d_; %s %s for(int i=0;i<%d;i++) d_.%s[i]=%s(%s)m_.%s[2*i]+(%s)m_.%s[2*i+1]; %s }' % (
                LD('m_', m, q), LD('d_', d, q), nl, FLD[wt], ('d_.%s[i]+' % FLD[wt]) if acc else '', wt, FLD[ty], wt, FLD[ty], ST('d_', d, q))
        return UNDEF
    if A == 1:
        fl = bit(w, 10); op = bits(w, 9, 7)
        if q and (d | m) & 1: return UNDEF
        if fl:
            if sz != 2: return UNDEF
            if op <= 4:
                cmpo = ['>', '>=', '==', '<=', '<'][op]
                return '{ V128 m_,d_; %s for(int i=0;i<%d;i++) d_.s[i]=(a32_fz(m_.f[i])%s0.0f)? 0xFFFFFFFFu : 0; %s }' % (LD('m_', m, q), nb // 4, cmpo, ST('d_', d, q))
            if op == 6: return binop_m(q, 'u32', 'A&0x7FFFFFFFu', d, m)
            if op == 7: return binop_m(q, 'u32', 'A^0x80000000u', d, m)
            return UNDEF
        if sz == 3: return UNDEF
        ty = ITY[(sz, 0)]
        if op <= 4:
            cmpo = ['>', '>=', '==', '<=', '<'][op]
            return binop_m(q, ty, '(A%s0)? -1 : 0' % cmpo, d, m)
        if op == 6: return binop_m(q, ty, 'A<0? -A : A', d, m)
        if op == 7: return binop_m(q, ty, '-A', d, m)
        return UNDEF
    if A == 2:
        if B >> 1 == 0:     # VSWP
            if q and (d | m) & 1: return UNDEF
            return '{ u8 t_[16]; memcpy(t_,VB+%d,%d); memcpy(VB+%d,VB+%d,%d); memcpy(VB+%d,t_,%d); }' % (d * 8, nb, d * 8, m * 8, nb, m * 8, nb)
        if B >> 1 in (1, 2, 3):   # VTRN VUZP VZIP
            if q and (d | m) & 1: return UNDEF
            if sz == 3 or (not q and sz == 2 and B >> 1 != 1): return UNDEF
            es = 1 << sz; ne = nb // es; kind = B >> 1
            return ('{ u8 a_[16], b_[16], x_[32], y_[32]; memcpy(a_,VB+%d,%d); memcpy(b_,VB+%d,%d); '
                    'a32_permute(%d,%d,%d,a_,b_,x_); memcpy(VB+%d,x_,%d); memcpy(VB+%d,x_+%d,%d); }') % (
                d * 8, nb, m * 8, nb, kind, es, ne, d * 8, nb, m * 8, nb, nb)
        if B == 0b01000:    # VMOVN
            if m & 1 or sz == 3: return UNDEF
            st = ITY[(sz + 1, 1)]; dt = ITY[(sz, 1)]
            return '{ V128 m_,d_; %s for(int i=0;i<%d;i++) d_.%s[i]=(%s)m_.%s[i]; %s }' % (LD('m_', m, 1), 8 >> sz, FLD[dt], dt, FLD[st], ST('d_', d, 0))
        if B >> 1 == 0b0100 or B >> 1 == 0b0101:   # VQMOVUN (01001) / VQMOVN (0101x)
            if m & 1 or sz == 3: return UNDEF
            op = bits(w, 7, 6)
            if op == 1: st, dt = ITY[(sz + 1, 0)], ITY[(sz, 1)]
            elif op == 2: st, dt = ITY[(sz + 1, 0)], ITY[(sz, 0)]
            else: st, dt = ITY[(sz + 1, 1)], ITY[(sz, 1)]
            e = sat(dt, 'm_.%s[i]' % FLD[st])
            return '{ V128 m_,d_; %s for(int i=0;i<%d;i++) d_.%s[i]=%s; %s }' % (LD('m_', m, 1), 8 >> sz, FLD[dt], e, ST('d_', d, 0))
        if B == 0b01100:    # VSHLL max shift
            if d & 1 or sz == 3: return UNDEF
            ty = ITY[(sz, 1)]; wt = WIDE[ty]
            return '{ V128 m_,d_; %s for(int i=0;i<%d;i++) d_.%s[i]=(%s)m_.%s[i]<<%d; %s }' % (LD('m_', m, 0), 8 >> sz, FLD[wt], wt, FLD[ty], 8 << sz, ST('d_', d, 1))
        return UNDEF
    # A == 3
    if q and (d | m) & 1: return UNDEF
    if B >> 2 == 0b100 or B >> 2 == 0b101:   # VRECPE / VRSQRTE (bit 8 F)
        if sz != 2: return UNDEF
        rs = bit(w, 7); fl = bit(w, 8)
        if not fl: return UNDEF
        return binop_m(q, 'f32', 'a32_rsqrte(A)' if rs else 'a32_recpe(A)', d, m)
    if B >> 2 in (0b110, 0b111):             # VCVT f32 <-> s32/u32
        if sz != 2: return UNDEF
        op = bits(w, 8, 7)
        if op == 0: return '{ V128 m_,d_; %s for(int i=0;i<%d;i++) d_.f[i]=(f32)m_.ss[i]; %s }' % (LD('m_', m, q), nb // 4, ST('d_', d, q))
        if op == 1: return '{ V128 m_,d_; %s for(int i=0;i<%d;i++) d_.f[i]=(f32)m_.s[i]; %s }' % (LD('m_', m, q), nb // 4, ST('d_', d, q))
        f = 'a32_f2s' if op == 2 else 'a32_f2u'
        return '{ V128 m_,d_; %s for(int i=0;i<%d;i++) d_.s[i]=(u32)%s(m_.f[i]); %s }' % (LD('m_', m, q), nb // 4, f, ST('d_', d, q))
    return UNDEF


# ---------------------------------------------------------------- loads / stores
def ldst(w, pc):
    A = bit(w, 23); L = bit(w, 21); n = bits(w, 19, 16); m = bits(w, 3, 0)
    d = dreg(bits(w, 15, 12), bit(w, 22))
    if n == 15: return UNDEF
    moves = []    # (reg, byte offset in reg, memory offset, size)
    if not A:
        t = bits(w, 11, 8); sz = bits(w, 7, 6); es = 1 << sz
        table = {0b0111: (1, 1, 1), 0b1010: (1, 2, 1), 0b0110: (1, 3, 1), 0b0010: (1, 4, 1),
                 0b1000: (2, 1, 1), 0b1001: (2, 1, 2), 0b0011: (2, 2, 2),
                 0b0100: (3, 1, 1), 0b0101: (3, 1, 2), 0b0000: (4, 1, 1), 0b0001: (4, 1, 2)}
        if t not in table: return UNDEF
        N, nregs, inc = table[t]
        if N > 1 and sz == 3: return UNDEF
        ne = 8 // es; mo = 0
        if N == 1:
            for r in range(nregs):
                for e in range(ne): moves.append((d + r, e * es, mo, es)); mo += es
        elif t == 0b0011:
            for e in range(2 * ne):
                for s in range(2):
                    moves.append((d + 2 * s, e * es, mo, es)); mo += es
        else:
            for e in range(ne):
                for s in range(N):
                    moves.append((d + s * inc, e * es, mo, es)); mo += es
        total = mo
    else:
        sz = bits(w, 11, 10); N = bits(w, 9, 8) + 1
        if sz == 3:      # all lanes (load only)
            if not L: return UNDEF
            sz = bits(w, 7, 6); es = 1 << sz; T = bit(w, 5)
            if sz == 3: return UNDEF
            nr = (T + 1) if N == 1 else 1; inc = (T + 1) if N > 1 else 1
            body = ''
            for s in range(N):
                for r in range(nr):
                    reg = d + s * inc + r
                    body += ' { u%d v_=*(u%d*)MP(a_+%d); for(int i=0;i<%d;i++) ((u%d*)(VB+%d))[i]=v_; }' % (8 * es, 8 * es, s * es, 8 // es, 8 * es, reg * 8)
            total = N * es
            return '{ u32 a_=R(%d);%s %s }' % (n, body, wb(n, m, total))
        es = 1 << sz
        idx = bits(w, 7, 4) >> (sz + 1)
        inc = 1
        if sz == 1 and bit(w, 5): inc = 2
        if sz == 2 and bit(w, 6): inc = 2
        if N == 1: inc = 1
        for s in range(N): moves.append((d + s * inc, idx * es, s * es, es))
        total = N * es
    if any(r > 31 for r, _, _, _ in moves): return UNDEF
    body = ''
    for r, ro, mo, es in moves:
        body += (' memcpy(VB+%d,MP(a_+%d),%d);' if L else ' memcpy(MP(a_+%d),VB+%d,%d);') % ((r * 8 + ro, mo, es) if L else (mo, r * 8 + ro, es))
    return '{ u32 a_=R(%d);%s %s }' % (n, body, wb(n, m, total))


def wb(n, m, total):
    if m == 15: return ''
    if m == 13: return 'SR(%d,a_+%d);' % (n, total)
    return 'SR(%d,a_+R(%d));' % (n, m)
