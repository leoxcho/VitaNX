#include "vita_display.h"
#include "vita_metal.h"
#include "vita_frame.h"
#include <string.h>
/* Public prototypes/NIDs: installed VitaSDK psp2/display.h,
   psp2common/display.h, db/360/SceDisplay.yml and SceDriverUser.yml. */
#define INVALID_VALUE UINT32_C(0x80290001)
#define INVALID_ADDR UINT32_C(0x80290002)
#define INVALID_FORMAT UINT32_C(0x80290003)
#define INVALID_PITCH UINT32_C(0x80290004)
#define INVALID_RESOLUTION UINT32_C(0x80290005)
#define INVALID_SYNC UINT32_C(0x80290006)
#define NO_FRAMEBUFFER UINT32_C(0x80290007)
#define NO_OUTPUT UINT32_C(0x80290009)
static _Thread_local vx_metal *context;
static _Thread_local vx_frame_clock frame_clock;
static _Thread_local int clock_ready,has_framebuffer;
static _Thread_local uint32_t rate=60,simulation_rate=60,target_width,target_height;
static _Thread_local uint8_t framebuffer[24];
static _Thread_local vx_display_stats stats;
static _Thread_local int display_linear;
int vx_display_set_filter(int linear_filter){if(linear_filter!=0&&linear_filter!=1)return -1;display_linear=linear_filter;return 0;}
#ifdef VX_ENABLE_WINDOW
static _Thread_local vx_window *game_window;
static _Thread_local int window_enabled,window_fullscreen,window_vsync=1,window_linear;
static _Thread_local char window_title[256];
int vx_display_configure_window(const char *title,int fullscreen,int vsync,int linear_filter){
 if(!title||strlen(title)>=sizeof window_title||(fullscreen!=0&&fullscreen!=1)||(vsync!=0&&vsync!=1)||(linear_filter!=0&&linear_filter!=1))return -1;
 vx_window_destroy(game_window);game_window=NULL;
 strcpy(window_title,title);window_enabled=1;window_fullscreen=fullscreen;window_vsync=vsync;window_linear=linear_filter;display_linear=linear_filter;return 0;
}
int vx_display_input_state(vx_window_input *out){return vx_window_input_state(game_window,out);}
int vx_display_close_requested(void){return vx_window_close_requested(game_window);}
void vx_display_window_stats(vx_window_stats *out){vx_window_get_stats(game_window,out);}
#endif
static uint32_t read32(const uint8_t *p){return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static void write32(uint8_t *p,uint32_t value){for(int i=0;i<4;i++)p[i]=(uint8_t)(value>>(i*8));}
static int range(uint32_t pointer,size_t count,size_t size,uint32_t base){
 return pointer>=base&&(uint64_t)pointer-base<=size&&count<=size-((uint64_t)pointer-base);
}
static int clock_init(void){
 if(clock_ready)return 0;
 uint64_t now;vx_frame_sample sample;
 if(vx_frame_now(&now)||vx_frame_init(&frame_clock,rate,simulation_rate,now)||vx_frame_advance(&frame_clock,now,&sample))return -1;
 clock_ready=1;return 0;
}
int vx_display_configure(uint32_t render_hz,uint32_t simulation_hz,uint32_t width,uint32_t height){
 if((render_hz!=30&&render_hz!=60&&render_hz!=120)||!simulation_hz||simulation_hz>1000||((!width)!=(!height))||width>4096||height>4096)return -1;
 vx_display_shutdown();rate=render_hz;simulation_rate=simulation_hz;target_width=width;target_height=height;display_linear=0;
#ifdef VX_ENABLE_WINDOW
 window_enabled=0;
#endif
 return 0;
}
void vx_display_shutdown(void){
#ifdef VX_ENABLE_WINDOW
 vx_window_destroy(game_window);game_window=NULL;
#endif
 vx_metal_destroy(context);context=0;clock_ready=0;has_framebuffer=0;
 memset(&frame_clock,0,sizeof frame_clock);memset(framebuffer,0,sizeof framebuffer);memset(&stats,0,sizeof stats);
 /* Configuration survives shutdown so a launcher can configure before mounting. */
}
void vx_display_get_stats(vx_display_stats *out){if(out){*out=stats;out->render_hz=rate;out->simulation_hz=simulation_rate;}}
int vx_display_readback(uint8_t *rgba,size_t capacity){return vx_metal_readback(context,rgba,capacity);}
static uint32_t wait_frames(uint32_t count){
 if(!count||count>120)return INVALID_VALUE;
 if(clock_init())return NO_OUTPUT;
 for(uint32_t i=0;i<count;i++){
#ifdef VX_ENABLE_WINDOW
  if(game_window&&vx_window_pump(game_window))return NO_OUTPUT;
#endif
  vx_frame_sample sample;if(vx_frame_wait(&frame_clock,&sample))return NO_OUTPUT;
  stats.simulation_ticks+=sample.simulation_steps;
 }
 stats.wait_calls++;return 0;
}
int vx_display_import(uint32_t nid,uint32_t r[16],uint8_t *mem,size_t size,uint32_t memory_base,uint32_t *out_result){
 if(!r||!out_result)return 0;
 uint32_t result;
 switch(nid){
 case UINT32_C(0x7178FADA):result=0;break; /* primary head */
 case UINT32_C(0xA08CA60D):{ /* configured theoretical software refresh rate */
  if(!mem||!r[0]||!range(r[0],4,size,memory_base)){result=INVALID_ADDR;break;}
  float hz=(float)rate;uint32_t bits;memcpy(&bits,&hz,4);write32(mem+(r[0]-memory_base),bits);result=0;break;
 }
 case UINT32_C(0x8848ADDD):{
  if(!mem||!r[0]||!r[1]||!range(r[0],4,size,memory_base)||!range(r[1],4,size,memory_base)){result=INVALID_ADDR;break;}
  write32(mem+(r[0]-memory_base),960);write32(mem+(r[1]-memory_base),544);result=0;break;
 }
 case UINT32_C(0xB6FDE0BA):{
  uint64_t now;if(clock_init()||vx_frame_now(&now)){result=NO_OUTPUT;break;}
  result=(uint32_t)((__uint128_t)(now-frame_clock.start_ns)*rate/UINT64_C(1000000000));break;
 }
 case UINT32_C(0x5795E898):result=wait_frames(1);break;
 case UINT32_C(0xDD0A13B8):result=wait_frames(r[0]);break;
 case UINT32_C(0x42AE6BBC):{
  if(r[1]>1){result=INVALID_SYNC;break;}
  if(!mem||!r[0]||!range(r[0],24,size,memory_base)){result=INVALID_ADDR;break;}
  uint8_t *out=mem+(r[0]-memory_base);
  if(read32(out)!=24){result=INVALID_VALUE;break;}
  if(!has_framebuffer){result=NO_FRAMEBUFFER;break;}
  memcpy(out,framebuffer,24);result=0;break;
 }
 case UINT32_C(0x7A410B64):{
  if(r[1]>1){result=INVALID_SYNC;break;}
  if(!r[0]){ /* Disable request is valid even before a GPU context exists. */
   result=0;if(context){float black[4]={0,0,0,1};int status=vx_metal_draw(context,0,0,black);
#ifdef VX_ENABLE_WINDOW
    if(!status&&game_window)status=vx_window_present(game_window,context);
#endif
    stats.metal_status=status;if(status)result=NO_OUTPUT;}
   if(!result)has_framebuffer=0;break;
  }
  if(!mem||!range(r[0],24,size,memory_base)){result=INVALID_ADDR;break;}
  uint8_t *fb=mem+(r[0]-memory_base);
  uint32_t base=read32(fb+4),pitch=read32(fb+8),format=read32(fb+12),width=read32(fb+16),height=read32(fb+20);
  if(read32(fb)!=24){result=INVALID_VALUE;break;}
  if(format!=0){result=INVALID_FORMAT;break;} /* Vita A8B8G8R8 is RGBA bytes on LE ARM. */
  if(!width||!height||width>4096||height>4096){result=INVALID_RESOLUTION;break;}
  if(pitch<width||pitch>4096){result=INVALID_PITCH;break;}
  size_t required,rgba;
  if(vx_framebuffer_required(width,height,(size_t)pitch*4,VX_PIXELS_RGBA8,&required,&rgba)||!base||(base&3)||!range(base,required,size,memory_base)){result=INVALID_ADDR;break;}
  stats.frames_submitted++;
  uint32_t output_width=target_width?target_width:width,output_height=target_height?target_height:height;
  int status;
  if(!context)status=vx_metal_create(output_width,output_height,&context);
  else {uint32_t old_width,old_height;status=vx_metal_size(context,&old_width,&old_height);if(!status&&(old_width!=output_width||old_height!=output_height))status=vx_metal_resize(context,output_width,output_height);}
  stats.metal_status=status;if(status){result=NO_OUTPUT;break;}
  if(vx_metal_set_filter(context,display_linear)){result=NO_OUTPUT;break;}
  if(r[1]&&(result=wait_frames(1)))break;
  status=vx_metal_present(context,mem+(base-memory_base),required,width,height,(size_t)pitch*4,VX_PIXELS_RGBA8);
  stats.metal_status=status;if(status){result=NO_OUTPUT;break;}
#ifdef VX_ENABLE_WINDOW
  if(window_enabled){
   if(!game_window)status=vx_window_create(window_title,output_width,output_height,window_fullscreen,window_vsync,window_linear,&game_window);
   if(!status)status=vx_window_present(game_window,context);
   stats.metal_status=status;if(status){result=NO_OUTPUT;break;}
  }
#endif
  memcpy(framebuffer,fb,24);has_framebuffer=1;stats.frames_presented++;
  stats.guest_width=width;stats.guest_height=height;stats.target_width=output_width;stats.target_height=output_height;result=0;break;
 }
 default:return 0;
 }
 *out_result=result;return 1;
}
