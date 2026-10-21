"""Installer boundary and real subprocess tests; no system packages or logins."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from fmj.installer import Cancelled, Handoff, Options, ORIGIN, Runner, checkout, external_environment, github_login


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.options = Options(self.base / 'source ü;$(echo test)', self.base / 'private ü')

    def test_boundaries_and_existing_data_are_rejected_without_mutation(self):
        for source, private in ((self.base, self.base / 'nested'), (Path.home(), self.base / 'private'),
                                (self.base / 'same', self.base / 'same')):
            with self.assertRaises(Handoff):
                Options(source, private).validate()
        self.options.source.mkdir()
        sentinel = self.options.source / 'keep'
        sentinel.write_text('unrelated')
        with self.assertRaises(Handoff):
            self.options.validate()
        self.assertEqual(sentinel.read_text(), 'unrelated')

    def test_environment_collision_and_wrong_workspace_agent(self):
        environment = Path(str(self.options.workspace) + '.venv')
        environment.mkdir()
        with self.assertRaises(Handoff):
            self.options.validate()
        environment.rmdir()
        self.options.workspace.mkdir()
        (self.options.workspace / 'workspace.json').write_text(json.dumps({'agent': 'claude', 'mode': 'self_hosted'}))
        with self.assertRaises(Handoff):
            self.options.validate()

    @unittest.skipIf(os.name == 'nt', 'Windows junction behavior exercised in native installer checks')
    def test_symlink_parent_rejected(self):
        link = self.base / 'link'
        link.symlink_to(self.base, target_is_directory=True)
        with self.assertRaises(Handoff):
            Options(link / 'source', self.options.workspace).validate()

    def test_real_process_arguments_are_literal_and_failure_is_not_success(self):
        sentinel = self.base / 'should-not-exist'
        argument = 'ü; $(touch ' + str(sentinel) + ')'
        result = Runner().run([sys.executable, '-c', 'import json,sys;print(json.dumps(sys.argv[1:]))', argument], timeout=15)
        self.assertEqual(json.loads(result.stdout), [argument])
        self.assertFalse(sentinel.exists())
        with self.assertRaises(Handoff):
            Runner().run([sys.executable, '-c', 'raise SystemExit(7)'], timeout=15)

    def test_auth_output_is_delivered_before_auth_process_finishes(self):
        seen = threading.Event()
        release = self.base / 'release'
        output = []
        def emit(line):
            output.append(line)
            if 'DEVICE CODE' in line:
                seen.set()
        runner = Runner(emit)
        errors = []
        def work():
            try:
                runner.run([sys.executable, '-u', '-c',
                            'import pathlib,sys,time;print("DEVICE CODE EXAMPLE",flush=True);'
                            'p=pathlib.Path(sys.argv[1]);'
                            '\nwhile not p.exists():time.sleep(.02)', str(release)], sensitive=True)
            except Exception as error:
                errors.append(error)
        thread = threading.Thread(target=work)
        thread.start()
        try:
            self.assertTrue(seen.wait(10), 'Auth code must be visible while the child is waiting')
            self.assertTrue(thread.is_alive())
        finally:
            release.write_text('continue')
            thread.join(10)
            if thread.is_alive():
                runner.stop(); thread.join(10)
        self.assertEqual(errors, [])
        self.assertFalse((self.base / 'installer.log').exists())

    def test_cancel_prevents_following_commands(self):
        runner = Runner()
        runner.stop()
        with self.assertRaises(Cancelled):
            runner.run([sys.executable, '-c', 'raise SystemExit(0)'])

    def test_frozen_environment_does_not_poison_external_python(self):
        env = {'PATH': '/bundle/bin' + os.pathsep + '/usr/bin', 'LD_LIBRARY_PATH': '/bundle',
               'LD_LIBRARY_PATH_ORIG': '/system', 'PYTHONHOME': '/bundle', 'TCL_LIBRARY': '/bundle', '_PYI_ARCHIVE_FILE': 'private'}
        with patch.dict(os.environ, env, clear=True), patch.object(sys, '_MEIPASS', '/bundle', create=True), patch.object(sys, 'frozen', True, create=True):
            result = external_environment()
        self.assertNotIn('/bundle/bin', result['PATH'].split(os.pathsep))
        self.assertNotIn('PYTHONHOME', result)
        self.assertNotIn('_PYI_ARCHIVE_FILE', result)
        self.assertEqual(result['LD_LIBRARY_PATH'], '/system')

    def test_existing_wrong_origin_and_dirty_checkout_are_preserved(self):
        self.options.source.mkdir()
        subprocess.run(['git', 'init', str(self.options.source)], capture_output=True, check=True)
        subprocess.run(['git', '-C', str(self.options.source), 'remote', 'add', 'origin', 'https://example.com/other.git'], check=True)
        with self.assertRaisesRegex(Handoff, 'different origin'):
            checkout(self.options, {'git': 'git'}, Runner())
        subprocess.run(['git', '-C', str(self.options.source), 'remote', 'set-url', 'origin', ORIGIN], check=True)
        sentinel = self.options.source / 'keep'
        sentinel.write_text('uncommitted')
        with self.assertRaisesRegex(Handoff, 'uncommitted'):
            checkout(self.options, {'git': 'git'}, Runner())
        self.assertEqual(sentinel.read_text(), 'uncommitted')

    def test_github_login_failure_does_not_report_authenticated(self):
        class FailedLogin:
            def emit(self, message): pass
            def run(self, argv, **kwargs):
                return subprocess.CompletedProcess(argv, 1, '')
        with patch('fmj.installer.shutil.which', return_value='gh'):
            self.assertFalse(github_login(FailedLogin()))


if __name__ == '__main__':
    unittest.main()
