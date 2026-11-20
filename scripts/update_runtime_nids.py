"""Record exact public VitaSDK library/function IDs already implemented locally."""
from pathlib import Path
import hashlib,json,re,urllib.request
root=Path(__file__).resolve().parents[1]
implemented={name:int(nid,16) for nid,name in re.findall(r'\{UINT32_C\(0x([0-9a-fA-F]+)\),"([^"]+)"',(root/'runtime/vita_runtime.c').read_text())}
rows=[];sources=[]
for filename in ('SceLibKernel','SceKernelThreadMgr','SceIofilemgr','SceProcessmgr','SceSysmem'):
    url=f'https://raw.githubusercontent.com/vitasdk/vita-headers/master/db/360/{filename}.yml'
    raw=urllib.request.urlopen(url,timeout=20).read();sources.append({'url':url,'sha256':hashlib.sha256(raw).hexdigest()})
    library=None;libnid=None
    for line in raw.decode().splitlines():
        m=re.fullmatch(r'      (\w+):',line)
        if m:library=m[1];libnid=None
        m=re.fullmatch(r'        nid: 0x([0-9a-fA-F]+)',line)
        if m:libnid=m[1].lower().zfill(8)
        m=re.fullmatch(r'          (\w+): 0x([0-9a-fA-F]+)',line)
        if m and libnid and implemented.get(m[1])==int(m[2],16):
            rows.append({'library':library,'library_nid':libnid,'name':m[1],'function_nid':m[2].lower().zfill(8)})
rows.append({'library':'SceThreadmgr','library_nid':'859a24b1','name':'sceKernelExitThread','function_nid':'0c8a38e1','compatibility_alias':'Legacy library import observed in original SceLibc; current SDK lists the same API/NID under SceThreadmgrCoredumpTime.'})
addons=set()
for name in ('device-nids.json','process-nids.json','format-nids.json','io-nids.json','memory-nids.json'):
    p=root/'vitanx'/name
    if p.exists():addons.update((r['library_nid'],r['function_nid']) for r in json.loads(p.read_text())['bindings'])
rows=[r for r in rows if (r['library_nid'],r['function_nid']) not in addons]
(root/'vitanx/runtime-nids.json').write_text(json.dumps({'sources':sources,'bindings':rows},indent=2)+'\n')
print('recorded',len(rows),'exact library/function runtime bindings')
