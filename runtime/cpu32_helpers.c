/* AArch32 helpers that are too big to inline in the generated code (see cpu32.h). */
#include "cpu32.h"

/* SADD16 .. UHSUB8. kind: bits 22:20 (1 S, 2 Q, 3 SH, 5 U, 6 UQ, 7 UH); op: bits 7:5 (0 ADD16 1 ASX 2 SAX 3 SUB16 4 ADD8 7 SUB8) */
u32 a32_parallel(CPU* c, u32 kind, u32 op, u32 a, u32 b){
  int sgn= kind<4; int mode=kind&3;   /* 1 plain(GE) 2 saturating 3 halving */
  int es= op>=4? 8 : 16, n=32/es; u32 r=0, ge=0; i64 lo= sgn? -(1ll<<(es-1)) : 0, hi= sgn? (1ll<<(es-1))-1 : (1ll<<es)-1;
  for(int i=0;i<n;i++){
    u32 msk=(1u<<es)-1;
    i64 x=(a>>(i*es))&msk, y;
    int sub;
    if(op==1){ y=(b>>((i^1)*es))&msk; sub= i==0; }        /* ASX: lo = a.lo - b.hi, hi = a.hi + b.lo */
    else if(op==2){ y=(b>>((i^1)*es))&msk; sub= i==1; }   /* SAX */
    else { y=(b>>(i*es))&msk; sub= op==3||op==7; }
    if(sgn){ x=(i64)(x<<(64-es))>>(64-es); y=(i64)(y<<(64-es))>>(64-es); }
    i64 v= sub? x-y : x+y;
    if(mode==2){ if(v<lo) v=lo; if(v>hi) v=hi; }
    else if(mode==3) v>>=1;
    else { int g= sgn? v>=0 : (sub? v>=0 : v>=(1ll<<es)); if(g) ge|= (es==16? 3u : 1u)<<(i*(es/8)); }
    r|= ((u32)v&msk)<<(i*es); }
  if(mode==1) A32GE=ge;
  return r; }

/* VTRN(1) VUZP(2) VZIP(3) on a (d) and b (m), es-byte elements, ne per register. out: 2*ne elements, d then m */
void a32_permute(int kind, int es, int ne, const u8* a, const u8* b, u8* out){
  u8 cat[32]; memcpy(cat,a,ne*es); memcpy(cat+ne*es,b,ne*es);
  if(kind==3){ for(int i=0;i<ne;i++){ memcpy(out+(2*i)*es,a+i*es,es); memcpy(out+(2*i+1)*es,b+i*es,es); } }
  else if(kind==2){ for(int i=0;i<ne;i++){ memcpy(out+i*es,cat+(2*i)*es,es); memcpy(out+(ne+i)*es,cat+(2*i+1)*es,es); } }
  else { memcpy(out,a,ne*es); memcpy(out+ne*es,b,ne*es);
    for(int i=0;i+1<ne;i+=2){ memcpy(out+(i+1)*es,b+i*es,es); memcpy(out+(ne+i)*es,a+(i+1)*es,es); } } }

/* ARMv7 FPRecipEstimate / FPRSqrtEstimate (8-bit tables computed as in the ARM ARM; FZ, default NaN) */
static u32 recip_est(u32 a){ a=a*2+1; u32 b=(1u<<19)/a; return (b+1)>>1; }
static u32 rsqrt_est(u32 a){ if(a<256) a=a*2+1; else { a=(a>>1)<<1; a=(a+1)*2; }
  u32 b=512; while((u64)a*(b+1)*(b+1) < (1ull<<28)) b++; return (b+1)>>1; }
static f32 fbits(u32 v){ f32 f; memcpy(&f,&v,4); return f; }
f32 a32_recpe(f32 x){ u32 v; memcpy(&v,&x,4); u32 s=v&0x80000000u, e=(v>>23)&0xFF, f=v&0x7FFFFF;
  if(e==0xFF) return f? fbits(0x7FC00000u) : fbits(s);
  if(e==0) return fbits(s|0x7F800000u);
  if(e>=253) return fbits(s);
  u32 est=recip_est(0x100|(f>>15));
  return fbits(s|((253-e)<<23)|((est&0xFF)<<15)); }
f32 a32_rsqrte(f32 x){ u32 v; memcpy(&v,&x,4); u32 s=v>>31, e=(v>>23)&0xFF, f=v&0x7FFFFF;
  if(e==0xFF && f) return fbits(0x7FC00000u);
  if(e==0) return fbits((s<<31)|0x7F800000u);
  if(s) return fbits(0x7FC00000u);
  if(e==0xFF) return fbits(0);
  u32 sc= (e&1)? (0x80|(f>>16)) : (0x100|(f>>15));
  u32 est=rsqrt_est(sc);
  return fbits(((380-e)/2)<<23|((est&0xFF)<<15)); }
