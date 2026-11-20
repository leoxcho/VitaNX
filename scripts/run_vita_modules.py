"""Explicit plaintext Vita module execution; no packaging or original writes."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from vitanx.modules import ModuleSession
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('main',type=Path);p.add_argument('output',type=Path)
p.add_argument('--module',action='append',type=Path,default=[])
p.add_argument('--deferred',action='append',type=Path,default=[])
def system_provider(value):
    try:
        ident,path=value.split('=',1);ident=int(ident,0)
        if not 1<=ident<=0x55:raise ValueError()
        return ident,Path(path)
    except ValueError:raise argparse.ArgumentTypeError('expected ID=/plaintext/provider.elf, ID 1..0x55')
p.add_argument('--sysmodule',action='append',type=system_provider,default=[],help='Explicit authorized plaintext system-module provider, ID=PATH')
p.add_argument('--boundary-handler',type=Path,help='Developer Python resolver exporting resolve(session, import_info, cpu_pointer); runs at a live import boundary')
p.add_argument('--apputil-config',type=Path,help='Explicit local AppUtil device configuration JSON')
p.add_argument('--assets',type=Path,help='Read-only original game asset root; saves stay in output')
p.add_argument('--native-cache',type=Path)
p.add_argument('--media',action='store_true',help='Connect existing GXM/Metal, Core Audio, controller and touch bridges to shared guest memory')
p.add_argument('--max-regions',type=int,default=128)
p.add_argument('--checkpoint-at',type=int,action='append',default=[])
p.add_argument('--heap-mib',type=int,default=4)
p.add_argument('--instruction-limit',type=int,default=100000)
p.add_argument('--diagnostic-unresolved',action='store_true',help='Keep unresolved imports as traps reached at runtime; never return invented results')
a=p.parse_args()
try:
    handler=None
    if a.boundary_handler:
        import runpy
        handler=runpy.run_path(str(a.boundary_handler)).get('resolve')
        if not callable(handler):raise ValueError('boundary handler must export callable resolve')
    result=ModuleSession([a.main,*a.module],a.output,deferred=a.deferred,
                         instruction_limit=a.instruction_limit,allow_unresolved=a.diagnostic_unresolved,heap_size=a.heap_mib*1024*1024,execution_checkpoints=a.checkpoint_at,native_cache=a.native_cache,max_regions=a.max_regions,assets=a.assets,media=a.media,sysmodules=dict(a.sysmodule),boundary_handler=handler,apputil_config=json.loads(a.apputil_config.read_text()) if a.apputil_config else None).run()
    print(json.dumps(result,indent=2));sys.exit(int(result['status']!=0))
except (ValueError,OSError,RuntimeError) as e:
    print(json.dumps({'error':str(e),'commercial_compatibility':False}),file=sys.stderr);sys.exit(1)
