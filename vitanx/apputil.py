"""Original bounded AppUtil host compatibility, using public Vita ABI facts.

This is an explicit local device model, not original firmware. Host-owned work
storage needs zero guest scratch bytes. Boot defaults describe an ordinary local
launch. Events are injected, never invented. All filesystem capabilities stay
under this execution's isolated savedata0 mount. No Vita3K implementation copied.
"""
import ctypes as C
from collections import deque
import errno
import os
from pathlib import Path
import stat
import struct
import threading

# ABI references: vitasdk/vita-headers include/psp2/apputil.h, system_param.h
# and db/360/SceAppUtil.yml. Numeric constants/layout facts only.

LIBRARY='48e01d74'
APIS={0xdaffe671:'init',0xb220b00b:'shutdown',0x5dfb9ca0:'system_int',
      0x6e6aa267:'system_string',0xee0dbed9:'event',0x7e8fe96a:'slot_create',
      0x266a7646:'slot_delete',0x93f0d89f:'slot_get',0x98630136:'slot_set',
      0x607647ba:'data_save',0xd1c6ab8e:'data_remove',
      0x9d8ac677:'safe_save',0x3424d772:'safe_load',0xc560e716:'quota'}
PARAM=0x80100600;NOT_INIT=0x80100601;BUSY=0x80100603;PERMISSION=0x80100605
EXISTS=0x80100640;NOT_FOUND=0x80100641;QUOTA=0x80100642;NO_SPACE=0x80100643
MAX_TRANSFER=16*1024*1024
class AppError(Exception):
    def __init__(self,code):self.code=code

class AppUtil:
    def __init__(self,session,config=None):
        self.session=session;self.lock=threading.RLock();self.initialized=False
        self.root=None;self.meta=None;self.events=deque();self.trace=deque(maxlen=64)
        cfg=dict(config or {})
        defaults={'language':1,'enter_button':1,'username':'vitanx','date_format':0,
                  'time_format':1,'time_zone':0,'daylight_savings':0,
                  'boot_attribute':0,'boot_version':0,'quota_kib':65536}
        if cfg.keys()-defaults.keys():raise ValueError('unknown AppUtil configuration')
        quota=getattr(session,'application_metadata',{}).get('SAVEDATA_MAX_SIZE')
        if 'quota_kib' not in cfg and type(quota) is int and 1<=quota<=1024*1024:defaults['quota_kib']=quota
        defaults.update(cfg);self.config=defaults
        for name,lo,hi in [('language',0,19),('enter_button',0,1),('date_format',0,2),
                           ('time_format',0,1),('time_zone',-720,840),('daylight_savings',0,1),
                           ('boot_attribute',0,0xffffffff),('boot_version',0,0xffffffff),('quota_kib',1,1024*1024)]:
            if type(defaults[name]) is not int or not lo<=defaults[name]<=hi:raise ValueError('invalid AppUtil '+name)
        if not isinstance(defaults['username'],str) or '\0' in defaults['username'] or not 1<=len(defaults['username'].encode())<=16:raise ValueError('invalid AppUtil username')

    def span(self,address,size,write=False):
        off=address-self.session.base
        if not address or size<0 or off<0 or off>len(self.session.memory) or size>len(self.session.memory)-off:raise AppError(PARAM)
        if write and size:
            runtime=self.session.runtime
            if not runtime.vn_guest_write_allowed(C.addressof(self.session.memory)+off,size):raise AppError(PARAM)
        return off

    def read(self,address,size):
        off=self.span(address,size);return bytes(self.session.memory[off:off+size])

    def write(self,address,data):
        off=self.span(address,len(data),True)
        C.memmove(C.addressof(self.session.memory)+off,data,len(data))
        self.session.runtime.vx_guest_memory_written()

    def word(self,address):return struct.unpack('<I',self.read(address,4))[0]

    def string(self,address):
        off=self.span(address,1);limit=min(1024,len(self.session.memory)-off)
        data=bytes(self.session.memory[off:off+limit]);end=data.find(b'\0')
        if end<0:raise AppError(PARAM)
        try:return data[:end].decode('utf-8')
        except UnicodeError:raise AppError(PARAM)

    def _mount(self):
        if self.root is not None:return
        root=getattr(self.session,'save_path',self.session.output/'saves')
        self.root=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            try:os.mkdir('.vitanx-apputil',mode=0o700,dir_fd=self.root)
            except FileExistsError:pass
            self.meta=os.open('.vitanx-apputil',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=self.root)
        except BaseException:
            os.close(self.root);self.root=None;raise

    def close(self):
        with self.lock:
            for fd in (self.meta,self.root):
                if fd is not None:os.close(fd)
            self.meta=self.root=None;self.initialized=False;self.events.clear()

    def _parts(self,name):
        if name.startswith('savedata0:'):name=name[10:];name=name[1:] if name.startswith('/') else name
        if not name or ':' in name or '\\' in name:raise AppError(PERMISSION)
        parts=name.split('/')
        if any(not p or p in ('.','..') or p.lower().startswith('.vitanx-') for p in parts):raise AppError(PERMISSION)
        return parts

    def parent(self,parts):
        fd=os.dup(self.root)
        try:
            for part in parts[:-1]:
                nextfd=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                os.close(fd);fd=nextfd
            return fd,parts[-1]
        except BaseException:os.close(fd);raise

    def _slot(self,ident):
        if not 0<=ident<256:raise AppError(PARAM)
        return 'slot-%03d.bin'%ident

    def _file_read(self,fd,name,size):
        f=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=fd)
        try:
            if not stat.S_ISREG(os.fstat(f).st_mode):raise AppError(PERMISSION)
            return os.read(f,size)
        finally:os.close(f)

    def _atomic(self,fd,name,data,exclusive=False):
        # Every persistent write, including metadata/safe memory, consumes quota.
        try:
            previous=os.stat(name,dir_fd=fd,follow_symlinks=False)
            old=previous.st_size if stat.S_ISREG(previous.st_mode) else 0
        except FileNotFoundError:old=0
        if self._used(self.root)+max(0,len(data)-old)>self.config['quota_kib']*1024:raise AppError(QUOTA)
        # New, inaccessible temporary file; rename remains inside the capability.
        temp='.vitanx-write-%s'%os.urandom(12).hex()
        f=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
        try:
            with os.fdopen(f,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
            if exclusive:
                os.link(temp,name,src_dir_fd=fd,dst_dir_fd=fd,follow_symlinks=False)
            else:os.replace(temp,name,src_dir_fd=fd,dst_dir_fd=fd)
        finally:
            try:os.unlink(temp,dir_fd=fd)
            except FileNotFoundError:pass

    def _used(self,fd):
        total=0
        for name in os.listdir(fd):
            st=os.stat(name,dir_fd=fd,follow_symlinks=False)
            if stat.S_ISREG(st.st_mode):total+=st.st_size
            elif stat.S_ISDIR(st.st_mode):
                sub=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                try:total+=self._used(sub)
                finally:os.close(sub)
        return total

    def queue_event(self,event_type,payload=b''):
        with self.lock:
            if not self.initialized:raise AppError(NOT_INIT)
            if not 1<=event_type<=0xffffffff or len(payload)>1024:raise AppError(PARAM)
            if len(self.events)>=32:raise AppError(BUSY)
            self.events.append(struct.pack('<I',event_type)+payload.ljust(1024,b'\0'))

    def invoke(self,nid,regs):
        with self.lock:
            args=list(regs[:4]);name=APIS[nid]
            try:result=self._invoke(name,regs)
            except AppError as error:result=error.code
            except OSError as error:
                result={errno.ENOENT:NOT_FOUND,errno.EEXIST:EXISTS,errno.ENOSPC:NO_SPACE,
                        errno.EDQUOT:QUOTA}.get(error.errno,PERMISSION)
            self.trace.append({'nid':'%08x'%nid,'name':name,'args':args,'result':result})
            return result

    def _invoke(self,name,r):
        if name=='init':
            if self.initialized:return BUSY
            a,b=r[0],r[1];self.span(a,64,True);self.span(b,40,True)
            if a<b+40 and b<a+64:raise AppError(PARAM)
            if any(self.read(a,64)) or any(self.read(b,40)):raise AppError(PARAM)
            self._mount()
            # Host storage handles work, so no guest scratch allocation is needed.
            self.write(a,bytes(64));self.write(b,struct.pack('<II',self.config['boot_attribute'],self.config['boot_version'])+bytes(32))
            self.initialized=True;return 0
        if not self.initialized:return NOT_INIT
        if name=='shutdown':self.close();return 0
        if name=='system_int':
            key={1:'language',2:'enter_button',4:'date_format',5:'time_format',6:'time_zone',7:'daylight_savings'}.get(r[0])
            if key is None:return PARAM
            self.write(r[1],struct.pack('<I',self.config[key]&0xffffffff));return 0
        if name=='system_string':
            if r[0]!=3:return PARAM
            data=self.config['username'].encode()+b'\0'
            if r[2]<len(data):return PARAM
            self.write(r[1],data);return 0
        if name=='event':
            self.span(r[0],1028,True)
            self.write(r[0],self.events[0] if self.events else bytes(1028))
            if self.events:self.events.popleft()
            return 0
        if name.startswith('slot_'):
            filename=self._slot(r[0]);mount=r[1] if name=='slot_delete' else r[2]
            if mount and any(self.read(mount,16)):return PARAM # only default mount supported
            if name=='slot_get':
                self.span(r[1],844,True);data=self._file_read(self.meta,filename,845)
                if len(data)!=844:return PARAM
                self.write(r[1],data)
            elif name=='slot_delete':os.unlink(filename,dir_fd=self.meta)
            else:
                data=self.read(r[1],844)
                if name=='slot_set':self._file_read(self.meta,filename,1)
                self._atomic(self.meta,filename,data,exclusive=name=='slot_create')
            return 0
        if name in ('safe_save','safe_load'):
            count=r[1];offset=struct.unpack('<q',struct.pack('<II',r[2],r[3]))[0]
            if offset<0 or count>65536 or offset+count>65536:return PARAM
            self.span(r[0],count,name=='safe_load')
            try:data=self._file_read(self.meta,'safe-memory.bin',65537)
            except FileNotFoundError:data=bytes(65536)
            if len(data)!=65536:return PARAM
            if name=='safe_load':self.write(r[0],data[offset:offset+count])
            else:self._atomic(self.meta,'safe-memory.bin',data[:offset]+self.read(r[0],count)+data[offset+count:])
            return count
        if name=='quota':
            if not r[0] and not r[1]:return PARAM
            if r[2] and any(self.read(r[2],16)):return PARAM
            if r[0]:self.span(r[0],4,True)
            if r[1]:self.span(r[1],4,True)
            used=(self._used(self.root)+1023)//1024
            if r[0]:self.write(r[0],struct.pack('<I',self.config['quota_kib']))
            if r[1]:self.write(r[1],struct.pack('<I',used))
            return 0
        if name in ('data_save','data_remove'):return self._data(name,r)
        raise RuntimeError('unregistered AppUtil operation')

    def _data(self,name,r):
        count=r[2]
        if not 1<=count<=256:return PARAM
        if r[3] and any(self.read(r[3],16)):return PARAM
        slotname=None;slotdata=None
        if r[0]:
            raw=self.read(r[0],40);ident,param=struct.unpack_from('<II',raw)
            if any(raw[8:]):return PARAM
            slotname=self._slot(ident)
            if param:slotdata=self.read(param,844)
        required=0
        if name=='data_save':
            required=self.word(r[13]) # fifth AAPCS argument is on guest stack
            if required:self.span(required,4,True)
        size=64 if name=='data_save' else 44
        raw=self.read(r[1],count*size);plans=[];growth=0;batch_bytes=0;seen=set()
        try:
            for i in range(count):
                record=raw[i*size:(i+1)*size];parts=self._parts(self.string(struct.unpack_from('<I',record)[0]))
                key=tuple(parts)
                if key in seen:return PARAM
                seen.add(key)
                fd,leaf=self.parent(parts)
                plans.append((fd,leaf,None,None))
                if name=='data_save':
                    buf,n=struct.unpack_from('<II',record,4);offset=struct.unpack_from('<q',record,16)[0];mode=struct.unpack_from('<I',record,24)[0]
                    if mode not in (0,1,2) or offset<0 or offset+n>MAX_TRANSFER or any(record[28:]):return PARAM
                    old=b''
                    if mode!=2:
                        try:old=self._file_read(fd,leaf,MAX_TRANSFER+1)
                        except FileNotFoundError:pass
                        if len(old)>MAX_TRANSFER:return PARAM
                        if n and not buf:return PARAM
                        payload=self.read(buf,n) if n else b''
                        new=old.ljust(offset+n,b'\0');new=new[:offset]+payload+new[offset+n:]
                        if mode==1:new=new[:offset+n]
                        batch_bytes+=len(new)
                        if batch_bytes>MAX_TRANSFER:return PARAM
                        growth+=max(0,len(new)-len(old))
                    else:
                        if buf or n or offset:return PARAM
                        new=None
                    plans[-1]=(fd,leaf,mode,new)
                else:
                    mode=struct.unpack_from('<I',record,4)[0]
                    if mode not in (0,1) or any(record[8:]):return PARAM
                    os.stat(leaf,dir_fd=fd,follow_symlinks=False) # validate all before removal
                    plans[-1]=(fd,leaf,mode,None)
            if name=='data_remove' and slotname and any(p[2]==0 for p in plans):
                os.stat(slotname,dir_fd=self.meta,follow_symlinks=False)
            if name=='data_save':
                excess=max(0,self._used(self.root)+growth-self.config['quota_kib']*1024)
                if required:self.write(required,struct.pack('<I',(excess+1023)//1024))
                if excess:return QUOTA
            for fd,leaf,mode,data in plans:
                if name=='data_save':
                    if mode==2:os.mkdir(leaf,mode=0o700,dir_fd=fd)
                    else:self._atomic(fd,leaf,data)
                else:
                    st=os.stat(leaf,dir_fd=fd,follow_symlinks=False)
                    if stat.S_ISDIR(st.st_mode):os.rmdir(leaf,dir_fd=fd)
                    else:os.unlink(leaf,dir_fd=fd)
            if slotname:
                if name=='data_save' and slotdata is not None:self._atomic(self.meta,slotname,slotdata)
                elif name=='data_remove' and any(p[2]==0 for p in plans):os.unlink(slotname,dir_fd=self.meta)
            return 0
        finally:
            for fd,_,_,_ in plans:os.close(fd)

    def report(self):
        with self.lock:return {'initialized':self.initialized,'configuration':self.config,'queued_events':len(self.events),'trace':list(self.trace),'implementation':'bounded native AppUtil model; partial API coverage'}
