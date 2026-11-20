/* Original cold-thread entry regression. No platform headers or game code. */
typedef unsigned u32;
static volatile u32 marker;
__attribute__((noinline)) static int worker(u32 size,void *args){
 (void)size;(void)args;marker=0x12345678;return 42;
}
int _start(void){
 int id=((int(*)(const char*,void*,int,u32,u32,u32,void*))0x2000)("cold",worker,384,4096,0,0,0);
 if(id<0)return 111;
 if(((int(*)(int,u32,void*))0x2004)(id,0,0))return 112;
 int status=0;
 if(((int(*)(int,int*,void*))0x2008)(id,&status,0))return 113;
 return marker==0x12345678?status:114;
}
