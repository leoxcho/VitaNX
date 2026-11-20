/* Original ARMv7 homebrew reads packaged app0 resource through Vita I/O ABI. */
typedef unsigned int u32;
#define IMPORT(address, result, args) ((result (*) args)(address))
#define io_open IMPORT(0x2000, int, (const char*,u32,u32,const void*))
#define io_read IMPORT(0x2008, int, (int,void*,u32))
#define io_close IMPORT(0x200c, int, (int))
static const u32 options[2]={0,0};
static u32 value;
int _start(void) {
 int fd=io_open("app0:/data/payload.bin",1,0,options);
 if(fd<0)return 1;
 if(io_read(fd,&value,4)!=4)return 2;
 if(io_close(fd)!=0)return 3;
 return value==0x41544956 ? 0 : 4;
}
