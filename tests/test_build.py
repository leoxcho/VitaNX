"""End-to-end translation, packaging, signing and direct native execution."""
import hashlib
import json
import platform
import subprocess
import tempfile
import unittest
from pathlib import Path
from vitaxnative.build import build_native

ROOT = Path(__file__).resolve().parents[1]

@unittest.skipUnless(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'Apple Silicon required')
class BuildIntegrationTests(unittest.TestCase):
    def test_signed_standalone_homebrew_and_no_overwrite(self):
        source = ROOT/'fixtures/recompiler/hello.elf'
        original = source.read_bytes()
        manifest = json.loads((source.with_suffix('.json')).read_text())
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'build'
            result = build_native(source, out, imports={int(k):v for k,v in manifest['imports'].items()},
                                  expected_r0=manifest['expected_r0'], verify=True)
            self.assertEqual(result['execution']['stdout'], manifest['expected_stdout'])
            self.assertTrue(result['execution']['executed'])
            app = Path(result['app'])
            subprocess.run(['codesign','--verify','--strict',str(app)],check=True,capture_output=True)
            self.assertTrue((app/'Contents/Resources/conversion.json').is_file())
            binary = app/'Contents/MacOS/Game'
            self.assertEqual(hashlib.sha256(binary.read_bytes()).hexdigest(),result['binary_sha256'])
            with self.assertRaises(FileExistsError): build_native(source, out)
            # A failed translation must not leave a published app or staging tree.
            bad = Path(tmp)/'bad.elf'; bad.write_bytes(b'invalid')
            with self.assertRaises(ValueError): build_native(bad, Path(tmp)/'failed')
            self.assertFalse((Path(tmp)/'failed').exists())
            self.assertFalse(list(Path(tmp).glob('.vx-build-*')))
        self.assertEqual(source.read_bytes(), original)

    def test_compiled_c_source_pipeline(self):
        import shutil
        if not shutil.which('ld.lld'):
            self.skipTest('LLD required to compile ARM fixture')
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)/'source.elf'
            subprocess.run(['python3',str(ROOT/'fixtures/homebrew/build_fixture.py'),str(source)],
                           check=True,capture_output=True)
            manifest = json.loads((ROOT/'fixtures/homebrew/main.json').read_text())
            result = build_native(source,Path(tmp)/'native',imports={8192:0x34efd876},verify=True)
            self.assertEqual(result['execution']['stdout'],manifest['expected_stdout'])
            self.assertEqual(result['execution']['returncode'],0)

    def test_plaintext_self_to_native_and_encrypted_refusal(self):
        import struct
        from test_self_extract import fixture
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)/'homebrew.self'
            data = fixture(True)
            # Reuse original synthetic SELF layout at a supported fixed address.
            struct.pack_into('<I',data,184,0x100)
            struct.pack_into('<I',data,232,0x100)
            source.write_bytes(data)
            result = build_native(source,Path(tmp)/'native',expected_r0=1,verify=True)
            self.assertTrue(result['execution']['executed'])
            self.assertEqual(source.read_bytes(),data)
            struct.pack_into('<Q',data,280,1)
            source.write_bytes(data)
            with self.assertRaisesRegex(ValueError,'encrypted SELF'):
                build_native(source,Path(tmp)/'rejected')
            self.assertFalse((Path(tmp)/'rejected').exists())

    def test_compiled_save_roundtrip_persists_between_processes(self):
        import os
        import shutil
        if not shutil.which('ld.lld'):
            self.skipTest('LLD required')
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)/'save.elf'
            subprocess.run(['python3',str(ROOT/'fixtures/homebrew/build_fixture.py'),str(source),
                            '--source','save.c'],check=True,capture_output=True)
            manifest = json.loads((ROOT/'fixtures/homebrew/save.json').read_text())
            out = Path(tmp)/'build'
            result = build_native(source,out,imports={int(k):v for k,v in manifest['imports'].items()},verify=True)
            saved = out/'saves/homebrew-save.bin'
            self.assertEqual(saved.read_bytes(),b'VITA')
            # Directly launch the final signed bundle again against the same save root.
            subprocess.run([str(Path(result['app'])/'Contents/MacOS/Game')],
                           env={**os.environ,'VX_SAVE_ROOT':str(out/'saves')},
                           check=True,capture_output=True,timeout=10)
            self.assertEqual(saved.read_bytes(),b'VITA')

    def test_standalone_app0_resources(self):
        import os
        import shutil
        if not shutil.which('ld.lld'):
            self.skipTest('LLD required')
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp)
            source=tmp/'assets.elf'
            subprocess.run(['python3',str(ROOT/'fixtures/homebrew/build_fixture.py'),str(source),
                            '--source','assets.c'],check=True,capture_output=True)
            assets=tmp/'original-assets'
            (assets/'data').mkdir(parents=True)
            payload=assets/'data/payload.bin';payload.write_bytes(b'VITA')
            result=build_native(source,tmp/'native',assets=assets,
                                imports={8192:0xcc67b6fd,8200:0xfdb32293,8204:0xc70b8886},verify=True)
            self.assertTrue(result['execution']['executed'])
            self.assertEqual(result['assets'],[{'path':'data/payload.bin',
                             'sha256':hashlib.sha256(b'VITA').hexdigest()}])
            # Remove the fixture input from the resolution path; bundle is standalone.
            assets.rename(tmp/'preserved-original-assets')
            subprocess.run([str(Path(result['app'])/'Contents/MacOS/Game')],check=True,
                           env={**os.environ,'VX_SAVE_ROOT':str(tmp/'native/saves')},
                           capture_output=True,timeout=10)
            self.assertEqual((tmp/'preserved-original-assets/data/payload.bin').read_bytes(),b'VITA')
            (tmp/'preserved-original-assets/link').symlink_to(payload)
            with self.assertRaisesRegex(ValueError,'symlinks'):
                build_native(source,tmp/'rejected',assets=tmp/'preserved-original-assets',
                             imports={8192:0xcc67b6fd,8200:0xfdb32293,8204:0xc70b8886})
            self.assertFalse((tmp/'rejected').exists())

    def test_execution_failure_does_not_publish(self):
        source = ROOT/'fixtures/recompiler/hello.elf'
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'failed'
            # Hello returns its write count, so expecting zero must fail verification.
            with self.assertRaisesRegex(RuntimeError,'failed'):
                build_native(source,out,imports={8192:0x34efd876},verify=True)
            self.assertFalse(out.exists())
            self.assertFalse(list(Path(tmp).glob('.vx-build-*')))

    def test_thumb_standalone_conversion(self):
        source = ROOT/'fixtures/homebrew/thumb.elf'
        manifest=json.loads(source.with_suffix('.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            result=build_native(source,Path(tmp)/'thumb',imports={0x2348:0x34efd876},
                                expected_r0=manifest['expected_r0'],verify=True)
            self.assertEqual(result['entry']&1,1)
            self.assertEqual(result['execution']['stdout'],manifest['expected_stdout'])
            self.assertIn('final signed',result['execution']['method'])

@unittest.skipUnless(platform.system()=='Darwin' and platform.machine()=='arm64','Apple Silicon required')
class VitaSDKStandaloneTests(unittest.TestCase):
    def test_display_pacing_standalone_and_configuration_validation(self):
        import importlib.util
        sdk=ROOT.parent/'vitasdk/bin/arm-vita-eabi-gcc'
        if not sdk.is_file():self.skipTest('VitaSDK required')
        spec=importlib.util.spec_from_file_location('sdk_fixture',ROOT/'fixtures/vitasdk/build_fixture.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as d:
            d=Path(d)
            source=module.build(d/'fixture','display')
            result=build_native(source,d/'native',imports={},verify=True,
                                display={'render_hz':120,'simulation_hz':60})
            self.assertEqual(result['memory_base'],0x81000000)
            self.assertIn('waits 1',result['execution']['stderr'])
            self.assertIn('presented 0',result['execution']['stderr'])
            self.assertEqual(len(result['runtime_sources']),10)
            self.assertTrue(result['relocation_validation']['identity_load_validated'])
            for display in ({'render_hz':0},{'width':960},{'unknown':1},{'render_hz':True}):
                with self.assertRaisesRegex(ValueError,'display configuration'):
                    build_native(source,d/'invalid',display=display)
                self.assertFalse((d/'invalid').exists())
