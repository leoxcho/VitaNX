/* Original Thumb C fixture; explicit import address, not VitaSDK linked. */
typedef unsigned int u32;
static const char text[]="Thumb C native ABI test\n";
__attribute__((noinline)) static int helper(void){
 return ((int (*)(int,const void*,u32))0x2348)(1,text,sizeof(text)-1);
}
int _start(void){return helper()+1;}
