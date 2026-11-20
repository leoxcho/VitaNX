"""Compile and execute real native C tests of the limited Vita NID bridge."""
import os
import pathlib
import platform
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

@unittest.skipUnless(platform.system() == 'Darwin' and shutil.which('clang'), 'requires macOS Clang')
class RuntimeTests(unittest.TestCase):
    def test_native_services(self):
        source = r'''
#include "vita_runtime.h"
#include <assert.h>
#include <string.h>
#include <stdio.h>
int main(int argc,char **argv){
 uint8_t m[1024]={0};uint32_t r[16]={0};r[3]=512;
 assert(vx_runtime_mount(argv[1])==0);
 vx_import(0xF4EE4FA9,r,m,sizeof m);uint64_t before=((uint64_t)r[1]<<32)|r[0];
 r[0]=1000;assert(vx_import(0x4B675D05,r,m,sizeof m)==0);
 vx_import(0xF4EE4FA9,r,m,sizeof m);assert((((uint64_t)r[1]<<32)|r[0])>=before+1000);
 strcpy((char*)m+32,"savedata0:/roundtrip.bin");r[0]=32;r[1]=0x602;
 r[3]=0;assert(vx_import(0xCC67B6FD,r,m,sizeof m)==0x80010016);
 r[0]=32;r[3]=1020;assert(vx_import(0xCC67B6FD,r,m,sizeof m)==0x80010016);
 r[0]=32;r[3]=0xffffffff;assert(vx_import(0xCC67B6FD,r,m,sizeof m)==0x80010016);
 r[0]=32;r[3]=512;memset(m+512,0xff,8); /* Reserved words are ignored. */
 uint32_t fd=vx_import(0xCC67B6FD,r,m,sizeof m);assert(fd>=3&&fd<35);
 memcpy(m+128,"vita-save",9);r[0]=fd;r[1]=128;r[2]=9;assert(vx_import(0x34EFD876,r,m,sizeof m)==9);
 r[0]=fd;r[1]=0;assert(vx_import(0x16512F59,r,m,sizeof m)==0);
 r[0]=fd;r[1]=1;assert(vx_import(0x16512F59,r,m,sizeof m)==0x80010016);
 r[0]=fd;assert(vx_import(0xC70B8886,r,m,sizeof m)==0);
 r[0]=32;r[1]=1;fd=vx_import(0xCC67B6FD,r,m,sizeof m);assert(fd>=3&&fd<35);
 r[0]=fd;r[1]=256;r[2]=9;assert(vx_import(0xFDB32293,r,m,sizeof m)==9);assert(!memcmp(m+128,m+256,9));
 r[0]=fd;r[1]=(uint32_t)-4;r[2]=2;assert(vx_import(0x49252B9B,r,m,sizeof m)==5);
 r[0]=fd;r[1]=300;r[2]=4;assert(vx_import(0xFDB32293,r,m,sizeof m)==4);assert(!memcmp(m+300,"save",4));
 r[0]=fd;r[1]=0;r[2]=1;assert(vx_import(0x49252B9B,r,m,sizeof m)==9);
 r[0]=fd;r[1]=(uint32_t)-10;r[2]=2;assert(vx_import(0x49252B9B,r,m,sizeof m)==0x80010016);
 r[0]=fd;r[1]=0;r[2]=1;assert(vx_import(0x49252B9B,r,m,sizeof m)==9);
 r[0]=fd;r[1]=0;r[2]=3;assert(vx_import(0x49252B9B,r,m,sizeof m)==0x80010016);
 r[0]=fd;r[1]=0x7fffffff;r[2]=1;assert(vx_import(0x49252B9B,r,m,sizeof m)==0x80010016);
 r[0]=fd;r[1]=1020;r[2]=9;assert(vx_import(0xFDB32293,r,m,sizeof m)==0x80010016);
 r[0]=fd;assert(vx_import(0xC70B8886,r,m,sizeof m)==0);
 strcpy((char*)m+32,"savedata0:/../outside");r[0]=32;r[1]=0x602;assert((int32_t)vx_import(0xCC67B6FD,r,m,sizeof m)<0);
 strcpy((char*)m+32,"savedata0:/link");r[0]=32;r[1]=0x602;assert((int32_t)vx_import(0xCC67B6FD,r,m,sizeof m)<0);
 strcpy((char*)m+32,"savedata0:/fifo");r[0]=32;r[1]=1;assert((int32_t)vx_import(0xCC67B6FD,r,m,sizeof m)<0);
 strcpy((char*)m+32,"savedata0:/directory");r[0]=32;r[1]=1;assert((int32_t)vx_import(0xCC67B6FD,r,m,sizeof m)<0);
 r[0]=1;r[1]=128;r[2]=9;assert(vx_import(0x34EFD876,r,m,sizeof m)==9);
 assert(vx_import(0xdeadbeef,r,m,sizeof m)==0x80010030);
 strcpy((char*)m+32,"savedata0:/roundtrip.bin");uint32_t fds[32];
 for(int i=0;i<32;i++){r[0]=32;r[1]=1;fds[i]=vx_import(0xCC67B6FD,r,m,sizeof m);assert(fds[i]>=3&&fds[i]<35);}
 r[0]=32;r[1]=1;assert(vx_import(0xCC67B6FD,r,m,sizeof m)==0x80010018);
 r[0]=fds[0];assert(vx_import(0xC70B8886,r,m,sizeof m)==0);
 r[0]=fds[0];r[1]=0;r[2]=0;assert(vx_import(0x49252B9B,r,m,sizeof m)==0x80010009);
 r[0]=fds[0];r[1]=0;assert(vx_import(0x16512F59,r,m,sizeof m)==0x80010009);
 vx_runtime_shutdown();assert(vx_runtime_mount(argv[1])==0);vx_runtime_shutdown();return 0;
}'''
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d)
            (p/'probe.c').write_text(source)
            (p/'link').symlink_to(p/'outside')
            os.mkfifo(p/'fifo')
            (p/'directory').mkdir()
            subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-I',str(ROOT/'runtime'),str(p/'probe.c'),str(ROOT/'runtime/vita_runtime.c'),'-o',str(p/'probe')],check=True,capture_output=True)
            result = subprocess.run([str(p/'probe'),str(p)],check=True,capture_output=True,timeout=5)
            self.assertEqual(result.stdout,b'vita-save')
            self.assertEqual((p/'roundtrip.bin').read_bytes(),b'vita-save')
            self.assertFalse((p/'outside').exists())

    def test_delay_failure_and_interruption(self):
        source = r'''
#include "vita_runtime.h"
#include <assert.h>
#include <errno.h>
#include <time.h>
static int calls;
int vx_test_nanosleep(const struct timespec *req, struct timespec *rem){
 (void)req;calls++;if(calls==1){errno=EIO;return -1;}
 if(calls==2){*rem=*req;errno=EINTR;return -1;}return 0;
}
int main(void){uint32_t r[16]={1000};uint8_t m[1]={0};
 assert(vx_import(0x4B675D05,r,m,sizeof m)==0x80010005);assert(calls==1);
 r[0]=1000;assert(vx_import(0x4B675D05,r,m,sizeof m)==0);assert(calls==3);
 r[0]=1000001;assert(vx_import(0x4B675D05,r,m,sizeof m)==0x80010016);assert(calls==3);
 return 0;}
'''
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d)
            (p/'probe.c').write_text(source)
            subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror',
                '-Dnanosleep=vx_test_nanosleep','-I',str(ROOT/'runtime'),
                str(p/'probe.c'),str(ROOT/'runtime/vita_runtime.c'),'-o',str(p/'probe')],check=True,capture_output=True)
            subprocess.run([str(p/'probe')],check=True,capture_output=True,timeout=5)

    def test_read_only_app_assets(self):
        source = r'''
#include "vita_runtime.h"
#include <assert.h>
#include <string.h>
static uint32_t open_guest(const char *path,uint32_t flags,uint32_t *r,uint8_t *m){
 strcpy((char*)m+32,path);r[0]=32;r[1]=flags;r[2]=0600;r[3]=512;
 return vx_import(0xCC67B6FD,r,m,1024);
}
int main(int argc,char **argv){
 (void)argc;uint8_t m[1024]={0};uint32_t r[16]={0};
 assert(vx_runtime_mount_app(argv[1])==0);
 assert(vx_runtime_mount_app(argv[1])<0);
 uint32_t fd=open_guest("app0:/assets/nested/hello.txt",1,r,m);assert(fd>=3&&fd<35);
 r[0]=fd;r[1]=256;r[2]=6;assert(vx_import(0xFDB32293,r,m,sizeof m)==6);assert(!memcmp(m+256,"asset!",6));
 r[0]=fd;r[1]=256;r[2]=6;assert(vx_import(0x34EFD876,r,m,sizeof m)==0x80010009);
 r[0]=fd;assert(vx_import(0xC70B8886,r,m,sizeof m)==0);
 const char *bad[]={"app0:/../outside.txt","app0:/assets/../../outside.txt",
   "app0:/assets//nested/hello.txt","app0://assets/nested/hello.txt",
   "app0:/assets/./nested/hello.txt","app0:/assets/nested/",
   "app0:/assets/nested","app0:/linked-dir/outside.txt","app0:/linked-file",
   "app0:/assets\\nested\\hello.txt","app0:/","app0:../outside.txt"};
 for(unsigned i=0;i<sizeof bad/sizeof *bad;i++)assert((int32_t)open_guest(bad[i],1,r,m)<0);
 const uint32_t write_flags[]={2,3,0x201,0x401,0x101,0x602};
 for(unsigned i=0;i<sizeof write_flags/sizeof *write_flags;i++)
  assert(open_guest("app0:/assets/nested/hello.txt",write_flags[i],r,m)==0x8001001e);
 assert((int32_t)open_guest("app0:/new.bin",0x602,r,m)<0);
 assert(vx_runtime_mount(argv[2])==0);assert(vx_runtime_mount(argv[2])<0);
 fd=open_guest("savedata0:/save.bin",0x602,r,m);assert(fd>=3&&fd<35);
 uint32_t asset=open_guest("app0:assets/nested/hello.txt",1,r,m);assert(asset>=3&&asset<35&&asset!=fd);
 vx_runtime_shutdown();r[0]=asset;r[1]=256;r[2]=6;
 assert(vx_import(0xFDB32293,r,m,sizeof m)==0x80010009);
 assert((int32_t)open_guest("app0:assets/nested/hello.txt",1,r,m)<0);
 assert(vx_runtime_mount_app(argv[1])==0);
 asset=open_guest("app0:assets/nested/hello.txt",1,r,m);assert(asset==3);
 vx_runtime_shutdown();return 0;
}'''
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d)
            app, save, outside = p/'app', p/'save', p/'outside'
            (app/'assets/nested').mkdir(parents=True)
            save.mkdir(); outside.mkdir()
            (outside/'outside.txt').write_text('outside')
            (app/'assets/nested/hello.txt').write_bytes(b'asset!')
            (app/'linked-dir').symlink_to(outside, target_is_directory=True)
            (app/'linked-file').symlink_to(outside/'outside.txt')
            (p/'probe.c').write_text(source)
            subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror',
                '-I',str(ROOT/'runtime'),str(p/'probe.c'),str(ROOT/'runtime/vita_runtime.c'),
                '-o',str(p/'probe')],check=True,capture_output=True)
            subprocess.run([str(p/'probe'),str(app),str(save)],check=True,capture_output=True,timeout=5)
            self.assertEqual((app/'assets/nested/hello.txt').read_bytes(), b'asset!')
            self.assertEqual((outside/'outside.txt').read_text(), 'outside')
            self.assertFalse((app/'new.bin').exists())
            self.assertTrue((save/'save.bin').is_file())

    def test_process_and_single_guest_thread_termination(self):
        source = r'''
#include "vita_runtime.h"
#include <assert.h>
#include <pthread.h>
#include <string.h>
static void *worker(void *unused){
 (void)unused;uint32_t status=123,r[16]={7};uint8_t mem[1]={0};
 assert(vx_runtime_stop_requested(&status)==VX_STOP_NONE);assert(status==123);
 assert(vx_import(0x1D17DECF,r,mem,sizeof mem)==7);
 assert(vx_runtime_stop_requested(&status)==VX_STOP_THREAD&&status==7);
 vx_runtime_shutdown();assert(vx_runtime_stop_requested(0)==VX_STOP_NONE);
 return 0;
}
int main(int argc,char **argv){
 (void)argc;uint8_t mem[1024]={0};uint32_t r[16]={0},status=999;
 assert(vx_runtime_stop_requested(&status)==VX_STOP_NONE);assert(status==999);
 assert(vx_runtime_mount(argv[1])==0);
 assert(vx_import(0xE5AA625C,r,mem,sizeof mem)==1);
 assert(vx_import(0xFA5E3ADA,r,mem,sizeof mem)==2);
 strcpy((char*)mem+32,"savedata0:/public-open.bin");
 r[0]=32;r[1]=0x602;r[2]=0600;r[3]=0xffffffff;
 uint32_t fd=vx_import(0x6C60AC61,r,mem,sizeof mem);assert(fd>=3&&fd<35);
 r[0]=fd;assert(vx_import(0xC70B8886,r,mem,sizeof mem)==0);
 /* Raw syscall still requires its option block, unlike public sceIoOpen. */
 r[0]=32;r[1]=1;assert(vx_import(0xCC67B6FD,r,mem,sizeof mem)==0x80010016);
 const uint32_t exits[]={0x7595D9AA,0xC053DC6B,0x1D17DECF,0x0C8A38E1};
 for(unsigned i=0;i<4;i++){
  vx_runtime_reset_stop();uint32_t value=i?0x80000000u+i:42;
  r[0]=value;assert(vx_import(exits[i],r,mem,sizeof mem)==value);
  assert(vx_runtime_stop_requested(&status)==(i<2?VX_STOP_PROCESS:VX_STOP_THREAD));
  assert(status==value);
  /* Later import attempts cannot modify stop status or create a file. */
  strcpy((char*)mem+32,"savedata0:/after-exit.bin");
  r[0]=32;r[1]=0x602;assert(vx_import(0x6C60AC61,r,mem,sizeof mem)==value);
  assert(vx_runtime_stop_requested(&status)!=VX_STOP_NONE&&status==value);
 }
 vx_runtime_reset_stop();r[0]=42;vx_import(0x7595D9AA,r,mem,sizeof mem);
 pthread_t thread;assert(pthread_create(&thread,0,worker,0)==0);assert(pthread_join(thread,0)==0);
 assert(vx_runtime_stop_requested(&status)==VX_STOP_PROCESS&&status==42);
 vx_runtime_shutdown();assert(vx_runtime_stop_requested(0)==VX_STOP_NONE);
 assert(vx_runtime_mount(argv[1])==0);r[0]=0;
 assert(vx_import(0x7595D9AA,r,mem,sizeof mem)==0);
 assert(vx_runtime_stop_requested(&status)==VX_STOP_PROCESS&&status==0);
 vx_runtime_shutdown();return 0;
}'''
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)
            (p/'probe.c').write_text(source)
            subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror',
                '-I',str(ROOT/'runtime'),str(p/'probe.c'),str(ROOT/'runtime/vita_runtime.c'),
                '-o',str(p/'probe')],check=True,capture_output=True)
            subprocess.run([str(p/'probe'),str(p)],check=True,capture_output=True,timeout=5)
            self.assertTrue((p/'public-open.bin').is_file())
            self.assertFalse((p/'after-exit.bin').exists())

    def test_high_guest_virtual_base_io_roundtrip(self):
        source = r'''
#include "vita_runtime.h"
#include <assert.h>
#include <string.h>
int main(int argc,char **argv){
 (void)argc;const uint32_t base=0x81000000u;uint32_t r[16]={0};uint8_t m[1024]={0};
 vx_runtime_set_memory_base(base);assert(vx_runtime_get_memory_base()==base);
 assert(vx_runtime_mount(argv[1])==0);assert(vx_runtime_mount_app(argv[2])==0);
 strcpy((char*)m+32,"savedata0:/high-base.bin");
 r[0]=base+32;r[1]=0x602;r[2]=0600;r[3]=base+512;
 uint32_t fd=vx_import(0xCC67B6FD,r,m,sizeof m);assert(fd>=3&&fd<35);
 memcpy(m+128,"high-base",9);r[0]=fd;r[1]=base+128;r[2]=9;
 assert(vx_import(0x34EFD876,r,m,sizeof m)==9);
 r[0]=fd;r[1]=base-1;r[2]=1;assert(vx_import(0x34EFD876,r,m,sizeof m)==0x80010016);
 r[0]=fd;r[1]=0;r[2]=1;assert(vx_import(0x34EFD876,r,m,sizeof m)==0x80010016);
 r[0]=fd;assert(vx_import(0xC70B8886,r,m,sizeof m)==0);
 r[0]=base+32;r[1]=1;r[3]=base-1;assert(vx_import(0xCC67B6FD,r,m,sizeof m)==0x80010016);
 r[0]=base-1;r[1]=1;assert(vx_import(0x6C60AC61,r,m,sizeof m)==0x80010016);
 r[0]=base+32;r[1]=1;fd=vx_import(0x6C60AC61,r,m,sizeof m);assert(fd>=3&&fd<35);
 r[0]=fd;r[1]=base+256;r[2]=9;assert(vx_import(0xFDB32293,r,m,sizeof m)==9);
 assert(!memcmp(m+128,m+256,9));
 r[0]=fd;r[1]=0xffffffffu;r[2]=9;assert(vx_import(0xFDB32293,r,m,sizeof m)==0x80010016);
 r[0]=fd;assert(vx_import(0xC70B8886,r,m,sizeof m)==0);
 strcpy((char*)m+32,"app0:/nested/asset.bin");r[0]=base+32;r[1]=1;
 fd=vx_import(0x6C60AC61,r,m,sizeof m);assert(fd>=3&&fd<35);
 r[0]=fd;r[1]=base+400;r[2]=5;assert(vx_import(0xFDB32293,r,m,sizeof m)==5);
 assert(!memcmp(m+400,"asset",5));
 r[0]=base+600;assert(vx_import(0x4C4672BF,r,m,sizeof m)==0);
 r[0]=base-8;assert(vx_import(0x4C4672BF,r,m,sizeof m)==0x80010016);
 vx_runtime_shutdown();assert(vx_runtime_get_memory_base()==0);return 0;
}'''
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d);save=p/'save';save.mkdir();app=p/'app';(app/'nested').mkdir(parents=True)
            (app/'nested/asset.bin').write_bytes(b'asset')
            (p/'probe.c').write_text(source)
            subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror',
                '-I',str(ROOT/'runtime'),str(p/'probe.c'),str(ROOT/'runtime/vita_runtime.c'),
                '-o',str(p/'probe')],check=True,capture_output=True)
            subprocess.run([str(p/'probe'),str(save),str(app)],check=True,capture_output=True,timeout=5)
            self.assertEqual((save/'high-base.bin').read_bytes(),b'high-base')

    def test_process_clock_64_bit_abi_and_reset(self):
        source = r'''
#include "vita_runtime.h"
#include <assert.h>
#include <errno.h>
#include <time.h>
static uint64_t clock_ns=UINT64_C(5000000000000);
static int failed;
int vx_test_clock_gettime(clockid_t which,struct timespec *t){
 (void)which;if(failed){errno=EIO;return -1;}
 t->tv_sec=(time_t)(clock_ns/1000000000);t->tv_nsec=(long)(clock_ns%1000000000);return 0;
}
static uint64_t read64(const uint8_t *p){uint64_t n=0;for(int i=0;i<8;i++)n|=(uint64_t)p[i]<<(i*8);return n;}
int main(void){
 uint32_t r[16]={0};uint8_t m[128]={0};
 assert(vx_import(0xB110C123,r,m,sizeof m)==0&&r[1]==0);
 clock_ns+=UINT64_C(0x100000002)*1000;
 assert(vx_import(0xB110C123,r,m,sizeof m)==2&&r[1]==1);
 r[1]=77;assert(vx_import(0xE9F973B1,r,m,sizeof m)==2&&r[1]==77);
 r[0]=32;assert(vx_import(0x4C4672BF,r,m,sizeof m)==0);
 assert(read64(m+32)==UINT64_C(0x100000002));
 r[0]=121;assert(vx_import(0xD37A8437,r,m,sizeof m)==0x80010016);
 r[0]=0;assert(vx_import(0x4C4672BF,r,m,sizeof m)==0x80010016);
 assert(vx_import(0x89DA0967,r,m,sizeof m)==2&&r[1]==1);
 assert(vx_import(0xF5D0D4C6,r,m,sizeof m)==2);
 r[0]=48;assert(vx_import(0xD37A8437,r,m,sizeof m)==0&&read64(m+48)==UINT64_C(0x100000002));
 failed=1;assert(vx_import(0xB110C123,r,m,sizeof m)==0x80010005&&r[1]==0xffffffffu);
 failed=0;vx_runtime_shutdown();
 assert(vx_import(0xB110C123,r,m,sizeof m)==0&&r[1]==0);
 vx_runtime_shutdown();return 0;
}'''
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d);(p/'probe.c').write_text(source)
            subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror',
                '-D_POSIX_C_SOURCE=200809L','-Dclock_gettime=vx_test_clock_gettime',
                '-I',str(ROOT/'runtime'),str(p/'probe.c'),str(ROOT/'runtime/vita_runtime.c'),
                '-o',str(p/'probe')],check=True,capture_output=True)
            subprocess.run([str(p/'probe')],check=True,capture_output=True,timeout=5)
