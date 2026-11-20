import tempfile, unittest
from pathlib import Path
from vitanx.launcher import game_command
from vitanx.graphics import RuntimeShaderTranslator

class LauncherTests(unittest.TestCase):
    def test_plan_and_safety(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); main=Path('fixtures/recompiler/hello.elf').resolve(); assets=root/'original assets';assets.mkdir()
            out=root/'new run'; cmd=game_command(main,out,assets=assets)
            self.assertIn('--media',cmd); self.assertIn(str(assets),cmd);self.assertFalse(out.exists())
            for kwargs in ({'modules':[main]}, {'limit':0}):
                with self.assertRaises(ValueError):game_command(main,out,**kwargs)
            with self.assertRaises(ValueError):game_command(main,assets/'new',assets=assets)
            with self.assertRaises(ValueError):game_command(main,assets)
            bad=root/'bad.elf';bad.write_bytes(b'SCE\0'+bytes(100))
            with self.assertRaises(ValueError):game_command(bad,out)
    def test_null_shader_pointer(self):
        translator=RuntimeShaderTranslator.__new__(RuntimeShaderTranslator)
        self.assertIsNone(translator._resolve(None,156))
