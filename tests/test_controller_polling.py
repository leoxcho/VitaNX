"""Real GameController polling path with deterministic host objects, without UI."""
from pathlib import Path
import platform
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
@unittest.skipUnless(platform.system()=='Darwin','GameController requires macOS')
class ControllerPollingTests(unittest.TestCase):
    def test_attached_controller_before_window_and_disconnect(self):
        source=r'''
#import <Foundation/Foundation.h>
#import <GameController/GameController.h>
#import <objc/runtime.h>
#include "vita_window.h"
#include <assert.h>
@interface ProbeButton:NSObject
@property(getter=isPressed) BOOL pressed;
@end
@implementation ProbeButton
@end
@interface ProbeAxis:NSObject
@property float value;
@end
@implementation ProbeAxis
@end
@interface ProbeDirection:NSObject
@property(strong) ProbeButton *up,*right,*down,*left;
@property(strong) ProbeAxis *xAxis,*yAxis;
@end
@implementation ProbeDirection
@end
@interface ProbePad:NSObject
@property(strong) ProbeDirection *dpad,*leftThumbstick,*rightThumbstick;
@property(strong) ProbeButton *buttonA,*buttonB,*buttonX,*buttonY,*leftShoulder,*leftTrigger,*rightShoulder,*rightTrigger,*buttonMenu,*buttonOptions;
@end
@implementation ProbePad
@end
@interface ProbeController:NSObject
@property(strong) ProbePad *extendedGamepad;
@end
@implementation ProbeController
@end
static NSArray *attached;
static NSArray *controllers(id self,SEL command){(void)self;(void)command;return attached;}
int vx_metal_present_layer(vx_metal *context,void *layer,int linear){(void)context;(void)layer;(void)linear;assert(0);return -1;}
int main(void){@autoreleasepool{
 Method method=class_getClassMethod(GCController.class,@selector(controllers));
 IMP original=method_setImplementation(method,(IMP)controllers);
 ProbeController *controller=[ProbeController new];ProbePad *pad=[ProbePad new];controller.extendedGamepad=pad;
 pad.buttonA=[ProbeButton new];pad.buttonA.pressed=YES;pad.buttonMenu=[ProbeButton new];pad.buttonMenu.pressed=YES;
 pad.leftThumbstick=[ProbeDirection new];pad.leftThumbstick.xAxis=[ProbeAxis new];pad.leftThumbstick.xAxis.value=-1;
 pad.leftThumbstick.yAxis=[ProbeAxis new];pad.leftThumbstick.yAxis.value=1;
 pad.rightThumbstick=[ProbeDirection new];pad.rightThumbstick.xAxis=[ProbeAxis new];pad.rightThumbstick.xAxis.value=1;
 pad.rightThumbstick.yAxis=[ProbeAxis new];pad.rightThumbstick.yAxis.value=-1;
 attached=@[controller];vx_window_input state;
 assert(!vx_window_input_state(NULL,&state));assert(state.connected&&!state.suspended&&!state.close_requested);
 assert(state.buttons==0x4008&&state.lx==0&&state.ly==0&&state.rx==255&&state.ry==255);
 assert(!state.touch_down[0]&&!state.touch_down[1]);
 attached=@[];assert(!vx_window_input_state(NULL,&state));
 assert(!state.connected&&!state.buttons&&state.lx==128&&state.ly==128&&state.rx==128&&state.ry==128);
 method_setImplementation(method,original);return 0;
}}
'''
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);(tmp/'probe.m').write_text(source)
            subprocess.run(['clang','-DVX_ENABLE_WINDOW','-fobjc-arc','-Wall','-Wextra','-Werror','-I',str(ROOT/'runtime'),str(tmp/'probe.m'),str(ROOT/'runtime/vita_window.m'),'-framework','Cocoa','-framework','Metal','-framework','QuartzCore','-framework','GameController','-o',str(tmp/'probe')],check=True,capture_output=True)
            subprocess.run([str(tmp/'probe')],check=True,capture_output=True,timeout=5)
