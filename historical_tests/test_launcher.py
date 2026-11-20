"""Library safety, honest capability gates and recoverable app installation."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import platform
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from vitaxnative import workflow

ROOT=Path(__file__).resolve().parents[1]

class LauncherWorkflowTests(unittest.TestCase):
    def test_catalogue_handles_disconnected_volume_and_hidden_files(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            self.assertFalse(workflow.catalogue(root/'missing')['available'])
            (root/'demo.elf').write_bytes(b'bad')
            (root/'.sidecar.elf').write_bytes(b'bad')
            (root/'notes.txt').write_text('test')
            result=workflow.catalogue(root)
            self.assertEqual([Path(g['path']).name for g in result['games']],['demo.elf'])

    def test_supported_and_missing_runtime_import_reports(self):
        source=ROOT/'fixtures/homebrew/main.elf'
        result=workflow.compatibility(source)
        self.assertTrue(result['conversion_candidate'],result)
        self.assertFalse(result['native_execution_verified'])
        self.assertFalse(result['playable'])
        with patch.object(workflow,'supported_nids',return_value=set()):
            result=workflow.compatibility(source)
        self.assertFalse(result['conversion_candidate'])
        self.assertEqual(result['missing_imports'],['0x34efd876'])
        self.assertIn('runtime imports',result['reason'])

    def test_controller_import_requires_window_feature(self):
        with patch.object(workflow,'_manifest',return_value={'imports':{8192:0xA497B150}}):
            result=workflow.compatibility(ROOT/'fixtures/homebrew/main.elf')
        self.assertTrue(result['conversion_candidate'],result)
        self.assertIn('window',result['required_features'])
        self.assertIn('display',result['required_features'])

    def test_encrypted_self_report_preserves_source(self):
        from test_self_extract import fixture
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'eboot.bin';original=fixture(encryption=1);source.write_bytes(original)
            result=workflow.compatibility(source)
            self.assertFalse(result['conversion_candidate'])
            self.assertIn('encrypted SELF',result['reason'])
            self.assertEqual(workflow.library_status(source),'Blocked: encrypted executable')
            self.assertEqual(source.read_bytes(),original)

    def test_archive_traversal_and_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'bad.vpk'
            with zipfile.ZipFile(p,'w') as z:
                z.writestr('eboot.bin',b'bad');z.writestr('../escape',b'bad')
            with self.assertRaisesRegex(ValueError,'unsafe'):
                with workflow.prepared_source(p):pass
            with zipfile.ZipFile(p,'w') as z:
                z.writestr('eboot.bin',b'bad')
                item=zipfile.ZipInfo('link');item.external_attr=0o120777<<16
                z.writestr(item,'/elsewhere')
            with self.assertRaisesRegex(ValueError,'symlink'):
                with workflow.prepared_source(p,assets=True):pass
            self.assertFalse((Path(d)/'escape').exists())

    def test_diagnosis_does_not_modify_input(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'bad.elf';p.write_bytes(b'bad')
            result=workflow.diagnose_build(p)
            self.assertFalse(result['changes_made'])
            self.assertEqual(p.read_bytes(),b'bad')
            with self.assertRaises(ValueError):workflow.convert_game(p,applications=Path(d)/'apps')
            self.assertFalse((Path(d)/'apps').exists())

    def test_terminal_menu_exit_and_invalid_selection(self):
        from vitaxnative.launcher import main,MENU
        self.assertEqual(len(MENU),10)
        with patch('builtins.input',side_effect=['99','0']),redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(),0)
        self.assertIn('Browse PlayStation Vita Games',output.getvalue())
        self.assertIn('Choose a number from 0 to 10',output.getvalue())

    @unittest.skipUnless(platform.system()=='Darwin' and platform.machine()=='arm64' and shutil.which('clang'),'Apple Silicon required')
    def test_native_install_rebuild_retains_original_and_signed_app(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d)
            with patch.object(workflow,'BUILD_ROOT',d/'builds'):
                result=workflow.convert_game(ROOT/'fixtures/homebrew/main.elf',applications=d/'apps',display={},verify=True)
                app=Path(result['app'])
                self.assertTrue(result['execution']['executed'])
                self.assertTrue((app/'Contents/MacOS/Game').is_file())
                with self.assertRaises(FileExistsError):
                    workflow.convert_game(ROOT/'fixtures/homebrew/main.elf',applications=d/'apps',display={})
                updated=workflow.rebuild_app(app,display={})
                backup=Path(updated['backup'])
                self.assertTrue((backup/'Contents/MacOS/Game').is_file())
                self.assertTrue((app/'Contents/MacOS/Game').is_file())
                self.assertNotEqual(updated['build'],result['build'])
                self.assertEqual(len(workflow.installed_apps(d/'apps')),1)
                manifest=json.loads((Path(updated['build'])/'build.json').read_text())
                self.assertEqual(manifest['binary_sha256'],updated['binary_sha256'])


class LauncherMenuTests(unittest.TestCase):
    def test_browse_launch_build_rebuild_and_compatibility_dispatch(self):
        from vitaxnative.launcher import main
        config={'roms':'/library','applications':'/apps','display':{'window':True}}
        game={'title':'Demo','path':'/library/demo.velf'}
        with patch.object(workflow,'settings',return_value=config), \
             patch.object(workflow,'catalogue',return_value={'available':True,'games':[game]}), \
             patch.object(workflow,'installed_apps',return_value=[Path('/apps/Demo.app')]), \
             patch.object(workflow,'convert_game',return_value={}) as convert, \
             patch.object(workflow,'rebuild_app',return_value={}) as rebuild, \
             patch.object(workflow,'launch_app',return_value={}) as launch, \
             patch.object(workflow,'compatibility',return_value={}) as compatibility, \
             patch('builtins.input',side_effect=['1','2','1','3','1','4','1','5','1','8','1','0']), \
             redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(),0)
        convert.assert_called_once_with(Path('/library/demo.velf'),applications='/apps',display={'window':True})
        launch.assert_called_once_with(Path('/apps/Demo.app'))
        self.assertEqual(rebuild.call_count,2)
        compatibility.assert_called_once_with(Path('/library/demo.velf'))
        self.assertIn('Demo',output.getvalue())

    def test_operation_error_returns_to_menu(self):
        from vitaxnative.launcher import main
        with patch.object(workflow,'settings',return_value={'applications':'/apps'}), \
             patch.object(workflow,'installed_apps',return_value=[Path('/apps/Demo.app')]), \
             patch.object(workflow,'launch_app',side_effect=RuntimeError('signature failed')), \
             patch('builtins.input',side_effect=['3','1','0']),redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(),0)
        self.assertIn('signature failed',output.getvalue())

    @unittest.skipUnless(platform.system()=='Darwin' and platform.machine()=='arm64','Apple Silicon required')
    def test_window_install_uses_startup_and_failed_rebuild_preserves_app(self):
        from vitaxnative.build import NativeVerificationError
        evidence={'executed':True,'observation':'running_at_deadline_then_terminated',
                  'native_exit_verified':False,'playable_verified':False}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with patch.object(workflow,'BUILD_ROOT',root/'builds'), \
                 patch('vitaxnative.build.verify_native',return_value=evidence) as verify:
                result=workflow.convert_game(ROOT/'fixtures/homebrew/main.elf',applications=root/'apps',display={'window':True})
            verify.assert_called_once()
            self.assertEqual(verify.call_args.kwargs['mode'],'startup')
            app=Path(result['app']);original=(app/'Contents/MacOS/Game').read_bytes()
            self.assertFalse(result['execution']['native_exit_verified'])
            with patch.object(workflow,'BUILD_ROOT',root/'builds'), \
                 patch('vitaxnative.build.verify_native',side_effect=NativeVerificationError('crash',{'observation':'crashed'})):
                with self.assertRaisesRegex(RuntimeError,'crash'):workflow.rebuild_app(app)
            self.assertEqual((app/'Contents/MacOS/Game').read_bytes(),original)
            self.assertFalse((root/'apps/.vitaxnative-backups').exists())
            failed=[json.loads(p.read_text()) for p in (root/'builds').glob('*/build.json')]
            self.assertIn('crashed',[r['execution'].get('observation') for r in failed])

class ExecutableSelectionTests(unittest.TestCase):
    def make_game(self, root, suffix='.elf'):
        from test_self_extract import fixture
        from vitaxnative.self_extract import extract_self
        original=root/'eboot.bin';original.write_bytes(fixture(encryption=1))
        plain=root/'plain.bin';plain.write_bytes(fixture())
        companion=root/('eboot'+suffix)
        if suffix=='.self':companion.write_bytes(plain.read_bytes())
        else:extract_self(plain,companion)
        plain.unlink()
        return original,companion

    def test_elf_velf_and_plaintext_self_selected_without_modifying_original(self):
        for suffix in ('.elf','.velf','.self'):
            with self.subTest(suffix=suffix),tempfile.TemporaryDirectory() as d:
                root=Path(d);original,companion=self.make_game(root,suffix)
                before=original.read_bytes()
                report=workflow.compatibility(root)
                self.assertTrue(report['conversion_candidate'],report)
                self.assertEqual(report['selected_executable'],str(companion))
                self.assertFalse(report['playable'])
                with workflow.prepared_source(root,assets=True) as (source,assets):
                    self.assertEqual(source,companion);self.assertEqual(assets,root)
                self.assertEqual(original.read_bytes(),before)

    def test_invalid_mismatched_encrypted_and_ambiguous_companions_fail_closed(self):
        import struct
        from test_self_extract import fixture
        for mode in ('invalid','mismatch','encrypted','ambiguous','symlink'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
                root=Path(d);original,companion=self.make_game(root)
                if mode=='invalid':companion.write_bytes(b'bad')
                elif mode=='mismatch':
                    data=bytearray(companion.read_bytes());struct.pack_into('<I',data,24,0x81000004);companion.write_bytes(data)
                elif mode=='encrypted':companion.write_bytes(fixture(encryption=1))
                elif mode=='ambiguous':(root/'eboot.velf').write_bytes(companion.read_bytes())
                else:
                    companion.unlink();companion.symlink_to(original)
                with patch.object(workflow,'translate_elf') as translate:
                    report=workflow.compatibility(root)
                self.assertFalse(report['conversion_candidate'],report)
                translate.assert_not_called()
                self.assertEqual(original.read_bytes(),fixture(encryption=1))

    def test_missing_companion_actionable_error_and_no_build(self):
        from test_self_extract import fixture
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'eboot.bin').write_bytes(fixture(encryption=1))
            with patch('vitaxnative.build.build_native') as build:
                with self.assertRaisesRegex(ValueError,'Supply a same-build decrypted eboot.elf'):
                    workflow.convert_game(root,applications=root/'apps')
            build.assert_not_called()
            self.assertFalse((root/'apps').exists())

    def test_terminal_menu_compatibility_uses_companion(self):
        from vitaxnative.launcher import main
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.make_game(root)
            config={'roms':str(root.parent),'applications':str(root/'apps')}
            with patch.object(workflow,'settings',return_value=config), \
                 patch.object(workflow,'catalogue',return_value={'available':True,'games':[{'title':'Demo','path':str(root)}]}), \
                 patch('builtins.input',side_effect=['8','1','0']),redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(),0)
            self.assertIn('eboot.elf',output.getvalue())
            self.assertIn('"conversion_candidate": true',output.getvalue())
