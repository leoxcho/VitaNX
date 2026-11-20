"""Native rational scheduling tests; software timer evidence is not display VSync."""
import json
import platform
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(shutil.which('clang'),'Clang required')
class FramePacingTests(unittest.TestCase):
    def run_native(self,source):
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);(tmp/'probe.c').write_text(source)
            subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror',
                            '-I',str(ROOT/'runtime'),str(tmp/'probe.c'),
                            str(ROOT/'runtime/vita_frame.c'),'-o',str(tmp/'probe')],
                           check=True,capture_output=True)
            return subprocess.run([str(tmp/'probe')],check=True,capture_output=True,timeout=5)

    def test_rates_keep_simulation_time_and_rational_deadlines(self):
        self.run_native(r'''
#include "vita_frame.h"
#include <assert.h>
#include <stdint.h>
int main(void){
 uint32_t rates[]={30,60,120};
 for(unsigned r=0;r<3;r++){
  vx_frame_clock c;vx_frame_sample s;uint64_t deadline;
  assert(!vx_frame_init(&c,rates[r],60,700));
  assert(!vx_frame_next_deadline(&c,&deadline)&&deadline==700);
  assert(!vx_frame_advance(&c,700,&s));assert(s.render_due&&s.render_index==0&&s.simulation_steps==0);
  assert(!vx_frame_advance(&c,700,&s));assert(!s.render_due&&s.simulation_steps==0);
  uint64_t total_ticks=0;
  /* Irregular observations preserve every fixed simulation step. */
  uint64_t elapsed[]={1,16666666,16666667,33333334,101234567,500000000,1000000000};
  for(unsigned i=0;i<sizeof(elapsed)/sizeof(elapsed[0]);i++){
   assert(!vx_frame_advance(&c,700+elapsed[i],&s));total_ticks+=s.simulation_steps;
  }
  assert(total_ticks==60);assert(c.render_count==rates[r]+1);assert(s.render_index==rates[r]);
  assert(!vx_frame_next_deadline(&c,&deadline));
  assert(deadline==700+1000000000+((1000000000u+rates[r]-1)/rates[r]));
  /* 24 hours: sixty simulation ticks/second, independent of render rate. */
  assert(!vx_frame_advance(&c,700+UINT64_C(86400000000000),&s));
  assert(c.simulation_count==UINT64_C(5184000));
  assert(c.render_count==(uint64_t)rates[r]*86400+1);
 }
 return 0;
}''')

    def test_invalid_and_late_frames_preserve_state(self):
        self.run_native(r'''
#include "vita_frame.h"
#include <assert.h>
#include <string.h>
#include <stdint.h>
int main(void){
 vx_frame_clock c,old;vx_frame_sample s;uint64_t deadline;
 assert(vx_frame_init(0,60,60,0)==VX_FRAME_INVALID);
 assert(vx_frame_init(&c,0,60,0)==VX_FRAME_INVALID);
 assert(vx_frame_init(&c,1001,60,0)==VX_FRAME_INVALID);
 assert(vx_frame_init(&c,60,0,0)==VX_FRAME_INVALID);
 assert(!vx_frame_init(&c,120,60,100));
 assert(!vx_frame_advance(&c,100,&s));
 assert(!vx_frame_advance(&c,1000000100,&s));
 assert(s.render_due&&s.skipped_renders==119&&s.simulation_steps==60);
 old=c;
 assert(vx_frame_advance(&c,99,&s)==VX_FRAME_INVALID);
 assert(!memcmp(&c,&old,sizeof c));
 assert(vx_frame_advance(&c,c.last_ns,0)==VX_FRAME_INVALID);
 assert(!vx_frame_init(&c,60,60,UINT64_MAX));old=c;
 assert(vx_frame_advance(&c,UINT64_MAX,&s)==VX_FRAME_OVERFLOW);
 assert(!memcmp(&c,&old,sizeof c));
 assert(vx_frame_next_deadline(0,&deadline)==VX_FRAME_INVALID);
 assert(vx_frame_now(0)==VX_FRAME_INVALID);
 assert(vx_frame_wait(0,&s)==VX_FRAME_INVALID);
 return 0;
}''')

    def test_measured_monotonic_software_pacing(self):
        result=self.run_native(r'''
#include "vita_frame.h"
#include <assert.h>
#include <inttypes.h>
#include <stdio.h>
int main(void){
 uint32_t rates[]={30,60,120};printf("[");
 for(unsigned i=0;i<3;i++){
  uint64_t start,end;vx_frame_clock c;vx_frame_sample s;
  assert(!vx_frame_now(&start));assert(!vx_frame_init(&c,rates[i],60,start));
  for(int frame=0;frame<5;frame++){
   assert(!vx_frame_wait(&c,&s));assert(s.render_due);
  }
  assert(!vx_frame_now(&end));assert(end>=start);
  assert(end-start>=UINT64_C(1000000000)*4/rates[i]);
  assert(end-start<UINT64_C(2000000000));
  printf("%s{\"render_hz\":%u,\"frames_observed\":5,\"elapsed_ns\":%" PRIu64 ",\"simulation_ticks\":%" PRIu64 "}",i?",":"",rates[i],end-start,c.simulation_count);
 }
 printf("]\n");return 0;
}''')
        measured=json.loads(result.stdout)
        self.assertEqual([r['render_hz'] for r in measured],[30,60,120])
        print('Measured software pacing (not VSync): '+result.stdout.decode().strip())
