/* Original variadic ABI regression; generated ARM code calls the actual bridge. */
static char buffer[64];
int _start(void){
 const char *expected="key:7FFF8000:1234605616436508552:abc";
 int n=((int(*)(char*,unsigned,const char*,...))0x2000)(buffer,sizeof buffer,
          "%s:%08X:%lld:%.*s","key",0x7fff8000,0x1122334455667788LL,3,"abcdef");
 for(int i=0;expected[i];i++)if(buffer[i]!=expected[i])return 111;
 return n;
}
