"""CommonDialog configuration only; no simulated UI or rendering completion.

Numeric ABI/layout references: VitaSDK psp2/common_dialog.h and SceCommonDialog.yml.
"""
import struct,threading
LIBRARY='e537816c'
APIS={0xbecd35c8:'configure',0x043a353e:'is_running'}
class CommonDialog:
    def __init__(self,session):
        self.session=session;self.lock=threading.RLock();self.config=None;self.trace=[]
    def invoke(self,nid,r):
        with self.lock:
            result=0
            if nid==0xbecd35c8:
                a=r[0];off=a-self.session.base
                if not a:result=0x80020402
                elif off<0 or off+44>len(self.session.memory):result=0x80020403
                else:
                    raw=bytes(self.session.memory[off:off+44]);sdk,language,button=struct.unpack_from('<III',raw)
                    if any(raw[12:]):result=0x80020403
                    elif language!=0xffffffff and language>19:result=0x80020431
                    elif button not in (0,1,0xffffffff):result=0x80020432
                    else:
                        app=getattr(self.session,'apputil',None)
                        defaults=app.config if app is not None else {'language':1,'enter_button':1}
                        self.config={'sdk_version':sdk,'language':defaults['language'] if language==0xffffffff else language,
                                     'enter_button':defaults['enter_button'] if button==0xffffffff else button}
            elif nid!=0x043a353e:raise ValueError('unsupported CommonDialog NID')
            self.trace.append({'nid':'%08x'%nid,'argument':int(r[0]),'result':result})
            self.trace=self.trace[-64:]
            return result
    def report(self):
        with self.lock:return {'configured':self.config is not None,'configuration':self.config,'running':False,'trace':self.trace,'scope':'configuration and idle query only; dialog UI unsupported'}
