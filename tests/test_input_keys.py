"""Physical keyboard state aggregation, without Cocoa windows or GPU access."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
@unittest.skipUnless(shutil.which('clang'),'Clang required')
class InputKeyTests(unittest.TestCase):
    def test_shared_bindings_independent_shifts_and_release(self):
        source=r'''
#include "vita_input.h"
#include <assert.h>
int main(void){vx_input_keys s={0};
 vx_input_key_set(&s,8,1);vx_input_key_set(&s,56,1);
 vx_input_key_set(&s,8,0);assert(vx_input_key_buttons(&s)==0x100);
 vx_input_key_set(&s,60,1);assert(vx_input_key_buttons(&s)==0x300);
 vx_input_key_set(&s,56,0);assert(vx_input_key_buttons(&s)==0x200);
 vx_input_key_set(&s,9,1);vx_input_key_set(&s,60,0);assert(vx_input_key_buttons(&s)==0x200);
 vx_input_key_set(&s,9,0);assert(!vx_input_key_buttons(&s));
 vx_input_key_set(&s,6,1);vx_input_key_set(&s,6,1);assert(vx_input_key_buttons(&s)==0x4000);
 vx_input_key_set(&s,6,0);assert(!vx_input_key_buttons(&s));
 vx_input_key_set(&s,0,1);vx_input_key_set(&s,2,1);assert(vx_input_key_axes(&s)==3);
 vx_input_key_set(&s,0,0);assert(vx_input_key_axes(&s)==2);
 vx_input_key_set(&s,65535,1);assert(vx_input_key_axes(&s)==2);
 s=(vx_input_keys){0};assert(!vx_input_key_axes(&s)&&!vx_input_key_buttons(&s));
 return 0;}
'''
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);(d/'probe.c').write_text(source)
            subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-I',str(ROOT/'runtime'),str(d/'probe.c'),'-o',str(d/'probe')],check=True,capture_output=True)
            subprocess.run([str(d/'probe')],check=True,capture_output=True,timeout=5)
