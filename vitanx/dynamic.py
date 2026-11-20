"""Live native translation extension for explicit authorized plaintext ELF inputs.

One compatibility-runtime instance owns the scheduler and memory. On a missing
PC, compile more original code, load signed native code, and resume the exact
suspended guest context. No restart, instruction skipping, or executable writes.
"""
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
from .fallback import TranslationCache
from vitaxnative.recompiler import translate_elf
from vitaxnative.elf_segments import inspect_elf_segments

ROOT=Path(__file__).resolve().parents[1]
class HostServiceFault(RuntimeError):
    guest_status=-9
    def __init__(self,message,context):
        self.context=context
        super().__init__(message)

class GuestState(C.Structure):
    _fields_=[('r',C.c_uint32*16),('f',C.c_uint32*64)] + [
        (name,C.c_uint32) for name in ('pc','n','z','c','v','fpscr')] + [
        ('instructions',C.c_uint64),('services',C.c_uint64),
        ('exclusive_epoch',C.c_uint64),('exclusive_memory',C.c_size_t)] + [
        (name,C.c_uint32) for name in ('exclusive_address','exclusive_size','exclusive_valid','tpidruro')]
RESUME=C.CFUNCTYPE(C.c_int,C.POINTER(GuestState),C.POINTER(C.c_uint8),C.c_size_t,C.c_uint32)
TARGET=C.CFUNCTYPE(C.c_int,C.c_uint32)

def command(argv):
    try:
        p=subprocess.run([str(x) for x in argv],capture_output=True,text=True,timeout=90)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError('native compilation/signing exceeded 90 seconds') from error
    if p.returncode: raise RuntimeError(p.stderr[-4000:])
    return p

class NativeSession:
    def __init__(self,source,output,*,imports=None,max_blocks=32,instruction_limit=1000000,tls=None,decode_traps=False,translation_limit=65536,heap_size=4*1024*1024,region_entry=False,execution_checkpoints=(),native_cache=None,assets=None,partial_regions=False,media=False):
        if platform.system()!='Darwin' or platform.machine()!='arm64':
            raise RuntimeError('Apple Silicon macOS required')
        if type(instruction_limit) is not int or not 1<=instruction_limit<=10000000:
            raise ValueError('invalid execution budget')
        if type(media) is not bool:raise ValueError('media must be boolean')
        self.media=media
        self.assets=Path(assets).resolve() if assets is not None else None
        if self.assets is not None and not self.assets.is_dir():raise ValueError('asset root must be a directory')
        self.native_cache=Path(native_cache).resolve() if native_cache is not None else None
        self.build_events=[]
        self.source=Path(source).resolve(); self.output=Path(output).resolve()
        if self.output.exists(): raise FileExistsError(self.output)
        self.cache=TranslationCache(self.source,max_blocks,imports=imports,live=True,decode_traps=decode_traps,translation_limit=translation_limit,region_entry=region_entry,partial_regions=partial_regions)
        self.initial=translate_elf(self.source,imports=imports,runtime_fallback=True,defer_decode_errors=decode_traps,max_instructions=translation_limit,partial_regions=partial_regions)
        self.output.mkdir(parents=True)
        self.instruction_limit=instruction_limit
        self.execution_checkpoints=sorted(set(execution_checkpoints))
        if any(type(x) is not int or not 0<x<=instruction_limit for x in self.execution_checkpoints):raise ValueError('invalid execution checkpoint')
        self.saved_checkpoints=set()
        self.error=None; self.misses=[];self.libraries=[]; self.executed=False; self.retired=0;self.regions=[];self.region_by_pc={};self.region_selections=0;self.decode_faults={}
        self.image=self.initial['memory_image']; self.base=self.initial['memory_base']
        self.segments=inspect_elf_segments(self.source)['segments']
        if type(heap_size) is not int or not 4096<=heap_size<=512*1024*1024 or heap_size%4096:
            raise ValueError('invalid page-aligned heap capacity')
        self.heap_size=heap_size
        self.tls=tls
        self.tls_offset=(len(self.image)+4095)&~4095
        self.heap_offset=self.tls_offset+(32*4096 if tls is not None else 0)
        if self.base+self.heap_offset+heap_size+65536>0xffffffff:
            raise ValueError('guest heap/stack exceeds address space')
        self.memory=(C.c_uint8*(self.heap_offset+heap_size+65536))()
        C.memmove(self.memory,self.image,len(self.image))
        self.state=GuestState(); self.state.pc=self.initial['entry']
        self.state.r[13]=(self.base+len(self.memory))&~7; self.state.r[14]=0xffffffff
        # Feature selection and generated shader catalog are part of cache identity.
        runtime_files=['vita_runtime.c','vita_runtime.h','vita_memblock_diag.h','vita_guest.h','vita_kernel.inc','vitanx_dynamic.c','vitanx_devices.c','vitanx_devices.h','vitanx_format.c','vitanx_format.h','vitanx_memory.c','vitanx_memory.h']
        extra_args=[]
        if self.media:
            from .graphics import MEDIA_FILES,prepare_media,media_compile_args
            runtime_files.extend(MEDIA_FILES)
        for name in runtime_files:
            shutil.copyfile(ROOT/'runtime'/name,self.output/name)
        if self.media:
            self.media_catalog=prepare_media(self.output,self.assets)
            runtime_files.extend(('gxm_catalog.h','vitanx_media.c'))
            extra_args=media_compile_args(self.output)
        build_config={'media':self.media,'schema':1}
        (self.output/'runtime-build.json').write_text(json.dumps(build_config,sort_keys=True)+'\n')
        runtime_files.append('runtime-build.json')
        runtime=self.output/'libvitanx_runtime.dylib'
        self.cache_runtime_ok=bool(self.native_cache and (self.native_cache/runtime.name).is_file() and all((self.native_cache/name).is_file() and (self.native_cache/name).read_bytes()==(self.output/name).read_bytes() for name in runtime_files))
        self.cache_abi_ok=bool(self.native_cache and all((self.native_cache/name).is_file() and (self.native_cache/name).read_bytes()==(self.output/name).read_bytes() for name in ('vita_guest.h','vita_runtime.h')))
        if self.cache_runtime_ok:
            shutil.copyfile(self.native_cache/runtime.name,runtime)
        else:
            command(['clang','-dynamiclib','-std=c11','-O2','-Wl,-install_name,@loader_path/libvitanx_runtime.dylib',self.output/'vita_runtime.c',self.output/'vitanx_dynamic.c',self.output/'vitanx_devices.c',self.output/'vitanx_format.c',self.output/'vitanx_memory.c',*extra_args,'-o',runtime])
            command(['codesign','--force','--sign','-',runtime])
        self.runtime=C.CDLL(str(runtime),mode=C.RTLD_LOCAL)
        if self.media:
            self.runtime.vn_media_initialize.restype=C.c_int
            if self.runtime.vn_media_initialize():raise RuntimeError('GXM shader catalog installation failed')
            self.runtime.vx_display_configure_window.argtypes=[C.c_char_p,C.c_int,C.c_int,C.c_int]
            if self.runtime.vx_display_configure_window(b'vitanx',0,1,0):raise RuntimeError('window configuration failed')
            from .graphics import RuntimeShaderTranslator
            self.runtime_shaders=RuntimeShaderTranslator(self.runtime,self.output)
        self.runtime.vn_import_error.restype=C.c_char_p
        self.runtime.vn_import_trace_count.restype=C.c_size_t
        self.runtime.vn_import_trace_field.argtypes=[C.c_size_t,C.c_uint]
        self.runtime.vn_import_trace_field.restype=C.c_uint32
        self.runtime.vn_state_size.restype=C.c_size_t
        self.runtime.vn_state_monitor_offset.restype=C.c_size_t
        if self.runtime.vn_state_size()!=C.sizeof(GuestState) or self.runtime.vn_state_monitor_offset()!=GuestState.exclusive_epoch.offset:
            raise RuntimeError('native guest ABI mismatch')
        self.runtime.vn_set_target_validator.argtypes=[TARGET]
        self.runtime.vx_runtime_run.argtypes=[C.POINTER(GuestState),C.POINTER(C.c_uint8),C.c_size_t,RESUME]
        self.runtime.vx_runtime_run.restype=C.c_int
        self.runtime.vx_runtime_set_memory_base.argtypes=[C.c_uint32]
        self.runtime.vx_runtime_set_heap.argtypes=[C.c_uint32,C.c_uint32]
        self.runtime.vx_runtime_mount.argtypes=[C.c_char_p]
        self.runtime.vn_protect_executable.argtypes=[C.c_void_p,C.c_size_t]
        for seg in self.segments:
            if seg['flags']&1 and self.runtime.vn_protect_executable(C.addressof(self.memory)+seg['virtual_address']-self.base,seg['file_size']):
                raise RuntimeError('executable range registration failed')
        self._load(self.initial,'initial')
        self.dispatch_callback=RESUME(self._dispatch)

    def _load(self,translation,label):
        src=self.output/(label+'.c'); lib=self.output/(label+'.dylib')
        src.write_text(translation['c_source'])
        cached_source=self.native_cache/src.name if self.native_cache else None
        hit=bool(self.cache_abi_ok and cached_source.is_file() and cached_source.read_text()==translation['c_source'] and (self.native_cache/lib.name).is_file())
        if hit:
            shutil.copyfile(self.native_cache/lib.name,lib)
        else:
            command(['clang','-dynamiclib','-std=c11','-O2',src,'-L'+str(self.output),'-lvitanx_runtime','-Wl,-rpath,@loader_path','-o',lib])
            command(['codesign','--force','--sign','-',lib])
        self.build_events.append({'region':label,'cache_hit':hit,'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'binary_sha256':hashlib.sha256(lib.read_bytes()).hexdigest()})
        loaded=C.CDLL(str(lib),mode=C.RTLD_LOCAL); self.libraries.append(loaded)
        resume=loaded.vx_guest_resume; resume.argtypes=RESUME._argtypes_;resume.restype=C.c_int
        validator=TARGET(('vx_guest_target_valid',loaded))
        self.active_resume=resume; self.active_validator=validator
        self.regions.append((resume,validator))
        self.decode_faults.update(translation["decode_errors"])
        for pc in translation["dispatch_addresses"]:
            self.region_by_pc.setdefault(pc,(resume,validator))
        if not hasattr(self,'target_callback'):self.target_callback=TARGET(self._known_target)
        self.runtime.vn_set_target_validator(self.target_callback)

    def _known_target(self,pc):
        if pc in self.region_by_pc:return 1
        if not self.cache.region_entry:return 0
        address=pc&~1;width=2 if pc&1 else 4
        return int(address%width==0 and any(s['flags']&1 and s['virtual_address']<=address and address+width<=s['virtual_address']+s['file_size'] for s in self.segments))

    def _check_code(self,mem):
        if hashlib.sha256(self.source.read_bytes()).hexdigest()!=self.cache.digest:
            raise RuntimeError('input changed during execution')
        for seg in self.segments:
            if seg['flags']&1:
                off=seg['virtual_address']-self.base; size=seg['file_size']
                if C.string_at(C.addressof(mem.contents)+off,size)!=self.image[off:off+size]:
                    raise RuntimeError('self-modifying executable memory unsupported')

    def _dispatch(self,state,mem,size,budget):
        start=state.contents.instructions
        try:
            while True:
                control=self._control(state,mem)
                if control==2:
                    self._check_code(mem)
                    return 1
                if control:continue
                self._check_code(mem)
                used=state.contents.instructions-start
                remaining=min(budget-used,self.instruction_limit-self.retired)
                future=[n for n in self.execution_checkpoints if n>self.retired]
                if future:remaining=min(remaining,future[0]-self.retired)
                if remaining<=0:
                    return -4 if self.retired>=self.instruction_limit else 1
                before=state.contents.instructions;before_services=state.contents.services
                rc=self.active_resume(state,mem,size,remaining)
                self.retired+=state.contents.instructions-before
                if state.contents.services!=before_services:
                    self._check_code(mem)
                    message=self.runtime.vn_import_error()
                    if message:
                        index=self.runtime.vn_import_trace_count()-1
                        nid=self.runtime.vn_import_trace_field(index,0)
                        context={'function_nid':'%08x'%nid,'reason':message.decode(),'caller_lr':state.contents.r[14],
                                 'args':[self.runtime.vn_import_trace_field(index,j) for j in range(1,5)]}
                        raise HostServiceFault(message.decode(),context)
                if self.retired in self.execution_checkpoints and self.retired not in self.saved_checkpoints:
                    s=state.contents
                    checkpoint={'pc':s.pc,'r':list(s.r),'f':list(s.f),'nzcv':[s.n,s.z,s.c,s.v],'fpscr':s.fpscr,'tpidruro':s.tpidruro,'instructions':s.instructions,'services':s.services,'total_instructions':self.retired}
                    (self.output/('cpu-at-%d.json'%self.retired)).write_text(json.dumps(checkpoint,indent=2)+'\n')
                    self.saved_checkpoints.add(self.retired)
                if rc==1 and state.contents.services==before_services and state.contents.instructions-start<budget and self.retired<self.instruction_limit:continue
                if rc!=2:
                    if rc in (-2,-3,-6,-8):
                        pc=state.contents.pc
                        context={'stage':'cpu','status':rc,'pc':pc,'isa':'thumb' if pc&1 else 'arm',
                                 'caller_lr':state.contents.r[14]}
                        if rc==-8:
                            context.update(self.decode_faults.get(pc,{}))
                        context['kind']={-2:'memory access or executable write rejected',-3:'untranslated target',
                                         -6:'unsupported host floating-point rounding',-8:'unsupported guest instruction'}[rc]
                        self.error=context['kind'];self.fault_context=context
                    return rc
                control=self._control(state,mem)
                if control==2:
                    self._check_code(mem)
                    return 1
                if control:continue
                pc=state.contents.pc
                found=self.region_by_pc.get(pc)
                if found is not None:
                    self.active_resume,self.active_validator=found
                    self.region_selections+=1
                    continue
                # Cache misses do not count as instructions or invalidate the monitor.
                if pc in self.cache.blocks:
                    raise RuntimeError('cached translation cannot dispatch requested PC')
                translation=self.cache.request(pc)
                event={'pc':pc,'instructions':state.contents.instructions,'services':state.contents.services,
                       'lr':state.contents.r[14],'sp':state.contents.r[13]}
                self._load(translation,'target-%08x'%pc)
                self.misses.append(event)
        except Exception as e:
            self.error=str(e);self.fault_context=getattr(e,'context',None)
            return getattr(e,'guest_status',-10)

    def _control(self,state,mem):
        return False

    def _execute(self):
        return self.runtime.vx_runtime_run(C.byref(self.state),self.memory,len(self.memory),self.dispatch_callback)

    def run(self):
        if self.executed: raise RuntimeError('session already executed')
        self.executed=True
        self.runtime.vx_runtime_set_memory_base(self.base)
        heap=self.heap_offset
        if self.tls is not None:
            source,filesz,memsz=self.tls
            self.runtime.vx_runtime_set_tls.argtypes=[C.c_uint32]*5
            self.runtime.vx_runtime_set_tls_user_offset.argtypes=[C.c_uint32]
            if self.runtime.vx_runtime_set_tls(self.base+self.tls_offset,4096,source,filesz,memsz) or self.runtime.vx_runtime_set_tls_user_offset(0x800):
                raise RuntimeError('TLS setup failed')
        if self.runtime.vx_runtime_set_heap(self.base+heap,self.heap_size):
            raise RuntimeError('heap setup failed')
        saves=self.output/'saves';saves.mkdir()
        if self.runtime.vx_runtime_mount(os.fsencode(saves)): raise RuntimeError('save mount failed')
        try:
            if self.assets is not None:
                self.runtime.vx_runtime_mount_app.argtypes=[C.c_char_p]
                if self.runtime.vx_runtime_mount_app(os.fsencode(self.assets)):raise RuntimeError('read-only app0 mount failed')
            status=self._execute()
            report={'status':status,'error':self.error,'pc':self.state.pc,'r':list(self.state.r),'f':list(self.state.f),
                    'tpidruro':self.state.tpidruro,'nzcv':[getattr(self.state,k) for k in ('n','z','c','v')],'fpscr':self.state.fpscr,
                    'instructions':self.state.instructions,'total_instructions':self.retired,'services':self.state.services,'translation_misses':self.misses,
                    'input_sha256':self.cache.digest,'commercial_compatibility':False,'native_builds':self.build_events,'fault_context':getattr(self,'fault_context',None)}
            self.runtime.vn_devices_get_gpo.restype=C.c_uint32
            self.runtime.vn_devices_get_gpi.restype=C.c_uint32
            if self.media:
                from .graphics import media_stats
                report['media']=media_stats(self.runtime)
                report['media']['runtime_shaders']=self.runtime_shaders.report()
                report['media']['shader_catalog']={'files_examined':len(self.media_catalog),'translated':sum(row.get('translation_supported') is not False for row in self.media_catalog),'unsupported':sum(row.get('translation_supported') is False for row in self.media_catalog),'diagnostics':'gxm-catalog.json','discovery':'loose .gxp/.vpo/.fpo files only; packed shaders require extraction or runtime translation'}
            report['region_dispatch']={'indexed_targets':len(self.region_by_pc),'cross_region_selections':self.region_selections}
            report['devices']={'gpo':self.runtime.vn_devices_get_gpo(),'gpi':self.runtime.vn_devices_get_gpi()}
            self.runtime.vn_import_trace_count.restype=C.c_size_t
            self.runtime.vn_import_trace_field.argtypes=[C.c_size_t,C.c_uint]
            self.runtime.vn_import_trace_field.restype=C.c_uint32
            count=self.runtime.vn_import_trace_count()
            report['runtime_imports']=[{'nid':'%08x'%self.runtime.vn_import_trace_field(i,0),'args':[self.runtime.vn_import_trace_field(i,j) for j in range(1,5)],'result':self.runtime.vn_import_trace_field(i,5),'fault':bool(self.runtime.vn_import_trace_field(i,6)),'r1_after':self.runtime.vn_import_trace_field(i,7),**({'memblock_failure_reason':self.runtime.vn_import_trace_field(i,8)} if self.runtime.vn_import_trace_field(i,0)==0xB9D5EBDE else {})} for i in range(max(0,count-64),count)]
            (self.output/'execution.json').write_text(json.dumps(report,indent=2)+'\n')
            return report
        finally:
            self.runtime.vx_runtime_shutdown()
            self.runtime.vn_devices_reset()
