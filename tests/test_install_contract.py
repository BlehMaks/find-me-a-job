"""Installer contracts use inert commands: no downloads or provider logins."""
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipIf(os.name == "nt", "POSIX bootstrap execution; native PowerShell is checked separately")
class PosixInstallContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fmj-install-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.source = self.base / "source with spaces"
        (self.source / "install").mkdir(parents=True)
        shutil.copy2(ROOT / "install/install.sh", self.source / "install/install.sh")
        self.workspace = self.base / "private workspace"
        self.trace = self.base / "trace.jsonl"
        self.bin = self.base / "bin"
        self.bin.mkdir()
        for tool in ('sh', 'dirname', 'uname'):
            (self.bin / tool).symlink_to(shutil.which(tool))
        self.env = dict(os.environ, PATH=str(self.bin), FMJ_INSTALL_TRACE=str(self.trace))
        self.python = self.bin / "python-test"
        self.python.write_text("#!/bin/sh\n'''exec' " + shlex.quote(sys.executable) + ' "$0" "$@"\n\' \'\'\'\n' + r'''
import json, os, pathlib, sys
args = sys.argv[1:]
trace = pathlib.Path(os.environ['FMJ_INSTALL_TRACE'])
with trace.open('a') as log: log.write(json.dumps(args) + '\n')
if args[:2] == ['-m', 'venv']:
    root = pathlib.Path(args[2]); (root / 'bin').mkdir(parents=True)
    (root / 'pyvenv.cfg').write_text('synthetic=true\n')
    target = root / 'bin/python'; target.write_text(pathlib.Path(__file__).read_text()); target.chmod(0o700)
elif args[:2] == ['-m', 'pip']:
    pass
elif args[:3] == ['-m', 'fmj', 'init']:
    root = pathlib.Path(args[args.index('--workspace')+1]); root.mkdir()
    (root / 'workspace.json').write_text(json.dumps({'agent': args[args.index('--agent')+1]}))
elif args[:3] in (['-m', 'fmj', 'doctor'], ['-m', 'fmj', 'run']) or args[:2] == ['-m', 'fmj.setup']:
    pass
else:
    os.execv(sys.executable, [sys.executable, *args])
''')
        self.python.chmod(0o700)
        for agent in ("codex", "claude"):
            path = self.bin / agent
            path.write_text("#!/bin/sh\nexit 0\n")
            path.chmod(0o700)

    def run_installer(self, *args):
        return subprocess.run(["sh", str(self.source / "install/install.sh"), '--interface', 'cli', *args],
                              cwd=self.base, env=self.env, capture_output=True, text=True)

    def calls(self):
        return [json.loads(line) for line in self.trace.read_text().splitlines()] if self.trace.exists() else []

    def test_default_and_dry_run_do_not_mutate_or_invoke_python(self):
        for args in ((), ("--dry-run", "--workspace", str(self.workspace), "--agent", "codex", "--install-dependencies")):
            result = self.run_installer(*args)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.workspace.exists())
        self.assertFalse(self.trace.exists())
        self.assertFalse(Path(str(self.workspace) + ".venv").exists())

    def test_offline_conflicts_with_external_install_before_changes(self):
        result = self.run_installer("--offline", "--install-dependencies", "--yes")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.trace.exists())

    def test_offline_setup_resumes_preserves_policy_and_uses_cli_contract(self):
        arguments = ("--yes", "--offline", "--workspace", str(self.workspace), "--agent", "claude", "--python", str(self.python), "--smoke")
        result = self.run_installer(*arguments)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        pip = next(call for call in calls if call[:2] == ["-m", "pip"])
        self.assertIn("--no-index", pip)
        self.assertIn("--no-build-isolation", pip)
        self.assertEqual(pip[-1], str(self.source))
        init = next(call for call in calls if call[:3] == ["-m", "fmj", "init"])
        self.assertEqual(init[init.index("--agent")+1], "claude")
        self.assertEqual(init[init.index("--feedback")+1], "unset")
        self.assertTrue(any(call[:3] == ["-m", "fmj", "doctor"] and "--smoke" in call for call in calls))
        original = '{"preserve":"existing policy","agent":"claude"}'
        (self.workspace / "workspace.json").write_text(original)
        result = self.run_installer(*arguments)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.workspace / "workspace.json").read_text(), original)
        self.assertEqual(sum(call[:3] == ["-m", "fmj", "init"] for call in self.calls()), 1)

    def test_overlap_and_symlink_are_rejected_before_environment_creation(self):
        for path in (self.source / "private", self.base):
            result = self.run_installer("--yes", "--offline", "--workspace", str(path), "--agent", "codex", "--python", str(self.python))
            self.assertNotEqual(result.returncode, 0)
        link = self.base / "link"
        link.symlink_to(self.source, target_is_directory=True)
        result = self.run_installer("--yes", "--offline", "--workspace", str(link / "private"), "--agent", "codex", "--python", str(self.python))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(call[:2] == ["-m", "venv"] for call in self.calls()))

    def test_quoted_home_paths_are_normalized_before_venv_and_resume(self):
        home = self.base / "synthetic-home"
        home.mkdir()
        self.env["HOME"] = str(home)
        result = self.run_installer("--yes", "--offline", "--workspace", "~/private", "--agent", "codex", "--python", str(self.python))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((home / "private/workspace.json").is_file())
        venv_call = next(call for call in self.calls() if call[:2] == ["-m", "venv"])
        self.assertEqual(venv_call[2], str(home / "private.venv"))
        self.assertFalse((self.base / "~").exists())
        self.assertFalse((self.source / "~").exists())
        again = self.run_installer("--yes", "--offline", "--workspace", "~/private", "--agent", "codex", "--python", str(self.python))
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(sum(call[:3] == ["-m", "fmj", "init"] for call in self.calls()), 1)

    def test_resume_rejects_different_agent_before_environment_mutations(self):
        self.workspace.mkdir()
        config = self.workspace / "workspace.json"
        original = json.dumps({"agent": "claude", "policy": "preserve"})
        config.write_text(original)
        result = self.run_installer("--yes", "--offline", "--workspace", str(self.workspace), "--agent", "codex", "--python", str(self.python))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("configured agent", result.stderr)
        self.assertFalse(any(call[:2] in (["-m", "venv"], ["-m", "pip"]) for call in self.calls()))
        self.assertFalse(Path(str(self.workspace) + ".venv").exists())
        self.assertEqual(config.read_text(), original)

    def test_existing_non_environment_is_not_overwritten(self):
        env_root = self.base / "existing"
        env_root.mkdir()
        sentinel = env_root / "keep.txt"
        sentinel.write_text("preserve")
        result = self.run_installer("--yes", "--offline", "--workspace", str(self.workspace), "--venv", str(env_root), "--agent", "codex", "--python", str(self.python))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sentinel.read_text(), "preserve")

    def test_check_has_no_mutation(self):
        result = self.run_installer("--check", "--agent", "codex", "--python", str(self.python))
        self.assertIn(result.returncode, (0, 2))
        self.assertIn("not capability verification", result.stdout)
        self.assertTrue(all(call == ["-B", "-c", "import pypdf"] for call in self.calls()))
        self.assertFalse(self.workspace.exists())
        self.assertFalse(Path(str(self.workspace) + ".venv").exists())

    def test_desktop_only_does_not_require_cli_and_reports_unknown_service(self):
        (self.bin / 'codex').unlink()
        app = self.base / 'Custom App.app'
        app.mkdir()
        result = self.run_installer('--yes', '--offline', '--interface', 'desktop',
                                    '--desktop-app', str(app), '--workspace', str(self.workspace),
                                    '--agent', 'codex', '--python', str(self.python))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Account/login/plan/quota: unknown', result.stdout)
        self.assertIn('paid agent plan', result.stdout)
        self.assertNotIn('fmj run --workspace', result.stdout)
        self.assertTrue(any(call[:2] == ['-m', 'fmj.setup'] for call in self.calls()))
        result = self.run_installer('--yes', '--offline', '--interface', 'desktop',
                                    '--desktop-app', str(app), '--workspace', str(self.workspace),
                                    '--agent', 'codex', '--python', str(self.python))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sum(call[:3] == ['-m', 'fmj', 'init'] for call in self.calls()), 1)

    def test_cli_does_not_satisfy_desktop_and_missing_app_preserves_data(self):
        self.workspace.mkdir()
        config = self.workspace / 'workspace.json'
        config.write_text('{"agent":"codex","keep":"private"}')
        result = self.run_installer('--yes', '--offline', '--interface', 'desktop',
                                    '--desktop-app', str(self.base / 'absent.app'),
                                    '--workspace', str(self.workspace), '--agent', 'codex',
                                    '--python', str(self.python))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Desktop application not detected', result.stderr)
        self.assertEqual(config.read_text(), '{"agent":"codex","keep":"private"}')
        self.assertFalse(any(call[:2] in (['-m', 'venv'], ['-m', 'pip']) for call in self.calls()))

    def test_invalid_interface_rejected_without_writes(self):
        result = self.run_installer('--interface', 'invalid', '--yes')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.trace.exists())

    def test_check_reports_both_components_independently(self):
        for tool in ('git', 'xelatex', 'pdftoppm'):
            path = self.bin / tool
            path.write_text('#!/bin/sh\nexit 0\n')
            path.chmod(0o700)
        app = self.base / 'Desktop ü.app'
        cli = self.bin / 'codex'
        for has_desktop, has_cli in ((False, False), (False, True), (True, False), (True, True)):
            if has_desktop:
                app.mkdir(exist_ok=True)
            elif app.exists():
                app.rmdir()
            if has_cli:
                cli.write_text('#!/bin/sh\nexit 0\n'); cli.chmod(0o700)
            else:
                cli.unlink(missing_ok=True)
            for interface in ('desktop', 'cli'):
                result = self.run_installer('--check', '--interface', interface, '--agent', 'codex',
                                            '--desktop-app', str(app), '--python', str(self.python))
                with self.subTest(desktop=has_desktop, cli=has_cli, interface=interface):
                    self.assertEqual(result.returncode, 0 if (has_desktop if interface == 'desktop' else has_cli) else 2)
                    self.assertIn('codex: present' if has_cli else 'codex: missing', result.stdout)
                    self.assertIn('desktop: present' if has_desktop else 'desktop: not detected', result.stdout)
                    self.assertIn('Account/login/plan/quota: unknown', result.stdout)
        self.assertFalse(self.workspace.exists())

    def test_macos_dependencies_and_user_agent_work_without_terminal_restart(self):
        tools = self.base / 'new brew tools'
        texbin = self.base / 'new TeX tools'
        tools.mkdir(); texbin.mkdir()
        home = self.base / 'home'
        agent = home / '.local/bin/codex'
        agent.parent.mkdir(parents=True)
        agent.write_text('#!/bin/sh\nexit 0\n'); agent.chmod(0o700)
        (self.bin / 'codex').unlink()
        (self.bin / 'uname').unlink()
        (self.bin / 'uname').write_text('#!/bin/sh\nprintf Darwin\n')
        (self.bin / 'uname').chmod(0o700)
        script = self.source / 'install/install.sh'
        script.write_text(script.read_text().replace('/Library/TeX/texbin', str(texbin)))
        brew_trace = self.base / 'brew.jsonl'
        brew_code = self.base / 'brew.py'
        brew_code.write_text('''import json, os, pathlib, shlex, sys
args = sys.argv[1:]
with open(os.environ['BREW_TRACE'], 'a') as trace:
    trace.write(json.dumps(args) + '\\n')
tools = pathlib.Path(os.environ['BREW_TOOLS'])
if args == ['shellenv']:
    print('export PATH=' + shlex.quote(str(tools)) + ':"$PATH"')
elif args[:1] == ['install']:
    name = {'git':'git', 'poppler':'pdftoppm', 'basictex':'xelatex'}[args[-1]]
    target = pathlib.Path(os.environ['TEX_BIN']) / name if name == 'xelatex' else tools / name
    target.write_text('#!/bin/sh\\nexit 0\\n'); target.chmod(0o700)
else:
    raise SystemExit(9)
''')
        brew = self.bin / 'brew'
        brew.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' ' + shlex.quote(str(brew_code)) + ' "$@"\n')
        brew.chmod(0o700)
        self.env.update(HOME=str(home), BREW_TRACE=str(brew_trace), BREW_TOOLS=str(tools), TEX_BIN=str(texbin))
        result = self.run_installer('--yes', '--install-dependencies', '--workspace', str(self.workspace),
                                    '--agent', 'codex', '--python', str(self.python))
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in brew_trace.read_text().splitlines()]
        self.assertEqual(calls, [['shellenv'], ['install', 'git'], ['install', 'poppler'], ['install', '--cask', 'basictex']])
        self.assertTrue((self.workspace / 'workspace.json').is_file())

    def test_clone_launcher_plan_collision_and_network_failure(self):
        script = ROOT / 'install/clone.sh'
        def run(*args):
            return subprocess.run(['sh', str(script), str(self.workspace), *args],
                                  env=self.env, capture_output=True, text=True)
        for args in ((), ('--yes', '--dry-run'), ('--yes', '--offline')):
            result = run(*args)
            self.assertEqual(result.returncode, 2 if '--offline' in args else 0)
            self.assertFalse(self.workspace.exists())
        self.workspace.mkdir()
        sentinel = self.workspace / 'keep'
        sentinel.write_text('private')
        result = run('--yes')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(sentinel.read_text(), 'private')
        sentinel.unlink(); self.workspace.rmdir()
        git = self.bin / 'git'
        git.write_text('#!/bin/sh\nexit 17\n'); git.chmod(0o700)
        self.assertEqual(run('--yes').returncode, 17)
        self.assertFalse(self.trace.exists())


class PowerShellInstallContract(unittest.TestCase):
    def test_windows_dependency_recipes_and_guarded_winget_bootstrap(self):
        source = (ROOT / 'install/install.ps1').read_text()
        bootstrap = source.split('function Ensure-WinGet {', 1)[1].split('function Find-Desktop', 1)[0]
        self.assertLess(bootstrap.index('Get-Command winget'), bootstrap.index('Install-PackageProvider'))
        self.assertLess(bootstrap.index('if (-not $InstallDependencies)'), bootstrap.index('Install-PackageProvider'))
        self.assertIn('Install-PackageProvider -Name NuGet -Force -Scope CurrentUser', bootstrap)
        self.assertIn('Install-Module -Name Microsoft.WinGet.Client -Force -Repository PSGallery -Scope CurrentUser', bootstrap)
        self.assertIn('Import-Module Microsoft.WinGet.Client', bootstrap)
        self.assertIn('Repair-WinGetPackageManager -Force -Latest', bootstrap)
        self.assertLess(bootstrap.index('Repair-WinGetPackageManager'), bootstrap.index('Refresh-Path'))
        self.assertIn('WinGet is still unavailable', bootstrap)
        for recipe in ("@{ Command = 'git'; Id = 'Git.Git' }", "@{ Command = 'gh'; Id = 'GitHub.cli' }",
                       "@{ Command = 'xelatex'; Id = 'MiKTeX.MiKTeX' }",
                       "@{ Command = 'pdftoppm'; Id = 'oschwartz10612.Poppler' }"):
            self.assertIn(recipe, source)
        self.assertIn("'--id','Python.Python.3.12','--source','winget'", source)
        self.assertIn("'--accept-source-agreements','--accept-package-agreements'", source)
        self.assertIn('Get-Command $Package.Command', source)
        self.assertIn('Complete its native installer and rerun', source)
        self.assertIn('$env:LOCALAPPDATA\\Microsoft\\WindowsApps', source)
        self.assertIn('$env:USERPROFILE\\.local\\bin', source)
        self.assertNotIn('Set-PSRepository', source)
        self.assertNotIn('-Scope AllUsers', source)

    def test_powershell_safety_and_cli_contract(self):
        source = (ROOT / "install/install.ps1").read_text()
        self.assertIn("if ($DryRun) { exit 0 }", source)
        self.assertLess(source.index("if ($DryRun)"), source.index("Invoke-WebRequest"))
        self.assertIn("--no-index", source)
        self.assertIn("$InstallDependencies", source)
        self.assertIn("--workspace", source)
        self.assertIn("--smoke", source)
        self.assertIn("st_file_attributes", source)
        self.assertIn("$Workspace = $NormalizedPaths[0]", source)
        self.assertIn("$Venv = $NormalizedPaths[1]", source)
        self.assertIn("@{ Command = 'git'; Id = 'Git.Git' }", source)
        self.assertLess(source.index("$ConfiguredAgent -ne $Agent"), source.index("if ($InstallDependencies) {"))
        self.assertNotIn("$Package[0]", source)
        self.assertNotIn("$Package[1]", source)
        self.assertNotIn("Set-ExecutionPolicy", source)
        self.assertNotIn("Invoke-Expression", source)
        self.assertNotIn("--dangerously", source)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell not installed; native Windows execution untested")
    def test_powershell_parses_and_dry_runs_without_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "not-created"
            result = subprocess.run(["pwsh", "-NoProfile", "-File", str(ROOT / "install/install.ps1"), "-Workspace", str(root), "-Agent", "codex", "-DryRun"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(root.exists())
            result = subprocess.run(['pwsh', '-NoProfile', '-File', str(ROOT / 'install/clone.ps1'),
                                     '-Checkout', str(root), '-DryRun'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(root.exists())

    @unittest.skipUnless(shutil.which('pwsh'), 'PowerShell not installed; component behavior untested')
    def test_powershell_desktop_presence_does_not_require_cli(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            app = base / 'desktop app'
            app.mkdir()
            for interface in ('desktop', 'cli'):
                script = base / 'probe.ps1'
                def quote(value):
                    return "'" + str(value).replace("'", "''") + "'"
                script.write_text('''function Get-Command {
    [CmdletBinding()]param([string]$Name)
    if ($Name -eq 'codex') { return $null }
    return [pscustomobject]@{ Name = $Name }
}
& ''' + quote(ROOT / 'install/install.ps1') + ' -Check -Agent codex -Interface ' + interface +
                                  ' -DesktopApp ' + quote(app) + '\nexit $LASTEXITCODE\n', encoding='utf-8')
                result = subprocess.run(['pwsh', '-NoProfile', '-File', str(script)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0 if interface == 'desktop' else 2, result.stderr)
                self.assertIn('desktop: present', result.stdout)
                self.assertIn('codex: missing', result.stdout)
                self.assertIn('Account/login/plan/quota: unknown', result.stdout)


class DesktopHandoffTests(unittest.TestCase):
    def test_real_workspace_gets_exact_private_context_and_rerun_preserves_config(self):
        from fmj.setup import handoff
        from fmj.workspace import create_workspace
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / 'private space ü'
            create_workspace(root, agent='claude')
            config = (root / 'workspace.json').read_bytes()
            text, path = handoff(root, ROOT, 'desktop')
            self.assertEqual(path.read_text(encoding='utf-8'), text)
            self.assertIn('Code tab', text)
            self.assertIn(str(root), text)
            prompt = text.split('Paste this into a new local agent chat:\n\n', 1)[1]
            instruction_path, _ = json.JSONDecoder().raw_decode(prompt[len('Read '):])
            self.assertEqual(Path(instruction_path), ROOT / 'AGENTS.md')
            self.assertTrue(Path(instruction_path).is_file())
            runtime, _ = json.JSONDecoder().raw_decode(prompt.split('using this argument list: ', 1)[1])
            self.assertEqual(runtime, [sys.executable, '-m', 'fmj'])
            self.assertTrue(Path(runtime[0]).is_file())
            self.assertIn('Do not buy anything', text)
            self.assertIn('separate permissions', text)
            handoff(root, ROOT, 'desktop')
            self.assertEqual((root / 'workspace.json').read_bytes(), config)
            self.assertFalse((ROOT / 'runtime/start-here.md').exists())
            cli_text, _ = handoff(root, ROOT, 'cli')
            self.assertIn('fmj run', cli_text)
            self.assertNotIn('Open the source folder:', cli_text)
            result = subprocess.run([sys.executable, '-m', 'fmj.setup', '--workspace', str(root),
                                     '--source', str(ROOT), '--interface', 'desktop'],
                                    env=dict(os.environ, PYTHONIOENCODING='ascii'),
                                    capture_output=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(str(root), result.stdout)

    def test_missing_source_instructions_rejected(self):
        from fmj.setup import handoff
        from fmj.workspace import create_workspace
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / 'private'
            create_workspace(root, agent='codex')
            with self.assertRaises(ValueError):
                handoff(root, Path(temporary) / 'missing source', 'desktop')
            self.assertFalse((root / 'runtime/start-here.md').exists())


if __name__ == "__main__":
    unittest.main()
