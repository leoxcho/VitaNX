/* Original bounded ARM AAPCS integer/string snprintf bridge.
   Variadic integers are read from r3 then the guest stack; 64-bit arguments
   advance to an even core register / 8-byte stack boundary. No host va_list
   or host pointers are constructed from guest data. Unsupported formats fail
   before any destination bytes are changed. */
#include "vitanx_format.h"
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <limits.h>
#define LIMIT 65536u
extern int vn_guest_write_allowed(const uint8_t *,size_t);
static _Thread_local const char *error;
const char *vn_format_error(void){return error;}
static int fault(const char *text){error=text;return -1;}
static int span(uint32_t a,size_t n,uint32_t base,size_t size){return a>=base&&(uint64_t)a-base<=size&&n<=size-((uint64_t)a-base);}
static uint32_t word(const uint8_t *p){return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
typedef struct {uint32_t *r;uint8_t *mem;size_t size,stack;uint32_t base;unsigned reg;} args;
static int next32(args *a,uint32_t *v){
 if(a->reg<4){*v=a->r[a->reg++];return 1;}
 uint64_t p=(uint64_t)a->r[13]+a->stack;
 if(p>UINT32_MAX||!span((uint32_t)p,4,a->base,a->size)||(p&3))return 0;
 *v=word(a->mem+(p-a->base));a->stack+=4;return 1;
}
static int next64(args *a,uint64_t *v){
 a->reg=(a->reg+1u)&~1u;
 if(a->reg+1<4){*v=(uint64_t)a->r[a->reg]|(uint64_t)a->r[a->reg+1]<<32;a->reg+=2;return 1;}
 a->reg=4;a->stack=(a->stack+7u)&~(size_t)7u;
 uint64_t p=(uint64_t)a->r[13]+a->stack;
 if(p>UINT32_MAX||!span((uint32_t)p,8,a->base,a->size)||(p&7))return 0;
 *v=(uint64_t)word(a->mem+(p-a->base))|(uint64_t)word(a->mem+(p-a->base)+4)<<32;a->stack+=8;return 1;
}
static int string(uint32_t p,uint32_t base,uint8_t *mem,size_t size,char *dst,size_t cap,int precision){
 size_t max=precision>=0?(size_t)precision:LIMIT;
 if(max>=cap)max=cap-1;
 for(size_t i=0;i<max;i++){
  uint64_t at=(uint64_t)p+i;
  if(at>UINT32_MAX||!span((uint32_t)at,1,base,size))return 0;
  dst[i]=(char)mem[at-base];if(!dst[i])return 1;
 }
 dst[max]=0;return precision>=0;
}
static int digits(const char **f,unsigned *value){
 unsigned n=0;while(**f>='0'&&**f<='9'){unsigned d=(unsigned)(*(*f)++-'0');if(n>(LIMIT-d)/10)return 0;n=n*10+d;}
 *value=n;return 1;
}
static int append(char *out,size_t n,size_t *written,uint64_t *total,const char *s,size_t length){
 if(*total+length>INT_MAX)return 0;
 size_t available=n&&*written<n-1?n-1-*written:0;
 size_t take=length<available?length:available;
 if(take)memcpy(out+*written,s,take);*written+=take;*total+=length;return 1;
}
int vn_format_import(uint32_t nid,uint32_t *r,uint8_t *mem,size_t size,uint32_t base,uint32_t *result){
 if(nid!=UINT32_C(0x8cba03d5))return 0;
 error=NULL;
 if(r[1]>LIMIT)return fault("snprintf destination limit exceeded");
 char format[4097];if(!string(r[2],base,mem,size,format,sizeof format,-1))return fault("invalid or oversized snprintf format");
 char *out=malloc(r[1]?r[1]:1);if(!out)return fault("snprintf host allocation failed");
 char field[LIMIT+128],text[LIMIT+1];size_t written=0;uint64_t total=0;
 args a={r,mem,size,0,base,3};const char *f=format;const char *why=NULL;
 while(*f&&!why){
  if(*f!='%'){if(!append(out,r[1],&written,&total,f++,1))why="snprintf length overflow";continue;}
  f++;if(*f=='%'){if(!append(out,r[1],&written,&total,f++,1))why="snprintf length overflow";continue;}
  char flags[7]={0};size_t nf=0;
  while(*f&&strchr("-+ #0",*f)){if(!strchr(flags,*f))flags[nf++]=*f;f++;}
  unsigned width=0;int precision=-1;uint32_t raw;
  if(*f=='*'){
   f++;if(!next32(&a,&raw)){why="invalid snprintf width argument";break;}
   int64_t w=(int32_t)raw;if(w<0){if(!strchr(flags,'-'))flags[nf++]='-';w=-w;}
   if(w>LIMIT){why="snprintf width limit exceeded";break;}width=(unsigned)w;
  }else if(!digits(&f,&width)){why="snprintf width limit exceeded";break;}
  if(*f=='.'){
   f++;unsigned p=0;
   if(*f=='*'){f++;if(!next32(&a,&raw)){why="invalid snprintf precision argument";break;}precision=(int32_t)raw;if(precision<0)precision=-1;}
   else {if(!digits(&f,&p)){why="snprintf precision limit exceeded";break;}precision=(int)p;}
   if(precision>(int)LIMIT){why="snprintf precision limit exceeded";break;}
  }
  enum {NORMAL,HH,H,L,LL,J,Z,T} length=NORMAL;
  if(*f=='h'){f++;length=H;if(*f=='h'){f++;length=HH;}}
  else if(*f=='l'){f++;length=L;if(*f=='l'){f++;length=LL;}}
  else if(*f=='j'){f++;length=J;}else if(*f=='z'){f++;length=Z;}else if(*f=='t'){f++;length=T;}
  char spec=*f;if(!spec){why="incomplete snprintf conversion";break;}f++;
  if(!strchr("diuoxXcs",spec)){why="unsupported snprintf conversion";break;}
  if((spec=='s'||spec=='c')&&length!=NORMAL){why="wide snprintf characters unsupported";break;}
  char fmt[64],wbuf[16]={0},pbuf[16]={0};if(width)snprintf(wbuf,sizeof wbuf,"%u",width);if(precision>=0)snprintf(pbuf,sizeof pbuf,".%d",precision);
  int count=-1;
  if(spec=='s'||spec=='c'){
   if(!next32(&a,&raw)){why="invalid snprintf argument";break;}
   snprintf(fmt,sizeof fmt,"%%%s%s%s%c",flags,wbuf,pbuf,spec);
   if(spec=='s'){
    if(!string(raw,base,mem,size,text,sizeof text,precision)){why="invalid snprintf string argument";break;}
    count=snprintf(field,sizeof field,fmt,text);
   }else count=snprintf(field,sizeof field,fmt,(int)(unsigned char)raw);
  }else{
   uint64_t bits;
   if(length==LL||length==J){if(!next64(&a,&bits)){why="invalid snprintf 64-bit argument";break;}}
   else {if(!next32(&a,&raw)){why="invalid snprintf argument";break;}bits=raw;}
   snprintf(fmt,sizeof fmt,"%%%s%s%sll%c",flags,wbuf,pbuf,spec);
   if(spec=='d'||spec=='i'){
    int64_t value=length==LL||length==J?(int64_t)bits:length==HH?(int8_t)bits:length==H?(int16_t)bits:(int32_t)bits;
    count=snprintf(field,sizeof field,fmt,(long long)value);
   }else {
    if(length==HH)bits=(uint8_t)bits;else if(length==H)bits=(uint16_t)bits;
    count=snprintf(field,sizeof field,fmt,(unsigned long long)bits);
   }
  }
  if(count<0||(size_t)count>=sizeof field){why="snprintf field limit exceeded";break;}
  if(!append(out,r[1],&written,&total,field,(size_t)count))why="snprintf length overflow";
 }
 if(!why&&r[1]){
  size_t n=written+1;
  if(!span(r[0],n,base,size)||!vn_guest_write_allowed(mem+(r[0]-base),n))why="invalid snprintf destination";
  else {out[written]=0;memcpy(mem+(r[0]-base),out,n);}
 }
 free(out);if(why)return fault(why);*result=(uint32_t)total;return 1;
}
