#import <Cocoa/Cocoa.h>
#include "vita_display.h"
#include "vita_frame.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static void word(uint8_t *p,uint32_t value){memcpy(p,&value,4);}
static void key(unsigned short code,BOOL down){
 NSWindow *window=nil;
 for(NSWindow *candidate in NSApp.windows)if([candidate.title isEqualToString:@"vitaxnative — Metal window validation"]&&candidate.delegate){window=candidate;break;}
 assert(window);
 fprintf(stderr,"post key=%u down=%d target=%s number=%ld key=%d\n",code,down,NSStringFromClass(window.class).UTF8String,(long)window.windowNumber,window.keyWindow);
 NSEvent *event=[NSEvent keyEventWithType:down?NSEventTypeKeyDown:NSEventTypeKeyUp location:NSZeroPoint modifierFlags:0 timestamp:0 windowNumber:window.windowNumber context:nil characters:@"" charactersIgnoringModifiers:@"" isARepeat:NO keyCode:code];[NSApp postEvent:event atStart:NO];
}
int main(int argc,char **argv){
 @autoreleasepool {
  int fullscreen=argc>1?atoi(argv[1]):0;
  assert(!vx_display_configure(60,60,960,544));assert(!vx_display_configure_window("vitaxnative — Metal window validation",fullscreen,1,0));
  uint8_t mem[1024]={0};uint32_t r[16]={0},result;const uint32_t base=0x81000000;
  uint32_t values[]={24,base+128,2,0,2,2};memcpy(mem+32,values,sizeof values);
  uint8_t pixels[]={255,0,0,255,0,255,0,255,0,0,255,255,255,255,255,255};memcpy(mem+128,pixels,sizeof pixels);
  r[0]=base+32;r[1]=0;assert(vx_display_import(0x7a410b64,r,mem,sizeof mem,base,&result));if(result){fprintf(stderr,"display unavailable: %08x\n",result);vx_display_shutdown();return 77;}
  uint8_t *readback=malloc(960*544*4);assert(readback);assert(!vx_display_readback(readback,960*544*4));
  assert(readback[0]==255&&readback[1]==0&&readback[2]==0);
  size_t last=((size_t)960*544-1)*4;assert(readback[last]==255&&readback[last+1]==255&&readback[last+2]==255);free(readback);
  vx_window_input input;
  for(unsigned attempt=0;!NSApp.keyWindow&&attempt<100;attempt++){
   assert(!vx_display_input_state(&input));
   [[NSRunLoop mainRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.01]];
  }
  fprintf(stderr,"window activation: active=%d windows=%lu key=%d\n",NSApp.active,(unsigned long)NSApp.windows.count,NSApp.keyWindow!=nil);
  key(6,YES);key(0,YES);
  for(unsigned attempt=0;attempt<100;attempt++){
   assert(!vx_display_input_state(&input));if(input.buttons==0x4000&&input.lx==0)break;
   [[NSRunLoop mainRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.005]];
  }
  vx_window_stats keys;vx_display_window_stats(&keys);fprintf(stderr,"key down: buttons=%x lx=%u events=%llu\n",input.buttons,input.lx,(unsigned long long)keys.key_events);
  assert(input.buttons==0x4000&&input.lx==0);
  key(6,NO);key(0,NO);
  for(unsigned attempt=0;attempt<100;attempt++){
   assert(!vx_display_input_state(&input));if(input.buttons==0&&input.lx==128)break;
   [[NSRunLoop mainRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.005]];
  }
  assert(input.buttons==0&&input.lx==128);
  for(unsigned frame=0;frame<90;frame++){
   word(mem+128,frame%2?0xff0000ffu:0xff00ff00u);r[0]=base+32;r[1]=0;assert(vx_display_import(0x7a410b64,r,mem,sizeof mem,base,&result)&&!result);
   r[0]=0;assert(vx_display_import(0x5795e898,r,mem,sizeof mem,base,&result)&&!result);
  }
  vx_window_stats stats;vx_display_window_stats(&stats);printf("{\"window_frames\":%llu,\"events\":%llu,\"synthetic_key_events\":%llu,\"fullscreen\":%d,\"controller_connected\":%d,\"pixel_readback\":true}\n",(unsigned long long)stats.frames_presented,(unsigned long long)stats.events_processed,(unsigned long long)stats.key_events,stats.fullscreen,stats.controller_connected);
  assert(stats.frames_presented==91&&stats.key_events>=4);if(fullscreen)assert(stats.fullscreen);
  if(!fullscreen){
   key(53,YES);
   for(unsigned attempt=0;attempt<100;attempt++){
    assert(!vx_display_input_state(&input));if(input.close_requested)break;
    [[NSRunLoop mainRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.005]];
   }
   assert(input.close_requested);
  }
  vx_display_shutdown();return 0;
 }
}
