"""Bounded read-only header/metadata inventory. Never extracts or decrypts ROMs."""
import argparse,json,os,struct,zipfile
from pathlib import Path

def classify(stream,size):
    head=stream.read(min(size,65536))
    if head[:4]==b'\x7fELF':return {'format':'ELF','content':'plaintext','arm32':head[4:7]==b'\x01\x01\x01' and len(head)>20 and struct.unpack_from('<H',head,18)[0]==40}
    if head[:4]!=b'SCE\0':return {'format':'unknown','content':'undetermined'}
    result={'format':'SELF','content':'undetermined'}
    try:
        eo,si=struct.unpack_from('<Q',head,64)[0],struct.unpack_from('<Q',head,88)[0]
        n=struct.unpack_from('<H',head,eo+44)[0]
        if not 0<n<=128 or si+n*32>len(head):return result
        enc=[struct.unpack_from('<Q',head,si+i*32+24)[0] for i in range(n)]
        result.update(segment_encryption_flags=enc,content='encrypted' if 1 in enc else 'plaintext_container' if all(x==2 for x in enc) else 'undetermined')
    except (struct.error,IndexError):pass
    return result

def inventory(root,max_entries=100000):
    root=Path(root);games={};count=0;truncated=False
    for parent,dirs,files in os.walk(root,followlinks=False):
        dirs[:]=[d for d in dirs if not d.startswith('.') and not (Path(parent)/d).is_symlink()]
        for name in files:
            if name.startswith('.'):continue
            p=Path(parent)/name; rel=p.relative_to(root);game=rel.parts[0]
            row=games.setdefault(game,{'files':0,'metadata':[],'executables':[],'archives':[],'asset_extensions':{}})
            row['files']+=1;count+=1
            if count>max_entries:truncated=True;break
            suffix=p.suffix.lower()
            try:
                if name.lower()=='eboot.bin' or suffix in ('.self','.elf','.suprx','.skprx'):
                    with p.open('rb') as f: kind=classify(f,p.stat().st_size)
                    row['executables'].append({'path':str(rel),'bytes':p.stat().st_size,**kind})
                elif 'sce_sys' in rel.parts and suffix in ('.sfo','.xml','.png'):
                    row['metadata'].append(str(rel))
                elif suffix in ('.vpk','.zip'):
                    with zipfile.ZipFile(p) as z:
                        items=z.infolist();targets=[]
                        for i in items[:30000]:
                            if Path(i.filename).name.lower()=='eboot.bin' or Path(i.filename).suffix.lower() in ('.elf','.suprx','.self'):
                                with z.open(i) as f:kind=classify(f,i.file_size)
                                targets.append({'path':i.filename,**kind})
                        row['archives'].append({'path':str(rel),'entries':len(items),'executables':targets})
                else:row['asset_extensions'][suffix]=row['asset_extensions'].get(suffix,0)+1
            except (OSError,zipfile.BadZipFile,RuntimeError) as e:row.setdefault('errors',[]).append({'path':str(rel),'error':str(e)})
        if truncated:break
    return {'root':str(root),'files_enumerated':count,'truncated':truncated,'games':games,'read_only':True,'decryption_performed':False}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    a.output.write_text(json.dumps(inventory(a.root),indent=2)+'\n')
