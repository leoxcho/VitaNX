"""Embed bounded translated asset shaders, keyed by exact original GXP bytes."""
import json
import struct
from pathlib import Path
from .usse import translate_gxp, UnsupportedShader


def write_catalog(assets, destination):
    entries=[];report=[];declarations=[]
    root=Path(assets) if assets is not None else None
    if root is not None and (root.is_symlink() or not root.is_dir()):
        raise ValueError('GXM assets must be a real directory')
    paths=sorted(p for p in root.rglob('*') if p.suffix.lower() in ('.gxp','.vpo','.fpo') and p.is_file()) if root else []
    if len(paths)>256:
        raise ValueError('GXM asset catalog exceeds 256 shader files')
    for path in paths:
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('GXM shader assets must stay within asset directory')
        try:
            shader=translate_gxp(path)
        except (UnsupportedShader,ValueError) as error:
            report.append({'asset':str(path.relative_to(root)),'translation_supported':False,'reason':str(error)})
            continue
        raw=path.read_bytes();raw=raw[:struct.unpack_from("<I",raw,8)[0]];index=len(entries)
        declarations.append(f'static const uint8_t vx_gxp_bytes_{index}[]={{'+','.join(str(b) for b in raw)+'};')
        registers=','.join(str(p['resource_index']) for p in shader['inputs']) or '0'
        components=','.join(str(p['components']) for p in shader['inputs']) or '0'
        varyings=int(shader['interface']['color']) | (int(shader['interface']['texcoord'])<<1)
        entries.append('{'+f'vx_gxp_bytes_{index},{len(raw)},{json.dumps(shader["msl"])},'+
                       f'{int(shader["stage"]=="fragment")},{shader["uniform_words"]},{len(shader["inputs"])},{shader["texture_mask"]},{varyings},'+
                       '{'+registers+'},{'+components+'}}')
        report.append({k:v for k,v in shader.items() if k not in ('msl','operations') } | {'asset':str(path.relative_to(root))})
    text='\n'.join(declarations)+'\n'
    if entries:
        text+='static const vx_gxm_shader vx_gxm_catalog[]={\n'+',\n'.join(entries)+'\n};\n'
        text+='static int vx_install_gxm_catalog(void){return vx_gxm_set_catalog(vx_gxm_catalog,sizeof vx_gxm_catalog/sizeof vx_gxm_catalog[0]);}\n'
    else:
        text+='static int vx_install_gxm_catalog(void){return vx_gxm_set_catalog(0,0);}\n'
    Path(destination).write_text(text)
    return report
