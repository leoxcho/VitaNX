"""Explicit-input, read-only discovery and isolated conversion frontend."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import sys
from vitaxnative.elf_segments import inspect_elf_segments
from vitaxnative.build import build_native

ROOT = Path(__file__).resolve().parents[1]

def inspect(path):
    report = inspect_elf_segments(path)
    report.update(project='vitanx', commercial_compatibility=False,
                  status='structural_candidate_only', dynamic_execution_fallback='available via run-native; input not execution-verified',
                  warning='Structural analysis only; conversion must separately validate reachable instructions and imports')
    return report

def convert(source, output, *, expected_r0=0, imports=None, verify=False):
    inspect(source)  # CLI deliberately accepts plaintext ELF only.
    return build_native(source, output, imports=imports, expected_r0=expected_r0,
                        name='vitanx Homebrew', bundle_id='org.vitanx.homebrew', verify=verify)

def smoke(output):
    source=ROOT/'fixtures/recompiler/hello.elf'
    manifest=json.loads(source.with_suffix('.json').read_text())
    before=hashlib.sha256(source.read_bytes()).hexdigest()
    result=convert(source,output,imports={int(k):v for k,v in manifest['imports'].items()},
                   expected_r0=manifest['expected_r0'],verify=True)
    if result['execution']['stdout'] != manifest['expected_stdout']:
        raise RuntimeError('smoke stdout mismatch')
    if hashlib.sha256(source.read_bytes()).hexdigest()!=before:
        raise RuntimeError('fixture changed')
    result.update(project='vitanx', plaintext_smoke_verified=True,
                  fixture_provenance=manifest['provenance'], commercial_compatibility=False,
                  rendering_verified=False, gameplay_verified=False)
    (output/'vitanx-evidence.json').write_text(json.dumps(result,indent=2)+'\n')
    return result

def main(argv=None):
    p=argparse.ArgumentParser(prog='vitanx',description='Plaintext Vita ELF static recompilation; experimental, no commercial compatibility claim.')
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('doctor')
    q=sub.add_parser('inspect'); q.add_argument('source',type=Path)
    q=sub.add_parser('inspect-gxp',help='Read bounded original shader metadata; no translation or execution'); q.add_argument('source',type=Path)
    q=sub.add_parser('discover'); q.add_argument('directory',type=Path)
    q=sub.add_parser('convert'); q.add_argument('source',type=Path); q.add_argument('output',type=Path); q.add_argument('--expected-r0',type=lambda s:int(s,0),default=0)
    q=sub.add_parser('run-native',help='Execute authorized plaintext ELF with live native translation; no app build'); q.add_argument('source',type=Path); q.add_argument('output',type=Path); q.add_argument('--instruction-limit',type=int,default=1000000); q.add_argument('--imports',type=Path,help='Explicit homebrew import manifest when module metadata is absent')
    q=sub.add_parser('list-games',help='Read-only inventory of installed Vita3K titles, patches and DLC')
    q.add_argument('--app-root',type=Path,default=None)
    q=sub.add_parser('run-game',help='Run original plaintext game and support modules with media; experimental, not standalone packaging')
    q.add_argument('source',type=Path); q.add_argument('output',type=Path)
    q.add_argument('--module',type=Path,action='append',default=[]); q.add_argument('--assets',type=Path); q.add_argument('--native-cache',type=Path)
    q.add_argument('--instruction-limit',type=int,default=1000000); q.add_argument('--max-regions',type=int,default=4096); q.add_argument('--heap-mib',type=int,default=256)
    q.add_argument('--no-media',action='store_true'); q.add_argument('--plan',action='store_true',help='Validate inputs and print command without executing')
    q=sub.add_parser('smoke'); q.add_argument('output',type=Path)
    a=p.parse_args(argv)
    try:
        if a.command=='doctor':
            result={'project':'vitanx','host':platform.platform(),'machine':platform.machine(),
                    'tools':{x:shutil.which(x) for x in ('clang','codesign','otool')},
                    'static_translation':True,'runtime_fallback':'run-native can extend translated code at an unseen executable PC',
                    'dynamic_execution_fallback':True,'commercial_compatibility':False}
        elif a.command=='list-games':
            from .installed_games import DEFAULT_APP_ROOT, list_installed_games
            result=list_installed_games(a.app_root if a.app_root is not None else DEFAULT_APP_ROOT)
        elif a.command=='run-game':
            from .launcher import game_command,run_game
            command=game_command(a.source,a.output,modules=a.module,assets=a.assets,cache=a.native_cache,limit=a.instruction_limit,regions=a.max_regions,heap=a.heap_mib,media=not a.no_media)
            if not a.plan: return run_game(command)
            result={'command':command,'execution_verified':False,'commercial_compatibility':False}
        elif a.command=='inspect': result=inspect(a.source)
        elif a.command=='inspect-gxp':
            from vitaxnative.gxp import inspect_gxp
            result=inspect_gxp(a.source)
        elif a.command=='discover':
            result=[]
            # One directory only: no ROM/library/home traversal or implicit launch.
            for path in sorted(a.directory.iterdir()):
                if path.is_file() and not path.is_symlink() and path.suffix.lower()=='.elf':
                    try: result.append(inspect(path))
                    except ValueError as e: result.append({'path':str(path),'error':str(e)})
        elif a.command=='run-native':
            from .dynamic import NativeSession
            imports=None
            if a.imports:
                from vitaxnative.__main__ import _manifest_object,_manifest_imports
                manifest=json.loads(a.imports.read_text(),object_pairs_hook=_manifest_object)
                if not isinstance(manifest,dict): raise ValueError('import manifest must be an object')
                mapping=manifest.get('imports',manifest)
                if not isinstance(mapping,dict): raise ValueError('imports must be an object')
                imports=_manifest_imports(mapping)
            result=NativeSession(a.source,a.output,imports=imports,instruction_limit=a.instruction_limit).run()
        elif a.command=='convert': result=convert(a.source,a.output,expected_r0=a.expected_r0)
        else: result=smoke(a.output)
        print(json.dumps(result,indent=2)); return int(a.command=='run-native' and result['status']!=0)
    except (ValueError,OSError,RuntimeError) as e:
        print(json.dumps({'project':'vitanx','error':str(e),'commercial_compatibility':False}),file=sys.stderr); return 1
