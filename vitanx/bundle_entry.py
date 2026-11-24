"""Run one installed bundle with user-owned storage and bundled native tools."""
import json
import os
from pathlib import Path
import tempfile
import traceback

from .modules import ModuleSession


def main():
    resources = Path(__file__).resolve().parents[1]
    config = json.loads((resources/'game.json').read_text())
    support = Path.home()/'Library'/'Application Support'/config['bundle_id']
    support.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.environ['VITANX_BUNDLED_TOOLCHAIN'] = str(resources/'Toolchain')
    os.environ['VITANX_BUNDLED_FFMPEG'] = str(resources/'FFmpeg')
    os.environ['PATH'] = '/usr/bin:/bin'
    game = resources/'Game'
    with (support/'Last Run.log').open('a', encoding='utf-8') as log:
        try:
            with tempfile.TemporaryDirectory(prefix='run-', dir=support) as temp:
                result = ModuleSession(
                    [game/name for name in config['executables']], Path(temp)/'guest',
                    assets=game/'Assets', media=True, allow_unresolved=True,
                    instruction_limit=None, max_regions=4096, heap_size=256*1024**2,
                    native_cache=resources/'NativeCache', save_storage=support/'Saves',
                    region_store=support/'Native Regions',
                ).run()
                print(json.dumps({'status': result['status'], 'error': result.get('error'),
                                  'fault_context': result.get('fault_context')}), file=log)
                return int(result['status'] != 0)
        except Exception:
            traceback.print_exc(file=log)
            return 1


if __name__ == '__main__':
    raise SystemExit(main())
