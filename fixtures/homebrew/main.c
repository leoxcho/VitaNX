/* Original freestanding ARMv7 source. Explicit import, no VitaSDK claim. */
typedef unsigned int u32;
static const char message[] = "C-compiled ARMv7 homebrew running as native ARM64!\n";
__attribute__((noinline)) static u32 write_message(void) {
    typedef int (*write_fn)(int,const void*,u32);
    return ((write_fn)0x2000)(1,message,sizeof(message)-1);
}
u32 _start(void) { return write_message() == sizeof(message)-1 ? 0 : 1; }
