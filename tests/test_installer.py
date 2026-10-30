"""Installer boundary and real subprocess tests; no system packages or logins."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fmj.installer import Cancelled, Handoff, Options, ORIGIN, Runner, checkout, external_environment, github_login, configure_feedback, probe, agent_status, ensure_tools, install_homebrew, install_macos_package


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.options = Options(self.base / 'source ü;$(echo test)', self.base / 'private ü')

    def test_chatgpt_desktop_is_reported_without_codex_cli(self):
        app = self.base / 'Applications' / 'ChatGPT.app'
        app.mkdir(parents=True)
        for base in (Path('/Applications'), self.base / 'Applications'):
            expected = base / 'ChatGPT.app'
            with self.subTest(location=base), patch('fmj.installer.platform.system', return_value='Darwin'), \
                    patch('fmj.installer.Path.home', return_value=self.base), \
                    patch('fmj.installer.Path.is_dir', lambda path: path == expected), \
                    patch('fmj.installer.shutil.which', return_value=None), \
                    patch('fmj.installer.find_python', return_value=None):
                result = probe(Runner())
            self.assertIsNone(result['codex'])
            self.assertEqual(result['desktop_apps']['codex'], str(expected))
            self.assertIsNone(result['desktop_apps']['claude'])

    def test_agent_status_separates_desktop_and_cli_requirements(self):
        app = self.base / 'ChatGPT.app'
        app.mkdir()
        tools = {'desktop_apps': {'codex': str(app)}, 'codex': None}
        self.assertEqual(agent_status(self.options, tools), (
            f'Desktop app (required): {app}', 'CLI (optional for desktop): not found'))
        cli_options = Options(self.options.source, self.options.workspace, interface='cli')
        self.assertEqual(agent_status(cli_options, tools), (
            f'Desktop app (optional): {app}', 'CLI (required): not found'))
        tools['codex'] = 'installed-cli'
        self.assertEqual(agent_status(cli_options, tools)[1], 'CLI (required): installed-cli')
        custom = self.base / 'custom.app'
        custom.mkdir()
        options = Options(self.options.source, self.options.workspace, desktop_app=str(custom))
        self.assertEqual(agent_status(options, tools)[0], f'Desktop app (required): {custom}')
        custom.rmdir()
        self.assertIn('not detected automatically', agent_status(options, tools)[0])

    def test_macos_git_stub_without_developer_tools_is_missing(self):
        runner = Mock(spec=Runner())
        runner.run.return_value = subprocess.CompletedProcess([], 1, '')
        with patch('fmj.installer.platform.system', return_value='Darwin'), \
                patch('fmj.installer.shutil.which', side_effect=lambda name, **kw: '/usr/bin/git' if name == 'git' else None), \
                patch('fmj.installer.find_python', return_value=None):
            self.assertIsNone(probe(runner)['git'])
            runner.run.return_value = subprocess.CompletedProcess([], 0, '/Library/Developer/CommandLineTools')
            self.assertEqual(probe(runner)['git'], '/usr/bin/git')

    def test_macos_packages_use_native_authorization_after_trust_checks(self):
        package = self.base / 'Basic TeX ü;$(touch unwanted).pkg'
        runner = Mock(spec=Runner())
        install_macos_package(package, runner)
        calls = [call.args[0] for call in runner.run.call_args_list]
        self.assertEqual(calls[0], ['/usr/sbin/pkgutil', '--check-signature', str(package)])
        self.assertEqual(calls[1], ['/usr/sbin/spctl', '--assess', '--type', 'install', str(package)])
        self.assertEqual(calls[2][:2], ['/usr/bin/osascript', '-e'])
        self.assertIn('quoted form of (item 1 of argv)', calls[2][2])
        self.assertIn('with administrator privileges', calls[2][2])
        self.assertEqual(calls[2][3:], [str(package)])
        for failed_check in (0, 1):
            runner.reset_mock()
            runner.run.side_effect = [None] * failed_check + [Handoff('untrusted package')]
            with self.assertRaises(Handoff):
                install_macos_package(package, runner)
            self.assertEqual(runner.run.call_count, failed_check + 1)

    def test_homebrew_download_and_temporary_cleanup_on_cancel(self):
        runner = Mock(spec=Runner())
        with patch('fmj.installer.platform.machine', return_value='arm64'), \
                patch('fmj.installer.install_macos_package', side_effect=Cancelled('stopped')) as install:
            with self.assertRaises(Cancelled):
                install_homebrew(runner)
        argv = runner.run.call_args.args[0]
        self.assertEqual(argv[-1], 'https://github.com/Homebrew/brew/releases/latest/download/Homebrew.pkg')
        self.assertIn('--fail', argv)
        self.assertIn('=https', argv)
        package = install.call_args.args[0]
        self.assertEqual(str(package), argv[argv.index('--output') + 1])
        self.assertFalse(package.parent.exists())

    def test_missing_macos_tools_install_in_order_and_reprobe(self):
        package = self.base / 'basictex.pkg'
        package.touch()
        missing = dict.fromkeys(('git', 'gh', 'python', 'pdftoppm', 'xelatex'), 'installed')
        missing.update(brew=None, xelatex=None, python=None, codex='installed')
        brew = dict(missing, brew='/opt/homebrew/bin/brew')
        python = dict(brew, python='python3.12')
        ready = dict(python, xelatex='/Library/TeX/texbin/xelatex')
        runner = Mock(spec=Runner())
        runner.run.return_value = subprocess.CompletedProcess([], 0, str(package))
        options = Options(self.options.source, self.options.workspace, dependencies=True)
        with patch('fmj.installer.platform.system', return_value='Darwin'), \
                patch('fmj.installer.probe', side_effect=[missing, brew, python, ready]), \
                patch('fmj.installer.install_homebrew') as bootstrap, \
                patch('fmj.installer.install_macos_package') as install:
            self.assertEqual(ensure_tools(options, runner), ready)
        bootstrap.assert_called_once_with(runner)
        install.assert_called_once_with(package, runner)
        self.assertEqual([c.args[0] for c in runner.run.call_args_list], [
            [brew['brew'], 'install', 'python@3.12'], [brew['brew'], 'fetch', '--cask', 'basictex'],
            [brew['brew'], '--cache', '--cask', 'basictex']])

    def test_macos_dependency_consent_reuse_and_failed_recheck(self):
        tools = dict.fromkeys(('git', 'gh', 'python', 'pdftoppm', 'xelatex'), 'installed')
        tools.update(brew=None, codex='installed', desktop_apps={'codex': 'installed'})
        runner = Mock(spec=Runner())
        options = Options(self.options.source, self.options.workspace, dependencies=True)
        with patch('fmj.installer.platform.system', return_value='Darwin'), \
                patch('fmj.installer.probe', return_value=tools), patch('fmj.installer.install_homebrew') as install:
            self.assertEqual(ensure_tools(options, runner), tools)
            install.assert_not_called()
            tools['xelatex'] = None
            with self.assertRaisesRegex(Handoff, 'Allow missing-software'):
                ensure_tools(self.options, runner)
            install.assert_not_called()
            with self.assertRaisesRegex(Handoff, 'Homebrew is still unavailable'):
                ensure_tools(options, runner)
            install.assert_called_once_with(runner)
        runner.run.assert_not_called()

    def test_macos_cli_only_does_not_need_homebrew(self):
        tools = dict.fromkeys(('git', 'gh', 'python', 'pdftoppm', 'xelatex'), 'installed')
        tools.update(brew=None, codex=None)
        options = Options(self.options.source, self.options.workspace, interface='cli', dependencies=True)
        with patch('fmj.installer.platform.system', return_value='Darwin'), \
                patch('fmj.installer.probe', return_value=tools), patch('fmj.installer.install_homebrew') as install:
            self.assertEqual(ensure_tools(options, Runner()), tools)
            install.assert_not_called()

    def test_windows_bootstraps_winget_and_rechecks_each_package(self):
        recipes = [('git', 'Git.Git'), ('gh', 'GitHub.cli'), ('python', 'Python.Python.3.12'),
                   ('pdftoppm', 'oschwartz10612.Poppler'), ('xelatex', 'MiKTeX.MiKTeX')]
        state = dict.fromkeys([name for name, _ in recipes] + ['winget'])
        state['desktop_apps'] = {'codex': 'installed'}
        probes = [dict(state)]
        state['winget'] = 'winget.exe'
        probes.append(dict(state))
        for name, _ in recipes:
            state[name] = name + '.exe'
            probes.append(dict(state))
        runner = Mock(spec=Runner())
        options = Options(self.options.source, self.options.workspace, dependencies=True)
        with patch('fmj.installer.platform.system', return_value='Windows'), \
                patch('fmj.installer.probe', side_effect=probes) as inspect:
            self.assertEqual(ensure_tools(options, runner), state)
        self.assertEqual(inspect.call_count, len(recipes) + 2)
        commands = [call.args[0] for call in runner.run.call_args_list]
        self.assertEqual(commands[0][:5], ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command'])
        self.assertIn('Install-PackageProvider -Name NuGet -Force -Scope CurrentUser', commands[0][-1])
        self.assertIn('Install-Module -Name Microsoft.WinGet.Client -Force -Repository PSGallery -Scope CurrentUser', commands[0][-1])
        self.assertIn('Import-Module Microsoft.WinGet.Client; Repair-WinGetPackageManager -Force -Latest', commands[0][-1])
        self.assertNotIn('Set-ExecutionPolicy', commands[0][-1])
        self.assertEqual(commands[1:], [
            ['winget.exe', 'install', '--exact', '--id', package, '--source', 'winget', '--interactive',
             '--accept-source-agreements', '--accept-package-agreements'] for _, package in recipes])

    def test_windows_bootstrap_consent_reuse_and_failed_rechecks(self):
        ready = dict.fromkeys(('git', 'gh', 'python', 'pdftoppm', 'xelatex'), 'installed')
        ready.update(winget=None, codex='installed', desktop_apps={'codex': 'installed'})
        runner = Mock(spec=Runner())
        options = Options(self.options.source, self.options.workspace, dependencies=True)
        with patch('fmj.installer.platform.system', return_value='Windows'), \
                patch('fmj.installer.probe', return_value=ready):
            self.assertEqual(ensure_tools(options, runner), ready)
            runner.run.assert_not_called()
            ready['git'] = None
            with self.assertRaisesRegex(Handoff, 'Allow missing-software'):
                ensure_tools(self.options, runner)
            runner.run.assert_not_called()
            with self.assertRaisesRegex(Handoff, 'WinGet is still unavailable'):
                ensure_tools(options, runner)
            self.assertEqual(runner.run.call_count, 1)
            runner.reset_mock()
            ready['winget'] = 'existing-winget'
            with self.assertRaisesRegex(Handoff, 'git is still not available'):
                ensure_tools(options, runner)
            self.assertEqual(runner.run.call_count, 1)
            self.assertEqual(runner.run.call_args.args[0][0], 'existing-winget')

    def test_windows_missing_selected_agent_bootstraps_only_with_consent(self):
        tools = dict.fromkeys(('git', 'gh', 'python', 'pdftoppm', 'xelatex'), 'installed')
        tools.update(winget=None, codex=None, desktop_apps={'codex': None})
        for interface in ('desktop', 'cli'):
            for consent in (False, True):
                runner = Mock(spec=Runner())
                options = Options(self.options.source, self.options.workspace, interface=interface, dependencies=consent)
                ready = dict(tools, winget='winget.exe')
                needs_winget = consent and interface == 'desktop'
                with self.subTest(interface=interface, consent=consent), \
                        patch('fmj.installer.platform.system', return_value='Windows'), \
                        patch('fmj.installer.probe', side_effect=[tools, ready]):
                    self.assertEqual(ensure_tools(options, runner), ready if needs_winget else tools)
                self.assertEqual(runner.run.call_count, int(needs_winget))

    def test_windows_environment_finds_new_user_tools_without_restart(self):
        registry = Mock()
        registry.OpenKey.side_effect = OSError('no registry PATH')
        local = self.base / 'Local'
        env = {'LOCALAPPDATA': str(local), 'PROGRAMFILES': str(self.base / 'Programs'), 'PATH': 'existing'}
        with patch.dict(os.environ, env, clear=True), patch.dict(sys.modules, winreg=registry), \
                patch('fmj.installer.os', SimpleNamespace(environ=os.environ, name='nt', path=os.path, pathsep=';')), \
                patch('fmj.installer.Path.home', return_value=self.base):
            result = external_environment()
        paths = result['PATH'].split(';')
        for directory in (self.base / '.local/bin', local / 'Microsoft/WindowsApps',
                          local / 'Microsoft/WinGet/Links', local / 'Programs/MiKTeX/miktex/bin/x64',
                          self.base / 'Programs/MiKTeX/miktex/bin/x64'):
            self.assertIn(str(directory), paths)

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

    @unittest.skipIf(os.name == 'nt', 'POSIX symlink case; Windows junction handling is not exercised here')
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
        env = {'USERPROFILE': str(Path.home()), 'HOME': str(Path.home()), 'PATH': '/bundle/bin' + os.pathsep + '/usr/bin', 'LD_LIBRARY_PATH': '/bundle',
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

    def release_remote(self):
        remote = self.base / 'remote'
        subprocess.run(['git', 'init', '--initial-branch=main', str(remote)], capture_output=True, check=True)
        def git(*args):
            return subprocess.check_output(['git', '-C', str(remote), *args], text=True).strip()
        git('config', 'user.name', 'Release Test')
        git('config', 'user.email', 'release@example.com')
        (remote / 'install').mkdir()
        for name in ('install.sh', 'install.ps1'):
            (remote / 'install' / name).write_text('release contents\n')
        git('add', '.')
        git('commit', '-m', 'Release source')
        revision = git('rev-parse', 'HEAD')
        for name in ('install.sh', 'install.ps1'):
            (remote / 'install' / name).write_text('later main contents\n')
        git('commit', '-am', 'Advance main after release build')
        bundle = self.base / 'bundle'
        bundle.mkdir()
        (bundle / 'source-revision.txt').write_text(revision + '\n', encoding='ascii')
        return remote, bundle, revision, git('rev-parse', 'HEAD')

    def test_frozen_checkout_pins_build_revision_after_remote_main_advances(self):
        remote, bundle, revision, latest = self.release_remote()
        self.assertNotEqual(revision, latest)
        with patch('fmj.installer.ORIGIN', str(remote)), patch.object(sys, 'frozen', True, create=True), \
                patch.object(sys, '_MEIPASS', str(bundle), create=True):
            checkout(self.options, {'git': 'git'}, Runner())
        actual = subprocess.check_output(['git', '-C', str(self.options.source), 'rev-parse', 'HEAD'], text=True).strip()
        self.assertEqual(actual, revision)
        self.assertEqual((self.options.source / 'install/install.sh').read_text(), 'release contents\n')

    def test_frozen_checkout_preserves_existing_different_revision(self):
        remote, bundle, revision, latest = self.release_remote()
        # Source-launched setup keeps its existing default-branch behavior.
        with patch('fmj.installer.ORIGIN', str(remote)), patch.object(sys, 'frozen', False, create=True):
            checkout(self.options, {'git': 'git'}, Runner())
        def state():
            return subprocess.check_output(['git', '-C', str(self.options.source), 'status', '--porcelain=v2', '--branch'], text=True)
        before = state()
        self.assertIn(latest, before)
        with patch('fmj.installer.ORIGIN', str(remote)), patch.object(sys, 'frozen', True, create=True), \
                patch.object(sys, '_MEIPASS', str(bundle), create=True):
            with self.assertRaisesRegex(Handoff, 'differs from this setup build'):
                checkout(self.options, {'git': 'git'}, Runner())
        self.assertEqual(state(), before)
        self.assertEqual((self.options.source / 'install/install.sh').read_text(), 'later main contents\n')

    def test_frozen_checkout_rejects_missing_or_malformed_revision_before_clone(self):
        bundle = self.base / 'bundle'
        bundle.mkdir()
        metadata = bundle / 'source-revision.txt'
        for value in (None, b'not-a-revision\n', b'a' * 39, b'g' * 40, b'\xff' * 40):
            with self.subTest(value=value):
                if value is not None:
                    metadata.write_bytes(value)
                with patch.object(sys, 'frozen', True, create=True), patch.object(sys, '_MEIPASS', str(bundle), create=True):
                    with self.assertRaisesRegex(Handoff, 'build revision'):
                        checkout(self.options, {'git': 'git'}, Runner())
                self.assertFalse(self.options.source.exists())

    def test_github_login_failure_does_not_report_authenticated(self):
        class FailedLogin:
            def emit(self, message): pass
            def run(self, argv, **kwargs):
                return subprocess.CompletedProcess(argv, 1, '')
        with patch('fmj.installer.shutil.which', return_value='gh'):
            self.assertFalse(github_login(FailedLogin()))


    def test_failed_command_keeps_diagnostic_output_visible(self):
        output = []
        with self.assertRaises(Handoff):
            Runner(output.append).run([sys.executable, '-c',
                                       'print("missing required package");raise SystemExit(2)'], timeout=10)
        self.assertIn('missing required package', '\n'.join(output))

    def test_cancel_terminates_real_waiting_child(self):
        ready = threading.Event()
        runner = Runner(lambda line: ready.set() if line == 'waiting' else None)
        errors = []
        def work():
            try:
                runner.run([sys.executable, '-u', '-c', 'import time;print("waiting",flush=True);time.sleep(120)'])
            except Cancelled:
                errors.append('cancelled')
        thread = threading.Thread(target=work)
        thread.start()
        try:
            self.assertTrue(ready.wait(10))
        finally:
            runner.stop()
            thread.join(15)
        self.assertFalse(thread.is_alive(), 'Stop must release the streaming reader')
        self.assertEqual(errors, ['cancelled'])

    def test_feedback_opt_in_repair_preserves_identity_and_never_sends(self):
        workspace = self.options.workspace
        (workspace / 'runtime').mkdir(parents=True)
        consent = workspace / 'runtime/feedback-consent.json'
        source = self.options.source
        subprocess.run(['git', 'init', str(source)], capture_output=True, check=True)
        subprocess.run(['git', '-C', str(source), 'config', '--local', 'user.name', 'Existing identity'], check=True)
        calls = []
        actual = Runner()
        class GitHubStub:
            authenticated = False
            def run(self, argv, **kwargs):
                calls.append(argv)
                if argv[0] == 'gh':
                    if argv[1:3] == ['auth', 'status']:
                        return subprocess.CompletedProcess(argv, 0 if self.authenticated else 1, '')
                    if argv[1:] == ['api', 'user']:
                        return subprocess.CompletedProcess(argv, 0, '{"login":"example-account","id":12345}')
                    raise AssertionError('Unexpected GitHub action: ' + repr(argv))
                return actual.run(argv, **kwargs)
        runner = GitHubStub()
        for state in ('unset', 'disabled'):
            consent.write_text(json.dumps({'state': state}))
            self.assertEqual(configure_feedback(source, workspace, {'git':'git','gh':'gh'}, runner), (state, 'not requested'))
        self.assertEqual(calls, [])
        consent.write_text('{"state":"enabled"}')
        self.assertEqual(configure_feedback(source, workspace, {'git':'git','gh':'gh'}, runner), ('enabled', 'needs sign-in'))
        runner.authenticated = True
        state, auth = configure_feedback(source, workspace, {'git':'git','gh':'gh'}, runner)
        self.assertEqual(state, 'enabled')
        self.assertIn('authenticated', auth)
        name = actual.run(['git', '-C', source, 'config', 'user.name'], timeout=10).stdout.strip()
        self.assertEqual(name, 'Existing identity')
        self.assertFalse(any('--global' in command for command in calls))
        writes = [command for command in calls if command[0] == 'gh']
        self.assertTrue(all(command[1:3] in (['api','user'], ['auth','status']) for command in writes))


if __name__ == '__main__':
    unittest.main()
