/* ARMv7 Advanced SIMD binary32 standard arithmetic: DN/FZ, ties-to-even.
 * Integer implementation, independent of host rounding/denormal controls.
 * Only cumulative exception bits are added to the caller's guest FPSCR.
 */
static uint64_t vx_neon_jam(uint64_t x,unsigned n){
 if(!n)return x;
 return n<64?(x>>n)|((x<<(64-n))!=0):(x!=0);
}
static uint32_t vx_neon_unpack(uint32_t x,uint32_t *fpscr){
 if(!(x&0x7f800000u)&&(x&0x007fffffu)){*fpscr|=128u;return x&0x80000000u;}
 return x;
}
/* sig has three guard/round/sticky bits and a leading bit at position 26. */
static uint32_t vx_neon_round(uint32_t sign,int exp,uint64_t sig,uint32_t *fpscr){
 if(!sig)return sign;
 while(sig>=(UINT64_C(1)<<27)){sig=vx_neon_jam(sig,1);exp++;}
 while(sig<(UINT64_C(1)<<26)){sig<<=1;exp--;}
 /* ARM flushes tiny results before rounding, setting UFC, not IXC. */
 if(exp<=0){*fpscr|=8u;return sign;}
 uint32_t tail=sig&7u,mant=(uint32_t)(sig>>3);
 if(tail>4||(tail==4&&(mant&1)))mant++;
 if(mant==0x1000000u){mant>>=1;exp++;}
 if(exp>=255){*fpscr|=20u;return sign|0x7f800000u;}
 if(tail)*fpscr|=16u;
 return sign|((uint32_t)exp<<23)|(mant&0x7fffffu);
}
static uint32_t vx_neon_binary_scaled(uint32_t a,uint32_t b,unsigned op,int scale,uint32_t *fpscr){
 a=vx_neon_unpack(a,fpscr);b=vx_neon_unpack(b,fpscr);
 uint32_t aa=a&0x7fffffffu,bb=b&0x7fffffffu;
 int nan_a=aa>0x7f800000u,nan_b=bb>0x7f800000u;
 if(nan_a||nan_b){
  if((nan_a&&!(a&0x400000u))||(nan_b&&!(b&0x400000u)))*fpscr|=1u;
  return 0x7fc00000u;
 }
 if(op==1)b^=0x80000000u;
 uint32_t sa=a&0x80000000u,sb=b&0x80000000u;
 int ea=(a>>23)&255,eb=(b>>23)&255;
 if(op==2){
  uint32_t sign=sa^sb;
  if((aa==0x7f800000u&&!bb)||(bb==0x7f800000u&&!aa)){*fpscr|=1u;return 0x7fc00000u;}
  if(ea==255||eb==255)return sign|0x7f800000u;
  if(!aa||!bb)return sign;
  uint64_t product=(uint64_t)((a&0x7fffffu)|0x800000u)*((b&0x7fffffu)|0x800000u);
  return vx_neon_round(sign,ea+eb-127+scale,vx_neon_jam(product,20),fpscr);
 }
 if(ea==255||eb==255){
  if(ea==255&&eb==255&&sa!=sb){*fpscr|=1u;return 0x7fc00000u;}
  return ea==255?a:b;
 }
 if(!aa&&!bb)return sa==sb?sa:0;
 if(!aa)return vx_neon_round(sb,eb+scale,(uint64_t)((b&0x7fffffu)|0x800000u)<<3,fpscr);
 if(!bb)return vx_neon_round(sa,ea+scale,(uint64_t)((a&0x7fffffu)|0x800000u)<<3,fpscr);
 /* Order magnitudes before aligning so subtraction cannot underflow. */
 if(aa<bb){uint32_t t=a;a=b;b=t;t=sa;sa=sb;sb=t;int e=ea;ea=eb;eb=e;}
 uint64_t x=(uint64_t)((a&0x7fffffu)|0x800000u)<<3;
 uint64_t y=vx_neon_jam((uint64_t)((b&0x7fffffu)|0x800000u)<<3,(unsigned)(ea-eb));
 uint64_t sig=sa==sb?x+y:x-y;
 return vx_neon_round(sig?sa:0,ea+scale,sig,fpscr);
}
static uint32_t vx_neon_binary(uint32_t a,uint32_t b,unsigned op,uint32_t *fpscr){
 return vx_neon_binary_scaled(a,b,op,0,fpscr);
}
static uint32_t vx_neon_rsqrte(uint32_t a,uint32_t *fpscr){
 a=vx_neon_unpack(a,fpscr);uint32_t mag=a&0x7fffffffu,exp=(a>>23)&255;
 if(mag>0x7f800000u){if(!(a&0x400000u))*fpscr|=1u;return 0x7fc00000u;}
 if(!mag){*fpscr|=2u;return (a&0x80000000u)|0x7f800000u;}
 if(a>>31){*fpscr|=1u;return 0x7fc00000u;}
 if(exp==255)return 0;
 /* Quantize the scaled input to the midpoint of its ARM estimate bucket.
  * Compare squared integer thresholds to round its reciprocal sqrt to 1/256.
  * No host sqrt, host rounding state, or mathematical reciprocal substitution.
  */
 uint32_t q=128u+((a&0x7fffffu)>>16),den=2*q+1;
 uint64_t num=(uint64_t)(exp&1?1024:512)*65536;
 unsigned low=256,high=512;
 while(low+1<high){unsigned mid=(low+high)/2;if((uint64_t)mid*mid*den<=num)low=mid;else high=mid;}
 if(4*num>(uint64_t)den*(2*low+1)*(2*low+1))low++;
 return ((380-exp)/2)<<23|((low&255u)<<15);
}
static uint32_t vx_neon_rsqrt_step(uint32_t a,uint32_t b,uint32_t *fpscr){
 a=vx_neon_unpack(a,fpscr);b=vx_neon_unpack(b,fpscr);
 uint32_t x=a&0x7fffffffu,y=b&0x7fffffffu;
 uint32_t product=((x==0x7f800000u&&!y)||(y==0x7f800000u&&!x))?0:
                  vx_neon_binary(a,b,2,fpscr);
 /* Multiply rounds first; the subsequent subtraction and halving round once. */
 return vx_neon_binary_scaled(0x40400000u,product,1,-1,fpscr);
}
static uint32_t vx_neon_recip(uint32_t a,uint32_t *fpscr){
 a=vx_neon_unpack(a,fpscr);uint32_t sign=a&0x80000000u,mag=a&0x7fffffffu,exp=(a>>23)&255;
 if(mag>0x7f800000u){if(!(a&0x400000u))*fpscr|=1u;return 0x7fc00000u;}
 if(!mag){*fpscr|=2u;return sign|0x7f800000u;}
 if(exp==255)return sign;
 if(exp>=253){*fpscr|=8u;return sign;}
 uint32_t q=256+((a&0x7fffffu)>>15),den=2*q+1;
 uint32_t estimate=(524288u+den)/(2*den);
 return sign|((253-exp)<<23)|((estimate&255u)<<15);
}
static uint32_t vx_neon_recip_step(uint32_t a,uint32_t b,uint32_t *fpscr){
 a=vx_neon_unpack(a,fpscr);b=vx_neon_unpack(b,fpscr);
 uint32_t x=a&0x7fffffffu,y=b&0x7fffffffu;
 uint32_t product=((x==0x7f800000u&&!y)||(y==0x7f800000u&&!x))?0:
                  vx_neon_binary(a,b,2,fpscr);
 return vx_neon_binary(0x40000000u,product,1,fpscr);
}
static uint32_t vx_neon_minmax(uint32_t a,uint32_t b,int minimum,uint32_t *fpscr){
 a=vx_neon_unpack(a,fpscr);b=vx_neon_unpack(b,fpscr);
 uint32_t aa=a&0x7fffffffu,bb=b&0x7fffffffu;
 if(aa>0x7f800000u||bb>0x7f800000u){
  if((aa>0x7f800000u&&!(a&0x400000u))||(bb>0x7f800000u&&!(b&0x400000u)))*fpscr|=1u;
  return 0x7fc00000u;
 }
 if(!aa&&!bb)return (minimum?(a|b):(a&b))&0x80000000u;
 uint32_t ka=a>>31?~a:a|0x80000000u,kb=b>>31?~b:b|0x80000000u;
 return (minimum?ka<kb:ka>kb)?a:b;
}
