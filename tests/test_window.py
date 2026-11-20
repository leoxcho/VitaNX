"""Window API compilation/bounds; GUI runs opt-in outside the sandbox."""
import os
import platform
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(platform.system()=='Darwin' and shutil.which('clang'),'macOS Clang required')
class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temporary.cleanup)
        cls.path=Path(cls.temporary.name)
        cls.command=['clang','-fobjc-arc','-Wall','-Wextra','-Werror','-DVX_ENABLE_WINDOW','-I',str(ROOT/'runtime'),
                     str(ROOT/'runtime/vita_metal.m'),str(ROOT/'runtime/vita_window.m'),str(ROOT/'runtime/vita_display.m'),str(ROOT/'runtime/vita_frame.c'),
                     '-framework','Cocoa','-framework','QuartzCore','-framework','GameController','-framework','Metal']

    def test_invalid_inputs_and_neutral_state(self):
        source=self.path/'bounds.m';binary=self.path/'bounds'
        source.write_text(r'''
#include "vita_display.h"
#include <assert.h>
#include <string.h>
int main(void){
 vx_window *window=(vx_window*)1;vx_window_input input;vx_window_stats stats;
 assert(vx_window_create("bounds",0,544,0,1,0,&window)==VX_METAL_INVALID&&!window);
 assert(vx_window_create("bounds",960,4097,0,1,0,&window)==VX_METAL_INVALID&&!window);
 assert(vx_window_create("bounds",960,544,2,1,0,&window)==VX_METAL_INVALID&&!window);
 assert(vx_window_create(0,960,544,0,1,0,&window)==VX_METAL_INVALID&&!window);
 assert(vx_window_input_state(0,0)==VX_METAL_INVALID);
 assert(!vx_display_input_state(&input));assert(!input.buttons&&input.lx==128&&input.ly==128&&input.rx==128&&input.ry==128);
 vx_display_window_stats(&stats);assert(!stats.frames_presented&&!stats.closed);
 assert(vx_window_present(0,0)==VX_METAL_INVALID);
 assert(vx_window_set_fullscreen(0,1)==VX_METAL_INVALID);
 assert(vx_display_configure_window(0,0,1,0)==-1);
 char title[257];memset(title,'x',256);title[256]=0;assert(vx_display_configure_window(title,0,1,0)==-1);
 assert(vx_display_configure_window("bounds",0,2,0)==-1);
 assert(vx_metal_set_filter(0,0)==VX_METAL_INVALID);
 vx_window_destroy(0);vx_display_shutdown();return 0;
}''')
        subprocess.run(self.command+[str(source),'-o',str(binary)],check=True,capture_output=True)
        subprocess.run([str(binary)],check=True,capture_output=True,timeout=5)

    @unittest.skipUnless(os.environ.get('VX_TEST_WINDOWS')=='1','GUI validation requires VX_TEST_WINDOWS=1 and desktop access')
    def test_window_pixels_keyboard_and_fullscreen(self):
        binary=self.path/'window-probe'
        subprocess.run(self.command+[str(ROOT/'runtime/window_probe.m'),'-o',str(binary)],check=True,capture_output=True)
        # Exercise the same Launch Services path as the interactive launcher.
        # macOS can deny foreground activation to a bare Terminal child.
        from vitaxnative.packaging import package_native
        app=package_native(binary,self.path,'Window Probe','org.vitaxnative.windowprobe')
        subprocess.run(['/usr/bin/codesign','--force','--sign','-',str(app)],check=True,capture_output=True)
        for fullscreen in ('0','1'):
            stdout=self.path/('stdout-'+fullscreen);stderr=self.path/('stderr-'+fullscreen)
            result=subprocess.run(['/usr/bin/open','-W','-n',str(app),'--stdout',str(stdout),'--stderr',str(stderr),'--args',fullscreen],capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('"pixel_readback":true',stdout.read_text(),stderr.read_text())
