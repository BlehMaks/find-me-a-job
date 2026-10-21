"""Installer contracts use inert commands: no downloads or provider logins."""
import json
import os
from pathlib import Path
import shutil
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
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ["PATH"], FMJ_INSTALL_TRACE=str(self.trace))
        self.python = self.bin / "python-test"
        self.python.write_text("#!" + sys.executable + "\n" + r'''
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


class PowerShellInstallContract(unittest.TestCase):
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


class DesktopHandoffTests(unittest.TestCase):
    def test_real_workspace_gets_exact_private_context_and_rerun_preserves_config(self):
        from fmj.setup import handoff
        from fmj.workspace import create_workspace
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / 'private space ü'
            create_workspace(root, agent='claude')
            config = (root / 'workspace.json').read_bytes()
            text, path = handoff(root, ROOT, 'desktop')
            self.assertEqual(path.read_text(), text)
            self.assertIn('Code tab', text)
            self.assertIn(str(root), text)
            self.assertIn(str(ROOT / 'AGENTS.md'), text)
            self.assertIn(sys.executable, text)
            self.assertIn('Do not buy anything', text)
            self.assertIn('separate permissions', text)
            handoff(root, ROOT, 'desktop')
            self.assertEqual((root / 'workspace.json').read_bytes(), config)
            self.assertFalse((ROOT / 'runtime/start-here.md').exists())

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
