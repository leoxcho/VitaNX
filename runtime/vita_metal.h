#ifndef VITA_METAL_H
#define VITA_METAL_H
#include <stddef.h>
#include <stdint.h>
/* Host-side offscreen backend with separate built-in and translated GXP pipelines.
   One owner thread per context. All pixels are tightly packed RGBA8. */
typedef struct vx_metal vx_metal;
typedef struct { float x, y, r, g, b, a; } vx_metal_vertex;
enum { VX_METAL_OK=0, VX_METAL_INVALID=-1, VX_METAL_UNAVAILABLE=77,
       VX_METAL_ALLOCATION=-2, VX_METAL_SHADER=-3, VX_METAL_COMMAND=-4 };
/* Explicit host pixel formats; these values are not Vita firmware enum values. */
enum {VX_PIXELS_RGBA8=0,VX_PIXELS_BGRA8=1,VX_PIXELS_RGB565_LE=2};
int vx_framebuffer_required(uint32_t width,uint32_t height,size_t stride,
                            uint32_t format,size_t *source_bytes,size_t *rgba_bytes);
int vx_framebuffer_convert(uint32_t width,uint32_t height,size_t stride,uint32_t format,
                           const uint8_t *source,size_t source_capacity,
                           uint8_t *rgba,size_t rgba_capacity);
int vx_metal_upload(vx_metal *context,const uint8_t *source,size_t capacity,
                     size_t stride,uint32_t format);
/* Convert/upload source pixels then sample through a GPU fullscreen pass.
   Target dimensions may differ: this is nearest-neighbor presentation scaling,
   not increased internal game rendering resolution. */
int vx_metal_present(vx_metal *context,const uint8_t *source,size_t capacity,
                     uint32_t source_width,uint32_t source_height,size_t stride,uint32_t format);
int vx_metal_resize(vx_metal *context,uint32_t width,uint32_t height);
int vx_metal_size(vx_metal *context,uint32_t *width,uint32_t *height);
int vx_metal_set_filter(vx_metal *context,int linear_filter);
#ifdef VX_ENABLE_WINDOW
/* layer is a main-thread CAMetalLayer; caller owns its Cocoa lifecycle. */
int vx_metal_present_layer(vx_metal *context,void *layer,int linear_filter);
#endif
int vx_metal_create(uint32_t width, uint32_t height, vx_metal **out);
int vx_metal_draw(vx_metal *context, const vx_metal_vertex *vertices,
                  size_t count, const float clear[4]);
int vx_metal_readback(vx_metal *context, uint8_t *rgba, size_t capacity);
/* Generated GXP MSL only: separate pipeline, no fallback to the host triangle.
   Attributes are float32 vectors; uniforms are raw default-buffer words. */
typedef struct {uint32_t components,offset;} vx_gxp_attribute;
int vx_metal_gxp_pipeline(vx_metal *context,const char *vertex_msl,const char *fragment_msl,
 const vx_gxp_attribute *attributes,size_t attribute_count,size_t vertex_stride,
 size_t vertex_uniform_words,size_t fragment_uniform_words,
 uint32_t texture_mask,
 char *diagnostic,size_t diagnostic_capacity);
/* Host depth state: compare 0..7 = never, less, equal, less/equal, greater,
   not/equal, greater/equal, always. begin clears on the next successful draw or depth readback;
   subsequent draws preserve depth. Rebuild the GXP pipeline after enable changes.
   This is not a guest surface format/storage implementation. */
int vx_metal_gxp_depth_begin(vx_metal *context,int enabled,float clear_depth);
/* Upload linear DF32 rows before the first draw; synchronous and checked. */
int vx_metal_gxp_depth_upload(vx_metal *context,const uint8_t *depth,size_t capacity,size_t stride);
int vx_metal_gxp_depth_readback(vx_metal *context,float *depth,size_t count);
int vx_metal_gxp_depth_state(vx_metal *context,unsigned compare,int write_enabled);
/* Linear S8 attachment; guest surface validation is owned by vita_gxm.c. Operations 0..7 follow Vita KEEP, ZERO,
   REPLACE, INCR clamp, DECR clamp, INVERT, INCR wrap, DECR wrap.
   The convenience state call sets both faces; face_state selects front=0/back=1. */
int vx_metal_gxp_stencil_begin(vx_metal *context,int enabled,unsigned clear);
int vx_metal_gxp_stencil_face_state(vx_metal *context,unsigned face,unsigned compare,unsigned fail,
 unsigned depth_fail,unsigned pass,unsigned read_mask,unsigned write_mask,unsigned reference);
int vx_metal_gxp_stencil_state(vx_metal *context,unsigned compare,unsigned fail,
 unsigned depth_fail,unsigned pass,unsigned read_mask,unsigned write_mask,unsigned reference);
int vx_metal_gxp_stencil_upload(vx_metal *context,const uint8_t *data,size_t capacity,size_t stride);
int vx_metal_gxp_stencil_readback(vx_metal *context,uint8_t *data,size_t capacity);

enum { VX_GXP_FRAGMENT_TEXTURES = 16 };
unsigned vx_metal_gxp_texture_pixel_bytes(uint32_t format);
int vx_metal_gxp_upload_texture_format(vx_metal *context,unsigned slot,const uint8_t *data,size_t capacity,
 uint32_t width,uint32_t height,size_t stride,int linear_filter,uint32_t format);
int vx_metal_gxp_upload_texture_at(vx_metal *context,unsigned slot,const uint8_t *rgba,size_t capacity,
 uint32_t width,uint32_t height,size_t stride,int linear_filter);
int vx_metal_gxp_upload_texture(vx_metal *context,const uint8_t *rgba,size_t capacity,
 uint32_t width,uint32_t height,size_t stride,int linear_filter);
int vx_metal_gxp_draw(vx_metal *context,const void *vertices,size_t vertex_bytes,size_t count,
 const uint32_t *vertex_uniforms,size_t vertex_uniform_words,
 const uint32_t *fragment_uniforms,size_t fragment_uniform_words,const float clear[4]);
/* Preserve previous target contents for guest scene draws. Requires upload/draw. */
int vx_metal_gxp_draw_load(vx_metal *context,const void *vertices,size_t vertex_bytes,size_t count,
 const uint32_t *vertex_uniforms,size_t vertex_uniform_words,
 const uint32_t *fragment_uniforms,size_t fragment_uniform_words);
typedef enum {
 VX_METAL_TRIANGLES, VX_METAL_LINES, VX_METAL_TRIANGLE_STRIP
} vx_metal_primitive;
int vx_metal_gxp_set_cull(vx_metal *context,unsigned mode);
int vx_metal_gxp_set_raster(vx_metal *context,int wireframe,const uint32_t region[5]);
int vx_metal_gxp_draw_primitive_load(vx_metal *context,vx_metal_primitive primitive,
 const void *vertices,size_t vertex_bytes,size_t count,
 const uint32_t *vertex_uniforms,size_t vertex_uniform_words,
 const uint32_t *fragment_uniforms,size_t fragment_uniform_words);
/* Synchronous GXM linear transfer primitives. No shaders supplied by the guest.
   The GPU writes a staging buffer; destination is committed only on completion. */
int vx_metal_transfer_fill(vx_metal *context,uint32_t color,unsigned bytes_per_pixel,
 uint32_t width,uint32_t height,uint8_t *destination,size_t capacity,size_t stride);
int vx_metal_transfer_copy(vx_metal *context,unsigned bytes_per_pixel,uint32_t width,uint32_t height,
 const uint8_t *source,size_t source_capacity,size_t source_stride,
 uint8_t *destination,size_t destination_capacity,size_t destination_stride);
void vx_metal_destroy(vx_metal *context);
#endif
