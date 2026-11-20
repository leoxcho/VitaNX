"""Installed lightweight command, independent of current directory or PATH Python."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
COMMAND=Path.home()/'bin/vitaxnative'

class TerminalCommandTests(unittest.TestCase):
    def test_installed_command_and_cli_from_other_directory(self):
        self.assertEqual(COMMAND.read_bytes(),(ROOT/'scripts/vitaxnative').read_bytes())
        with tempfile.TemporaryDirectory() as directory:
            for args,expected in ((['--help'],'build-native'),(['status'],'graphics_scope'),([], '10. Exit')):
                run=subprocess.run([str(COMMAND),*args],cwd=directory,input='10\n',capture_output=True,text=True,timeout=15,env={**os.environ,'PATH':'/usr/bin:/bin'})
                self.assertEqual(run.returncode,0,run.stderr)
                self.assertIn(expected,run.stdout)

    def test_missing_interpreter_has_actionable_error(self):
        run=subprocess.run([str(COMMAND),'--help'],capture_output=True,text=True,env={**os.environ,'VITAXNATIVE_PYTHON':'/missing/python'})
        self.assertEqual(run.returncode,127)
        self.assertIn('Python interpreter unavailable',run.stderr)
