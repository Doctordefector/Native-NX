/* AArch32 (A32 + VFP/NEON) state on top of the A57 CPU struct, for 32-bit games (Pikmin 3 Deluxe).
   r0-r15 live in x[0..15] as zero-extended 32-bit values. The VFP/NEON file is the first 256 bytes of v[]:
   D(n) at byte n*8, S(n) at byte n*4, Q(n) = v[n]. FPSCR = fpcr | fpsr, its NZCV in fpsr bits 31:28.
   user[0] = Q flag, user[1] = GE bits (3:0). */
#ifndef SWR_CPU32_H
#define SWR_CPU32_H
#include "cpu.h"
#include <math.h>

#define R(n)      ((u32)c->x[n])
#define SR(n,v)   (c->x[n]=(u32)(v))
#define VB        ((u8*)c->v)
#define SF(n)     (((f32*)c->v)[n])
#define SU(n)     (((u32*)c->v)[n])
#define DF(n)     (((f64*)c->v)[n])
#define DU(n)     (((u64*)c->v)[n])
#define A32Q      (c->user[0])
#define A32GE     (c->user[1])

SWR_INLINE u32 a32_lsl_c(CPU* c, u32 x, u32 s, u32* co){ s&=255; if(!s){ *co=c->cf; return x; } if(s<32){ *co=(x>>(32-s))&1; return x<<s; } *co= s==32? x&1 : 0; return 0; }
SWR_INLINE u32 a32_lsr_c(CPU* c, u32 x, u32 s, u32* co){ s&=255; if(!s){ *co=c->cf; return x; } if(s<32){ *co=(x>>(s-1))&1; return x>>s; } *co= s==32? x>>31 : 0; return 0; }
SWR_INLINE u32 a32_asr_c(CPU* c, u32 x, u32 s, u32* co){ s&=255; if(!s){ *co=c->cf; return x; } if(s<32){ *co=(x>>(s-1))&1; return (u32)((i32)x>>s); } *co=x>>31; return (u32)((i32)x>>31); }
SWR_INLINE u32 a32_ror_c(CPU* c, u32 x, u32 s, u32* co){ s&=255; if(!s){ *co=c->cf; return x; } s&=31; if(!s){ *co=x>>31; return x; } *co=(x>>(s-1))&1; return (x>>s)|(x<<(32-s)); }
SWR_INLINE u32 a32_lsl(u32 x, u32 s){ s&=255; return s<32? x<<s : 0; }
SWR_INLINE u32 a32_lsr(u32 x, u32 s){ s&=255; return s<32? x>>s : 0; }
SWR_INLINE u32 a32_asr(u32 x, u32 s){ s&=255; return s<32? (u32)((i32)x>>s) : (u32)((i32)x>>31); }

SWR_INLINE u32 a32_apsr(const CPU* c){ return get_nzcv(c)|((u32)A32Q<<27)|((u32)A32GE<<16); }
SWR_INLINE void a32_set_apsr(CPU* c, u32 v, u32 mask){ /* mask bit 3: nzcvq, bit 2: ge */
  if(mask&8){ set_nzcv(c,v>>28); A32Q=(v>>27)&1; } if(mask&4) A32GE=(v>>16)&15; }

/* saturation */
SWR_INLINE u32 a32_qadd(CPU* c, i32 a, i32 b){ i64 r=(i64)a+b; if(r>INT32_MAX){ A32Q=1; return INT32_MAX; } if(r<INT32_MIN){ A32Q=1; return (u32)INT32_MIN; } return (u32)r; }
SWR_INLINE u32 a32_qsub(CPU* c, i32 a, i32 b){ i64 r=(i64)a-b; if(r>INT32_MAX){ A32Q=1; return INT32_MAX; } if(r<INT32_MIN){ A32Q=1; return (u32)INT32_MIN; } return (u32)r; }
SWR_INLINE u32 a32_ssat(CPU* c, i32 v, u32 n){ i64 hi=((i64)1<<(n-1))-1, lo=-((i64)1<<(n-1)); if(v>hi){ A32Q=1; return (u32)hi; } if(v<lo){ A32Q=1; return (u32)lo; } return (u32)v; }
SWR_INLINE u32 a32_usat(CPU* c, i32 v, u32 n){ i64 hi=((i64)1<<n)-1; if(v>hi){ A32Q=1; return (u32)hi; } if(v<0){ A32Q=1; return 0; } return (u32)v; }
u32 a32_parallel(CPU* c, u32 kind, u32 op, u32 a, u32 b);   /* SADD16.. UHSUB8 */
void a32_permute(int kind, int es, int ne, const u8* a, const u8* b, u8* out);   /* VTRN VUZP VZIP */

/* VFP */
SWR_INLINE void a32_fcmp32(CPU* c, f32 a, f32 b){ u32 f= (a!=a||b!=b)? 3 : a==b? 6 : a<b? 8 : 2; c->fpsr=(c->fpsr&0x0FFFFFFFu)|(f<<28); }
SWR_INLINE void a32_fcmp64(CPU* c, f64 a, f64 b){ u32 f= (a!=a||b!=b)? 3 : a==b? 6 : a<b? 8 : 2; c->fpsr=(c->fpsr&0x0FFFFFFFu)|(f<<28); }
SWR_INLINE i32 a32_f2s(f64 x){ if(x!=x) return 0; if(x>=2147483648.0) return INT32_MAX; if(x<=-2147483649.0) return INT32_MIN; return (i32)x; }
SWR_INLINE u32 a32_f2u(f64 x){ if(x!=x || x<=-1.0) return 0; if(x>=4294967296.0) return UINT32_MAX; return (u32)x; }
SWR_INLINE f64 a32_round(CPU* c, f64 x, int mode){ /* 0 nearest-even 1 +inf 2 -inf 3 zero 4 away; -1 = FPSCR */
  if(mode<0) mode=(int)((c->fpcr>>22)&3);
  switch(mode){ case 1: return ceil(x); case 2: return floor(x); case 3: return trunc(x); case 4: return round(x); default: return nearbyint(x); } }
SWR_INLINE u32 a32_fpscr(const CPU* c){ return c->fpcr|c->fpsr; }
SWR_INLINE void a32_set_fpscr(CPU* c, u32 v){ c->fpsr=v&0xF800009Fu; c->fpcr=v&~0xF800009Fu; }
SWR_INLINE f32 a32_fz(f32 x){ u32 b; memcpy(&b,&x,4); if(!(b&0x7F800000u)){ b&=0x80000000u; memcpy(&x,&b,4); } return x; }
SWR_INLINE f32 a32_fmaxnm(f32 a, f32 b){ return fmaxf(a,b); }
SWR_INLINE f32 a32_fminnm(f32 a, f32 b){ return fminf(a,b); }
SWR_INLINE f32 a32_fmax(f32 a, f32 b){ if(a!=a) return a; if(b!=b) return b; if(a==0&&b==0) return signbit(a)? b : a; return a>b? a : b; }
SWR_INLINE f32 a32_fmin(f32 a, f32 b){ if(a!=a) return a; if(b!=b) return b; if(a==0&&b==0) return signbit(a)? a : b; return a<b? a : b; }
f32 a32_recpe(f32 x); f32 a32_rsqrte(f32 x);
SWR_INLINE f32 a32_recps(f32 a, f32 b){ if((isinf(a)&&b==0)||(isinf(b)&&a==0)) return 2.0f; return 2.0f-a*b; }
SWR_INLINE f32 a32_rsqrts(f32 a, f32 b){ if((isinf(a)&&b==0)||(isinf(b)&&a==0)) return 1.5f; return (3.0f-a*b)/2.0f; }

/* exclusives: the monitor remembers the address and the value read, the store is a CAS against it */
SWR_INLINE u32 a32_ldrex(CPU* c, u8* M, u32 a, u32 sz){ u64 v= sz==1? *(volatile u8*)MP(a) : sz==2? *(volatile u16*)MP(a) : sz==4? *(volatile u32*)MP(a) : *(volatile u64*)MP(a);
  c->excl_addr=a; c->excl_val=v; c->excl_size=sz; c->excl_on=1; return (u32)v; }
SWR_INLINE u32 a32_strex(CPU* c, u8* M, u32 a, u64 v, u32 sz){ if(!c->excl_on || c->excl_addr!=a || c->excl_size!=sz){ c->excl_on=0; return 1; } c->excl_on=0;
  u32 ok= sz==1? swr_cas8((u8*)MP(a),(u8)c->excl_val,(u8)v) : sz==2? swr_cas16((u16*)MP(a),(u16)c->excl_val,(u16)v) : sz==4? swr_cas32((u32*)MP(a),(u32)c->excl_val,(u32)v) : swr_cas64((u64*)MP(a),c->excl_val,v);
  return ok? 0 : 1; }
#endif
