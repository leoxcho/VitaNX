/* Compile with vita_metal.m, -fobjc-arc -framework Foundation -framework Metal.
   Validates host triangles at configurable resolution, not Vita GXM rendering. */
#include "vita_metal.h"
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
static int dimension(const char *text,uint32_t *out){
 char *end;errno=0;unsigned long v=strtoul(text,&end,10);
 if(errno||!*text||*end||v<1||v>4096)return -1;*out=(uint32_t)v;return 0;
}
int main(int argc,char **argv){
 uint32_t width=64,height=64;
 if(argc!=1&&argc!=2&&argc!=3&&argc!=4)return 10;
 if(argc>=3&&(dimension(argv[1],&width)||dimension(argv[2],&height)))return 10;
 vx_metal *ctx=NULL;int status=vx_metal_create(width,height,&ctx);
 if(status){fprintf(stderr,"Metal create failed: %d\n",status);return status==77?77:1;}
 vx_metal_vertex vertices[3]={{-.7f,-.7f,1,0,0,1},{.7f,-.7f,1,0,0,1},{0,.7f,1,0,0,1}};
 float clear[4]={0,0,1,1};size_t bytes=(size_t)width*height*4;
 uint8_t *pixels=malloc(bytes);if(!pixels){vx_metal_destroy(ctx);return 2;}
 status=vx_metal_draw(ctx,vertices,3,clear);
 if(!status)status=vx_metal_readback(ctx,pixels,bytes);
 size_t center=((height/2)*(size_t)width+width/2)*4;
 if(!status&&(pixels[center]!=255||pixels[center+1]!=0||pixels[center+2]!=0||pixels[2]!=255||pixels[0]!=0))status=3;
 const char *output=argc==2?argv[1]:(argc==4?argv[3]:NULL);
 if(!status&&output){FILE *f=fopen(output,"wx");if(!f)status=4;else {
  if(fprintf(f,"P6\n%u %u\n255\n",width,height)<0)status=4;
  for(size_t i=0;i<(size_t)width*height&&!status;i++)if(fwrite(pixels+i*4,1,3,f)!=3)status=4;
  if(fclose(f))status=4;
 }}
 free(pixels);vx_metal_destroy(ctx);
 if(status){fprintf(stderr,"Metal draw/readback failed: %d\n",status);return 5;}
 printf("Metal triangle verified: %ux%u RGBA8, red center, blue corner\n",width,height);return 0;
}
