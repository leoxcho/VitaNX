import hashlib
from pathlib import Path
import tempfile
import unittest
from vitaxnative.patch_engine import apply_patch

class PatchTests(unittest.TestCase):
    def test_exact_build_and_original_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            src, dst = Path(td)/'original', Path(td)/'patched'
            src.write_bytes(b'abcdef')
            p = dict(title_id='TEST00001', version='1.00', kind='fps',
                     input_sha256=hashlib.sha256(b'abcdef').hexdigest(),
                     output_sha256=hashlib.sha256(b'abXYef').hexdigest(),
                     edits=[dict(offset=2,before='6364',after='5859')])
            kw = dict(title_id='TEST00001', version='1.00')
            self.assertFalse(apply_patch(src,dst,p,**kw)['enhancement_runtime_validated'])
            self.assertEqual(src.read_bytes(),b'abcdef')
            self.assertEqual(dst.read_bytes(),b'abXYef')
            with self.assertRaises(FileExistsError): apply_patch(src,dst,p,**kw)
            with self.assertRaises(ValueError): apply_patch(src,Path(td)/'bad',p,title_id='OTHER',version='1.00')
            p['edits'][0]['before']='0000'
            with self.assertRaises(ValueError): apply_patch(src,Path(td)/'bad',p,**kw)
            self.assertFalse((Path(td)/'bad').exists())

    def test_cli_fps_and_resolution_profiles(self):
        import json
        import subprocess
        import sys
        for kind in ('fps','resolution'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                source,output,profile = [Path(tmp)/name for name in ('source','output','profile.json')]
                source.write_bytes(b'original')
                profile.write_text(json.dumps(dict(title_id='TEST00001',version='1.00',kind=kind,
                    input_sha256=hashlib.sha256(b'original').hexdigest(),
                    output_sha256=hashlib.sha256(b'Original').hexdigest(),
                    edits=[dict(offset=0,before='6f',after='4f')])))
                command=[sys.executable,'-m','vitaxnative','apply-patch',str(source),str(output),str(profile),
                         '--title-id','TEST00001','--version','1.00']
                result=subprocess.run(command,capture_output=True,text=True,check=True)
                self.assertFalse(json.loads(result.stdout)['enhancement_runtime_validated'])
                self.assertEqual(output.read_bytes(),b'Original')
                self.assertEqual(source.read_bytes(),b'original')
                self.assertEqual(subprocess.run(command,capture_output=True).returncode,2)
