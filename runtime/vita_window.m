#import <Cocoa/Cocoa.h>
#import <QuartzCore/CAMetalLayer.h>
#import <Metal/Metal.h>
#import <GameController/GameController.h>
#include <math.h>
#include <string.h>
#include "vita_window.h"
#include "vita_input.h"
#import <IOKit/hidsystem/IOLLEvent.h>

/* A translated guest owns its window; restoring serialized host windows would
   create views without a guest/runtime owner on the next launch. */
@interface VXApplicationDelegate : NSObject <NSApplicationDelegate>
@end
@implementation VXApplicationDelegate
- (BOOL)applicationSupportsSecureRestorableState:(NSApplication *)app {(void)app;return YES;}
- (BOOL)applicationShouldRestoreApplicationState:(NSApplication *)app {(void)app;return NO;}
- (BOOL)applicationShouldSaveApplicationState:(NSApplication *)app {(void)app;return NO;}
- (BOOL)applicationShouldRestoreSecureApplicationState:(NSApplication *)app {(void)app;return NO;}
- (BOOL)applicationShouldSaveSecureApplicationState:(NSApplication *)app {(void)app;return NO;}
@end
static VXApplicationDelegate *application_delegate;

@interface VXGameView : NSView
@end
@implementation VXGameView
- (BOOL)acceptsFirstResponder{return YES;}
- (void)keyDown:(NSEvent *)event{(void)event;}
- (void)keyUp:(NSEvent *)event{(void)event;}
@end
@class VXGameWindow;
static void keyboard(VXGameWindow *ctx,NSEvent *event);
static void pointer_input(VXGameWindow *ctx,NSEvent *event);
@interface VXNativeWindow : NSWindow
@property(nonatomic,weak) VXGameWindow *game;
@end
@implementation VXNativeWindow
- (void)sendEvent:(NSEvent *)event {
 if(self.game){keyboard(self.game,event);pointer_input(self.game,event);}
 [super sendEvent:event];
}
- (BOOL)canBecomeKeyWindow{return YES;}
- (BOOL)canBecomeMainWindow{return YES;}
@end

@interface VXGameWindow : NSObject <NSWindowDelegate>
@property(nonatomic,strong) NSWindow *window;
@property(nonatomic,strong) CAMetalLayer *layer;
@property(nonatomic) BOOL closed;
@property(nonatomic) BOOL linear;
@property(nonatomic) uint64_t frames;
@property(nonatomic) uint64_t events;
@property(nonatomic) uint64_t keyEvents;
@property(nonatomic) uint32_t keys;
@property(nonatomic) uint32_t axes;
@property(nonatomic) vx_input_keys physicalKeys;
@property(nonatomic) vx_window_input pointerState;
@property(nonatomic) CGSize framebufferSize;
@end
@implementation VXGameWindow
- (BOOL)windowShouldClose:(NSWindow *)sender {(void)sender;self.closed=YES;return YES;}
- (void)windowDidResignKey:(NSNotification *)note {(void)note;self.keys=0;self.axes=0;self.physicalKeys=(vx_input_keys){0};self.pointerState=(vx_window_input){0};}
@end
static int main_thread(void){return [NSThread isMainThread];}
static uint8_t axis(float value){if(!isfinite(value))return 128;value=fmaxf(-1,fminf(1,value));return (uint8_t)lroundf((value+1)*127.5f);}
static uint8_t digital_axis(uint32_t axes,unsigned shift){
 unsigned directions=(axes>>shift)&3;
 return directions==1?0:directions==2?255:128;
}
static void keyboard(VXGameWindow *ctx,NSEvent *event){
 BOOL down=event.type==NSEventTypeKeyDown;
 if(event.type==NSEventTypeFlagsChanged){
  unsigned short code=event.keyCode;
  if(code==56||code==60){vx_input_keys state=ctx.physicalKeys;
   NSUInteger mask=code==56?NX_DEVICELSHIFTKEYMASK:NX_DEVICERSHIFTKEYMASK;
   vx_input_key_set(&state,code,(event.modifierFlags&mask)!=0);ctx.physicalKeys=state;ctx.keys=vx_input_key_buttons(&state);}
  return;
 }
 if(event.type!=NSEventTypeKeyDown&&event.type!=NSEventTypeKeyUp)return;
 ctx.keyEvents++;
 if(down&&!event.isARepeat&&event.keyCode==3){[ctx.window toggleFullScreen:nil];return;}
 if(down&&event.keyCode==53){if(ctx.window.styleMask&NSWindowStyleMaskFullScreen)[ctx.window toggleFullScreen:nil];else [ctx.window performClose:nil];return;}
 vx_input_keys state=ctx.physicalKeys;vx_input_key_set(&state,event.keyCode,down);
 ctx.physicalKeys=state;ctx.keys=vx_input_key_buttons(&state);ctx.axes=vx_input_key_axes(&state);
}
/* Primary and secondary clicks map to the front and rear panel on the rendered viewport. */
static void pointer_input(VXGameWindow *ctx,NSEvent *event){
 int panel=-1,down=-1;
 switch(event.type){
 case NSEventTypeLeftMouseDown:panel=0;down=1;break;
 case NSEventTypeLeftMouseUp:panel=0;down=0;break;
 case NSEventTypeLeftMouseDragged:panel=0;break;
 case NSEventTypeRightMouseDown:panel=1;down=1;break;
 case NSEventTypeRightMouseUp:panel=1;down=0;break;
 case NSEventTypeRightMouseDragged:panel=1;break;
 default:return;
 }
 NSView *view=ctx.window.contentView;NSPoint point=[view convertPoint:event.locationInWindow fromView:nil];
 NSRect bounds=view.bounds;if(bounds.size.width<=0||bounds.size.height<=0)return;
 CGSize frame=ctx.framebufferSize;
 if(frame.width>0&&frame.height>0){
  CGFloat scale=fmin(bounds.size.width/frame.width,bounds.size.height/frame.height);
  CGFloat width=frame.width*scale,height=frame.height*scale;
  bounds=NSMakeRect(NSMidX(bounds)-width/2,NSMidY(bounds)-height/2,width,height);
 }
 if(down==1&&!NSPointInRect(point,bounds))return;
 point.x-=NSMinX(bounds);point.y-=NSMinY(bounds);
 vx_window_input state=ctx.pointerState;
 if(down>=0){if(down&&!state.touch_down[panel])state.touch_id[panel]=(state.touch_id[panel]+1)&127;state.touch_down[panel]=(uint8_t)down;}
 state.touch_x[panel]=(uint16_t)lround(fmax(0,fmin(1,point.x/bounds.size.width))*1919);
 state.touch_y[panel]=(uint16_t)lround(fmax(0,fmin(1,1-point.y/bounds.size.height))*1087);
 ctx.pointerState=state;
}
int vx_window_create(const char *title,uint32_t width,uint32_t height,int fullscreen,int vsync,int linear_filter,vx_window **out){
 if(!out)return VX_METAL_INVALID;*out=NULL;
 if(!title||!width||!height||width>4096||height>4096||!main_thread()||(fullscreen!=0&&fullscreen!=1)||(vsync!=0&&vsync!=1)||(linear_filter!=0&&linear_filter!=1))return VX_METAL_INVALID;
 @autoreleasepool {
  id<MTLDevice> device=MTLCreateSystemDefaultDevice();if(!device)return VX_METAL_UNAVAILABLE;
  [NSApplication sharedApplication];
  if(!application_delegate){application_delegate=[VXApplicationDelegate new];NSApp.delegate=application_delegate;}
  [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];[NSApp finishLaunching];
  VXGameWindow *ctx=[VXGameWindow new];
  NSScreen *screen=[NSScreen mainScreen];if(!screen)return VX_METAL_UNAVAILABLE;
  NSRect available=screen.visibleFrame;
  double factor=fmin(1,fmin(available.size.width/width,available.size.height/height));
  NSRect rectangle=NSMakeRect(0,0,fmax(160,width*factor),fmax(90,height*factor));
  ctx.window=[[VXNativeWindow alloc] initWithContentRect:rectangle styleMask:NSWindowStyleMaskTitled|NSWindowStyleMaskClosable|NSWindowStyleMaskMiniaturizable|NSWindowStyleMaskResizable backing:NSBackingStoreBuffered defer:NO];
  ctx.window.restorable=NO;ctx.window.releasedWhenClosed=NO;ctx.window.delegate=ctx;((VXNativeWindow *)ctx.window).game=ctx;
  ctx.window.title=[NSString stringWithUTF8String:title]?:@"vitaxnative";
  ctx.window.collectionBehavior=NSWindowCollectionBehaviorFullScreenPrimary;
  ctx.window.contentView=[[VXGameView alloc] initWithFrame:rectangle];
  ctx.window.contentView.wantsLayer=YES;ctx.layer=[CAMetalLayer layer];ctx.layer.device=device;
  ctx.layer.pixelFormat=MTLPixelFormatBGRA8Unorm;ctx.layer.framebufferOnly=YES;
  ctx.layer.displaySyncEnabled=vsync;ctx.layer.maximumDrawableCount=2;ctx.layer.allowsNextDrawableTimeout=YES;
  ctx.window.contentView.layer=ctx.layer;ctx.linear=linear_filter;
  [ctx.window center];[ctx.window makeMainWindow];[ctx.window makeKeyAndOrderFront:nil];[ctx.window makeFirstResponder:ctx.window.contentView];[NSApp activateIgnoringOtherApps:YES];
  if(fullscreen)[ctx.window toggleFullScreen:nil];
  *out=(vx_window *)CFBridgingRetain(ctx);return VX_METAL_OK;
 }
}
int vx_window_pump(vx_window *window){
 if(!window||!main_thread())return VX_METAL_INVALID;
 @autoreleasepool {VXGameWindow *ctx=(__bridge VXGameWindow *)window;
  /* Activation, fullscreen transitions and controller discovery are delivered
     on the main run loop even when a translated guest owns main(). */
  [[NSRunLoop mainRunLoop] runMode:NSDefaultRunLoopMode beforeDate:[NSDate date]];
  if(!ctx.closed&&NSApp.active&&!ctx.window.keyWindow)[ctx.window makeKeyWindow];
  for(unsigned count=0;count<1024;count++){
   NSEvent *event=[NSApp nextEventMatchingMask:NSEventMaskAny untilDate:[NSDate distantPast] inMode:NSDefaultRunLoopMode dequeue:YES];if(!event)break;
   ctx.events++;[NSApp sendEvent:event];
  }
  [NSApp updateWindows];return ctx.closed?1:0;
 }
}
int vx_window_set_fullscreen(vx_window *window,int fullscreen){
 if(!window||!main_thread()||(fullscreen!=0&&fullscreen!=1))return VX_METAL_INVALID;
 @autoreleasepool {VXGameWindow *ctx=(__bridge VXGameWindow *)window;if(ctx.closed)return 1;
  if(!!(ctx.window.styleMask&NSWindowStyleMaskFullScreen)!=fullscreen)[ctx.window toggleFullScreen:nil];return 0;}
}
int vx_window_close_requested(vx_window *window){
 if(!window)return 0;VXGameWindow *ctx=(__bridge VXGameWindow *)window;return ctx.closed;
}
int vx_window_present(vx_window *window,vx_metal *framebuffer){
 if(!window||!framebuffer||!main_thread())return VX_METAL_INVALID;
 uint32_t width,height;
 int status=vx_metal_size(framebuffer,&width,&height);if(status)return status;
 VXGameWindow *ctx=(__bridge VXGameWindow *)window;
 ctx.framebufferSize=CGSizeMake(width,height);
 status=vx_window_pump(window);if(status)return status;
 @autoreleasepool {
  NSSize size=[ctx.window.contentView convertSizeToBacking:ctx.window.contentView.bounds.size];
  if(size.width<1||size.height<1||ctx.window.miniaturized)return VX_METAL_OK;
  ctx.layer.drawableSize=CGSizeMake(size.width,size.height);
  status=vx_metal_present_layer(framebuffer,(__bridge void *)ctx.layer,ctx.linear);
  if(!status)ctx.frames++;return status;
 }
}
int vx_window_input_state(vx_window *window,vx_window_input *out){
 if(!out)return VX_METAL_INVALID;
 *out=(vx_window_input){.lx=128,.ly=128,.rx=128,.ry=128};
 /* Controller discovery is independent of the first graphics frame. Never
    create a Cocoa window or Metal device merely to poll an attached pad. */
 if(!main_thread())return VX_METAL_INVALID;
 if(window){int status=vx_window_pump(window);if(status<0)return status;}
 @autoreleasepool {VXGameWindow *ctx=(__bridge VXGameWindow *)window;uint32_t axes=0;
  if(ctx){
  *out=ctx.pointerState;out->buttons=ctx.keys;out->close_requested=ctx.closed;out->connected=1;
  out->suspended=ctx.window.miniaturized||!NSApp.active;
  out->lx=digital_axis(ctx.axes,0);out->ly=digital_axis(ctx.axes,2);
  out->rx=digital_axis(ctx.axes,4);out->ry=digital_axis(ctx.axes,6);
  if(out->buttons&0x100)out->ext_buttons|=0x400;
  if(out->buttons&0x200)out->ext_buttons|=0x800;
  axes=ctx.axes;
  }
  GCExtendedGamepad *pad=nil;for(GCController *controller in [GCController controllers]){if(controller.extendedGamepad){pad=controller.extendedGamepad;break;}}
  if(pad){
   out->connected=1;
   if(pad.dpad.up.pressed)out->buttons|=0x10;if(pad.dpad.right.pressed)out->buttons|=0x20;if(pad.dpad.down.pressed)out->buttons|=0x40;if(pad.dpad.left.pressed)out->buttons|=0x80;
   if(pad.buttonA.pressed)out->buttons|=0x4000;if(pad.buttonB.pressed)out->buttons|=0x2000;if(pad.buttonX.pressed)out->buttons|=0x8000;if(pad.buttonY.pressed)out->buttons|=0x1000;
   if(pad.leftShoulder.pressed||pad.leftTrigger.pressed)out->buttons|=0x100;
   if(pad.rightShoulder.pressed||pad.rightTrigger.pressed)out->buttons|=0x200;
   if(pad.leftShoulder.pressed)out->ext_buttons|=0x400;
   if(pad.rightShoulder.pressed)out->ext_buttons|=0x800;
   if(pad.leftThumbstickButton.pressed)out->ext_buttons|=2;
   if(pad.rightThumbstickButton.pressed)out->ext_buttons|=4;
   if(pad.leftTrigger.pressed)out->ext_buttons|=0x100;
   if(pad.rightTrigger.pressed)out->ext_buttons|=0x200;
   out->left_trigger=(uint8_t)lroundf(pad.leftTrigger.value*255);
   out->right_trigger=(uint8_t)lroundf(pad.rightTrigger.value*255);
   if(pad.buttonMenu.pressed)out->buttons|=8;if(pad.buttonOptions.pressed)out->buttons|=1;
   if(!(axes&3))out->lx=axis(pad.leftThumbstick.xAxis.value);if(!(axes&12))out->ly=axis(-pad.leftThumbstick.yAxis.value);
   if(!(axes&48))out->rx=axis(pad.rightThumbstick.xAxis.value);if(!(axes&192))out->ry=axis(-pad.rightThumbstick.yAxis.value);
  }
  return 0;
 }
}
void vx_window_get_stats(vx_window *window,vx_window_stats *out){
 if(!out)return;memset(out,0,sizeof *out);if(!window||!main_thread())return;
 @autoreleasepool {VXGameWindow *ctx=(__bridge VXGameWindow *)window;out->frames_presented=ctx.frames;out->events_processed=ctx.events;out->key_events=ctx.keyEvents;out->closed=ctx.closed;out->fullscreen=!!(ctx.window.styleMask&NSWindowStyleMaskFullScreen);
  for(GCController *controller in [GCController controllers])if(controller.extendedGamepad){out->controller_connected=1;break;}}
}
void vx_window_destroy(vx_window *window){if(window&&main_thread()){@autoreleasepool {VXGameWindow *ctx=CFBridgingRelease(window);ctx.window.delegate=nil;[ctx.window close];ctx.window=nil;}}}
