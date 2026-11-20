/* Original vitanx 2026-11-10. Public SceLibKernel clib ABI, no firmware code. */
#include "vitanx_memory.h"
#include <string.h>
extern int vn_guest_write_allowed(const uint8_t *,size_t);
static _Thread_local const char *failure;
const char *vn_memory_error(void){return failure;}
static int span(uint32_t a,size_t n,size_t size,uint32_t base){
 return !n||(a>=base&&(size_t)(a-base)<=size&&n<=size-(size_t)(a-base));
}
int vn_memory_import(uint32_t nid,uint32_t*r,uint8_t*mem,size_t size,uint32_t base,uint32_t*out){
 enum {FILL=1,COPY,MOVE,COMPARE,SEARCH,LENGTH};int kind=0;
 switch(nid){
 case 0x632980d7:kind=FILL;break;
 case 0x14e9dbd7:kind=COPY;break;
 case 0x736753c8:kind=MOVE;break;
 case 0x9cc2bfdf:kind=COMPARE;break;
 case 0x407d6153:kind=SEARCH;break;
 case 0xac595e68:kind=LENGTH;break;
 default:return 0;
 }
 failure=NULL;size_t n=kind==LENGTH?r[1]:r[2];uint32_t a=r[0],b=r[1];
 if(kind==LENGTH){
  if(!n){*out=0;return 1;}
  if(a<base||(size_t)(a-base)>=size){failure="SceClib string outside guest backing";return -1;}
  size_t available=size-(size_t)(a-base),scan=n<available?n:available;
  uint8_t *start=mem+(a-base),*end=memchr(start,0,scan);
  if(end){*out=(uint32_t)(end-start);return 1;}
  if(scan<n){failure="SceClib unterminated string crosses guest backing";return -1;}
  *out=(uint32_t)n;return 1;
 }
 if(!span(a,n,size,base)||((kind==COPY||kind==MOVE||kind==COMPARE)&&!span(b,n,size,base))){failure="SceClib memory range outside guest backing";return -1;}
 uint8_t *p=n?mem+(a-base):mem,*q=n&&(kind==COPY||kind==MOVE||kind==COMPARE)?mem+(b-base):mem;
 if((kind==FILL||kind==COPY||kind==MOVE)&&n&&!vn_guest_write_allowed(p,n)){failure="SceClib write overlaps executable bytes";return -1;}
 switch(kind){
 case FILL:if(n)memset(p,(unsigned char)b,n);*out=a;break;
 case COPY:case MOVE:if(n)memmove(p,q,n);*out=a;break;
 case COMPARE:*out=n?(uint32_t)memcmp(p,q,n):0;break;
 case SEARCH:{uint8_t *hit=n?memchr(p,(unsigned char)b,n):NULL;*out=hit?a+(uint32_t)(hit-p):0;break;}
 case LENGTH:{uint8_t *hit=n?memchr(p,0,n):NULL;*out=hit?(uint32_t)(hit-p):(uint32_t)n;break;}
 }
 return 1;
}
