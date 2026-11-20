"""Transactional Vita module mapping/linking and live guest module execution.

Uses the local validated SCE loader; no upstream implementation is copied.
Only explicit plaintext inputs (or explicitly plaintext SELF segments) accepted.
"""
import copy
import ctypes as C
import hashlib
import json
from pathlib import Path
import struct
from .dynamic import NativeSession,GuestState
from .fallback import TranslationCache
from vitaxnative.commercial_loader import map_module,align,make_link_plan,link_variables
from vitaxnative.recompiler import translate_elf,MAX_MEMORY
from vitaxnative.self_extract import extract_self

def runtime_bindings():
    data=json.loads((Path(__file__).with_name('runtime-nids.json')).read_text())
    return {(r['library_nid'],r['function_nid']):int(r['function_nid'],16) for r in data['bindings']}

def device_bindings():
    data=json.loads(Path(__file__).with_name('device-nids.json').read_text())
    return {(r['library_nid'],r['function_nid']):int(r['function_nid'],16) for r in data['bindings']}

# Numeric ABI facts: VitaSDK db/360/SceSysmodule.yml and psp2/sysmodule.h.
SYSMODULE_LIBRARY='03fcf19d'
SYSMODULE_APIS={'79a0160a':'load','53099b7a':'query','31d87805':'unload'}
SYSMODULE_INVALID=0x805a1000;SYSMODULE_UNLOADED=0x805a1001;SYSMODULE_FATAL=0x805a10ff
START='935cd196'; STOP='79f8e492'; SYSLIB='936c8a78'
class LinkError(ValueError):pass
class UnresolvedImport(LinkError):
    guest_status=-9
    def __init__(self,item,state):
        self.context={**item,'trap_pc':state.pc,'caller_lr':state.r[14],'args':list(state.r[:4])}
        super().__init__('unresolved import '+item['module']+': '+repr(item['key'])+' ('+item.get('reason','no qualified binding')+')')


def lifecycle(module,nid):
    addresses=[module.guest_address(int(a,16)) for lib in module.metadata['exports']
               if lib['library_nid'] in (SYSLIB,'00000000')
               for n,a in zip(lib['function_nids'],lib['function_addresses']) if n==nid]
    if len(addresses)>1:raise LinkError('duplicate lifecycle export')
    if addresses:return addresses[0]
    if nid==START and module.metadata['startup_entry']:
        return module.guest_address(int(module.metadata['startup_entry'],16))
    return None

class ModuleImage:
    def __init__(self,work,*,runtime_exports=None,reserve=8*1024*1024,runtime_intercepts=None):
        self.work=Path(work);self.work.mkdir(parents=True,exist_ok=True)
        self.modules=[];self.runtime_exports=dict(runtime_exports or {});self.runtime_intercepts=dict(runtime_intercepts or {});self.intercepts={}
        self.reserve=reserve;self.limit=None;self.revision=0
        self.pending={};self.hooks={};self.bindings=[];self.variables={};self.inputs={};self.markers={};self.plain_cache={}

    def _plain(self,path):
        path=Path(path).resolve()
        with path.open('rb') as f:magic=f.read(4)
        if magic==b'SCE\0':
            if path.stat().st_size>128*1024*1024:raise LinkError('SELF exceeds bounded loader size')
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            if path in self.plain_cache:
                before,target=self.plain_cache[path]
                if before!=digest:raise LinkError('SELF changed after inspection')
                return target
            target=self.work/('plaintext-'+hashlib.sha256(str(path).encode()).hexdigest()[:16]+'.elf')
            if target.exists():raise LinkError('duplicate SELF input')
            extract_self(path,target) # rejects encryption; no keys or decryption
            self.plain_cache[path]=(digest,target)
            return target
        return path

    def load(self,path,*,allow_unresolved=False):
        original=Path(path).resolve(); path=self._plain(original)
        old=self.modules
        base=None if not old else align(max(m.new_base+len(m.memory) for m in old))
        new=map_module(path,base)
        if any(m.name==new.name for m in old):raise LinkError('duplicate module name: '+new.name)
        if new.tls_memsz and old:raise LinkError('support-module TLS registration not implemented')
        if new.metadata['import_tls_count']:raise LinkError('TLS variable imports unsupported')
        candidate=copy.deepcopy(old)+[new]
        # Relink clean loader images; never derive relocations from mutable guest bytes.
        # Existing mapped data is committed to live memory only at changed link sites.
        for m in candidate[:-1]:
            clean=map_module(m.path,m.new_base);m.memory=clean.memory
        low=min(m.new_base for m in candidate)
        high=max(m.new_base+len(m.memory) for m in candidate)
        limit=self.limit if self.limit is not None else align(high+self.reserve)
        if high>limit or limit-low>MAX_MEMORY or limit+4*1024*1024+65536>0xffffffff:
            raise LinkError('module address arena exhausted')
        ranges=[]
        for m in candidate:
            for seg in m.segments:
                start=seg['address']+m.delta;end=start+seg['memory_size']
                if any(start<b and a<end for a,b in ranges):raise LinkError('module segment collision')
                ranges.append((start,end))
        plan=make_link_plan(candidate);hooks={};pending={};intercepts={};bindings=[]
        external_variables={}
        main=candidate[0]
        parameters=[int(a,16) for lib in main.metadata['exports'] for nid,a in zip(lib['variable_nids'],lib['variable_addresses']) if nid=='70fba1e7']
        if len(parameters)>1:raise LinkError('duplicate process parameter export')
        if parameters:
            address=parameters[0]
            def checked_word(address):
                if not any(seg['address']<=address and address+4<=seg['address']+seg['file_size'] for seg in main.segments):
                    raise LinkError('process/libc parameter outside file-backed memory')
                return main.word(address)
            if checked_word(address)>=48 and checked_word(address+4)==0x32505350:
                libc=checked_word(address+44)
                if checked_word(libc)<40:raise LinkError('invalid libc parameter size')
                external_variables[('5ad9c136','df084dfa')]=main.guest_address(libc)
        variables=link_variables(candidate,external_variables)
        if variables['missing'] and not allow_unresolved:raise LinkError('unresolved variable imports: '+json.dumps(variables['missing']))
        exported={}
        for m in candidate:
            for lib in m.metadata['exports']:
                for nid,addr in zip(lib['function_nids'],lib['function_addresses']):
                    exported.setdefault((lib['library_nid'],nid),[]).append((m.name,m.guest_address(int(addr,16))))
        markers=dict(self.markers)
        marker=max(markers.values(),default=0xfefffffc)+4
        for m in candidate:
            for lib in m.metadata['imports']:
                for nid,stub in zip(lib['function_nids'],lib['function_stubs']):
                    key=(lib['library_nid'],nid);providers=exported.get(key,[])
                    address=m.guest_address(int(stub,16));off=address-m.new_base
                    if address&3 or not any(s['flags']&1 and s['address']-m.old_base<=off and off+8<=s['address']-m.old_base+s['file_size'] for s in m.segments):
                        raise LinkError('unaligned or truncated import stub')
                    if len(providers)>1:raise LinkError('ambiguous function import: '+repr(key))
                    item={'module':m.name,'library':lib['library'],'library_nid':key[0],'function_nid':key[1],'stub':address}
                    if providers:
                        provider,target=providers[0]
                        bindings.append({**item,'provider':provider,'target':target})
                    elif key in self.runtime_exports:
                        target=address;hooks[address]=self.runtime_exports[key]
                        bindings.append({**item,'provider':'explicit host runtime','nid':hooks[address]})
                        continue
                    else:
                        if key not in self.runtime_intercepts and not allow_unresolved:raise LinkError('unresolved function import: '+repr(key))
                        if address not in markers:markers[address]=marker;marker+=4
                        target=markers[address]
                        if key in self.runtime_intercepts:
                            intercepts[target]={**item,'key':key,'nid':self.runtime_intercepts[key]}
                            bindings.append({**item,'provider':'dynamic host runtime','nid':self.runtime_intercepts[key]})
                        else:pending[target]={**item,'key':key}
                    # ARM literal PC load preserves LR and interworks on target bit 0.
                    struct.pack_into('<II',m.memory,off,0xe51ff004,target)
        # Commit only after all mapping, relocation and binding checks succeed.
        self.modules=candidate;self.limit=limit;self.pending=pending;self.hooks=hooks;self.markers=markers;self.intercepts=intercepts
        self.bindings=bindings;self.variables=variables;self.revision+=1
        self.inputs[str(original)]=hashlib.sha256(original.read_bytes()).hexdigest()
        return self.modules[-1]

    @property
    def entry(self):
        entry=lifecycle(self.modules[0],START)
        if entry is None:raise LinkError('main module has no startup entry')
        return entry

    def emit(self,entry=None):
        segments=[]
        for m in self.modules:
            for s in m.segments:
                off=s['address']-m.old_base
                segments.append((s['address']+m.delta,s['memory_size'],s['flags'],bytes(m.memory[off:off+s['file_size']])))
        high=max(a+size for a,size,_,_ in segments)
        if high<self.limit:segments.append((high,self.limit-high,6,b''))
        header=bytearray(52+32*len(segments))
        struct.pack_into('<16sHHIIIIIHHHHHH',header,0,b'\x7fELF\x01\x01\x01'+bytes(9),2,40,1,self.entry if entry is None else entry,52,0,0x5000000,52,32,len(segments),0,0,0)
        for i,(address,size,flags,data) in enumerate(segments):
            off=len(header);struct.pack_into('<IIIIIIII',header,52+32*i,1,off,address,address,len(data),size,flags,1);header.extend(data)
        path=self.work/('image-%d.elf'%self.revision)
        if path.exists():raise FileExistsError(path)
        path.write_bytes(header)
        return path

    def report(self):
        return {'modules':[{'name':m.name,'old_base':m.old_base,'base':m.new_base,
                            'relocations':m.relocation_counts,'start':lifecycle(m,START),'stop':lifecycle(m,STOP)} for m in self.modules],
                'function_bindings':self.bindings,'pending_imports':list(self.pending.values()),
                'variable_linking':self.variables,'source_sha256':self.inputs}

class ModuleSession(NativeSession):
    def __init__(self,paths,output,*,deferred=(),runtime_exports=None,instruction_limit=1000000,allow_unresolved=False,heap_size=4*1024*1024,execution_checkpoints=(),native_cache=None,max_regions=128,assets=None,sysmodules=None,native_apputil=True,apputil_config=None,boundary_handler=None,media=False):
        if boundary_handler is not None and not callable(boundary_handler):raise ValueError('boundary handler must be callable')
        self.boundary_handler=boundary_handler;self.handling_boundary=False
        output=Path(output).resolve()
        if output.exists():raise FileExistsError(output)
        output.mkdir(parents=True)
        self.application_metadata={}
        self.application_type=None
        if assets is not None:
            sfo=Path(assets)/'sce_sys/param.sfo'
            if sfo.is_file():
                from vitaxnative.analysis import parse_sfo,MAX_SFO
                if sfo.stat().st_size>MAX_SFO:raise LinkError('oversized app metadata')
                self.application_metadata=parse_sfo(sfo.read_bytes())
                if self.application_metadata.get('CATEGORY')=='gd':self.application_type=1
        self.sysmodule_paths={int(k):Path(v).resolve() for k,v in (sysmodules or {}).items()}
        if any(not 1<=k<=0x55 for k in self.sysmodule_paths):raise LinkError('invalid configured system module ID')
        if len(set(self.sysmodule_paths.values()))!=len(self.sysmodule_paths):raise LinkError('one provider cannot represent multiple system modules')
        self.sysmodule_loaded={};self.sysmodule_loading=set();self.sysmodule_events=[]
        self.apputil=None
        if native_apputil and 15 not in self.sysmodule_paths:
            from .apputil import AppUtil,APIS,LIBRARY
            self.apputil=AppUtil(self,apputil_config)
        from .common_dialog import CommonDialog,APIS as DIALOG_APIS,LIBRARY as DIALOG_LIBRARY
        self.common_dialog=CommonDialog(self)
        from .power import PowerPolicy,APIS as POWER_APIS,LIBRARY as POWER_LIBRARY
        self.power=PowerPolicy(self)
        from .screenshot import ScreenShotPolicy,APIS as SCREENSHOT_APIS,LIBRARY as SCREENSHOT_LIBRARY
        self.screenshot=ScreenShotPolicy(self)
        intercepts=device_bindings()
        intercepts.update({(SCREENSHOT_LIBRARY,"%08x"%nid):nid for nid in SCREENSHOT_APIS})
        intercepts.update({(POWER_LIBRARY,"%08x"%nid):nid for nid in POWER_APIS})
        self.media_keys=set()
        if media:
            from .graphics import media_bindings
            bindings=media_bindings()
            self.media_keys=set(bindings)
            intercepts.update(bindings)
        intercepts.update({(DIALOG_LIBRARY,'%08x'%nid):nid for nid in DIALOG_APIS})
        if self.apputil is not None:
            intercepts.update({(LIBRARY,'%08x'%nid):nid for nid in APIS})
        intercepts.update({(SYSMODULE_LIBRARY,nid):int(nid,16) for nid in SYSMODULE_APIS})
        for catalog in ('format-nids.json','io-nids.json','memory-nids.json'):
            rows=json.loads(Path(__file__).with_name(catalog).read_text())['bindings']
            intercepts.update({(r['library_nid'],r['function_nid']):int(r['function_nid'],16) for r in rows})
        if self.application_type is not None:
            rows=json.loads(Path(__file__).with_name('process-nids.json').read_text())['bindings']
            intercepts.update({(r['library_nid'],r['function_nid']):int(r['function_nid'],16) for r in rows})
        exports=runtime_bindings() if runtime_exports is None else runtime_exports
        if runtime_exports is None:
            # Preserve the existing generated hook table and import marker layout.
            # Every region includes that table; a new direct hook would rebuild
            # all regions. The qualified host path yields before FPSCR is read.
            key=('859a24b1','cc18fbae')
            exports=dict(exports)
            intercepts[key]=exports.pop(key)
        self.process=ModuleImage(output/'loader',runtime_exports=exports,runtime_intercepts=intercepts)
        self.deferred=list(dict.fromkeys(Path(p).resolve() for p in deferred));self.main_executed=False;self.phase_events=[];self.initialized=[];self.init_frames=[]
        for path in paths:self.process.load(path,allow_unresolved=True)
        if self.process.variables['missing']:
            raise LinkError('unresolved variable imports: '+json.dumps(self.process.variables['missing']))
        if self.process.pending and not self.deferred and not self.sysmodule_paths and boundary_handler is None and not allow_unresolved:
            raise LinkError('unresolved function imports: '+json.dumps(list(self.process.pending.values())))
        starts=[lifecycle(m,START) for m in self.process.modules[1:] if lifecycle(m,START) is not None]
        source=self.process.emit(entry=starts[0] if starts else None)
        main=self.process.modules[0]
        tls=(main.new_base+int(main.metadata['tls']['start'],16),len(main.tls_template),main.tls_memsz)
        super().__init__(source,output/'native',imports=self.process.hooks,instruction_limit=instruction_limit,tls=tls,decode_traps=True,heap_size=heap_size,region_entry=True,max_blocks=max_regions,execution_checkpoints=execution_checkpoints,native_cache=native_cache,assets=assets,partial_regions=True,translation_limit=1024,media=media)
        self.runtime.vn_guest_write_allowed.argtypes=[C.c_void_p,C.c_size_t]
        self.root_output=output
        if self.application_type is not None:
            self.runtime.vn_process_set_application_type.argtypes=[C.c_int]
            if self.runtime.vn_process_set_application_type(self.application_type):raise LinkError('invalid application type')
        self.runtime.vx_runtime_run_module.argtypes=self.runtime.vx_runtime_run.argtypes
        self.runtime.vx_runtime_run_module.restype=C.c_int
        self.runtime.vn_reset_executable.argtypes=[]

    def _activate_image(self):
        source=self.process.emit()
        translated=translate_elf(source,imports=self.process.hooks,runtime_fallback=True,defer_decode_errors=True,max_instructions=self.cache.translation_limit,partial_regions=True)
        old=self.image;new=translated['memory_image']
        if self.base!=translated['memory_base'] or len(old)!=len(new):raise LinkError('live arena moved')
        # Apply only loader-owned deltas, preserving all other mutable guest data.
        for i,(a,b) in enumerate(zip(old,new)):
            if a!=b:self.memory[i]=b
        self.image=new;self.source=source
        cache=TranslationCache(source,self.cache.max_blocks,imports=self.process.hooks,live=True,decode_traps=True,translation_limit=self.cache.translation_limit,region_entry=True,partial_regions=True)
        self.cache=cache;self.regions.clear();self.region_by_pc.clear();self.decode_faults.clear()
        self._load(translated,'link-revision-%d'%self.process.revision)
        from vitaxnative.elf_segments import inspect_elf_segments
        self.segments=inspect_elf_segments(source)['segments']
        self.runtime.vn_reset_executable()
        for seg in self.segments:
            if seg['flags']&1 and self.runtime.vn_protect_executable(C.addressof(self.memory)+seg['virtual_address']-self.base,seg['file_size']):
                raise LinkError('code protection registration failed')
        self.runtime.vx_guest_memory_written()

    def _control(self,state,mem):
        pc=state.contents.pc
        if self.init_frames and pc==0xfefffffc:
            saved,entry,module,system_id=self.init_frames.pop()
            if state.contents.r[0]!=0:raise LinkError('module_start returned failure for '+module.name)
            count,services=state.contents.instructions,state.contents.services
            C.memmove(state,C.byref(saved),C.sizeof(GuestState))
            state.contents.instructions=count;state.contents.services=services
            state.contents.exclusive_valid=0;state.contents.pc=entry
            self.initialized.append(module)
            self.phase_events.append({'module':module.name,'phase':'lazy_start','result':0})
            if system_id is not None:
                self.sysmodule_loading.remove(system_id);self.sysmodule_loaded[system_id]=module.name
                state.contents.r[0]=0;state.contents.services+=1
                self.sysmodule_events.append({'id':system_id,'operation':'load','result':0,'module':module.name})
                return 2
            self._register_system_module(module)
            return True
        host=self.process.intercepts.get(pc)
        if host is not None:
            if host['library_nid']=='f26fc97d':
                state.contents.r[0]=self.screenshot.invoke(host['nid'],state.contents.r)
                state.contents.pc=state.contents.r[14];state.contents.services+=1;state.contents.exclusive_valid=0
                return 2
            if host['library_nid']=='1082da7f':
                state.contents.r[0]=self.power.invoke(host['nid'],state.contents.r)
                state.contents.pc=state.contents.r[14];state.contents.services+=1;state.contents.exclusive_valid=0
                return 2
            if host['library_nid']=='e537816c':
                state.contents.r[0]=self.common_dialog.invoke(host['nid'],state.contents.r)
                state.contents.pc=state.contents.r[14];state.contents.services+=1;state.contents.exclusive_valid=0
                return 2
            if host['library_nid']=='48e01d74' and self.apputil is not None:
                state.contents.r[0]=self.apputil.invoke(host['nid'],state.contents.r)
                state.contents.pc=state.contents.r[14];state.contents.services+=1;state.contents.exclusive_valid=0
                return 2
            if host['library_nid']==SYSMODULE_LIBRARY:
                return self._system_call(host,state)
            self.runtime.vn_import.argtypes=[C.c_uint32,C.POINTER(C.c_uint32),C.POINTER(C.c_uint8),C.c_size_t]
            self.runtime.vn_import.restype=C.c_uint32
            state.contents.exclusive_valid=0
            if tuple(host['key']) in self.media_keys:
                self.runtime.vn_import_vfp.argtypes=[C.c_uint32,C.POINTER(C.c_uint32),C.POINTER(C.c_uint32),C.POINTER(C.c_uint8),C.c_size_t]
                self.runtime.vn_import_vfp.restype=C.c_uint32
                state.contents.r[0]=self.runtime.vn_import_vfp(host['nid'],state.contents.r,state.contents.f,mem,len(self.memory))
            else:
                state.contents.r[0]=self.runtime.vn_import(host['nid'],state.contents.r,mem,len(self.memory))
            self.runtime.vn_import_error.restype=C.c_char_p
            message=self.runtime.vn_import_error()
            if message:
                error=UnresolvedImport(host,state.contents);error.context['reason']=message.decode();error.args=(message.decode(),);raise error
            state.contents.pc=state.contents.r[14];state.contents.services+=1
            return 2 # Import yield: let the scheduler handle wait/exit effects.
        item=self.process.pending.get(pc)
        if item is None:
            # A different guest thread may have suspended at this marker before
            # the provider was loaded. Stable marker IDs retry its original stub.
            stubs=[stub for stub,marker in self.process.markers.items() if marker==pc]
            if not stubs:return False
            state.contents.pc=stubs[0];return True
        from vitaxnative.commercial_vita_inventory import inventory
        matches=[]
        for path in self.deferred:
            meta=inventory(self.process._plain(path))
            if any((lib['library_nid'],nid)==item['key'] for lib in meta['exports'] for nid in lib['function_nids']):matches.append(path)
        if len(matches)!=1:
            # Resolve while the scheduler, CPU, mappings and file descriptors are
            # still alive. No CPU-only snapshot restore or process-entry replay.
            if self.boundary_handler is not None and not self.handling_boundary:
                self.handling_boundary=True
                try:
                    if self.boundary_handler(self,item,state):return self._control(state,mem)
                finally:self.handling_boundary=False
            reason='no qualified provider' if not matches else 'multiple qualified deferred providers'
            diagnostic={**item,'reason':reason,'deferred_candidates':[str(p) for p in sorted(matches)],
                        'same_function_other_libraries':self._other_library_bindings(item['key'])}
            raise UnresolvedImport(diagnostic,state.contents)
        module=self.process.load(matches[0],allow_unresolved=True)
        if self.process.variables['missing']:raise LinkError('unresolved variables in dynamic module')
        self.deferred.remove(matches[0])
        self._activate_image()
        # Retry the same import stub; caller's LR/arguments/SP remain untouched.
        retry=item['stub'];start=lifecycle(module,START)
        if start is not None:
            saved=GuestState.from_buffer_copy(state.contents)
            self.init_frames.append((saved,retry,module,None))
            state.contents.pc=start;state.contents.r[0]=state.contents.r[1]=0
            state.contents.r[14]=0xfefffffc;state.contents.exclusive_valid=0
        else:
            state.contents.pc=retry
            self.initialized.append(module);self._register_system_module(module)
        return True

    def _other_library_bindings(self,key):
        """Diagnostic candidates only: never borrow a function from another library."""
        library,nid=key
        candidates=[]
        for module in self.process.modules:
            for exported in module.metadata['exports']:
                if exported['library_nid']!=library and nid in exported['function_nids']:
                    candidates.append({'library_nid':exported['library_nid'],'provider':module.name})
        for registry,provider in ((self.process.runtime_exports,'explicit host runtime'),
                                  (self.process.runtime_intercepts,'dynamic host runtime')):
            candidates.extend({'library_nid':lib,'provider':provider}
                              for lib,function in registry if function==nid and lib!=library)
        return sorted(candidates,key=lambda item:(item['library_nid'],item['provider']))

    def _register_system_module(self,module):
        # Only actual initialized providers count, never an ID requested by a game.
        system_id={'SceUlt':7,'SceLibFios2':16}.get(module.name)
        for ident,path in self.sysmodule_paths.items():
            if module.path.resolve()==self.process._plain(path).resolve():system_id=ident
        if system_id is not None:self.sysmodule_loaded[system_id]=module.name

    def _system_call(self,host,state):
        cpu=state.contents;ident=int(cpu.r[0]);operation=SYSMODULE_APIS[host['function_nid']]
        result=SYSMODULE_INVALID
        if 1<=ident<=0x55:
            loaded=ident in self.sysmodule_loaded
            if operation=='query':result=0 if loaded else SYSMODULE_UNLOADED
            elif operation=='unload':
                # Mappings/imports remain pinned: never claim unmapping succeeded.
                result=SYSMODULE_FATAL if loaded else SYSMODULE_UNLOADED
            elif loaded:result=0
            elif ident==15 and self.apputil is not None and ident not in self.sysmodule_paths:
                self.sysmodule_loaded[ident]='vitanx AppUtil compatibility provider (partial)';result=0
            elif ident not in self.sysmodule_paths or ident in self.sysmodule_loading:result=SYSMODULE_FATAL
            else:
                path=self.sysmodule_paths[ident]
                existing=[m for m in self.process.modules if m.path.resolve()==self.process._plain(path).resolve()]
                if existing:
                    # Already mapped but not initialized (or initialization failed).
                    result=SYSMODULE_FATAL
                else:
                    module=self.process.load(path,allow_unresolved=True)
                    if self.process.variables['missing']:raise LinkError('unresolved variables in system module')
                    self._activate_image()
                    start=lifecycle(module,START)
                    if start is not None:
                        saved=GuestState.from_buffer_copy(cpu)
                        self.init_frames.append((saved,int(cpu.r[14]),module,ident))
                        self.sysmodule_loading.add(ident)
                        cpu.pc=start;cpu.r[0]=cpu.r[1]=0;cpu.r[14]=0xfefffffc;cpu.exclusive_valid=0
                        return True
                    self.initialized.append(module);self.sysmodule_loaded[ident]=module.name;result=0
        self.sysmodule_events.append({'id':ident,'operation':operation,'result':result})
        cpu.r[0]=result;cpu.pc=cpu.r[14];cpu.services+=1;cpu.exclusive_valid=0
        return 2

    def _execute(self):
        main=self.state;main.pc=self.process.entry
        self.runtime.vx_runtime_stop_requested.argtypes=[C.POINTER(C.c_uint32)]
        parameters=[self.process.modules[0].guest_address(int(a,16)) for lib in self.process.modules[0].metadata['exports'] for nid,a in zip(lib['variable_nids'],lib['variable_addresses']) if nid=='70fba1e7']
        if parameters:
            self.runtime.vx_runtime_set_process_param.argtypes=[C.c_uint32]
            self.runtime.vx_runtime_set_process_param(parameters[0])
        for module in self.process.modules[1:]:
            entry=lifecycle(module,START)
            if entry is None:
                self.initialized.append(module);self._register_system_module(module);continue
            phase=GuestState();phase.pc=entry;phase.r[13]=main.r[13];phase.r[14]=0xffffffff
            self.runtime.vx_runtime_reset_stop()
            status=self.runtime.vx_runtime_run_module(C.byref(phase),self.memory,len(self.memory),self.dispatch_callback)
            self.phase_events.append({'module':module.name,'phase':'start','status':status,'result':phase.r[0]})
            if status or phase.r[0]:self.error=self.error or 'support module initialization failed';self.phase_events[-1].update(error=self.error,pc=phase.pc,r=list(phase.r),instructions=phase.instructions,services=phase.services);return status or -12
            exit_status=C.c_uint32()
            reason=self.runtime.vx_runtime_stop_requested(C.byref(exit_status))
            if reason==1:
                self.phase_events[-1]['process_exit_status']=exit_status.value
                return 0
            self.initialized.append(module);self._register_system_module(module)
        self.runtime.vx_runtime_reset_stop()
        self.main_executed=True
        status=super()._execute()
        if status:return status
        exit_status=C.c_uint32()
        if self.runtime.vx_runtime_stop_requested(C.byref(exit_status))==1:return status
        for module in reversed(self.initialized):
            entry=lifecycle(module,STOP)
            if entry is None:continue
            phase=GuestState();phase.pc=entry;phase.r[13]=main.r[13];phase.r[14]=0xffffffff
            self.runtime.vx_runtime_reset_stop()
            rc=self.runtime.vx_runtime_run_module(C.byref(phase),self.memory,len(self.memory),self.dispatch_callback)
            self.phase_events.append({'module':module.name,'phase':'stop','status':rc,'result':phase.r[0]})
            if rc or phase.r[0]:self.error=self.error or 'support module termination failed';self.phase_events[-1].update(error=self.error,pc=phase.pc);return rc or -12
        return status

    def run(self):
        try:
            report=super().run()
            if self.apputil is not None:report['apputil']=self.apputil.report()
            report['common_dialog']=self.common_dialog.report()
            report['power']=self.power.report()
            report['screenshot']=self.screenshot.report()
        finally:
            if self.apputil is not None:self.apputil.close()
        report['system_modules']={'loaded':self.sysmodule_loaded,'events':self.sysmodule_events};report['module_loader']=self.process.report();report['module_phases']=self.phase_events;report['main_executed']=self.main_executed;report['application_metadata']=self.application_metadata;report['application_type']=self.application_type
        (self.root_output/'execution.json').write_text(json.dumps(report,indent=2)+'\n')
        return report
