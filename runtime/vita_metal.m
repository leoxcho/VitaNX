#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#ifdef VX_ENABLE_WINDOW
#import <QuartzCore/CAMetalLayer.h>
#endif
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include "vita_metal.h"

@interface VXMetalContext : NSObject
@property(nonatomic,strong) id<MTLDevice> device;
@property(nonatomic,strong) id<MTLCommandQueue> queue;
@property(nonatomic,strong) id<MTLTexture> target;
@property(nonatomic,strong) id<MTLRenderPipelineState> pipeline;
@property(nonatomic) unsigned gxpCull;
@property(nonatomic) BOOL gxpWireframe;
@property(nonatomic) BOOL gxpScissorConfigured;
@property(nonatomic) NSUInteger gxpScissorCount;
@property(nonatomic) MTLScissorRect gxpScissor0;
@property(nonatomic) MTLScissorRect gxpScissor1;
@property(nonatomic) MTLScissorRect gxpScissor2;
@property(nonatomic) MTLScissorRect gxpScissor3;
@property(nonatomic,strong) id<MTLRenderPipelineState> gxpPipeline;
@property(nonatomic,strong) id<MTLTexture> depth;
@property(nonatomic,strong) id<MTLDepthStencilState> depthState;
@property(nonatomic) BOOL depthEnabled;
@property(nonatomic) BOOL depthValid;
@property(nonatomic) double depthClear;
@property(nonatomic,strong) id<MTLTexture> stencil;
@property(nonatomic,strong) MTLStencilDescriptor *stencilDescriptor;
@property(nonatomic,strong) MTLStencilDescriptor *backStencilDescriptor;
@property(nonatomic) uint32_t backStencilReference;
@property(nonatomic) BOOL stencilEnabled;
@property(nonatomic) BOOL stencilValid;
@property(nonatomic) uint32_t stencilClear;
@property(nonatomic) uint32_t stencilReference;
@property(nonatomic) unsigned depthCompare;
@property(nonatomic) BOOL depthWrite;
@property(nonatomic) size_t gxpStride;
@property(nonatomic) size_t gxpVWords;
@property(nonatomic) size_t gxpFWords;
@property(nonatomic) uint32_t gxpTextureMask;
@property(nonatomic,strong) NSMutableDictionary<NSNumber *,id<MTLTexture>> *gxpTextures;
@property(nonatomic,strong) NSMutableDictionary<NSNumber *,id<MTLSamplerState>> *gxpSamplers;
@property(nonatomic,strong) id<MTLRenderPipelineState> presentation;
@property(nonatomic,strong) id<MTLRenderPipelineState> windowPresentation;
@property(nonatomic,strong) id<MTLTexture> input;
@property(nonatomic,strong) id<MTLSamplerState> sampler;
@property(nonatomic,strong) id<MTLComputePipelineState> transferFill;
@property(nonatomic,strong) id<MTLComputePipelineState> transferCopy;
@property(nonatomic) BOOL linear;
@property(nonatomic) BOOL rendered;
@end

static NSString *presentation_shader(void){
 return @"#include <metal_stdlib>\nusing namespace metal;\nstruct O{float4 p [[position]];float2 uv;};\nvertex O pv(uint i [[vertex_id]]){const float2 p[3]={float2(-1,-1),float2(3,-1),float2(-1,3)};O o;o.p=float4(p[i],0,1);o.uv=float2((p[i].x+1)*.5,1-(p[i].y+1)*.5);return o;}\nfragment float4 pf(O o [[stage_in]],texture2d<float> src [[texture(0)]],sampler s [[sampler(0)]]){return src.sample(s,o.uv);}";
}
int vx_metal_set_filter(vx_metal *context,int linear_filter){
 if(!context||(linear_filter!=0&&linear_filter!=1))return VX_METAL_INVALID;
 @autoreleasepool {VXMetalContext *ctx=(__bridge VXMetalContext *)context;
  if(ctx.sampler&&ctx.linear==linear_filter)return 0;
  MTLSamplerDescriptor *desc=[MTLSamplerDescriptor new];desc.minFilter=desc.magFilter=linear_filter?MTLSamplerMinMagFilterLinear:MTLSamplerMinMagFilterNearest;
  desc.normalizedCoordinates=YES;desc.sAddressMode=desc.tAddressMode=MTLSamplerAddressModeClampToEdge;
  id<MTLSamplerState> sampler=[ctx.device newSamplerStateWithDescriptor:desc];if(!sampler)return VX_METAL_ALLOCATION;
  ctx.sampler=sampler;ctx.linear=linear_filter;return 0;}
}
@implementation VXMetalContext
@end

int vx_framebuffer_required(uint32_t width,uint32_t height,size_t stride,
                            uint32_t format,size_t *source_bytes,size_t *rgba_bytes){
 if(!source_bytes||!rgba_bytes||!width||!height||width>4096||height>4096||format>VX_PIXELS_RGB565_LE)return VX_METAL_INVALID;
 size_t pixel_size=format==VX_PIXELS_RGB565_LE?2:4;
 if(stride<(size_t)width*pixel_size||stride>4096*4)return VX_METAL_INVALID;
 *source_bytes=(height-1)*stride+(size_t)width*pixel_size;
 *rgba_bytes=(size_t)width*height*4;return VX_METAL_OK;
}
int vx_framebuffer_convert(uint32_t width,uint32_t height,size_t stride,uint32_t format,
                           const uint8_t *source,size_t source_capacity,
                           uint8_t *rgba,size_t rgba_capacity){
 size_t needed,output;
 if(vx_framebuffer_required(width,height,stride,format,&needed,&output)||!source||!rgba||source_capacity<needed||rgba_capacity<output)return VX_METAL_INVALID;
 /* Reject overlapping host ranges: conversion never overwrites unread pixels. */
 uintptr_t from=(uintptr_t)source,to=(uintptr_t)rgba;
 if(from>UINTPTR_MAX-needed||to>UINTPTR_MAX-output||(from<to+output&&to<from+needed))return VX_METAL_INVALID;
 for(size_t y=0;y<height;y++){
  const uint8_t *row=source+y*stride;uint8_t *dest=rgba+y*width*4;
  if(format==VX_PIXELS_RGBA8){memcpy(dest,row,width*4);continue;}
  for(size_t x=0;x<width;x++){
   if(format==VX_PIXELS_BGRA8){dest[x*4]=row[x*4+2];dest[x*4+1]=row[x*4+1];dest[x*4+2]=row[x*4];dest[x*4+3]=row[x*4+3];}
   else {uint16_t value=(uint16_t)row[x*2]|(uint16_t)row[x*2+1]<<8;
    uint8_t r=(value>>11)&31,g=(value>>5)&63,b=value&31;
    dest[x*4]=(r<<3)|(r>>2);dest[x*4+1]=(g<<2)|(g>>4);dest[x*4+2]=(b<<3)|(b>>2);dest[x*4+3]=255;
   }
  }
 }
 return VX_METAL_OK;
}
static id<MTLTexture> make_target(id<MTLDevice> device,uint32_t width,uint32_t height){
 MTLTextureDescriptor *td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:width height:height mipmapped:NO];
 td.storageMode=MTLStorageModeShared;td.usage=MTLTextureUsageRenderTarget|MTLTextureUsageShaderRead;
 return [device newTextureWithDescriptor:td];
}
int vx_metal_size(vx_metal *context,uint32_t *width,uint32_t *height){
 if(!context||!width||!height)return VX_METAL_INVALID;
 @autoreleasepool {VXMetalContext *ctx=(__bridge VXMetalContext *)context;
  *width=(uint32_t)ctx.target.width;*height=(uint32_t)ctx.target.height;return VX_METAL_OK;}
}
int vx_metal_resize(vx_metal *context,uint32_t width,uint32_t height){
 if(!context||!width||!height||width>4096||height>4096)return VX_METAL_INVALID;
 @autoreleasepool {VXMetalContext *ctx=(__bridge VXMetalContext *)context;
  id<MTLTexture> target=make_target(ctx.device,width,height);if(!target)return VX_METAL_ALLOCATION;
  ctx.target=target;ctx.depth=nil;ctx.depthValid=NO;ctx.stencil=nil;ctx.stencilValid=NO;ctx.rendered=NO;return VX_METAL_OK;}
}
int vx_metal_upload(vx_metal *context,const uint8_t *source,size_t capacity,size_t stride,uint32_t format){
 if(!context||!source)return VX_METAL_INVALID;
 @autoreleasepool {VXMetalContext *ctx=(__bridge VXMetalContext *)context;
  size_t needed,output;
  if(vx_framebuffer_required((uint32_t)ctx.target.width,(uint32_t)ctx.target.height,stride,format,&needed,&output)||capacity<needed)return VX_METAL_INVALID;
  uint8_t *pixels=malloc(output);if(!pixels)return VX_METAL_ALLOCATION;
  int result=vx_framebuffer_convert((uint32_t)ctx.target.width,(uint32_t)ctx.target.height,stride,format,source,capacity,pixels,output);
  if(!result){[ctx.target replaceRegion:MTLRegionMake2D(0,0,ctx.target.width,ctx.target.height) mipmapLevel:0 withBytes:pixels bytesPerRow:ctx.target.width*4];ctx.rendered=YES;}
  free(pixels);return result;
 }
}

int vx_metal_present(vx_metal *context,const uint8_t *source,size_t capacity,
                     uint32_t source_width,uint32_t source_height,size_t stride,uint32_t format){
 size_t needed,output;
 if(!context||!source||vx_framebuffer_required(source_width,source_height,stride,format,&needed,&output)||capacity<needed)return VX_METAL_INVALID;
 @autoreleasepool {VXMetalContext *ctx=(__bridge VXMetalContext *)context;
  ctx.rendered=NO;
  if(!ctx.presentation){
   NSError *error=nil;
   NSString *shader=presentation_shader();
   id<MTLLibrary> lib=[ctx.device newLibraryWithSource:shader options:nil error:&error];if(!lib)return VX_METAL_SHADER;
   MTLRenderPipelineDescriptor *pd=[MTLRenderPipelineDescriptor new];pd.vertexFunction=[lib newFunctionWithName:@"pv"];pd.fragmentFunction=[lib newFunctionWithName:@"pf"];pd.colorAttachments[0].pixelFormat=MTLPixelFormatRGBA8Unorm;
   ctx.presentation=[ctx.device newRenderPipelineStateWithDescriptor:pd error:&error];if(!ctx.presentation)return VX_METAL_SHADER;
  }
  if(!ctx.input||ctx.input.width!=source_width||ctx.input.height!=source_height)ctx.input=make_target(ctx.device,source_width,source_height);
  id<MTLTexture> input=ctx.input;if(!input)return VX_METAL_ALLOCATION;
  if(!ctx.sampler){int filtering=vx_metal_set_filter(context,0);if(filtering)return filtering;}
  uint8_t *pixels=malloc(output);if(!pixels)return VX_METAL_ALLOCATION;
  int status=vx_framebuffer_convert(source_width,source_height,stride,format,source,capacity,pixels,output);
  if(!status)[input replaceRegion:MTLRegionMake2D(0,0,source_width,source_height) mipmapLevel:0 withBytes:pixels bytesPerRow:source_width*4];
  free(pixels);if(status)return status;
  id<MTLCommandBuffer> buffer=[ctx.queue commandBuffer];if(!buffer)return VX_METAL_COMMAND;
  MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];pass.colorAttachments[0].texture=ctx.target;pass.colorAttachments[0].loadAction=MTLLoadActionDontCare;pass.colorAttachments[0].storeAction=MTLStoreActionStore;
  id<MTLRenderCommandEncoder> encoder=[buffer renderCommandEncoderWithDescriptor:pass];if(!encoder)return VX_METAL_COMMAND;
  [encoder setRenderPipelineState:ctx.presentation];[encoder setFragmentTexture:input atIndex:0];[encoder setFragmentSamplerState:ctx.sampler atIndex:0];[encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];[encoder endEncoding];[buffer commit];[buffer waitUntilCompleted];
  if(buffer.status!=MTLCommandBufferStatusCompleted)return VX_METAL_COMMAND;
  ctx.rendered=YES;return VX_METAL_OK;
 }
}

int vx_metal_create(uint32_t width,uint32_t height,vx_metal **out) {
 if(!out)return VX_METAL_INVALID;
 *out=NULL;
 /* Bound GPU and host allocation to 64 MiB; reject before touching Metal. */
 if(!width||!height||width>4096||height>4096)return VX_METAL_INVALID;
 @autoreleasepool {
  VXMetalContext *ctx=[VXMetalContext new];
  ctx.device=MTLCreateSystemDefaultDevice();
  if(!ctx.device)return VX_METAL_UNAVAILABLE;
  NSError *error=nil;
  NSString *shader=@"#include <metal_stdlib>\nusing namespace metal;\nstruct V{float x,y,r,g,b,a;}; struct O{float4 p [[position]];float4 c;};\nvertex O vx_v(uint i [[vertex_id]],const device V *v [[buffer(0)]]){O o;o.p=float4(v[i].x,v[i].y,0,1);o.c=float4(v[i].r,v[i].g,v[i].b,v[i].a);return o;}\nfragment float4 vx_f(O o [[stage_in]]){return o.c;}";
  id<MTLLibrary> lib=[ctx.device newLibraryWithSource:shader options:nil error:&error];
  if(!lib)return VX_METAL_SHADER;
  MTLRenderPipelineDescriptor *pd=[MTLRenderPipelineDescriptor new];
  pd.vertexFunction=[lib newFunctionWithName:@"vx_v"];
  pd.fragmentFunction=[lib newFunctionWithName:@"vx_f"];
  pd.colorAttachments[0].pixelFormat=MTLPixelFormatRGBA8Unorm;
  ctx.pipeline=[ctx.device newRenderPipelineStateWithDescriptor:pd error:&error];
  if(!ctx.pipeline)return VX_METAL_SHADER;
  ctx.target=make_target(ctx.device,width,height);
  ctx.queue=[ctx.device newCommandQueue];
  if(!ctx.target||!ctx.queue)return VX_METAL_ALLOCATION;
  *out=(vx_metal *)CFBridgingRetain(ctx);
  return VX_METAL_OK;
 }
}
int vx_metal_draw(vx_metal *context,const vx_metal_vertex *vertices,size_t count,const float clear[4]) {
 if(!context||!clear||count>65535||count%3||(count&&!vertices))return VX_METAL_INVALID;
 for(size_t i=0;i<4;i++)if(!isfinite(clear[i])||clear[i]<0||clear[i]>1)return VX_METAL_INVALID;
 for(size_t i=0;i<count;i++) {
  const vx_metal_vertex *v=vertices+i;
  if(!isfinite(v->x)||!isfinite(v->y)||!isfinite(v->r)||!isfinite(v->g)||!isfinite(v->b)||!isfinite(v->a))return VX_METAL_INVALID;
 }
 @autoreleasepool {
  VXMetalContext *ctx=(__bridge VXMetalContext *)context;
  ctx.rendered=NO;
  id<MTLBuffer> verts=nil;
  if(count){verts=[ctx.device newBufferWithBytes:vertices length:count*sizeof(*vertices) options:MTLResourceStorageModeShared];if(!verts)return VX_METAL_ALLOCATION;}
  id<MTLCommandBuffer> buffer=[ctx.queue commandBuffer];
  if(!buffer)return VX_METAL_COMMAND;
  MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];
  pass.colorAttachments[0].texture=ctx.target;
  pass.colorAttachments[0].loadAction=MTLLoadActionClear;
  pass.colorAttachments[0].storeAction=MTLStoreActionStore;
  pass.colorAttachments[0].clearColor=MTLClearColorMake(clear[0],clear[1],clear[2],clear[3]);
  id<MTLRenderCommandEncoder> enc=[buffer renderCommandEncoderWithDescriptor:pass];
  if(!enc)return VX_METAL_COMMAND;
  [enc setRenderPipelineState:ctx.pipeline];
  if(count){[enc setVertexBuffer:verts offset:0 atIndex:0];[enc drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:count];}
  [enc endEncoding];[buffer commit];[buffer waitUntilCompleted];
  if(buffer.status!=MTLCommandBufferStatusCompleted)return VX_METAL_COMMAND;
  ctx.rendered=YES;return VX_METAL_OK;
 }
}
int vx_metal_readback(vx_metal *context,uint8_t *rgba,size_t capacity) {
 if(!context||!rgba)return VX_METAL_INVALID;
 @autoreleasepool {
  VXMetalContext *ctx=(__bridge VXMetalContext *)context;
  size_t width=ctx.target.width,height=ctx.target.height;
  if(!ctx.rendered||capacity<width*height*4)return VX_METAL_INVALID;
  [ctx.target getBytes:rgba bytesPerRow:width*4 fromRegion:MTLRegionMake2D(0,0,width,height) mipmapLevel:0];
  return VX_METAL_OK;
 }
}
static void gxp_diagnostic(char *out,size_t capacity,NSError *error){
 if(out&&capacity){const char *message=error.localizedDescription.UTF8String;
  snprintf(out,capacity,"%s",message?message:"Metal shader/pipeline creation failed");}
}
int vx_metal_gxp_pipeline(vx_metal *context,const char *vertex_msl,const char *fragment_msl,
 const vx_gxp_attribute *attributes,size_t count,size_t stride,size_t vwords,size_t fwords,uint32_t texture_mask,char *diagnostic,size_t capacity){
 if(diagnostic&&capacity)diagnostic[0]=0;
 if(!context)return VX_METAL_INVALID;
 @autoreleasepool {VXMetalContext *ctx=(__bridge VXMetalContext *)context;
  ctx.gxpPipeline=nil;ctx.gxpStride=0;
  if(!vertex_msl||!fragment_msl||!attributes||!count||count>16||!stride||stride>4096||stride%4||vwords>1024||fwords>1024||texture_mask>=1u<<VX_GXP_FRAGMENT_TEXTURES||
     strnlen(vertex_msl,1024*1024)==1024*1024||strnlen(fragment_msl,1024*1024)==1024*1024)return VX_METAL_INVALID;
  MTLVertexDescriptor *vd=[MTLVertexDescriptor vertexDescriptor];
  for(size_t i=0;i<count;i++){
   unsigned components=attributes[i].components;size_t offset=attributes[i].offset;
   if(!components||components>4||offset%4||offset>stride||components*4>stride-offset)return VX_METAL_INVALID;
   MTLVertexFormat formats[]={MTLVertexFormatInvalid,MTLVertexFormatFloat,MTLVertexFormatFloat2,MTLVertexFormatFloat3,MTLVertexFormatFloat4};
   vd.attributes[i].format=formats[components];vd.attributes[i].offset=offset;vd.attributes[i].bufferIndex=0;
  }
  vd.layouts[0].stride=stride;vd.layouts[0].stepFunction=MTLVertexStepFunctionPerVertex;
  MTLCompileOptions *options=[MTLCompileOptions new];
  if(@available(macOS 15.0,*)){options.mathMode=MTLMathModeSafe;options.mathFloatingPointFunctions=MTLMathFloatingPointFunctionsPrecise;}
  else {
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
   options.fastMathEnabled=NO;
#pragma clang diagnostic pop
  }
  NSError *error=nil;
  NSString *vs=[[NSString alloc] initWithUTF8String:vertex_msl],*fs=[[NSString alloc] initWithUTF8String:fragment_msl];
  if(!vs||!fs)return VX_METAL_INVALID;
  id<MTLLibrary> vlib=[ctx.device newLibraryWithSource:vs options:options error:&error];
  if(!vlib){gxp_diagnostic(diagnostic,capacity,error);return VX_METAL_SHADER;}
  id<MTLLibrary> flib=[ctx.device newLibraryWithSource:fs options:options error:&error];
  if(!flib){gxp_diagnostic(diagnostic,capacity,error);return VX_METAL_SHADER;}
  MTLRenderPipelineDescriptor *pd=[MTLRenderPipelineDescriptor new];
  pd.vertexFunction=[vlib newFunctionWithName:@"vx_gxp_v"];pd.fragmentFunction=[flib newFunctionWithName:@"vx_gxp_f"];
  if(!pd.vertexFunction||!pd.fragmentFunction)return VX_METAL_SHADER;
  pd.vertexDescriptor=vd;pd.colorAttachments[0].pixelFormat=MTLPixelFormatRGBA8Unorm;
  if(ctx.depthEnabled)pd.depthAttachmentPixelFormat=MTLPixelFormatDepth32Float;
  if(ctx.stencilEnabled)pd.stencilAttachmentPixelFormat=MTLPixelFormatStencil8;
  id<MTLRenderPipelineState> pipeline=[ctx.device newRenderPipelineStateWithDescriptor:pd error:&error];
  if(!pipeline){gxp_diagnostic(diagnostic,capacity,error);return VX_METAL_SHADER;}
  ctx.gxpPipeline=pipeline;ctx.gxpStride=stride;ctx.gxpVWords=vwords;ctx.gxpFWords=fwords;ctx.gxpTextureMask=texture_mask;return VX_METAL_OK;
 }
}
int vx_metal_gxp_depth_begin(vx_metal *context,int enabled,float clear_depth){
 if(!context||(enabled!=0&&enabled!=1)||!isfinite(clear_depth)||clear_depth<0||clear_depth>1)return VX_METAL_INVALID;
 @autoreleasepool {VXMetalContext *ctx=(__bridge VXMetalContext *)context;
  id<MTLTexture> depth=ctx.depth;
  if(enabled&&(!depth||depth.width!=ctx.target.width||depth.height!=ctx.target.height)){
   MTLTextureDescriptor *td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatDepth32Float width:ctx.target.width height:ctx.target.height mipmapped:NO];
   td.storageMode=MTLStorageModePrivate;td.usage=MTLTextureUsageRenderTarget;
   depth=[ctx.device newTextureWithDescriptor:td];if(!depth)return VX_METAL_ALLOCATION;
  }
  if(ctx.depthEnabled!=enabled){ctx.gxpPipeline=nil;ctx.gxpStride=0;}
  ctx.depth=depth;ctx.depthEnabled=enabled;ctx.depthValid=NO;ctx.depthClear=clear_depth;
  return vx_metal_gxp_depth_state(context,ctx.depthCompare,ctx.depthWrite);
 }
}
int vx_metal_gxp_depth_upload(vx_metal *context,const uint8_t *depth,size_t capacity,size_t stride){
 if(!context||!depth)return VX_METAL_INVALID;
 @autoreleasepool {VXMetalContext *ctx=(__bridge VXMetalContext *)context;
  size_t w=ctx.target.width,h=ctx.target.height,row=(w*4+255)&~(size_t)255;
  if(!ctx.depthEnabled||!ctx.depth||stride<w*4||stride>4096*4||stride%4||capacity<(h-1)*stride+w*4)return VX_METAL_INVALID;
  id<MTLBuffer> staging=[ctx.device newBufferWithLength:row*h options:MTLResourceStorageModeShared];if(!staging)return VX_METAL_ALLOCATION;
  for(size_t y=0;y<h;y++)memcpy((uint8_t *)staging.contents+y*row,depth+y*stride,w*4);
  id<MTLCommandBuffer> command=[ctx.queue commandBuffer];if(!command)return VX_METAL_COMMAND;
  id<MTLBlitCommandEncoder> blit=[command blitCommandEncoder];if(!blit)return VX_METAL_COMMAND;
  [blit copyFromBuffer:staging sourceOffset:0 sourceBytesPerRow:row sourceBytesPerImage:row*h sourceSize:MTLSizeMake(w,h,1) toTexture:ctx.depth destinationSlice:0 destinationLevel:0 destinationOrigin:MTLOriginMake(0,0,0)];
  [blit endEncoding];[command commit];[command waitUntilCompleted];if(command.status!=MTLCommandBufferStatusCompleted)return VX_METAL_COMMAND;
  ctx.depthValid=YES;return VX_METAL_OK;
 }
}
int vx_metal_gxp_depth_readback(vx_metal *context,float *depth,size_t count){
 if(!context||!depth)return VX_METAL_INVALID;
 @autoreleasepool {VXMetalContext *ctx=(__bridge VXMetalContext *)context;
  size_t w=ctx.target.width,h=ctx.target.height,row=(w*4+255)&~(size_t)255;
  if(!ctx.depthEnabled||!ctx.depth||count<w*h)return VX_METAL_INVALID;
  id<MTLBuffer> staging=[ctx.device newBufferWithLength:row*h options:MTLResourceStorageModeShared];if(!staging)return VX_METAL_ALLOCATION;
  id<MTLCommandBuffer> command=[ctx.queue commandBuffer];if(!command)return VX_METAL_COMMAND;
  if(!ctx.depthValid){
   MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];
   pass.depthAttachment.texture=ctx.depth;pass.depthAttachment.loadAction=MTLLoadActionClear;
   pass.depthAttachment.storeAction=MTLStoreActionStore;pass.depthAttachment.clearDepth=ctx.depthClear;
   id<MTLRenderCommandEncoder> encoder=[command renderCommandEncoderWithDescriptor:pass];if(!encoder)return VX_METAL_COMMAND;[encoder endEncoding];
  }
  id<MTLBlitCommandEncoder> blit=[command blitCommandEncoder];if(!blit)return VX_METAL_COMMAND;
  [blit copyFromTexture:ctx.depth sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0,0,0) sourceSize:MTLSizeMake(w,h,1) toBuffer:staging destinationOffset:0 destinationBytesPerRow:row destinationBytesPerImage:row*h];
  [blit endEncoding];[command commit];[command waitUntilCompleted];if(command.status!=MTLCommandBufferStatusCompleted)return VX_METAL_COMMAND;
  ctx.depthValid=YES;
  for(size_t y=0;y<h;y++)memcpy(depth+y*w,(uint8_t *)staging.contents+y*row,w*4);
  return VX_METAL_OK;
 }
}
int vx_metal_gxp_depth_state(vx_metal *context,unsigned compare,int write_enabled){
 if(!context||compare>7||(write_enabled!=0&&write_enabled!=1))return VX_METAL_INVALID;
 @autoreleasepool {VXMetalContext *ctx=(__bridge VXMetalContext *)context;
  const MTLCompareFunction functions[]={MTLCompareFunctionNever,MTLCompareFunctionLess,MTLCompareFunctionEqual,MTLCompareFunctionLessEqual,MTLCompareFunctionGreater,MTLCompareFunctionNotEqual,MTLCompareFunctionGreaterEqual,MTLCompareFunctionAlways};
  MTLDepthStencilDescriptor *ds=[MTLDepthStencilDescriptor new];ds.depthCompareFunction=ctx.depthEnabled?functions[compare]:MTLCompareFunctionAlways;ds.depthWriteEnabled=ctx.depthEnabled?write_enabled:NO;
  ds.frontFaceStencil=ctx.stencilEnabled?ctx.stencilDescriptor:nil;
  ds.backFaceStencil=ctx.stencilEnabled?ctx.backStencilDescriptor:nil;
  id<MTLDepthStencilState> state=[ctx.device newDepthStencilStateWithDescriptor:ds];if(!state)return VX_METAL_ALLOCATION;
  ctx.depthState=state;ctx.depthCompare=compare;ctx.depthWrite=write_enabled;return VX_METAL_OK;
 }
}

int vx_metal_gxp_stencil_begin(vx_metal *context,int enabled,unsigned clear){
 if(!context||(enabled!=0&&enabled!=1)||clear>255)return VX_METAL_INVALID;
 @autoreleasepool {VXMetalContext *ctx=(__bridge VXMetalContext *)context;
  id<MTLTexture> stencil=ctx.stencil;
  if(enabled&&(!stencil||stencil.width!=ctx.target.width||stencil.height!=ctx.target.height)){
   MTLTextureDescriptor *td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatStencil8 width:ctx.target.width height:ctx.target.height mipmapped:NO];
   td.storageMode=MTLStorageModePrivate;td.usage=MTLTextureUsageRenderTarget;
   stencil=[ctx.device newTextureWithDescriptor:td];if(!stencil)return VX_METAL_ALLOCATION;
  }
  if(ctx.stencilEnabled!=enabled){ctx.gxpPipeline=nil;ctx.gxpStride=0;}
  ctx.stencil=stencil;ctx.stencilEnabled=enabled;ctx.stencilValid=NO;ctx.stencilClear=clear;
  if(!ctx.stencilDescriptor){MTLStencilDescriptor *sd=[MTLStencilDescriptor new];sd.stencilCompareFunction=MTLCompareFunctionAlways;ctx.stencilDescriptor=sd;ctx.backStencilDescriptor=[sd copy];}
  return vx_metal_gxp_depth_state(context,ctx.depthCompare,ctx.depthWrite);
 }
}
int vx_metal_gxp_stencil_face_state(vx_metal *context,unsigned face,unsigned compare,unsigned fail,unsigned depth_fail,unsigned pass,unsigned read_mask,unsigned write_mask,unsigned reference){
 if(!context||face>1||compare>7||fail>7||depth_fail>7||pass>7||read_mask>255||write_mask>255||reference>255)return VX_METAL_INVALID;
 @autoreleasepool {VXMetalContext *ctx=(__bridge VXMetalContext *)context;
  const MTLCompareFunction functions[]={MTLCompareFunctionNever,MTLCompareFunctionLess,MTLCompareFunctionEqual,MTLCompareFunctionLessEqual,MTLCompareFunctionGreater,MTLCompareFunctionNotEqual,MTLCompareFunctionGreaterEqual,MTLCompareFunctionAlways};
  const MTLStencilOperation ops[]={MTLStencilOperationKeep,MTLStencilOperationZero,MTLStencilOperationReplace,MTLStencilOperationIncrementClamp,MTLStencilOperationDecrementClamp,MTLStencilOperationInvert,MTLStencilOperationIncrementWrap,MTLStencilOperationDecrementWrap};
  MTLStencilDescriptor *sd=[MTLStencilDescriptor new];sd.stencilCompareFunction=functions[compare];
  sd.stencilFailureOperation=ops[fail];sd.depthFailureOperation=ops[depth_fail];sd.depthStencilPassOperation=ops[pass];sd.readMask=read_mask;sd.writeMask=write_mask;
  MTLStencilDescriptor *old=face?ctx.backStencilDescriptor:ctx.stencilDescriptor;
  if(face)ctx.backStencilDescriptor=sd;else ctx.stencilDescriptor=sd;
  int status=vx_metal_gxp_depth_state(context,ctx.depthCompare,ctx.depthWrite);
  if(status){if(face)ctx.backStencilDescriptor=old;else ctx.stencilDescriptor=old;return status;}
  if(face)ctx.backStencilReference=reference;else ctx.stencilReference=reference;return VX_METAL_OK;
 }
}
int vx_metal_gxp_stencil_state(vx_metal *context,unsigned compare,unsigned fail,unsigned depth_fail,unsigned pass,unsigned read_mask,unsigned write_mask,unsigned reference){
 int status=vx_metal_gxp_stencil_face_state(context,0,compare,fail,depth_fail,pass,read_mask,write_mask,reference);
 return status?status:vx_metal_gxp_stencil_face_state(context,1,compare,fail,depth_fail,pass,read_mask,write_mask,reference);
}

int vx_metal_gxp_stencil_upload(vx_metal *context,const uint8_t *data,size_t capacity,size_t stride){
 if(!context||!data)return VX_METAL_INVALID;
 @autoreleasepool {VXMetalContext *ctx=(__bridge VXMetalContext *)context;
  size_t w=ctx.target.width,h=ctx.target.height,row=(w+255)&~(size_t)255;
  if(!ctx.stencilEnabled||!ctx.stencil||stride<w||stride>4096||capacity<(h-1)*stride+w)return VX_METAL_INVALID;
  id<MTLBuffer> staging=[ctx.device newBufferWithLength:row*h options:MTLResourceStorageModeShared];if(!staging)return VX_METAL_ALLOCATION;
  for(size_t y=0;y<h;y++)memcpy((uint8_t *)staging.contents+y*row,data+y*stride,w);
  id<MTLCommandBuffer> command=[ctx.queue commandBuffer];if(!command)return VX_METAL_COMMAND;
  id<MTLBlitCommandEncoder> blit=[command blitCommandEncoder];if(!blit)return VX_METAL_COMMAND;
  [blit copyFromBuffer:staging sourceOffset:0 sourceBytesPerRow:row sourceBytesPerImage:row*h sourceSize:MTLSizeMake(w,h,1) toTexture:ctx.stencil destinationSlice:0 destinationLevel:0 destinationOrigin:MTLOriginMake(0,0,0)];
  [blit endEncoding];[command commit];[command waitUntilCompleted];if(command.status!=MTLCommandBufferStatusCompleted)return VX_METAL_COMMAND;
  ctx.stencilValid=YES;return VX_METAL_OK;
 }
}
int vx_metal_gxp_stencil_readback(vx_metal *context,uint8_t *data,size_t capacity){
 if(!context||!data)return VX_METAL_INVALID;
 @autoreleasepool {VXMetalContext *ctx=(__bridge VXMetalContext *)context;
  size_t w=ctx.target.width,h=ctx.target.height,row=(w+255)&~(size_t)255;
  if(!ctx.stencilEnabled||!ctx.stencil||capacity<w*h)return VX_METAL_INVALID;
  id<MTLBuffer> staging=[ctx.device newBufferWithLength:row*h options:MTLResourceStorageModeShared];if(!staging)return VX_METAL_ALLOCATION;
  id<MTLCommandBuffer> command=[ctx.queue commandBuffer];if(!command)return VX_METAL_COMMAND;
  if(!ctx.stencilValid){MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];
   pass.stencilAttachment.texture=ctx.stencil;pass.stencilAttachment.loadAction=MTLLoadActionClear;pass.stencilAttachment.storeAction=MTLStoreActionStore;pass.stencilAttachment.clearStencil=ctx.stencilClear;
   id<MTLRenderCommandEncoder> encoder=[command renderCommandEncoderWithDescriptor:pass];if(!encoder)return VX_METAL_COMMAND;[encoder endEncoding];}
  id<MTLBlitCommandEncoder> blit=[command blitCommandEncoder];if(!blit)return VX_METAL_COMMAND;
  [blit copyFromTexture:ctx.stencil sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0,0,0) sourceSize:MTLSizeMake(w,h,1) toBuffer:staging destinationOffset:0 destinationBytesPerRow:row destinationBytesPerImage:row*h];
  [blit endEncoding];[command commit];[command waitUntilCompleted];if(command.status!=MTLCommandBufferStatusCompleted)return VX_METAL_COMMAND;
  ctx.stencilValid=YES;for(size_t y=0;y<h;y++)memcpy(data+y*w,(uint8_t *)staging.contents+y*row,w);
  return VX_METAL_OK;
 }
}

typedef struct {MTLPixelFormat pixel;unsigned bytes,channels;} vx_sample_format;
static vx_sample_format sample_format(uint32_t format){
 if(format&0x00ff8fffu)return (vx_sample_format){0};
 unsigned swizzle=(format>>12)&7;
 switch(format>>24){
  case 0x00:return (vx_sample_format){MTLPixelFormatR8Unorm,1,1};
  case 0x01:return (vx_sample_format){MTLPixelFormatR8Snorm,1,1};
  case 0x07:return swizzle<6?(vx_sample_format){MTLPixelFormatRG8Unorm,2,2}:(vx_sample_format){0};
  case 0x08:return swizzle<6?(vx_sample_format){MTLPixelFormatRG8Snorm,2,2}:(vx_sample_format){0};
  case 0x09:return (vx_sample_format){MTLPixelFormatR16Unorm,2,1};
  case 0x0a:return (vx_sample_format){MTLPixelFormatR16Snorm,2,1};
  case 0x0b:return (vx_sample_format){MTLPixelFormatR16Float,2,1};
  case 0x0c:return (vx_sample_format){MTLPixelFormatRGBA8Unorm,4,4};
  case 0x0d:return (vx_sample_format){MTLPixelFormatRGBA8Snorm,4,4};
  case 0x0f:return swizzle<6?(vx_sample_format){MTLPixelFormatRG16Unorm,4,2}:(vx_sample_format){0};
  case 0x10:return swizzle<6?(vx_sample_format){MTLPixelFormatRG16Snorm,4,2}:(vx_sample_format){0};
  case 0x11:return swizzle<6?(vx_sample_format){MTLPixelFormatRG16Float,4,2}:(vx_sample_format){0};
  case 0x1b:return (vx_sample_format){MTLPixelFormatRGBA16Float,8,4};
  default:return (vx_sample_format){0};
 }
}
unsigned vx_metal_gxp_texture_pixel_bytes(uint32_t format){
 return sample_format(format).bytes;
}
static MTLTextureSwizzleChannels sample_swizzle(unsigned channels,unsigned mode){
 /* Vita names list fields from most significant to least significant. */
 static const unsigned single[8][4]={{0,4,4,5},{0,4,4,4},{0,5,5,5},{0,0,0,0},
                                      {0,0,0,4},{0,0,0,5},{4,4,4,0},{5,5,5,0}};
 static const unsigned dual[6][4]={{0,1,4,5},{0,1,4,4},{0,0,0,1},{1,1,1,0},
                                    {0,1,0,1},{1,0,4,4}};
 static const unsigned quad[8][4]={{0,1,2,3},{2,1,0,3},{3,2,1,0},{1,2,3,0},
                                    {0,1,2,5},{2,1,0,5},{3,2,1,5},{1,2,3,5}};
 static const MTLTextureSwizzle values[]={MTLTextureSwizzleRed,MTLTextureSwizzleGreen,
  MTLTextureSwizzleBlue,MTLTextureSwizzleAlpha,MTLTextureSwizzleZero,MTLTextureSwizzleOne};
 const unsigned *p=channels==1?single[mode]:channels==2?dual[mode]:quad[mode];
 return MTLTextureSwizzleChannelsMake(values[p[0]],values[p[1]],values[p[2]],values[p[3]]);
}
int vx_metal_gxp_upload_texture_format(vx_metal *context,unsigned slot,const uint8_t *data,size_t capacity,
 uint32_t width,uint32_t height,size_t stride,int linear_filter,uint32_t format){
 vx_sample_format desc=sample_format(format);
 size_t row=(size_t)width*desc.bytes;
 if(!context||slot>=VX_GXP_FRAGMENT_TEXTURES||!data||!desc.bytes||!width||!height||width>4096||height>4096||
    (linear_filter!=0&&linear_filter!=1)||stride<row||stride%desc.bytes||capacity<row||
    (height-1)>(capacity-row)/stride)return VX_METAL_INVALID;
 @autoreleasepool {VXMetalContext *ctx=(__bridge VXMetalContext *)context;
  MTLTextureDescriptor *td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:desc.pixel width:width height:height mipmapped:NO];
  td.swizzle=sample_swizzle(desc.channels,(format>>12)&7);
  td.storageMode=MTLStorageModeShared;td.usage=MTLTextureUsageShaderRead;
  id<MTLTexture> texture=[ctx.device newTextureWithDescriptor:td];if(!texture)return VX_METAL_ALLOCATION;
  [texture replaceRegion:MTLRegionMake2D(0,0,width,height) mipmapLevel:0 withBytes:data bytesPerRow:stride];
  MTLSamplerDescriptor *sd=[MTLSamplerDescriptor new];sd.normalizedCoordinates=YES;
  sd.sAddressMode=sd.tAddressMode=MTLSamplerAddressModeClampToEdge;
  sd.minFilter=sd.magFilter=linear_filter?MTLSamplerMinMagFilterLinear:MTLSamplerMinMagFilterNearest;
  id<MTLSamplerState> sampler=[ctx.device newSamplerStateWithDescriptor:sd];if(!sampler)return VX_METAL_ALLOCATION;
  if(!ctx.gxpTextures)ctx.gxpTextures=[NSMutableDictionary new];
  if(!ctx.gxpSamplers)ctx.gxpSamplers=[NSMutableDictionary new];
  ctx.gxpTextures[@(slot)]=texture;
  ctx.gxpSamplers[@(slot)]=sampler;
  return VX_METAL_OK;
 }
}
int vx_metal_gxp_upload_texture_at(vx_metal *context,unsigned slot,const uint8_t *rgba,size_t capacity,
 uint32_t width,uint32_t height,size_t stride,int linear_filter){
 return vx_metal_gxp_upload_texture_format(context,slot,rgba,capacity,width,height,stride,linear_filter,0x0c000000);
}
int vx_metal_gxp_upload_texture(vx_metal *context,const uint8_t *rgba,size_t capacity,
 uint32_t width,uint32_t height,size_t stride,int linear_filter){
 return vx_metal_gxp_upload_texture_at(context,0,rgba,capacity,width,height,stride,linear_filter);
}
int vx_metal_gxp_set_cull(vx_metal *context,unsigned mode){
 if(!context||mode>2)return VX_METAL_INVALID;
 VXMetalContext *ctx=(__bridge VXMetalContext *)context;
 ctx.gxpCull=mode;
 return VX_METAL_OK;
}
static void append_scissor(MTLScissorRect *rects,NSUInteger *count,NSUInteger x,NSUInteger y,
                           NSUInteger right,NSUInteger bottom){
 if(right>x&&bottom>y)rects[(*count)++]=(MTLScissorRect){x,y,right-x,bottom-y};
}
int vx_metal_gxp_set_raster(vx_metal *context,int wireframe,const uint32_t region[5]){
 if(!context||!region)return VX_METAL_INVALID;
 VXMetalContext *ctx=(__bridge VXMetalContext *)context;
 NSUInteger width=ctx.target.width,height=ctx.target.height,count=0;
 MTLScissorRect rects[4]={{0}};
 /* GXM region bounds are inclusive and horizontal/vertical tile-aligned. */
 NSUInteger left=MIN(width,region[1]&~31u);
 NSUInteger top=MIN(height,region[2]&~31u);
 NSUInteger right=MIN(width,((uint64_t)region[3]|31u)+1);
 NSUInteger bottom=MIN(height,((uint64_t)region[4]|31u)+1);
 switch(region[0]){
  case 0:append_scissor(rects,&count,0,0,width,height);break;
  case 0x40000000:break;
  case 0xc0000000:append_scissor(rects,&count,left,top,right,bottom);break;
  case 0x80000000:
   append_scissor(rects,&count,0,0,width,top);
   append_scissor(rects,&count,0,bottom,width,height);
   append_scissor(rects,&count,0,top,left,bottom);
   append_scissor(rects,&count,right,top,width,bottom);
   break;
  default:return VX_METAL_INVALID;
 }
 ctx.gxpWireframe=wireframe!=0;
 ctx.gxpScissorConfigured=YES;
 ctx.gxpScissorCount=count;
 ctx.gxpScissor0=rects[0];ctx.gxpScissor1=rects[1];ctx.gxpScissor2=rects[2];ctx.gxpScissor3=rects[3];
 return VX_METAL_OK;
}
static int gxp_draw(vx_metal *context,vx_metal_primitive primitive,const void *vertices,size_t vertex_bytes,size_t count,
 const uint32_t *vu,size_t vwords,const uint32_t *fu,size_t fwords,const float clear[4],int load){
 MTLPrimitiveType topology;
 switch(primitive){
  case VX_METAL_TRIANGLES:if(count%3)return VX_METAL_INVALID;topology=MTLPrimitiveTypeTriangle;break;
  case VX_METAL_LINES:if(count%2)return VX_METAL_INVALID;topology=MTLPrimitiveTypeLine;break;
  case VX_METAL_TRIANGLE_STRIP:if(count<3)return VX_METAL_INVALID;topology=MTLPrimitiveTypeTriangleStrip;break;
  default:return VX_METAL_INVALID;
 }
 if(!context||!clear||count>65535||(count&&!vertices)||vwords>1024||fwords>1024||
    (vwords&&!vu)||(fwords&&!fu))return VX_METAL_INVALID;
 for(unsigned i=0;i<4;i++)if(!isfinite(clear[i])||clear[i]<0||clear[i]>1)return VX_METAL_INVALID;
 @autoreleasepool {VXMetalContext *ctx=(__bridge VXMetalContext *)context;
  if((load&&!ctx.rendered)||!ctx.gxpPipeline||!ctx.gxpStride||count>vertex_bytes/ctx.gxpStride||vwords<ctx.gxpVWords||fwords<ctx.gxpFWords)return VX_METAL_INVALID;
  for(unsigned slot=0;slot<VX_GXP_FRAGMENT_TEXTURES;slot++)if((ctx.gxpTextureMask&(1u<<slot))&&
    (!ctx.gxpTextures[@(slot)]||!ctx.gxpSamplers[@(slot)]))return VX_METAL_INVALID;
  if((ctx.depthEnabled&&(!ctx.depth||!ctx.depthState))||(ctx.stencilEnabled&&(!ctx.stencil||!ctx.depthState)))return VX_METAL_INVALID;
  ctx.rendered=NO;
  id<MTLBuffer> data=count?[ctx.device newBufferWithBytes:vertices length:count*ctx.gxpStride options:MTLResourceStorageModeShared]:nil;
  if(count&&!data)return VX_METAL_ALLOCATION;
  id<MTLCommandBuffer> buffer=[ctx.queue commandBuffer];if(!buffer)return VX_METAL_COMMAND;
  MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];
  pass.colorAttachments[0].texture=ctx.target;pass.colorAttachments[0].loadAction=load?MTLLoadActionLoad:MTLLoadActionClear;
  pass.colorAttachments[0].storeAction=MTLStoreActionStore;
  pass.colorAttachments[0].clearColor=MTLClearColorMake(clear[0],clear[1],clear[2],clear[3]);
  if(ctx.depthEnabled){pass.depthAttachment.texture=ctx.depth;
   pass.depthAttachment.loadAction=ctx.depthValid?MTLLoadActionLoad:MTLLoadActionClear;
   pass.depthAttachment.storeAction=MTLStoreActionStore;pass.depthAttachment.clearDepth=ctx.depthClear;}
  if(ctx.stencilEnabled){pass.stencilAttachment.texture=ctx.stencil;
   pass.stencilAttachment.loadAction=ctx.stencilValid?MTLLoadActionLoad:MTLLoadActionClear;
   pass.stencilAttachment.storeAction=MTLStoreActionStore;pass.stencilAttachment.clearStencil=ctx.stencilClear;}
  id<MTLRenderCommandEncoder> encoder=[buffer renderCommandEncoderWithDescriptor:pass];if(!encoder)return VX_METAL_COMMAND;
  if(ctx.depthEnabled||ctx.stencilEnabled){[encoder setDepthStencilState:ctx.depthState];[encoder setStencilFrontReferenceValue:ctx.stencilReference backReferenceValue:ctx.backStencilReference];}
  [encoder setFrontFacingWinding:MTLWindingClockwise];
  [encoder setTriangleFillMode:ctx.gxpWireframe?MTLTriangleFillModeLines:MTLTriangleFillModeFill];
  [encoder setCullMode:ctx.gxpCull==1?MTLCullModeFront:ctx.gxpCull==2?MTLCullModeBack:MTLCullModeNone];
  [encoder setRenderPipelineState:ctx.gxpPipeline];uint32_t zero=0;
  [encoder setVertexBytes:vwords?vu:&zero length:vwords?vwords*4:4 atIndex:1];
  [encoder setFragmentBytes:fwords?fu:&zero length:fwords?fwords*4:4 atIndex:1];
  for(unsigned slot=0;slot<VX_GXP_FRAGMENT_TEXTURES;slot++)if(ctx.gxpTextureMask&(1u<<slot)){
   [encoder setFragmentTexture:ctx.gxpTextures[@(slot)] atIndex:slot];
   [encoder setFragmentSamplerState:ctx.gxpSamplers[@(slot)] atIndex:slot];
  }
  if(count){
   [encoder setVertexBuffer:data offset:0 atIndex:0];
   if(!ctx.gxpScissorConfigured)[encoder drawPrimitives:topology vertexStart:0 vertexCount:count];
   else{
    MTLScissorRect rects[4]={ctx.gxpScissor0,ctx.gxpScissor1,ctx.gxpScissor2,ctx.gxpScissor3};
    for(NSUInteger i=0;i<ctx.gxpScissorCount;i++){
     [encoder setScissorRect:rects[i]];
     [encoder drawPrimitives:topology vertexStart:0 vertexCount:count];
    }
   }
  }
  [encoder endEncoding];[buffer commit];[buffer waitUntilCompleted];
  if(buffer.status!=MTLCommandBufferStatusCompleted)return VX_METAL_COMMAND;
  ctx.rendered=YES;if(ctx.depthEnabled)ctx.depthValid=YES;if(ctx.stencilEnabled)ctx.stencilValid=YES;return VX_METAL_OK;
 }
}
int vx_metal_gxp_draw(vx_metal *c,const void *v,size_t bytes,size_t count,const uint32_t *vu,size_t vw,const uint32_t *fu,size_t fw,const float clear[4]){
 return gxp_draw(c,VX_METAL_TRIANGLES,v,bytes,count,vu,vw,fu,fw,clear,0);
}
int vx_metal_gxp_draw_load(vx_metal *c,const void *v,size_t bytes,size_t count,const uint32_t *vu,size_t vw,const uint32_t *fu,size_t fw){
 return vx_metal_gxp_draw_primitive_load(c,VX_METAL_TRIANGLES,v,bytes,count,vu,vw,fu,fw);
}
int vx_metal_gxp_draw_primitive_load(vx_metal *c,vx_metal_primitive primitive,const void *v,size_t bytes,size_t count,const uint32_t *vu,size_t vw,const uint32_t *fu,size_t fw){
 const float unused[4]={0};return gxp_draw(c,primitive,v,bytes,count,vu,vw,fu,fw,unused,1);
}
void vx_metal_destroy(vx_metal *context) {
 if(context){@autoreleasepool {id released=CFBridgingRelease(context);(void)released;}}
}

static int transfer_bounds(unsigned bpp,uint32_t width,uint32_t height,size_t capacity,size_t stride){
 if((bpp!=1&&bpp!=2&&bpp!=4)||!width||!height||width>4096||height>4096||stride<width*bpp||stride>16384||capacity>64*1024*1024)return VX_METAL_INVALID;
 return (height-1)*stride+(size_t)width*bpp<=capacity?0:VX_METAL_INVALID;
}
static int transfer_execute(vx_metal *context,uint32_t color,unsigned bpp,uint32_t width,uint32_t height,
 const uint8_t *source,size_t source_capacity,size_t source_stride,uint8_t *dest,size_t capacity,size_t stride){
 if(!context||!dest||transfer_bounds(bpp,width,height,capacity,stride)||
    (source&&transfer_bounds(bpp,width,height,source_capacity,source_stride)))return VX_METAL_INVALID;
 @autoreleasepool {
  VXMetalContext *ctx=(__bridge VXMetalContext *)context;
  if(!ctx.transferFill||!ctx.transferCopy){
   NSString *code=@"#include <metal_stdlib>\nusing namespace metal;\n"
   "struct P{uint color,bpp,width,height,srcStride,dstStride;};\n"
   "kernel void fill(device uchar*d [[buffer(0)]],constant P&p [[buffer(2)]],uint2 i [[thread_position_in_grid]]){if(i.x>=p.width*p.bpp||i.y>=p.height)return;d[i.y*p.dstStride+i.x]=uchar(p.color>>((i.x%p.bpp)*8));}\n"
   "kernel void copy_pixels(device uchar*d [[buffer(0)]],device const uchar*s [[buffer(1)]],constant P&p [[buffer(2)]],uint2 i [[thread_position_in_grid]]){if(i.x>=p.width*p.bpp||i.y>=p.height)return;d[i.y*p.dstStride+i.x]=s[i.y*p.srcStride+i.x];}";
   NSError *error=nil;id<MTLLibrary> lib=[ctx.device newLibraryWithSource:code options:nil error:&error];if(!lib)return VX_METAL_SHADER;
   id<MTLComputePipelineState> fill=[ctx.device newComputePipelineStateWithFunction:[lib newFunctionWithName:@"fill"] error:&error];
   id<MTLComputePipelineState> copy=[ctx.device newComputePipelineStateWithFunction:[lib newFunctionWithName:@"copy_pixels"] error:&error];
   if(!fill||!copy)return VX_METAL_SHADER;ctx.transferFill=fill;ctx.transferCopy=copy;
  }
  id<MTLBuffer> output=[ctx.device newBufferWithBytes:dest length:capacity options:MTLResourceStorageModeShared];
  id<MTLBuffer> input=source?[ctx.device newBufferWithBytes:source length:source_capacity options:MTLResourceStorageModeShared]:nil;
  if(!output||(source&&!input))return VX_METAL_ALLOCATION;
  id<MTLCommandBuffer> command=[ctx.queue commandBuffer];if(!command)return VX_METAL_COMMAND;
  id<MTLComputeCommandEncoder> encoder=[command computeCommandEncoder];if(!encoder)return VX_METAL_COMMAND;
  id<MTLComputePipelineState> pipeline=source?ctx.transferCopy:ctx.transferFill;
  uint32_t parameters[]={color,bpp,width,height,(uint32_t)source_stride,(uint32_t)stride};
  [encoder setComputePipelineState:pipeline];[encoder setBuffer:output offset:0 atIndex:0];
  if(source)[encoder setBuffer:input offset:0 atIndex:1];
  [encoder setBytes:parameters length:sizeof parameters atIndex:2];
  NSUInteger groupWidth=MIN((NSUInteger)32,pipeline.maxTotalThreadsPerThreadgroup);
  [encoder dispatchThreads:MTLSizeMake(width*bpp,height,1) threadsPerThreadgroup:MTLSizeMake(groupWidth,1,1)];
  [encoder endEncoding];[command commit];[command waitUntilCompleted];
  if(command.status!=MTLCommandBufferStatusCompleted)return VX_METAL_COMMAND;
  memcpy(dest,output.contents,capacity);return 0;
 }
}
int vx_metal_transfer_fill(vx_metal *context,uint32_t color,unsigned bpp,uint32_t width,uint32_t height,uint8_t *dest,size_t capacity,size_t stride){
 return transfer_execute(context,color,bpp,width,height,NULL,0,0,dest,capacity,stride);
}
int vx_metal_transfer_copy(vx_metal *context,unsigned bpp,uint32_t width,uint32_t height,const uint8_t *source,size_t source_capacity,size_t source_stride,uint8_t *dest,size_t capacity,size_t stride){
 if(!source)return VX_METAL_INVALID;
 return transfer_execute(context,0,bpp,width,height,source,source_capacity,source_stride,dest,capacity,stride);
}

#ifdef VX_ENABLE_WINDOW
int vx_metal_present_layer(vx_metal *context,void *layer,int linear_filter){
 if(!context||!layer||(linear_filter!=0&&linear_filter!=1))return VX_METAL_INVALID;
 @autoreleasepool {VXMetalContext *ctx=(__bridge VXMetalContext *)context;
  CAMetalLayer *surface=(__bridge CAMetalLayer *)layer;
  if(!ctx.rendered||surface.device!=ctx.device||surface.pixelFormat!=MTLPixelFormatBGRA8Unorm)return VX_METAL_INVALID;
  if(!ctx.windowPresentation){
   NSError *error=nil;id<MTLLibrary> lib=[ctx.device newLibraryWithSource:presentation_shader() options:nil error:&error];if(!lib)return VX_METAL_SHADER;
   MTLRenderPipelineDescriptor *pd=[MTLRenderPipelineDescriptor new];pd.vertexFunction=[lib newFunctionWithName:@"pv"];pd.fragmentFunction=[lib newFunctionWithName:@"pf"];pd.colorAttachments[0].pixelFormat=surface.pixelFormat;
   ctx.windowPresentation=[ctx.device newRenderPipelineStateWithDescriptor:pd error:&error];if(!ctx.windowPresentation)return VX_METAL_SHADER;
  }
  if(!ctx.sampler||ctx.linear!=linear_filter){int status=vx_metal_set_filter(context,linear_filter);if(status)return status;}
  id<CAMetalDrawable> drawable=[surface nextDrawable];if(!drawable)return VX_METAL_COMMAND;
  id<MTLCommandBuffer> buffer=[ctx.queue commandBuffer];if(!buffer)return VX_METAL_COMMAND;
  MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];pass.colorAttachments[0].texture=drawable.texture;pass.colorAttachments[0].loadAction=MTLLoadActionClear;pass.colorAttachments[0].clearColor=MTLClearColorMake(0,0,0,1);pass.colorAttachments[0].storeAction=MTLStoreActionStore;
  id<MTLRenderCommandEncoder> encoder=[buffer renderCommandEncoderWithDescriptor:pass];if(!encoder)return VX_METAL_COMMAND;
  double width=drawable.texture.width,height=drawable.texture.height;
  double scale=fmin(width/ctx.target.width,height/ctx.target.height);
  double image_width=ctx.target.width*scale,image_height=ctx.target.height*scale;
  [encoder setViewport:(MTLViewport){(width-image_width)/2,(height-image_height)/2,image_width,image_height,0,1}];
  [encoder setRenderPipelineState:ctx.windowPresentation];[encoder setFragmentTexture:ctx.target atIndex:0];[encoder setFragmentSamplerState:ctx.sampler atIndex:0];[encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];[encoder endEncoding];
  [buffer presentDrawable:drawable];[buffer commit];[buffer waitUntilCompleted];return buffer.status==MTLCommandBufferStatusCompleted?0:VX_METAL_COMMAND;
 }
}
#endif
