/* Modified for vitanx 2026-11-09: signed 64-bit sceIoLseek AAPCS bridge. */
#define _DARWIN_C_SOURCE

#define _POSIX_C_SOURCE 200809L
#include "vita_runtime.h"
#ifdef VX_ENABLE_DISPLAY
#include "vita_display.h"
#endif
#ifdef VX_ENABLE_WINDOW
#include "vita_window.h"
#endif
#ifdef VX_ENABLE_AUDIO
#include "vita_audio.h"
#endif
#ifdef VX_ENABLE_NGS
#include "vita_ngs.h"
#endif
#ifdef VX_ENABLE_AUDIODEC
#include "vita_audiodec.h"
#endif
#ifdef VX_ENABLE_GXM
#include "vita_gxm.h"
#endif
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>
#include <time.h>
#include <sys/stat.h>
#include <unistd.h>

/* NIDs verified against vitasdk/vita-headers db/360. No host pointers cross ABI.
   Synchronous isolated savedata0: files and nested read-only app0: assets.
   Directories are internal traversal handles only; symlink components refused.
   Unsupported operations fail. No commercial-title compatibility is claimed. */
#define VX_EINVAL UINT32_C(0x80010016)
#define VX_ENOSYS UINT32_C(0x80010030)
#define VX_EBADF UINT32_C(0x80010009)
#define VX_EMFILE UINT32_C(0x80010018)
/* Explicit import inventory for native tooling. The feature guards mirror the
   dispatch below; callers never need to assume every optional backend exists. */
static _Thread_local uint32_t process_param;
void vx_runtime_set_process_param(uint32_t address){process_param=address;}
const vx_import_capability *vx_runtime_import_capabilities(size_t *count) {
 static const vx_import_capability capabilities[]={
  {UINT32_C(0x48C7EAE6),"sceKernelCreateLwCond","core","checked condition workarea, attributes and live lightweight-mutex association"},
  {UINT32_C(0x721F6CB3),"sceKernelDeleteLwCond","core","delete tracked lightweight condition"},
  {UINT32_C(0xDA6EC8EF),"sceKernelCreateLwMutex","core","checked guest workarea; recursive counts; priority/FIFO blocking, timeout and deletion wake"},
  {UINT32_C(0xB84EF718),"_sceKernelCreateLwMutex","core","checked guest workarea; recursive counts; priority/FIFO blocking, timeout and deletion wake"},
  {UINT32_C(0x244E76D2),"sceKernelDeleteLwMutex","core","checked guest workarea; recursive counts; priority/FIFO blocking, timeout and deletion wake"},
  {UINT32_C(0x46E7BE7B),"sceKernelLockLwMutex","core","checked guest workarea; recursive counts; priority/FIFO blocking, timeout and deletion wake"},
  {UINT32_C(0x3148C6B6),"sceKernelLockLwMutexCB","core","checked guest workarea; recursive counts; priority/FIFO blocking, timeout and deletion wake"},
  {UINT32_C(0xA6A2C915),"sceKernelTryLockLwMutex","core","checked guest workarea; recursive counts; priority/FIFO blocking, timeout and deletion wake"},
  {UINT32_C(0x91FA6614),"sceKernelUnlockLwMutex","core","checked guest workarea; recursive counts; priority/FIFO blocking, timeout and deletion wake"},
  {UINT32_C(0x120AFC8C),"sceKernelUnlockLwMutex2","core","checked guest workarea; recursive counts; priority/FIFO blocking, timeout and deletion wake"},

  {UINT32_C(0x2BE3E066),"sceKernelGetProcessParam","core","loader-supplied exported guest process parameter structure"},
  {UINT32_C(0xB295EB61),"sceKernelGetTLSAddr","core","configured private per-thread TLS; bounded 64 key slots"},
  {UINT32_C(0xBACA6891),"sceKernelGetThreadTLSAddr","core","configured private per-thread TLS; bounded 64 key slots"},
  {UINT32_C(0xCC18FBAE),"sceKernelChangeThreadVfpException","core","current guest thread FPSCR cumulative status clear/set at native service yield"},
 {UINT32_C(0x0FB972F9),"sceKernelGetThreadId","core","cooperative single-host-thread scheduler; bounded objects/stacks; no multicore or dynamic guest code"},
  {UINT32_C(0xC5C11EE7),"sceKernelCreateThread","core","cooperative single-host-thread scheduler; bounded objects/stacks; no multicore or dynamic guest code"},
  {UINT32_C(0xF08DE149),"sceKernelStartThread","core","cooperative single-host-thread scheduler; bounded objects/stacks; no multicore or dynamic guest code"},
  {UINT32_C(0x1BBDE3D9),"sceKernelDeleteThread","core","cooperative single-host-thread scheduler; bounded objects/stacks; no multicore or dynamic guest code"},
  {UINT32_C(0xDDB395A9),"sceKernelWaitThreadEnd","core","cooperative single-host-thread scheduler; bounded objects/stacks; no multicore or dynamic guest code"},
  {UINT32_C(0xC54941ED),"sceKernelWaitThreadEndCB","core","cooperative single-host-thread scheduler; bounded objects/stacks; no multicore or dynamic guest code"},
  {UINT32_C(0x9C0180E1),"sceKernelDelayThreadCB","core","cooperative single-host-thread scheduler; bounded objects/stacks; no multicore or dynamic guest code"},
  {UINT32_C(0xED53334A),"sceKernelCreateMutex","core","cooperative single-host-thread scheduler; bounded objects/stacks; no multicore or dynamic guest code"},
  {UINT32_C(0x1D8D7945),"sceKernelLockMutex","core","cooperative single-host-thread scheduler; bounded objects/stacks; no multicore or dynamic guest code"},
  {UINT32_C(0x2BDAA524),"sceKernelLockMutexCB","core","cooperative single-host-thread scheduler; bounded objects/stacks; no multicore or dynamic guest code"},
  {UINT32_C(0x72FC1F54),"sceKernelTryLockMutex","core","cooperative single-host-thread scheduler; bounded objects/stacks; no multicore or dynamic guest code"},
  {UINT32_C(0x1A372EC8),"sceKernelUnlockMutex","core","cooperative single-host-thread scheduler; bounded objects/stacks; no multicore or dynamic guest code"},
  {UINT32_C(0xCB78710D),"sceKernelDeleteMutex","core","cooperative single-host-thread scheduler; bounded objects/stacks; no multicore or dynamic guest code"},
  {UINT32_C(0x8516D040),"sceKernelCreateEventFlag","core","cooperative single-host-thread scheduler; bounded objects/stacks; no multicore or dynamic guest code"},
  {UINT32_C(0xEC94DFF7),"sceKernelSetEventFlag","core","cooperative single-host-thread scheduler; bounded objects/stacks; no multicore or dynamic guest code"},
  {UINT32_C(0x4CB87CA7),"sceKernelClearEventFlag","core","cooperative single-host-thread scheduler; bounded objects/stacks; no multicore or dynamic guest code"},
  {UINT32_C(0x1FBB0FE1),"sceKernelPollEventFlag","core","cooperative single-host-thread scheduler; bounded objects/stacks; no multicore or dynamic guest code"},
  {UINT32_C(0x83C0E2AF),"sceKernelWaitEventFlag","core","cooperative single-host-thread scheduler; bounded objects/stacks; no multicore or dynamic guest code"},
  {UINT32_C(0xE737B1DF),"sceKernelWaitEventFlagCB","core","cooperative single-host-thread scheduler; bounded objects/stacks; no multicore or dynamic guest code"},
  {UINT32_C(0x5840162C),"sceKernelDeleteEventFlag","core","cooperative single-host-thread scheduler; bounded objects/stacks; no multicore or dynamic guest code"},
  {UINT32_C(0xB19CF7E9),"sceKernelCreateCallback","core","cooperative single-host-thread scheduler; bounded objects/stacks; no multicore or dynamic guest code"},
  {UINT32_C(0xE53E41F6),"sceKernelCheckCallback","core","cooperative single-host-thread scheduler; bounded objects/stacks; no multicore or dynamic guest code"},
  {UINT32_C(0xA4683592),"sceKernelNotifyCallback","core","cooperative single-host-thread scheduler; bounded objects/stacks; no multicore or dynamic guest code"},
  {UINT32_C(0xD469676B),"sceKernelDeleteCallback","core","cooperative single-host-thread scheduler; bounded objects/stacks; no multicore or dynamic guest code"},
  {UINT32_C(0x038644D5),"sceKernelGetCallbackCount","core","cooperative single-host-thread scheduler; bounded objects/stacks; no multicore or dynamic guest code"},
  {UINT32_C(0x30741EF2),"sceKernelCancelCallback","core","cooperative single-host-thread scheduler; bounded objects/stacks; no multicore or dynamic guest code"},
  {UINT32_C(0x0C7B834B),"sceKernelWaitSema","core","cooperative blocking waits with timeout; immediate/poll fallback outside guest scheduler"},
  {UINT32_C(0x0C8A38E1),"sceKernelExitThread","core","bounded shared services; cooperative guest scheduling; no arbitrary module linking"},
  {UINT32_C(0x16512F59),"sceIoSyncByFd","core","bounded shared services; cooperative guest scheduling; no arbitrary module linking"},
  {UINT32_C(0x1BD67366),"sceKernelCreateSema","core","bounded shared services; cooperative guest scheduling; no arbitrary module linking"},
  {UINT32_C(0x1D17DECF),"sceKernelExitDeleteThread","core","bounded shared services; cooperative guest scheduling; no arbitrary module linking"},
  {UINT32_C(0x34EFD876),"sceIoWrite","core","bounded shared services; cooperative guest scheduling; no arbitrary module linking"},
  {UINT32_C(0xBCA5B623),"sceIoGetstat","core","isolated save and read-only asset paths"},
  {UINT32_C(0x9670D39F),"sceIoMkdir","core","isolated save paths"},
  {UINT32_C(0xE20ED0F3),"sceIoRemove","core","isolated save paths"},
  {UINT32_C(0xF737E369),"sceIoRename","core","isolated save paths"},
  {UINT32_C(0xE9F91EC8),"sceIoRmdir","core","isolated save paths"},
  {UINT32_C(0x99BA173E),"sceIoLseek","core","signed 64-bit offset in r2/r3; stack origin; signed 64-bit result in r0/r1"},
  {UINT32_C(0x49252B9B),"sceIoLseek32","core","bounded shared services; cooperative guest scheduling; no arbitrary module linking"},
  {UINT32_C(0x4B675D05),"sceKernelDelayThread","core","bounded shared services; cooperative guest scheduling; no arbitrary module linking"},
  {UINT32_C(0x4C4672BF),"sceKernelGetProcessTime","core","bounded shared services; cooperative guest scheduling; no arbitrary module linking"},
  {UINT32_C(0x6C60AC61),"sceIoOpen","core","bounded shared services; cooperative guest scheduling; no arbitrary module linking"},
  {UINT32_C(0x7595D9AA),"sceKernelExitProcess","core","bounded shared services; cooperative guest scheduling; no arbitrary module linking"},
  {UINT32_C(0x866EF048),"sceKernelPollSema","core","bounded shared services; cooperative guest scheduling; no arbitrary module linking"},
  {UINT32_C(0x89DA0967),"sceKernelGetProcessTimeWideCore","core","bounded shared services; cooperative guest scheduling; no arbitrary module linking"},
  {UINT32_C(0xA33B99D1),"sceKernelFindMemBlockByAddr","core","bounded shared services; cooperative guest scheduling; no arbitrary module linking"},
  {UINT32_C(0xA91E15EE),"sceKernelFreeMemBlock","core","invalidates allocation UID; flat backing does not enforce unmapped-page faults"},
  {UINT32_C(0xB110C123),"sceKernelGetProcessTimeWide","core","bounded shared services; cooperative guest scheduling; no arbitrary module linking"},
  {UINT32_C(0xB8EF5818),"sceKernelGetMemBlockBase","core","bounded shared services; cooperative guest scheduling; no arbitrary module linking"},
  {UINT32_C(0xB9D5EBDE),"sceKernelAllocMemBlock","core","page-sized USER_RW or USER_RW_UNCACHE within configured backing; null options only"},
  {UINT32_C(0xC053DC6B),"_sceKernelExitProcessForUser","core","bounded shared services; cooperative guest scheduling; no arbitrary module linking"},
  {UINT32_C(0xC70B8886),"sceIoClose","core","bounded shared services; cooperative guest scheduling; no arbitrary module linking"},
  {UINT32_C(0xCC67B6FD),"_sceIoOpen","core","bounded shared services; cooperative guest scheduling; no arbitrary module linking"},
  {UINT32_C(0xD37A8437),"sceKernelGetProcessTimeCore","core","bounded shared services; cooperative guest scheduling; no arbitrary module linking"},
  {UINT32_C(0xDB32948A),"sceKernelDeleteSema","core","bounded shared services; cooperative guest scheduling; no arbitrary module linking"},
  {UINT32_C(0xE5AA625C),"sceKernelGetStdout","core","bounded shared services; cooperative guest scheduling; no arbitrary module linking"},
  {UINT32_C(0xE6B761D1),"sceKernelSignalSema","core","bounded shared services; cooperative guest scheduling; no arbitrary module linking"},
  {UINT32_C(0xE9F973B1),"sceKernelGetProcessTimeLow","core","bounded shared services; cooperative guest scheduling; no arbitrary module linking"},
  {UINT32_C(0xF4EE4FA9),"sceKernelGetSystemTimeWide","core","bounded shared services; cooperative guest scheduling; no arbitrary module linking"},
  {UINT32_C(0xF5D0D4C6),"sceKernelGetProcessTimeLowCore","core","bounded shared services; cooperative guest scheduling; no arbitrary module linking"},
  {UINT32_C(0xFA5E3ADA),"sceKernelGetStderr","core","bounded shared services; cooperative guest scheduling; no arbitrary module linking"},
  {UINT32_C(0xFDB32293),"sceIoRead","core","bounded shared services; cooperative guest scheduling; no arbitrary module linking"},
#ifdef VX_ENABLE_DISPLAY
  {UINT32_C(0x42AE6BBC),"sceDisplayGetFrameBuf","display","CPU framebuffer presentation; no GXM/GXP shader translation"},
  {UINT32_C(0x5795E898),"sceDisplayWaitVblankStart","display","CPU framebuffer presentation; no GXM/GXP shader translation"},
  {UINT32_C(0x7178FADA),"sceDisplayGetPrimaryHead","display","CPU framebuffer presentation; no GXM/GXP shader translation"},
  {UINT32_C(0x7A410B64),"sceDisplaySetFrameBuf","display","CPU framebuffer presentation; no GXM/GXP shader translation"},
  {UINT32_C(0x8848ADDD),"sceDisplayGetMaximumFrameBufResolution","display","CPU framebuffer presentation; no GXM/GXP shader translation"},
  {UINT32_C(0xA08CA60D),"sceDisplayGetRefreshRate","display","CPU framebuffer presentation; no GXM/GXP shader translation"},
  {UINT32_C(0xB6FDE0BA),"sceDisplayGetVcount","display","CPU framebuffer presentation; no GXM/GXP shader translation"},
  {UINT32_C(0xDD0A13B8),"sceDisplayWaitVblankStartMulti","display","CPU framebuffer presentation; no GXM/GXP shader translation"},
#endif
#ifdef VX_ENABLE_GXM
  {UINT32_C(0x97118913),"sceGxmReserveVertexDefaultUniformBuffer","gxm","checked scene-local uniform ring allocation; no wrap before scene completion"},
  {UINT32_C(0x7B1FABB6),"sceGxmReserveFragmentDefaultUniformBuffer","gxm","checked scene-local uniform ring allocation; no wrap before scene completion"},
  {UINT32_C(0x0733D8AE),"sceGxmFinish","gxm","synchronous completed scenes only"},
  {UINT32_C(0x4811AECB),"sceGxmTextureInitLinear","gxm","linear normalized RGBA8 sampler0; one mip; equal point/linear filters; clamp addressing"},
  {UINT32_C(0xFA695FD7),"sceGxmTextureSetMagFilter","gxm","linear normalized RGBA8 sampler0; one mip; equal point/linear filters; clamp addressing"},
  {UINT32_C(0x416764E3),"sceGxmTextureSetMinFilter","gxm","linear normalized RGBA8 sampler0; one mip; equal point/linear filters; clamp addressing"},
  {UINT32_C(0x4281763E),"sceGxmTextureSetUAddrMode","gxm","linear normalized RGBA8 sampler0; one mip; equal point/linear filters; clamp addressing"},
  {UINT32_C(0x126CDAA3),"sceGxmTextureSetVAddrMode","gxm","linear normalized RGBA8 sampler0; one mip; equal point/linear filters; clamp addressing"},
  {UINT32_C(0x29C34DF5),"sceGxmSetFragmentTexture","gxm","linear normalized RGBA8 sampler0; one mip; equal point/linear filters; clamp addressing"},
  {UINT32_C(0xE84CE5B4),"sceGxmCreateContext","gxm","bounded synchronous scene ABI; exact-byte translated shader catalog; bounded linear DF32 depth; no MSAA/blending/callbacks"},
  {UINT32_C(0xEDDC5FB2),"sceGxmDestroyContext","gxm","bounded synchronous scene ABI; exact-byte translated shader catalog; bounded linear DF32 depth; no MSAA/blending/callbacks"},
  {UINT32_C(0x895DF2E9),"sceGxmSetVertexStream","gxm","bounded synchronous scene ABI; exact-byte translated shader catalog; bounded linear DF32 depth; no MSAA/blending/callbacks"},
  {UINT32_C(0xC697CAE5),"sceGxmSetVertexDefaultUniformBuffer","gxm","bounded synchronous scene ABI; exact-byte translated shader catalog; bounded linear DF32 depth; no MSAA/blending/callbacks"},
  {UINT32_C(0xA824EB24),"sceGxmSetFragmentDefaultUniformBuffer","gxm","bounded synchronous scene ABI; exact-byte translated shader catalog; bounded linear DF32 depth; no MSAA/blending/callbacks"},
  {UINT32_C(0x05032658),"sceGxmShaderPatcherCreate","gxm","bounded synchronous scene ABI; exact-byte translated shader catalog; bounded linear DF32 depth; no MSAA/blending/callbacks"},
  {UINT32_C(0x2B528462),"sceGxmShaderPatcherRegisterProgram","gxm","bounded synchronous scene ABI; exact-byte translated shader catalog; bounded linear DF32 depth; no MSAA/blending/callbacks"},
  {UINT32_C(0xB7BBA6D5),"sceGxmShaderPatcherCreateVertexProgram","gxm","bounded synchronous scene ABI; exact-byte translated shader catalog; bounded linear DF32 depth; no MSAA/blending/callbacks"},
  {UINT32_C(0x4ED2E49D),"sceGxmShaderPatcherCreateFragmentProgram","gxm","bounded synchronous scene ABI; exact-byte translated shader catalog; bounded linear DF32 depth; no MSAA/blending/callbacks"},
  {UINT32_C(0x31FF8ABD),"sceGxmSetVertexProgram","gxm","bounded synchronous scene ABI; exact-byte translated shader catalog; bounded linear DF32 depth; no MSAA/blending/callbacks"},
  {UINT32_C(0xAD2F48D9),"sceGxmSetFragmentProgram","gxm","bounded synchronous scene ABI; exact-byte translated shader catalog; bounded linear DF32 depth; no MSAA/blending/callbacks"},
  {UINT32_C(0xAC1FF2DA),"sceGxmShaderPatcherReleaseVertexProgram","gxm","bounded synchronous scene ABI; exact-byte translated shader catalog; bounded linear DF32 depth; no MSAA/blending/callbacks"},
  {UINT32_C(0xBE2743D1),"sceGxmShaderPatcherReleaseFragmentProgram","gxm","bounded synchronous scene ABI; exact-byte translated shader catalog; bounded linear DF32 depth; no MSAA/blending/callbacks"},
  {UINT32_C(0xF103AF8A),"sceGxmShaderPatcherUnregisterProgram","gxm","bounded synchronous scene ABI; exact-byte translated shader catalog; bounded linear DF32 depth; no MSAA/blending/callbacks"},
  {UINT32_C(0xEAA5B100),"sceGxmShaderPatcherDestroy","gxm","bounded synchronous scene ABI; exact-byte translated shader catalog; bounded linear DF32 depth; no MSAA/blending/callbacks"},
  {UINT32_C(0x249D5B00),"sceGxmCreateDeferredContext","gxm","bounded deferred command streams and Metal raster state"},
  {UINT32_C(0xD6A2FF2F),"sceGxmDestroyDeferredContext","gxm","bounded deferred command streams and Metal raster state"},
  {UINT32_C(0x944D3F83),"sceGxmBeginCommandList","gxm","bounded deferred command streams and Metal raster state"},
  {UINT32_C(0x36D85916),"sceGxmEndCommandList","gxm","bounded deferred command streams and Metal raster state"},
  {UINT32_C(0xE8E139DD),"sceGxmExecuteCommandList","gxm","bounded deferred command streams and Metal raster state"},
  {UINT32_C(0xFA081D05),"sceGxmGetDeferredContextFragmentBuffer","gxm","checked deferred buffer replacement and live range tracking"},
  {UINT32_C(0xAD8C2EBA),"sceGxmGetDeferredContextVdmBuffer","gxm","checked deferred buffer replacement and live range tracking"},
  {UINT32_C(0x87632B9C),"sceGxmGetDeferredContextVertexBuffer","gxm","checked deferred buffer replacement and live range tracking"},
  {UINT32_C(0xC6B3FCD0),"sceGxmSetDeferredContextFragmentBuffer","gxm","checked deferred buffer replacement and live range tracking"},
  {UINT32_C(0x0B9D13CE),"sceGxmSetDeferredContextVdmBuffer","gxm","checked deferred buffer replacement and live range tracking"},
  {UINT32_C(0x27CAD127),"sceGxmSetDeferredContextVertexBuffer","gxm","checked deferred buffer replacement and live range tracking"},
  {UINT32_C(0xFD93209D),"sceGxmSetFrontPolygonMode","gxm","Metal raster state; deferred replay"},
  {UINT32_C(0x70C86868),"sceGxmSetRegionClip","gxm","Metal raster state; deferred replay"},
  {UINT32_C(0xE1CA72AE),"sceGxmSetCullMode","gxm","bounded deferred command streams and Metal raster state"},
  {UINT32_C(0x207AF96B),"sceGxmCreateRenderTarget","gxm","bounded synchronous scene ABI; exact-byte translated shader catalog; bounded linear DF32 depth; no MSAA/blending/callbacks"},
  {UINT32_C(0x0B94C50A),"sceGxmDestroyRenderTarget","gxm","bounded synchronous scene ABI; exact-byte translated shader catalog; bounded linear DF32 depth; no MSAA/blending/callbacks"},
  {UINT32_C(0xED0F6E25),"sceGxmColorSurfaceInit","gxm","bounded synchronous scene ABI; exact-byte translated shader catalog; bounded linear DF32 depth; no MSAA/blending/callbacks"},
  {UINT32_C(0xB8645A9A),"sceGxmSetFrontStencilFunc","gxm","checked linear S8 stencil, independent front/back state"},
  {UINT32_C(0x1A68C8D2),"sceGxmSetBackStencilFunc","gxm","checked linear S8 stencil, independent front/back state"},
  {UINT32_C(0x8FA6FE44),"sceGxmSetFrontStencilRef","gxm","checked linear S8 stencil, independent front/back state"},
  {UINT32_C(0x866A0517),"sceGxmSetBackStencilRef","gxm","checked linear S8 stencil, independent front/back state"},
  {UINT32_C(0xAAFC062B),"sceGxmDepthStencilSurfaceGetBackgroundStencil","gxm","checked linear S8 stencil, independent front/back state"},
  {UINT32_C(0xF5D3F3E8),"sceGxmDepthStencilSurfaceSetBackgroundStencil","gxm","checked linear S8 stencil, independent front/back state"},
  {UINT32_C(0xCA9D41D1),"sceGxmDepthStencilSurfaceInit","gxm","linear DF32/S8/DF32_S8, separate checked storage, force load and atomic readback"},
  {UINT32_C(0x14BD831F),"sceGxmSetFrontDepthFunc","gxm","eight depth comparisons; one-sided state"},
  {UINT32_C(0xF32CBF34),"sceGxmSetFrontDepthWriteEnable","gxm","bounded depth write state"},
  {UINT32_C(0xA41DB0D6),"sceGxmDepthStencilSurfaceInitDisabled","gxm","opaque disabled surface"},
  {UINT32_C(0x082200E1),"sceGxmDepthStencilSurfaceIsEnabled","gxm","bounded initialized depth surface enabled query"},
  {UINT32_C(0x8734FF4E),"sceGxmBeginScene","gxm","bounded synchronous scene ABI; exact-byte translated shader catalog; bounded linear DF32 depth; no MSAA/blending/callbacks"},
  {UINT32_C(0xBC059AFC),"sceGxmDraw","gxm","bounded synchronous scene ABI; exact-byte translated shader catalog; bounded linear DF32 depth; no MSAA/blending/callbacks"},
  {UINT32_C(0xFE300E2F),"sceGxmEndScene","gxm","bounded synchronous scene ABI; exact-byte translated shader catalog; bounded linear DF32 depth; no MSAA/blending/callbacks"},
  {UINT32_C(0x06FF9151),"sceGxmProgramGetParameter","gxm","checked guest shader metadata; bounded default F32 vector/array uniform writes"},
  {UINT32_C(0x277794C4),"sceGxmProgramFindParameterByName","gxm","checked guest shader metadata; bounded default F32 vector/array uniform writes"},
  {UINT32_C(0x633CAA54),"sceGxmProgramFindParameterBySemantic","gxm","checked guest shader metadata; bounded default F32 vector/array uniform writes"},
  {UINT32_C(0x6E61DDF5),"sceGxmProgramParameterGetIndex","gxm","checked guest shader metadata; bounded default F32 vector/array uniform writes"},
  {UINT32_C(0x1997DC17),"sceGxmProgramParameterGetCategory","gxm","checked guest shader metadata; bounded default F32 vector/array uniform writes"},
  {UINT32_C(0x6AF88A5D),"sceGxmProgramParameterGetName","gxm","checked guest shader metadata; bounded default F32 vector/array uniform writes"},
  {UINT32_C(0xE6D9C4CE),"sceGxmProgramParameterGetSemantic","gxm","checked guest shader metadata; bounded default F32 vector/array uniform writes"},
  {UINT32_C(0xB85CC13E),"sceGxmProgramParameterGetSemanticIndex","gxm","checked guest shader metadata; bounded default F32 vector/array uniform writes"},
  {UINT32_C(0x7B9023C3),"sceGxmProgramParameterGetType","gxm","checked guest shader metadata; bounded default F32 vector/array uniform writes"},
  {UINT32_C(0xBD2998D1),"sceGxmProgramParameterGetComponentCount","gxm","checked guest shader metadata; bounded default F32 vector/array uniform writes"},
  {UINT32_C(0xDBA8D061),"sceGxmProgramParameterGetArraySize","gxm","checked guest shader metadata; bounded default F32 vector/array uniform writes"},
  {UINT32_C(0x5C79D59A),"sceGxmProgramParameterGetResourceIndex","gxm","checked guest shader metadata; bounded default F32 vector/array uniform writes"},
  {UINT32_C(0xBB58267D),"sceGxmProgramParameterGetContainerIndex","gxm","checked guest shader metadata; bounded default F32 vector/array uniform writes"},
  {UINT32_C(0xF7AA978B),"sceGxmProgramParameterIsSamplerCube","gxm","checked guest shader metadata; bounded default F32 vector/array uniform writes"},
  {UINT32_C(0x65DD0C84),"sceGxmSetUniformDataF","gxm","checked guest shader metadata; bounded default F32 vector/array uniform writes"},
  {UINT32_C(0xED8B6C69),"sceGxmProgramCheck","gxm","GXP 1.4/1.5 header/code/parameter extents only; no USSE validation or translation"},
  {UINT32_C(0xBF5E2090),"sceGxmProgramGetSize","gxm","validated GXP 1.4/1.5 metadata query"},
  {UINT32_C(0x04BB3C59),"sceGxmProgramGetType","gxm","validated GXP 1.4/1.5 metadata query"},
  {UINT32_C(0xD5D5FCCD),"sceGxmProgramGetParameterCount","gxm","validated GXP 1.4/1.5 metadata query"},
  {UINT32_C(0x8FA3F9C3),"sceGxmProgramGetDefaultUniformBufferSize","gxm","validated GXP 1.4/1.5 metadata query"},
  {UINT32_C(0x029B4F1C),"sceGxmProgramIsDiscardUsed","gxm","validated GXP 1.4/1.5 metadata query"},
  {UINT32_C(0x89613EF2),"sceGxmProgramIsDepthReplaceUsed","gxm","validated GXP 1.4/1.5 metadata query"},
  {UINT32_C(0xE63C53D8),"sceGxmProgramIsSpriteCoordUsed","gxm","validated GXP 1.4/1.5 metadata query"},
  {UINT32_C(0x32F280F0),"sceGxmDepthStencilSurfaceSetBackgroundDepth","gxm","linear DF32 background depth; S0 float argument"},
  {UINT32_C(0x269B56BE),"sceGxmDepthStencilSurfaceGetBackgroundDepth","gxm","linear DF32 background depth; S0 float result"},
  {UINT32_C(0x0C44ACD7),"sceGxmDepthStencilSurfaceSetForceLoadMode","gxm","linear DF32 force load/store control"},
  {UINT32_C(0x12AAA7AF),"sceGxmDepthStencilSurfaceSetForceStoreMode","gxm","linear DF32 force load/store control"},
  {UINT32_C(0x2F5CC20C),"sceGxmDepthStencilSurfaceGetForceLoadMode","gxm","linear DF32 force load/store control"},
  {UINT32_C(0x544AA05A),"sceGxmDepthStencilSurfaceGetForceStoreMode","gxm","linear DF32 force load/store control"},
  {UINT32_C(0xB0F1E4EC),"sceGxmInitialize","gxm","validated initialization; owned parameter/queue storage and guest display callback worker"},
  {UINT32_C(0x6A6013E1),"sceGxmSyncObjectCreate","gxm","synchronous Metal completion and cooperative display queue"},
  {UINT32_C(0x889AE88C),"sceGxmSyncObjectDestroy","gxm","synchronous Metal completion and cooperative display queue"},
  {UINT32_C(0xEC5C26B5),"sceGxmDisplayQueueAddEntry","gxm","synchronous Metal completion and cooperative display queue"},
  {UINT32_C(0xB98C5B0D),"sceGxmDisplayQueueFinish","gxm","synchronous Metal completion and cooperative display queue"},
  {UINT32_C(0x9F448E79),"sceGxmNotificationWait","gxm","synchronous Metal completion and cooperative display queue"},
  {UINT32_C(0xB627DE66),"sceGxmTerminate","gxm","synchronous lifecycle"},
  {UINT32_C(0xC61E34FC),"sceGxmMapMemory","gxm","bounded page-aligned guest GPU read/write mappings"},
  {UINT32_C(0x828C68E8),"sceGxmUnmapMemory","gxm","bounded guest GPU mapping removal"},
  {UINT32_C(0x008402C6),"sceGxmMapFragmentUsseMemory","gxm","tracked guest USSE address range"},
  {UINT32_C(0xFA437510),"sceGxmMapVertexUsseMemory","gxm","tracked guest USSE address range"},
  {UINT32_C(0x80CCEDBB),"sceGxmUnmapFragmentUsseMemory","gxm","tracked guest USSE address range"},
  {UINT32_C(0x099134F5),"sceGxmUnmapVertexUsseMemory","gxm","tracked guest USSE address range"},
  {UINT32_C(0x62312BF8),"sceGxmTransferCopy","gxm","synchronous Metal linear same-format copy; no sync objects or color keys"},
  {UINT32_C(0x69DDFF5E),"sceGxmTransferFill","gxm","synchronous Metal linear fill; no sync objects"},
  {UINT32_C(0x45229C39),"sceGxmTransferFinish","gxm","all supported transfers complete before return"},
#endif
#ifdef VX_ENABLE_WINDOW
  {UINT32_C(0x1B9C5D14),"sceTouchSetSamplingState","window","one virtual contact per panel; mouse/trackpad pointer; normalized virtual panel; no hardware multitouch history"},
  {UINT32_C(0x26531526),"sceTouchGetSamplingState","window","one virtual contact per panel; mouse/trackpad pointer; normalized virtual panel; no hardware multitouch history"},
  {UINT32_C(0x10A2CA25),"sceTouchGetPanelInfo","window","one virtual contact per panel; mouse/trackpad pointer; normalized virtual panel; no hardware multitouch history"},
  {UINT32_C(0xB18370C2),"sceTouchEnableTouchForce","window","one virtual contact per panel; mouse/trackpad pointer; normalized virtual panel; no hardware multitouch history"},
  {UINT32_C(0x41194411),"sceTouchDisableTouchForce","window","one virtual contact per panel; mouse/trackpad pointer; normalized virtual panel; no hardware multitouch history"},
  {UINT32_C(0xFF082DF0),"sceTouchPeek","window","one virtual contact per panel; mouse/trackpad pointer; normalized virtual panel; no hardware multitouch history"},
  {UINT32_C(0x169A1D58),"sceTouchRead","window","one virtual contact per panel; mouse/trackpad pointer; normalized virtual panel; no hardware multitouch history"},
  {UINT32_C(0x104ED1A7),"sceCtrlPeekBufferNegative","window","single handheld controller and host snapshots"},
  {UINT32_C(0x81A89660),"sceCtrlPeekBufferNegative2","window","single handheld controller and host snapshots"},
  {UINT32_C(0x15F81E8C),"sceCtrlPeekBufferPositive2","window","single handheld controller and host snapshots"},
  {UINT32_C(0xA59454D3),"sceCtrlPeekBufferPositiveExt","window","single handheld controller and host snapshots"},
  {UINT32_C(0x860BF292),"sceCtrlPeekBufferPositiveExt2","window","single handheld controller and host snapshots"},
  {UINT32_C(0x15F96FB0),"sceCtrlReadBufferNegative","window","single handheld controller and host snapshots"},
  {UINT32_C(0x27A0C5FB),"sceCtrlReadBufferNegative2","window","single handheld controller and host snapshots"},
  {UINT32_C(0xC4226A3E),"sceCtrlReadBufferPositive2","window","single handheld controller and host snapshots"},
  {UINT32_C(0xE2D99296),"sceCtrlReadBufferPositiveExt","window","single handheld controller and host snapshots"},
  {UINT32_C(0xA7178860),"sceCtrlReadBufferPositiveExt2","window","single handheld controller and host snapshots"},
  {UINT32_C(0xB1DC4378),"sceCtrlSetSamplingModeExt","window","single handheld controller and host snapshots"},
  {UINT32_C(0xBD27F830),"sceCtrlGetSamplingModeExt","window","single handheld controller and host snapshots"},
  {UINT32_C(0x324F1B66),"sceCtrlGetControllerPortInfo","window","single handheld controller and host snapshots"},
  {UINT32_C(0x1FFFD965),"sceCtrlIsMultiControllerSupported","window","single handheld controller and host snapshots"},
  {UINT32_C(0x67E7AB83),"sceCtrlReadBufferPositive","window","host snapshots and modeled 60Hz blocking reads; port zero; one sample"},
  {UINT32_C(0xA497B150),"sceCtrlSetSamplingMode","window","host snapshots and modeled 60Hz blocking reads; port zero; one sample"},
  {UINT32_C(0xA9C3CED6),"sceCtrlPeekBufferPositive","window","host snapshots and modeled 60Hz blocking reads; port zero; one sample"},
  {UINT32_C(0xEC752AAF),"sceCtrlGetSamplingMode","window","host snapshots and modeled 60Hz blocking reads; port zero; one sample"},
#endif
#ifdef VX_ENABLE_AUDIO
  {UINT32_C(0x12FB1767),"sceAudioOutGetAdopt","audio","CoreAudio PCM output ports"},
  {UINT32_C(0x940CE469),"sceAudioOutSetAlcMode","audio","CoreAudio PCM output ports"},
  {UINT32_C(0x9A5370C4),"sceAudioOutGetRestSample","audio","queued sample count at buffer granularity; three-buffer S16 PCM AudioQueue output"},
  {UINT32_C(0x02DB3F5F),"sceAudioOutOutput","audio","bounded S16 PCM output; no codec decoding"},
  {UINT32_C(0x5BC341E4),"sceAudioOutOpenPort","audio","bounded S16 PCM output; no codec decoding"},
  {UINT32_C(0x64167F11),"sceAudioOutSetVolume","audio","bounded S16 PCM output; no codec decoding"},
  {UINT32_C(0x69E2E6B5),"sceAudioOutReleasePort","audio","bounded S16 PCM output; no codec decoding"},
  {UINT32_C(0xB8BA0D07),"sceAudioOutSetConfig","audio","preserves port identity and volume across PCM reconfiguration"},
  {UINT32_C(0x9C8EDAEA),"sceAudioOutGetConfig","audio","bounded S16 PCM output; no codec decoding"},
#endif
 };
 if(count)*count=sizeof capabilities/sizeof capabilities[0];
 return capabilities;
}

static _Thread_local uint32_t memory_base;
/* VitaSDK sysmem.h and db/360/SceSysmem.yml. A bounded first-fit guest arena,
   not an implementation of physical/VRAM allocation or arbitrary mappings. */
#define K_ARGUMENT UINT32_C(0x80020005)
#define K_ADDRESS UINT32_C(0x80020006)
#define K_UID UINT32_C(0x80024501)
#define K_MEMORY UINT32_C(0x8002710B)
#define K_TIMEOUT UINT32_C(0x80028005)
#define K_SEMA_ZERO UINT32_C(0x80028102)
#define K_SEMA_OVERFLOW UINT32_C(0x80028103)
typedef struct { uint32_t uid,base,size; } memory_block;
typedef struct { uint32_t uid,count,maximum; } semaphore;
static _Thread_local memory_block blocks[32];
static _Thread_local semaphore semaphores[32];
static _Thread_local uint32_t heap_start,heap_capacity,next_uid=0x10000;
#ifdef VX_ENABLE_WINDOW
static _Thread_local uint32_t sampling_mode,sampling_mode_ext;
static _Thread_local uint64_t ctrl_last_read_us,touch_last_read_us[2];
static _Thread_local uint32_t touch_sampling[2],touch_force[2];
#endif
int vx_runtime_set_heap(uint32_t start,uint32_t capacity) {
 if((start&4095)||(capacity&4095)||(uint64_t)start+capacity>UINT32_MAX)return -1;
 for(int i=0;i<32;i++)if(blocks[i].uid)return -1;
 heap_start=start;heap_capacity=capacity;return 0;
}
void vx_runtime_set_memory_base(uint32_t base) { memory_base=base; }
uint32_t vx_runtime_get_memory_base(void) { return memory_base; }
static _Thread_local int root = -1;
static _Thread_local int app_root = -1;
static _Thread_local int files[32];
static _Thread_local unsigned char consoles[32];
static _Thread_local int ready;
static _Thread_local uint64_t process_epoch_ns;
static _Thread_local int process_epoch_ready;
static _Thread_local int stop_reason;
static _Thread_local uint32_t stop_status;
int vx_runtime_stop_requested(uint32_t *exit_status) {
 if(exit_status&&stop_reason)*exit_status=stop_status;
 return stop_reason;
}
void vx_runtime_reset_stop(void) { stop_reason=VX_STOP_NONE;stop_status=0; }
static void init(void) {
 if(!ready){for(int i=0;i<32;i++)files[i]=-1;ready=1;}
 if(!process_epoch_ready){struct timespec t;if(!clock_gettime(CLOCK_MONOTONIC,&t)){
  process_epoch_ns=(uint64_t)t.tv_sec*UINT64_C(1000000000)+(uint32_t)t.tv_nsec;
  process_epoch_ready=1;
 }}
}
static int process_time(uint64_t *us) {
 struct timespec t;
 if(!process_epoch_ready||clock_gettime(CLOCK_MONOTONIC,&t))return -1;
 uint64_t now=(uint64_t)t.tv_sec*UINT64_C(1000000000)+(uint32_t)t.tv_nsec;
 if(now<process_epoch_ns){errno=EIO;return -1;}
 *us=(now-process_epoch_ns)/1000;return 0;
}
static int range(uint32_t p,uint32_t n,size_t size) {
 return p>=memory_base&&(size_t)(p-memory_base)<=size&&n<=size-(size_t)(p-memory_base);
}
static uint8_t *guest_ptr(uint8_t *mem,uint32_t p) { return mem+(p-memory_base); }
static uint32_t read32(const uint8_t *p) { return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24; }
__attribute__((weak,noinline)) void vx_guest_memory_written(void) {}
static void write32(uint8_t *p,uint32_t value) { vx_guest_memory_written();for(int i=0;i<4;i++)p[i]=(uint8_t)(value>>(8*i)); }
static int guest_name(uint8_t *mem,uint32_t address,size_t size) {
 if(!address||!range(address,1,size))return 0;
 size_t available=size-(size_t)(address-memory_base);
 return memchr(guest_ptr(mem,address),0,available<32?available:32)!=0;
}
static memory_block *find_block(uint32_t uid) { for(int i=0;i<32;i++)if(blocks[i].uid==uid&&uid)return &blocks[i];return 0; }
static semaphore *find_semaphore(uint32_t uid) { for(int i=0;i<32;i++)if(semaphores[i].uid==uid&&uid)return &semaphores[i];return 0; }
/* Vita errno encoding follows newlib values; Darwin values are not portable. */
static void kernel_reset(void);
static uint32_t err(void) {
 uint32_t e;
 switch(errno) {
  case ENOENT:e=2;break;case EIO:e=5;break;case EBADF:e=9;break;
  case EACCES:e=13;break;case EEXIST:e=17;break;case ENOTDIR:e=20;break;
  case EISDIR:e=21;break;case EMFILE:e=24;break;case ENOSPC:e=28;break;
  case EFBIG:e=27;break;case EROFS:e=30;break;case ENOTEMPTY:e=39;break;case ELOOP:e=40;break;default:e=22;break;
 }
 return UINT32_C(0x80010000)|e;
}
int vx_runtime_mount(const char *path) { init(); if(root>=0)return -1;root=open(path,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);return root<0?-1:0; }
int vx_runtime_mount_app(const char *path) { init();if(app_root>=0)return -1;app_root=open(path,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);return app_root<0?-1:0; }
void vx_runtime_shutdown(void) {
#ifdef VX_ENABLE_GXM
 vx_gxm_shutdown();
#endif
#ifdef VX_ENABLE_AUDIO
 vx_audio_shutdown();
#endif
#ifdef VX_ENABLE_NGS
 vx_ngs_shutdown();
#endif
#ifdef VX_ENABLE_AUDIODEC
 vx_audiodec_shutdown();
#endif
#ifdef VX_ENABLE_DISPLAY
 vx_display_shutdown();
#endif
 kernel_reset();memset(blocks,0,sizeof blocks);memset(semaphores,0,sizeof semaphores);
 heap_start=heap_capacity=0;next_uid=0x10000;
#ifdef VX_ENABLE_WINDOW
 sampling_mode=sampling_mode_ext=0;ctrl_last_read_us=0;memset(touch_sampling,0,sizeof touch_sampling);memset(touch_force,0,sizeof touch_force);memset(touch_last_read_us,0,sizeof touch_last_read_us);
#endif
 init();for(int i=0;i<32;i++)if(files[i]>=0){close(files[i]);files[i]=-1;}if(root>=0)close(root);root=-1;if(app_root>=0)close(app_root);app_root=-1;vx_runtime_reset_stop();process_epoch_ready=0;process_epoch_ns=0;memory_base=0; }
/* Pin each intermediate component below the mounted directory. The returned
   descriptor owns a reference even when the path has just one component. */
static int io_parent(int mount,const char *name,int save,char path[240],const char **leaf) {
 size_t length=strlen(name);
 if(!length||length>=240||strchr(name,'\\')||(save&&strchr(name,':'))){errno=EINVAL;return -1;}
 memcpy(path,name,length+1);
 int dir=fcntl(mount,F_DUPFD_CLOEXEC,0);
 if(dir<0)return -1;
 for(char *part=path;;){
  char *slash=strchr(part,'/');if(slash)*slash=0;
  if(!*part||!strcmp(part,".")||!strcmp(part,"..")||(save&&!strncasecmp(part,".vitanx-",8))){
   close(dir);errno=EINVAL;return -1;
  }
  if(!slash){*leaf=part;return dir;}
  int next=openat(dir,part,O_RDONLY|O_NOFOLLOW|O_DIRECTORY|O_CLOEXEC);
  int saved=errno;
  close(dir);
  if(next<0){errno=saved;return -1;}
  dir=next;part=slash+1;
 }
}
static int io_open(int mount,const char *name,int save,int flags) {
 char path[240];const char *leaf;
 int dir=io_parent(mount,name,save,path,&leaf);
 if(dir<0)return -1;
 int fd=openat(dir,leaf,flags|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC,0600);
 int saved=errno;close(dir);errno=saved;
 return fd;
}
static const char *io_save_name(uint32_t ptr,uint8_t *mem,size_t size) {
 if(!range(ptr,1,size))return NULL;
 const char *name=(const char *)guest_ptr(mem,ptr);
 size_t available=size-(size_t)(ptr-memory_base);
 size_t limit=available<240?available:240;
 const char *end=memchr(name,0,limit);
 if(!end||end-name<=10||strncmp(name,"savedata0:",10))return NULL;
 name+=10;
 return *name=='/'?name+1:name;
}
/* VitaSDK SceIoStat, with explicit on-wire type bits and UTC timestamps. */
typedef struct {uint16_t year,month,day,hour,minute,second;uint32_t usec;} guest_io_date;
typedef struct {
 uint32_t mode,attr;
 uint64_t size;
 guest_io_date created,accessed,modified;
 uint32_t device_private[6];
} guest_io_stat;
_Static_assert(sizeof(guest_io_stat)==0x58,"Vita stat layout");
static guest_io_date io_date(struct timespec stamp) {
 struct tm value;
 if(!gmtime_r(&stamp.tv_sec,&value)||value.tm_year < -1900||value.tm_year>63635)return (guest_io_date){0};
 return (guest_io_date){value.tm_year+1900,value.tm_mon+1,value.tm_mday,
                        value.tm_hour,value.tm_min,value.tm_sec,(uint32_t)(stamp.tv_nsec/1000)};
}
static uint32_t io_getstat(uint32_t *r,uint8_t *mem,size_t size) {
 if(!range(r[0],1,size)||!r[1]||!range(r[1],sizeof(guest_io_stat),size))return VX_EINVAL;
 const char *name=(const char *)guest_ptr(mem,r[0]);
 size_t available=size-(size_t)(r[0]-memory_base);
 size_t limit=available<240?available:240;
 const char *end=memchr(name,0,limit);
 if(!end)return VX_EINVAL;
 int save=end-name>=10&&!strncmp(name,"savedata0:",10);
 int asset=end-name>=5&&!strncmp(name,"app0:",5);
 int mount=save?root:app_root;
 if((!save&&!asset)||mount<0)return VX_EINVAL;
 name+=save?10:5;
 if(*name=='/')name++;
 struct stat st;
 int status;
 if(!*name)status=fstat(mount,&st);
 else{
  char path[240];const char *leaf;
  int dir=io_parent(mount,name,save,path,&leaf);
  if(dir<0)return err();
  status=fstatat(dir,leaf,&st,AT_SYMLINK_NOFOLLOW);
  int saved=errno;close(dir);errno=saved;
 }
 if(status)return err();
 if(!S_ISREG(st.st_mode)&&!S_ISDIR(st.st_mode))return VX_EINVAL;
 uint32_t kind=S_ISDIR(st.st_mode)?0x1000:0x2000;
 guest_io_stat info={.mode=kind|(st.st_mode&0700),.attr=kind>>8,.size=S_ISREG(st.st_mode)?(uint64_t)st.st_size:0};
#ifdef __APPLE__
 info.created=io_date(st.st_birthtimespec);
 info.accessed=io_date(st.st_atimespec);
 info.modified=io_date(st.st_mtimespec);
#else
 info.created=io_date(st.st_ctim);
 info.accessed=io_date(st.st_atim);
 info.modified=io_date(st.st_mtim);
#endif
 vx_guest_memory_written();
 memcpy(guest_ptr(mem,r[1]),&info,sizeof info);
 return 0;
}
static uint32_t io_save_mutation(uint32_t nid,uint32_t *r,uint8_t *mem,size_t size) {
 const char *name=io_save_name(r[0],mem,size);
 if(root<0||!name)return VX_EINVAL;
 char path[240];const char *leaf;
 int dir=io_parent(root,name,1,path,&leaf);
 if(dir<0)return err();
 uint32_t result=0;
 if(nid==UINT32_C(0x9670D39F)){
  if(mkdirat(dir,leaf,0700))result=err();
 }else if(nid==UINT32_C(0xF737E369)){
  char target[240];const char *target_leaf;
  const char *target_name=io_save_name(r[1],mem,size);
  if(!target_name)result=VX_EINVAL;
  else{
   int target_dir=io_parent(root,target_name,1,target,&target_leaf);
   if(target_dir<0)result=err();
   else{
    if(renameat(dir,leaf,target_dir,target_leaf))result=err();
    close(target_dir);
   }
  }
 }else if(unlinkat(dir,leaf,nid==UINT32_C(0xE9F91EC8)?AT_REMOVEDIR:0)){
  result=err();
 }
 close(dir);
 return result;
}
#ifdef VX_ENABLE_WINDOW
enum {CTRL_VALID=1,CTRL_READ=2,CTRL_NEGATIVE=4,CTRL_WIRELESS=8,CTRL_STICK_BUTTONS=16,CTRL_EXT_MODE=32};
static unsigned ctrl_import_flags(uint32_t nid){
  switch(nid){
   case UINT32_C(0xA9C3CED6):return CTRL_VALID;
   case UINT32_C(0x67E7AB83):return CTRL_VALID | CTRL_READ;
   case UINT32_C(0x104ED1A7):return CTRL_VALID | CTRL_NEGATIVE;
   case UINT32_C(0x81A89660):return CTRL_VALID | CTRL_NEGATIVE | CTRL_WIRELESS;
   case UINT32_C(0x15F81E8C):return CTRL_VALID | CTRL_WIRELESS;
   case UINT32_C(0xA59454D3):return CTRL_VALID | CTRL_EXT_MODE;
   case UINT32_C(0x860BF292):return CTRL_VALID | CTRL_WIRELESS | CTRL_STICK_BUTTONS | CTRL_EXT_MODE;
   case UINT32_C(0x15F96FB0):return CTRL_VALID | CTRL_READ | CTRL_NEGATIVE;
   case UINT32_C(0x27A0C5FB):return CTRL_VALID | CTRL_READ | CTRL_NEGATIVE | CTRL_WIRELESS;
   case UINT32_C(0xC4226A3E):return CTRL_VALID | CTRL_READ | CTRL_WIRELESS;
   case UINT32_C(0xE2D99296):return CTRL_VALID | CTRL_READ | CTRL_EXT_MODE;
   case UINT32_C(0xA7178860):return CTRL_VALID | CTRL_READ | CTRL_WIRELESS | CTRL_STICK_BUTTONS | CTRL_EXT_MODE;
   default:return 0;
  }
}

static uint32_t window_read_input(uint32_t nid,uint32_t port,uint32_t address,uint8_t *mem){
 vx_window_input input;
 if(vx_display_input_state(&input))return VX_ENOSYS;
 uint64_t us=0;process_time(&us);
 uint8_t *sample=guest_ptr(mem,address);
 unsigned flags=ctrl_import_flags(nid);
 memset(sample,0,flags?32:144);
 for(unsigned i=0;i<8;i++)sample[i]=(uint8_t)(us>>(i*8));
 if(flags){
  uint32_t buttons=input.buttons;
  if(flags&CTRL_WIRELESS){
   buttons=(buttons&~UINT32_C(0x300))|input.ext_buttons;
   if(!(flags&CTRL_STICK_BUTTONS))buttons&=~6u;
  }else buttons&=~UINT32_C(0x0c06);
  write32(sample+8,flags&CTRL_NEGATIVE?~buttons:buttons);
  uint32_t mode=flags&CTRL_EXT_MODE?sampling_mode_ext:sampling_mode;
  sample[12]=mode?input.lx:128;sample[13]=mode?input.ly:128;
  sample[14]=mode?input.rx:128;sample[15]=mode?input.ry:128;
  for(unsigned i=0;i<12;i++)sample[16+i]=(buttons&(UINT32_C(0x10)<<i))?255:0;
  if(flags&CTRL_WIRELESS){
   sample[20]=input.left_trigger;sample[21]=input.right_trigger;
  }
  if(flags&CTRL_READ)ctrl_last_read_us=us;
 }else{
  if(touch_sampling[port]&&input.touch_down[port]){
   write32(sample+12,1);sample[16]=input.touch_id[port];sample[17]=touch_force[port]?128:0;
   uint16_t x=input.touch_x[port]>1919?1919:input.touch_x[port];
   uint16_t y=input.touch_y[port]>1087?1087:input.touch_y[port];
   sample[18]=(uint8_t)x;sample[19]=(uint8_t)(x>>8);
   sample[20]=(uint8_t)y;sample[21]=(uint8_t)(y>>8);
  }
  if(nid==UINT32_C(0x169A1D58))touch_last_read_us[port]=us;
 }
 return 1;
}
#endif
#include "vita_kernel.inc"
#ifdef VX_ENABLE_WINDOW
static uint32_t window_read(uint32_t nid,uint32_t port,uint32_t address,uint8_t *mem,uint64_t last_read){
 uint64_t now;
 if(last_read&&!process_time(&now)&&now<last_read+16667){
  uint64_t deadline=last_read+16667;
  if(kernel_active){
   kernel_thread *t=&kernel_threads[kernel_current];
   t->wait=(kernel_wait){.kind=KW_INPUT,.object=port,.mode=nid,.out=address,
                        .deadline=deadline,.ticket=++kernel_ticket};
   t->state=KT_WAIT;kernel_stats.waits++;
   return 0;
  }
  struct timespec delay={0,(long)((deadline-now)*1000)};
  while(nanosleep(&delay,&delay)&&errno==EINTR){}
 }
 return window_read_input(nid,port,address,mem);
}
#endif

#ifdef VX_ENABLE_GXM
/* Reserve the GXM guest worker stack in the existing memory-block arena so it
   cannot overlap game allocations. No host pointer enters guest state. */
static uint32_t gxm_queue_worker_create(uint32_t entry,uint32_t *worker,uint8_t *mem,size_t size){
 if(!kernel_active)return UINT32_C(0x805b0017);
 if(!vx_guest_target_valid(entry))return UINT32_C(0x805b0004);
 if(!heap_capacity||!range(heap_start,heap_capacity,size)||next_uid>INT32_MAX-2)return UINT32_C(0x805b0002);
 kernel_thread *t=0;memory_block *block=0;
 for(int i=1;i<32;i++)if(!kernel_threads[i].uid){t=&kernel_threads[i];break;}
 for(int i=0;i<32;i++)if(!blocks[i].uid){block=&blocks[i];break;}
 if(!t||!block)return UINT32_C(0x805b0002);
 const uint32_t stack_size=65536;uint64_t candidate=heap_start,end=(uint64_t)heap_start+heap_capacity;
 for(int pass=0;pass<=32&&candidate+stack_size<=end;pass++){
  uint64_t next=candidate;
  for(int i=0;i<32;i++)if(blocks[i].uid&&candidate<(uint64_t)blocks[i].base+blocks[i].size&&blocks[i].base<candidate+stack_size){
   uint64_t after=(uint64_t)blocks[i].base+blocks[i].size;if(after>next)next=after;
  }
  if(next!=candidate){candidate=next;continue;}
  *block=(memory_block){kernel_uid(),(uint32_t)candidate,stack_size};
  memset(guest_ptr(mem,block->base),0,stack_size);
  *t=(kernel_thread){.uid=kernel_uid(),.entry=entry,.priority=64,.stack_uid=block->uid,
                     .stack_base=block->base,.stack_size=stack_size,.state=KT_NEW};
  kernel_stats.threads_created++;*worker=t->uid;return 0;
 }
 return UINT32_C(0x805b0002);
}
static void gxm_queue_worker_destroy(uint32_t worker){
 kernel_thread *t=kernel_find_thread(worker);
 if(t&&t!=&kernel_threads[0]&&t->state==KT_NEW)kernel_reap(t);
}
#endif


uint32_t vx_import_vfp(uint32_t nid,uint32_t r[16],uint32_t f[64],uint8_t *mem,size_t size){
 vx_guest_memory_written();
#ifdef VX_ENABLE_GXM
 uint32_t result;
 if(vx_gxm_float_import(nid,r,f,mem,size,memory_base,&result))return result;
#else
 (void)f;
#endif
 return vx_import(nid,r,mem,size);
}
uint32_t vx_import(uint32_t nid,uint32_t r[16],uint8_t *mem,size_t size) {
#ifdef VX_ENABLE_WINDOW
 unsigned flags;
#endif
 vx_guest_memory_written();
 init();uint32_t result=VX_ENOSYS;
 /* Official VitaSDK SceLibKernel/SceProcessmgr/SceKernelThreadMgr exports.
    Guest scheduling intercepts child exits; direct-import fallback stops the caller.
    Dispatch must poll this state before executing a translated continuation. */
 if(stop_reason){r[0]=stop_status;return stop_status;}
 if(kernel_import(nid,r,mem,size,&result)){}
 else if(nid==UINT32_C(0x7595D9AA)||nid==UINT32_C(0xC053DC6B)||
    nid==UINT32_C(0x1D17DECF)||nid==UINT32_C(0x0C8A38E1)) {
  stop_reason=(nid==UINT32_C(0x7595D9AA)||nid==UINT32_C(0xC053DC6B))?VX_STOP_PROCESS:VX_STOP_THREAD;
  stop_status=r[0];result=stop_status;
 }
 else if(nid==UINT32_C(0x2BE3E066)){result=process_param&&range(process_param,8,size)?process_param:0;}
 else if(nid==UINT32_C(0xE5AA625C))result=1; /* sceKernelGetStdout */
 else if(nid==UINT32_C(0xFA5E3ADA))result=2; /* sceKernelGetStderr */
 else if(nid==UINT32_C(0xB9D5EBDE)) { /* sceKernelAllocMemBlock */
  /* Memblock names may be truncated to the kernel object name width.
     Require either a readable prefix or a terminator before backing ends. */
  if(!r[0]||(!range(r[0],32,size)&&!guest_name(mem,r[0],size)))result=K_ADDRESS;
  else if(r[1]!=UINT32_C(0x0C20D060)&&r[1]!=UINT32_C(0x0C208060))result=UINT32_C(0x8002000C);
  else if(!r[2]||(r[2]&4095))result=UINT32_C(0x8002000B);
  else if(r[3])result=range(r[3],64,size)?VX_ENOSYS:K_ADDRESS;
  else if(!heap_capacity||!range(heap_start,heap_capacity,size))result=K_MEMORY;
  else {
   result=K_MEMORY;memory_block *slot=0;
   for(int i=0;i<32;i++)if(!blocks[i].uid){slot=&blocks[i];break;}
   uint64_t candidate=heap_start,end=(uint64_t)heap_start+heap_capacity;
   if(slot)for(int pass=0;pass<=32&&candidate+r[2]<=end;pass++){
    uint64_t next=candidate;
    for(int i=0;i<32;i++)if(blocks[i].uid&&candidate<(uint64_t)blocks[i].base+blocks[i].size&&blocks[i].base<candidate+r[2]){
     uint64_t after=(uint64_t)blocks[i].base+blocks[i].size;if(after>next)next=after;
    }
    if(next!=candidate){candidate=next;continue;}
    if(next_uid>=INT32_MAX)break;
    *slot=(memory_block){next_uid++,(uint32_t)candidate,r[2]};
    memset(guest_ptr(mem,slot->base),0,slot->size);result=slot->uid;break;
   }
  }
 }
 else if(nid==UINT32_C(0xA91E15EE)) { /* sceKernelFreeMemBlock */
  memory_block *block=find_block(r[0]);
  if(!block)result=K_UID;
  else {*block=(memory_block){0};result=0;}
 }
 else if(nid==UINT32_C(0xB8EF5818)) { /* sceKernelGetMemBlockBase */
  memory_block *block=find_block(r[0]);
  if(!block)result=K_UID;
  else if(!r[1]||!range(r[1],4,size))result=K_ADDRESS;
  else {write32(guest_ptr(mem,r[1]),block->base);result=0;}
 }
 else if(nid==UINT32_C(0xA33B99D1)) { /* sceKernelFindMemBlockByAddr */
  result=K_UID;
  if(!r[1]||(uint64_t)r[0]+r[1]>UINT64_C(0x100000000))result=K_ARGUMENT;
  else for(int i=0;i<32;i++)if(blocks[i].uid&&r[0]>=blocks[i].base&&(uint64_t)r[0]+r[1]<=(uint64_t)blocks[i].base+blocks[i].size){result=blocks[i].uid;break;}
 }
 /* Immediate semaphore operations also work outside the scheduler; blocking
    guest waits are intercepted above by the cooperative kernel. */
 else if(nid==UINT32_C(0x1BD67366)) { /* public sceKernelCreateSema */
  if(!guest_name(mem,r[0],size)||!range(r[13],4,size))result=K_ADDRESS;
  else if(r[1]||read32(guest_ptr(mem,r[13])))result=VX_ENOSYS;
  else if((int32_t)r[2]<0||!r[3]||r[3]>INT32_MAX||r[2]>r[3])result=K_ARGUMENT;
  else {result=K_MEMORY;for(int i=0;i<32;i++)if(!semaphores[i].uid&&next_uid<INT32_MAX){semaphores[i]=(semaphore){next_uid++,r[2],r[3]};result=semaphores[i].uid;break;}}
 }
 else if(nid==UINT32_C(0xDB32948A)) {
  semaphore *sema=find_semaphore(r[0]);if(!sema)result=K_UID;else {*sema=(semaphore){0};result=0;}
 }
 else if(nid==UINT32_C(0xE6B761D1)||nid==UINT32_C(0x866EF048)||nid==UINT32_C(0x0C7B834B)) {
  semaphore *sema=find_semaphore(r[0]);
  if(!sema)result=K_UID;
  else if(!r[1]||r[1]>INT32_MAX)result=K_ARGUMENT;
  else if(nid==UINT32_C(0xE6B761D1)){
   if(r[1]>sema->maximum-sema->count)result=K_SEMA_OVERFLOW;else {sema->count+=r[1];result=0;}
  } else if(nid==UINT32_C(0x0C7B834B)&&r[2]&&(!range(r[2],4,size)))result=K_ADDRESS;
  else if(sema->count>=r[1]){sema->count-=r[1];result=0;}
  else if(nid==UINT32_C(0x866EF048))result=K_SEMA_ZERO;
  else if(r[2]&&!read32(guest_ptr(mem,r[2])))result=K_TIMEOUT;
  else result=VX_ENOSYS;
 }
#ifdef VX_ENABLE_WINDOW
 else if(nid==UINT32_C(0x1B9C5D14)||nid==UINT32_C(0x26531526)||nid==UINT32_C(0x10A2CA25)||nid==UINT32_C(0xB18370C2)||nid==UINT32_C(0x41194411)){
  const uint32_t bad=UINT32_C(0x80350001);
  if(r[0]>1)result=bad;
  else if(nid==UINT32_C(0x1B9C5D14)){if(r[1]>1)result=bad;else{touch_sampling[r[0]]=r[1];result=0;}}
  else if(nid==UINT32_C(0x26531526)){if(!r[1]||!range(r[1],4,size))result=bad;else{write32(guest_ptr(mem,r[1]),touch_sampling[r[0]]);result=0;}}
  else if(nid==UINT32_C(0x10A2CA25)){
   if(!r[1]||!range(r[1],48,size))result=bad;
   else{uint8_t *p=guest_ptr(mem,r[1]);memset(p,0,48);const uint16_t dims[8]={0,0,1919,1087,0,0,1919,1087};for(int i=0;i<8;i++){p[i*2]=(uint8_t)dims[i];p[i*2+1]=(uint8_t)(dims[i]>>8);}p[16]=1;p[17]=128;result=0;}
  }else{touch_force[r[0]]=nid==UINT32_C(0xB18370C2);result=0;}
 }
 else if(nid==UINT32_C(0xFF082DF0)||nid==UINT32_C(0x169A1D58)){
  if(r[0]>1||!r[2]||r[2]>64||!r[1]||!range(r[1],144,size))result=UINT32_C(0x80350001);
  else result=window_read(nid,r[0],r[1],mem,nid==UINT32_C(0x169A1D58)?touch_last_read_us[r[0]]:0);
 }
 else if(nid==UINT32_C(0xA497B150)||nid==UINT32_C(0xB1DC4378)) {
  uint32_t *mode=nid==UINT32_C(0xA497B150)?&sampling_mode:&sampling_mode_ext;
  if(r[0]>2)result=K_ARGUMENT;else {result=*mode;*mode=r[0];}
 }
 else if(nid==UINT32_C(0xEC752AAF)||nid==UINT32_C(0xBD27F830)) {
  uint32_t mode=nid==UINT32_C(0xEC752AAF)?sampling_mode:sampling_mode_ext;
  if(!r[0]||!range(r[0],4,size))result=K_ADDRESS;else {write32(guest_ptr(mem,r[0]),mode);result=0;}
 }
 else if(nid==UINT32_C(0x324F1B66)) {
  if(!r[0]||!range(r[0],16,size))result=K_ADDRESS;
  else {uint8_t *ports=guest_ptr(mem,r[0]);memset(ports,0,16);ports[0]=1;result=0;}
 }
 else if(nid==UINT32_C(0x1FFFD965))result=0;
 else if((flags=ctrl_import_flags(nid))!=0){
  if(r[0]>(flags&CTRL_WIRELESS?4u:0u)||!r[2]||r[2]>64)result=K_ARGUMENT;
  else if(!r[1]||!range(r[1],32,size))result=K_ADDRESS;
  else if(r[0])result=0; /* The virtual handheld has only its built-in port. */
  else result=window_read(nid,r[0],r[1],mem,flags&CTRL_READ?ctrl_last_read_us:0);
 }

#endif
 /* VitaSDK processmgr.h returns wide clocks in r0/r1; pointer clocks use
    guest little-endian uint64 storage. Time starts at this runtime instance. */
 else if(nid==UINT32_C(0xB110C123)||nid==UINT32_C(0x89DA0967)||
         nid==UINT32_C(0xE9F973B1)||nid==UINT32_C(0xF5D0D4C6)||
         nid==UINT32_C(0x4C4672BF)||nid==UINT32_C(0xD37A8437)) {
  int pointer=nid==UINT32_C(0x4C4672BF)||nid==UINT32_C(0xD37A8437);
  int wide=nid==UINT32_C(0xB110C123)||nid==UINT32_C(0x89DA0967);
  uint64_t us;
  if(pointer&&(!r[0]||!range(r[0],8,size)))result=VX_EINVAL;
  else if(process_time(&us)){result=err();if(wide)r[1]=UINT32_MAX;}
  else if(pointer){for(int i=0;i<8;i++)guest_ptr(mem,r[0])[i]=(uint8_t)(us>>(i*8));result=0;}
  else {result=(uint32_t)us;if(wide)r[1]=(uint32_t)(us>>32);}
 }
 else if(nid==UINT32_C(0xF4EE4FA9)) {struct timespec t;if(clock_gettime(CLOCK_MONOTONIC,&t))result=err();else {uint64_t us=(uint64_t)t.tv_sec*1000000+t.tv_nsec/1000;r[1]=(uint32_t)(us>>32);result=(uint32_t)us;}}
 else if(nid==UINT32_C(0x4B675D05)) { if(r[0]>1000000)result=VX_EINVAL;else {struct timespec t={r[0]/1000000,(r[0]%1000000)*1000};int status;do {status=nanosleep(&t,&t);}while(status<0&&errno==EINTR);result=status<0?err():0;}}
 else if(nid==UINT32_C(0xCC67B6FD)||nid==UINT32_C(0x6C60AC61)) { /* raw/public open */
  result=VX_EINVAL;
  /* Required sceIoOpenOpt is two reserved uint32 words, ignored on FW3.60.
     Guest null and truncated pointers are rejected before any filesystem effect. */
  if((nid==UINT32_C(0x6C60AC61)||(r[3]!=0&&range(r[3],8,size)))&&range(r[0],1,size)) {
   const char *s=(const char*)guest_ptr(mem,r[0]);const char *end=memchr(s,0,size-(size_t)(r[0]-memory_base));
   if(end&&end-s<240) {
    int asset=end-s>5&&!strncmp(s,"app0:",5);
    int save=end-s>10&&!strncmp(s,"savedata0:",10);
    const char *name=asset?s+5:(save?s+10:s);if(*name=='/')name++;
    uint32_t f=r[1];
    if((!strcmp(s,"tty0:")||!strcmp(s,"tty1:")||!strcmp(s,"tty2:"))&&f>=1&&f<=3){
     result=VX_EMFILE;for(int i=0;i<32;i++)if(files[i]<0){int host=dup(s[3]=='2'?2:1);if(host<0)result=err();else{files[i]=host;consoles[i]=1;result=(uint32_t)i+3;}break;}
    }
    else if(asset&&app_root>=0&&f!=1)result=UINT32_C(0x8001001e); /* read-only mount */
    else if((asset&&app_root>=0)||(save&&root>=0)) {
     if(!(f&~UINT32_C(0xF03))&&(f&3)>=1&&(f&3)<=3&&(!(f&0x800)||(f&0x200))) {
      int flags=(f&3)==1?O_RDONLY:((f&3)==2?O_WRONLY:O_RDWR);
      if(f&0x100)flags|=O_APPEND;if(f&0x200)flags|=O_CREAT;if(f&0x400)flags|=O_TRUNC;if(f&0x800)flags|=O_EXCL;
      result=VX_EMFILE;
      for(int i=0;i<32;i++)if(files[i]<0){
       int host=io_open(asset?app_root:root,name,save,flags);
       if(host<0)result=err();else {
        struct stat st;
        if(fstat(host,&st)||!S_ISREG(st.st_mode)){close(host);result=VX_EINVAL;}
        else {files[i]=host;consoles[i]=0;result=(uint32_t)i+3;}
       }break;
      }
     }
    }
   }
  }
 }

 /* Public SceLibKernel save paths, qualified through io-nids.json. */
 else if(nid==UINT32_C(0xBCA5B623))result=io_getstat(r,mem,size);
 else if(nid==UINT32_C(0x9670D39F)||nid==UINT32_C(0xE20ED0F3)||
         nid==UINT32_C(0xF737E369)||nid==UINT32_C(0xE9F91EC8)) {
  result=io_save_mutation(nid,r,mem,size);
 }

 else if(nid==UINT32_C(0x34EFD876)||nid==UINT32_C(0xFDB32293)) {
  int wr=nid==UINT32_C(0x34EFD876);int fd=-1;
  if(wr&&(r[0]==1||r[0]==2))fd=(int)r[0];
  else if(r[0]>=3&&r[0]<35)fd=(!wr&&consoles[r[0]-3]&&files[r[0]-3]>=0)?0:files[r[0]-3];
  if(fd<0)result=VX_EBADF;
  else if(!range(r[1],r[2],size)||r[2]>INT32_MAX)result=VX_EINVAL;
  else {ssize_t n;do {n=wr?write(fd,guest_ptr(mem,r[1]),r[2]):read(fd,guest_ptr(mem,r[1]),r[2]);}while(n<0&&errno==EINTR);result=n<0?err():(uint32_t)n;}
 }
 /* AAPCS: fd r0, alignment hole r1, SceOff r2/r3, origin [sp]. */
 else if(nid==UINT32_C(0x99BA173E)) {
  _Static_assert(sizeof(off_t)==8,"64-bit host file offsets required");
  uint64_t value;uint32_t failure=0;
  if(r[0]<3||r[0]>=35||files[r[0]-3]<0)failure=VX_EBADF;
  else if(!range(r[13],4,size)||(r[13]&3))failure=K_ADDRESS;
  else {
   uint32_t origin=read32(guest_ptr(mem,r[13]));
   int whence=origin==0?SEEK_SET:origin==1?SEEK_CUR:SEEK_END;
   if(origin>2)failure=VX_EINVAL;
   else if(consoles[r[0]-3])failure=UINT32_C(0x8001001D); /* ESPIPE */
   else {
    int64_t offset=(int64_t)((uint64_t)r[2]|((uint64_t)r[3]<<32));off_t pos;
    do {pos=lseek(files[r[0]-3],(off_t)offset,whence);}while(pos<0&&errno==EINTR);
    if(pos<0)failure=err();else value=(uint64_t)pos;
   }
  }
  if(failure)value=(uint64_t)(int64_t)(int32_t)failure;
  r[1]=(uint32_t)(value>>32);result=(uint32_t)value;
 }
 /* VitaSDK db/360/SceIofilemgr.yml and psp2/io/fcntl.h:
    sceIoLseek32(fd, signed 32-bit offset, whence), not the 64-bit _sceIoLseek. */
 else if(nid==UINT32_C(0x49252B9B)) {
  if(r[0]<3||r[0]>=35||files[r[0]-3]<0)result=VX_EBADF;
  else if(r[2]>2)result=VX_EINVAL;
  else {
   int fd=files[r[0]-3];off_t base=0;int failed=0;
   if(r[2]==1){base=lseek(fd,0,SEEK_CUR);failed=base<0;}
   else if(r[2]==2){struct stat st;if(fstat(fd,&st))failed=1;else base=st.st_size;}
   if(failed)result=err();
   else {
    int64_t position=(int64_t)base+(int32_t)r[1];
    /* Reject before seeking: 32-bit result must not alias an error code. */
    if(position<0||position>INT32_MAX)result=VX_EINVAL;
    else {off_t n=lseek(fd,(off_t)position,SEEK_SET);result=n<0?err():(uint32_t)n;}
   }
  }
 }
 else if(nid==UINT32_C(0x16512F59)) { /* sceIoSyncByFd: bounded flag=0 only */
  if(r[0]<3||r[0]>=35||files[r[0]-3]<0)result=VX_EBADF;
  else if(r[1])result=VX_EINVAL;
  else {int status;do {status=fsync(files[r[0]-3]);}while(status<0&&errno==EINTR);result=status<0?err():0;}
 }
 else if(nid==UINT32_C(0xC70B8886)) {
  if(r[0]<3||r[0]>=35||files[r[0]-3]<0)result=VX_EBADF;
  else {int i=(int)r[0]-3;result=close(files[i])?err():0;files[i]=-1;}
 }
#ifdef VX_ENABLE_DISPLAY
 if(result==VX_ENOSYS){uint32_t display_result;
  if(vx_display_import(nid,r,mem,size,memory_base,&display_result))result=display_result;
 }
#endif
#ifdef VX_ENABLE_NGS
 if(result==VX_ENOSYS){
  uint32_t ngs_result;
  if(vx_ngs_import(nid,r,mem,size,memory_base,kernel_active?kernel_owner():0,&ngs_result))
   result=ngs_result;
 }
#endif
#ifdef VX_ENABLE_AUDIODEC
 if(result==VX_ENOSYS){
  uint32_t decode_result;
  if(vx_audiodec_import(nid,r,mem,size,memory_base,&decode_result))result=decode_result;
 }
#endif
#ifdef VX_ENABLE_AUDIO
 if(result==VX_ENOSYS){uint32_t audio_result;
  if(vx_audio_import(nid,r,mem,size,memory_base,&audio_result)){
   result=audio_result;
   if(result==VX_AUDIO_WOULD_BLOCK&&kernel_active){uint64_t now=0;process_time(&now);kernel_thread *t=&kernel_threads[kernel_current];
    t->audio_r2=r[2];t->audio_r3=r[3];
    t->wait=(kernel_wait){.kind=KW_AUDIO,.object=r[0],.count=r[1],.mode=nid,.out=vx_audio_port_generation(r[0]),.deadline=now+UINT64_C(30000000),.ticket=++kernel_ticket};t->state=KT_WAIT;kernel_stats.waits++;result=0;
   }
  }
 }
#endif
#ifdef VX_ENABLE_GXM
 if(result==VX_ENOSYS){uint32_t gxm_result;
  vx_gxm_set_queue_backend(gxm_queue_worker_create,gxm_queue_worker_destroy);
  if(vx_gxm_import(nid,r,mem,size,memory_base,&gxm_result)){
   result=gxm_result;
   if(result==VX_GXM_ALLOCATE){
    vx_gxm_allocation request={0};
    vx_gxm_take_allocation(&request);
    kernel_thread *t=&kernel_threads[kernel_current];
    uint32_t sp=r[13];
    uint32_t bottom=(sp-64)&~7u;
    if(kernel_active&&request.entry&&!t->callback_active&&!t->gxm_allocation.entry&&
       t->uid!=vx_gxm_queue_worker()&&sp>=72&&range(bottom,sp-bottom,size)&&
       (!t->stack_uid||bottom>=t->stack_base)&&vx_guest_target_valid(request.entry)){
     t->gxm_allocation=request;result=0;
    }else{
     result=vx_gxm_finish_allocation(&request,0,0,NULL,0,memory_base);
    }
   }
   if(result==VX_GXM_WOULD_BLOCK){
    result=UINT32_C(0x805b0017);
    if(kernel_active){
     kernel_thread *t=&kernel_threads[kernel_current];
     if(t->uid!=vx_gxm_queue_worker()){
      t->wait=(kernel_wait){.kind=KW_GXM,.object=r[0],.count=r[1],.mode=nid,
                            .out=r[2],.timeout=0,.ticket=++kernel_ticket};
      t->gxm_r3=r[3];
      t->state=KT_WAIT;kernel_stats.waits++;result=0;
     }
    }
   }
  }
 }
#endif
#ifdef VX_ENABLE_WINDOW
 /* Pump only at import boundaries, never at every translated instruction.
    Closing the native game window terminates the sole guest with status zero.
    Preserve a guest's earlier explicit exit status. */
 if(!stop_reason){vx_window_input input;
  if(!vx_display_input_state(&input)&&input.close_requested){stop_reason=VX_STOP_PROCESS;stop_status=0;}
 }
#endif
 r[0]=result;return result;
}
