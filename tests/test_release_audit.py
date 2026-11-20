"""Offline guard regression tests using disposable private fixtures."""
import tempfile
import unittest
from pathlib import Path
from scripts.audit_public_release import audit

class ReleaseAuditTests(unittest.TestCase):
    def test_clean_synthetic_source(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'README.md').write_text('Safe synthetic test.\n')
            n, findings = audit(root)
            self.assertEqual(n,1)
            self.assertEqual(findings,[])

    def test_secret_and_home_path_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'config.txt').write_text('file=/' + 'Users/private-account/games\n')
            n, findings = audit(root)
            self.assertEqual(n,1)
            self.assertTrue(any(reason=='home-path' for _,reason in findings))

    def test_git_metadata_not_treated_as_source(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'.git').mkdir()
            (root/'.git'/'config').write_text('private host data never part of source')
            (root/'README.md').write_text('Safe source\n')
            n, findings = audit(root)
            self.assertEqual(n,1)
            self.assertEqual(findings,[])

    def test_disallowed_private_file(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'private.self').write_bytes(b'not an authorized source asset')
            n, findings = audit(root)
            self.assertEqual(n,1)
            self.assertTrue(any(reason=='disallowed file type' for _,reason in findings))

if __name__=='__main__': unittest.main()
