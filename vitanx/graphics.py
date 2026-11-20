"""Opt-in original GXM/Metal, AudioQueue and Cocoa input runtime integration.

No device is opened while preparing a build. Shader catalog entries retain exact
original GXP bytes; unsupported shaders are reported rather than substituted.
"""
import ctypes as C
import json
from pathlib import Path
from vitaxnative.gxm_catalog import write_catalog

MEDIA_FILES=('vita_gxm.c','vita_gxm.h','vita_metal.m','vita_metal.h',
             'vita_display.m','vita_display.h','vita_frame.c','vita_frame.h',
             'vita_window.m','vita_window.h','vita_input.h','vita_audio.c','vita_audio.h')
MEDIA_FLAGS=('-DVX_ENABLE_GXM','-DVX_ENABLE_DISPLAY','-DVX_ENABLE_WINDOW','-DVX_ENABLE_AUDIO','-fobjc-arc')
MEDIA_FRAMEWORKS=('Foundation','Metal','Cocoa','QuartzCore','GameController','AudioToolbox')

def media_bindings():
    rows=json.loads(Path(__file__).with_name('media-nids.json').read_text())['bindings']
    return {(r['library_nid'],r['function_nid']):int(r['function_nid'],16) for r in rows}

def prepare_media(output, assets):
    output=Path(output)
    report=write_catalog(assets,output/'gxm_catalog.h')
    (output/'gxm-catalog.json').write_text(json.dumps(report,indent=2)+'\n')
    (output/'vitanx_media.c').write_text('#include "vita_gxm.h"\n#include "gxm_catalog.h"\n'
                                     'int vn_media_initialize(void){return vx_install_gxm_catalog();}\n')
    return report

def media_compile_args(output):
    output=Path(output)
    sources=[str(output/name) for name in MEDIA_FILES if name.endswith(('.c','.m'))]
    return [*MEDIA_FLAGS,*sources,str(output/'vitanx_media.c'),
            *[arg for name in MEDIA_FRAMEWORKS for arg in ('-framework',name)]]

class _GxmStats(C.Structure):
    _fields_=[(name,C.c_uint64) for name in ('fills','copies','bytes','draws','scenes')]+[('metal_status',C.c_int32)]
class _GxmReadiness(C.Structure):
    _fields_=[(name,C.c_uint64) for name in ('initialize_calls','initializations','registration_calls')]+[('initialized',C.c_uint32)]
class _AudioStats(C.Structure):
    _fields_=[(name,C.c_uint64) for name in ('ports_opened','buffers_queued','buffers_completed','frames_queued','frames_completed','timeouts')]
class _DisplayStats(C.Structure):
    _fields_=[(name,C.c_uint64) for name in ('frames_submitted','frames_presented','wait_calls','simulation_ticks')]+[(name,C.c_uint32) for name in ('guest_width','guest_height','target_width','target_height','render_hz','simulation_hz')]+[('metal_status',C.c_int32)]

def media_stats(runtime):
    result={}
    for key,kind in (('gxm',_GxmStats),('audio',_AudioStats),('display',_DisplayStats)):
        value=kind();get=getattr(runtime,'vx_'+key+'_get_stats');get.argtypes=[C.POINTER(kind)];get(C.byref(value))
        result[key]={name:getattr(value,name) for name,_ in kind._fields_}
    readiness=_GxmReadiness()
    runtime.vx_gxm_get_readiness.argtypes=[C.POINTER(_GxmReadiness)]
    runtime.vx_gxm_get_readiness(C.byref(readiness))
    result['gxm'].update({name:getattr(readiness,name) for name,_ in readiness._fields_})
    return result

class _Shader(C.Structure):
    _fields_=[('gxp',C.POINTER(C.c_uint8)),('size',C.c_size_t),('msl',C.c_char_p),
              *[(name,C.c_uint32) for name in ('stage','uniform_words','input_count','texture_mask','varyings')],
              ('registers',C.c_uint32*16),('components',C.c_uint32*16)]
_SHADER_RESOLVER=C.CFUNCTYPE(C.c_void_p,C.POINTER(C.c_uint8),C.c_size_t)

class RuntimeShaderTranslator:
    """Translate unpacked original GXP at actual registration, never shader names.

    The host owns immutable copies and metadata until runtime shutdown. Guest
    mutation therefore cannot change an already registered shader. A packed
    archive's compression is handled by original guest game code before this
    hook; no archive guessing, arbitrary MSL, or rendering substitution occurs.
    """
    MAX_SHADERS=256
    MAX_BYTES=64*1024*1024
    def __init__(self,runtime,output):
        self.runtime=runtime
        self.output=Path(output)/'runtime-shaders';self.output.mkdir(exist_ok=False)
        self.entries={};self.storage=[];self.bytes=0;self.diagnostics=[]
        self.callback=_SHADER_RESOLVER(self._safe_resolve)
        runtime.vx_gxm_set_shader_resolver.argtypes=[_SHADER_RESOLVER]
        runtime.vx_gxm_set_shader_resolver(self.callback)

    def _safe_resolve(self,pointer,size):
        try:return self._resolve(pointer,size)
        except Exception:return None

    def _resolve(self,pointer,size):
        import hashlib
        from vitaxnative.usse import translate_gxp
        # Native registration has checked backing memory and the declared span.
        # Retain a second bound before any ctypes read or filesystem operation.
        if not pointer or not 156<=size<=16*1024*1024:return None
        raw=C.string_at(pointer,size);digest=hashlib.sha256(raw).hexdigest()
        if digest in self.entries:return self.entries[digest]
        if len(self.entries)>=self.MAX_SHADERS or size>self.MAX_BYTES-self.bytes:
            return None
        self.bytes+=size;self.entries[digest]=None
        record={'sha256':digest,'bytes':size,'translation_supported':False}
        self.diagnostics.append(record)
        try:
            path=self.output/(digest+'.gxp')
            with path.open('xb') as stream:stream.write(raw)
            shader=translate_gxp(path)
            data=(C.c_uint8*size).from_buffer_copy(raw)
            msl=shader['msl'].encode('utf-8')
            inputs=shader['inputs']
            if len(inputs)>16:raise ValueError('runtime shader input limit')
            registers=(C.c_uint32*16)(*[p['resource_index'] for p in inputs])
            components=(C.c_uint32*16)(*[p['components'] for p in inputs])
            interface=shader['interface']
            metadata=_Shader(data,size,msl,int(shader['stage']=='fragment'),shader['uniform_words'],len(inputs),
                             shader['texture_mask'],int(interface['color'])|(int(interface['texcoord'])<<1),registers,components)
            self.storage.append((data,msl,metadata))
            self.entries[digest]=C.addressof(metadata)
            record.update({k:v for k,v in shader.items() if k not in ('msl','operations')})
            record['translation_supported']=True
        except Exception as error:
            # ctypes callbacks must never propagate an exception through C.
            record['reason']=str(error)
        self._write_report()
        return self.entries[digest]

    def _write_report(self):
        (self.output/'diagnostics.json').write_text(json.dumps(self.diagnostics,indent=2)+'\n')

    def report(self):
        return {'unique_programs':len(self.entries),'bytes_retained':self.bytes,
                'translated':sum(x['translation_supported'] for x in self.diagnostics),
                'unsupported':sum(not x['translation_supported'] for x in self.diagnostics),
                'programs':self.diagnostics,'scope':'original runtime GXP registration; bounded fail-closed USSE subset'}
