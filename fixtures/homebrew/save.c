/* Original freestanding ARMv7 homebrew: save, sync, reopen, read, compare. */
typedef unsigned int u32;
#define IMPORT(address, result, args) ((result (*) args)(address))
#define io_open IMPORT(0x2000, int, (const char*,u32,u32,const void*))
#define io_write IMPORT(0x2004, int, (int,const void*,u32))
#define io_read IMPORT(0x2008, int, (int,void*,u32))
#define io_close IMPORT(0x200c, int, (int))
#define io_sync IMPORT(0x2010, int, (int,u32))
static const u32 options[2]={0,0};
static const char path[]="savedata0:/homebrew-save.bin";
static const u32 payload=0x41544956;
static u32 readback;
int _start(void) {
 int fd=io_open(path,0x602,0600,options);
 if(fd<0)return 1;
 if(io_write(fd,&payload,4)!=4)return 2;
 if(io_sync(fd,0)!=0)return 3;
 if(io_close(fd)!=0)return 4;
 fd=io_open(path,1,0,options);
 if(fd<0)return 5;
 if(io_read(fd,&readback,4)!=4)return 6;
 if(io_close(fd)!=0)return 7;
 return readback==payload ? 0 : 8;
}
