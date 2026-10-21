"""Graphical bootstrap orchestration. No customer data or credentials are exported."""
from dataclasses import dataclass
import ctypes
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import sys
import threading

ORIGIN = 'https://github.com/BlehMaks/find-me-a-job.git'
UPSTREAM = 'BlehMaks/find-me-a-job'


class Handoff(RuntimeError):
    def __init__(self, message, url=None):
        super().__init__(message)
        self.url = url


class Cancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class Options:
    source: Path
    workspace: Path
    agent: str = 'codex'
    interface: str = 'desktop'
    feedback: str = 'unset'
    dependencies: bool = False
    desktop_app: str = ''

    def validate(self):
        if self.agent not in {'codex', 'claude'} or self.interface not in {'desktop', 'cli'}:
            raise Handoff('Choose a supported agent and interface.')
        if self.feedback not in {'unset', 'enabled', 'disabled'}:
            raise Handoff('Choose whether generic feedback is allowed.')
        paths = [self.source, self.workspace, Path(str(self.workspace) + '.venv')]
        roots = []
        for path in paths:
            path = path.expanduser().absolute()
            for part in (path, *path.parents):
                if part.is_symlink() or (part.exists() and getattr(part.lstat(), 'st_file_attributes', 0) & 0x400):
                    raise Handoff('Choose paths without symbolic links or Windows junctions.')
            root = path.resolve()
            if root == Path(root.anchor) or root == Path.home().resolve() or root in Path.home().resolve().parents:
                raise Handoff('Choose dedicated folders, not a disk root or your home folder.')
            roots.append(root)
        for index, first in enumerate(roots):
            if any(first == second or first in second.parents or second in first.parents for second in roots[index + 1:]):
                raise Handoff('Source, private workspace and Python environment must be separate folders.')
        if roots[0].exists() and not (roots[0] / '.git').is_dir():
            raise Handoff('The source destination exists and is not a checkout. Choose a new folder; nothing is overwritten.')
        if roots[1].exists() and any(roots[1].iterdir()) and not (roots[1] / 'workspace.json').is_file():
            raise Handoff('The private destination contains other files. Choose a dedicated folder.')
        if roots[2].exists() and not (roots[2] / 'pyvenv.cfg').is_file():
            raise Handoff('The environment destination already contains unrelated files. Choose a different workspace.')
        config = roots[1] / 'workspace.json'
        if config.is_symlink():
            raise Handoff('Workspace configuration must not be a symbolic link.')
        if config.exists():
            try:
                value = json.loads(config.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                raise Handoff('Existing workspace configuration is unreadable; inspect it before retrying.') from None
            if value.get('agent') != self.agent or value.get('mode') != 'self_hosted':
                raise Handoff('Reuse the configured agent. Operator-managed workspaces require their operator setup.')
        return roots


def external_environment():
    env = os.environ.copy()
    bundle = str(getattr(sys, '_MEIPASS', ''))
    for key in ('LD_LIBRARY_PATH', 'LIBPATH'):
        if key + '_ORIG' in env:
            env[key] = env[key + '_ORIG']
        elif getattr(sys, 'frozen', False):
            env.pop(key, None)
    for key in ('PYTHONHOME', 'PYTHONPATH', 'TCL_LIBRARY', 'TK_LIBRARY', '_MEIPASS2'):
        env.pop(key, None)
    for key in list(env):
        if key.startswith('_PYI_'):
            env.pop(key)
    if bundle:
        for key in ('PATH', 'DYLD_LIBRARY_PATH', 'DYLD_FRAMEWORK_PATH'):
            if key in env:
                env[key] = os.pathsep.join(p for p in env[key].split(os.pathsep) if not p.startswith(bundle))
    extras = []
    if os.name == 'nt':
        import winreg
        for hive, key in ((winreg.HKEY_CURRENT_USER, 'Environment'),
                          (winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment')):
            try:
                with winreg.OpenKey(hive, key) as handle:
                    extras.extend(os.path.expandvars(winreg.QueryValueEx(handle, 'Path')[0]).split(os.pathsep))
            except OSError:
                pass
        local = Path(os.environ.get('LOCALAPPDATA', Path.home()))
        extras.extend(str(p) for p in (local / 'Programs/Python').glob('Python3*'))
        extras.extend([str(local / 'Programs/MiKTeX/miktex/bin/x64'),
                       str(Path(os.environ.get('PROGRAMFILES', 'C:/Program Files')) / 'Git/cmd')])
    else:
        extras = ['/opt/homebrew/bin', '/opt/homebrew/opt/python@3.12/bin', '/usr/local/bin',
                  '/usr/local/opt/python@3.12/bin', '/Library/TeX/texbin', str(Path.home() / '.local/bin')]
    env['PATH'] = os.pathsep.join(dict.fromkeys([*extras, *env.get('PATH', '').split(os.pathsep)]))
    env.update(PYTHONIOENCODING='utf-8', PYTHONUTF8='1', GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='Never')
    return env


class Runner:
    """One owned process group; output is ephemeral and never written to a journal."""
    def __init__(self, emit=lambda message: None):
        self.emit = emit
        self.cancelled = threading.Event()
        self.process = None

    def stop(self):
        self.cancelled.set()
        process = self.process
        if process is None:
            return
        try:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                               capture_output=True, timeout=10)
            else:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
                # Descendants can keep stdout open after the leader has exited.
                os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, OSError, subprocess.TimeoutExpired):
            pass

    def run(self, argv, *, cwd=None, sensitive=False, check=True, timeout=None):
        if self.cancelled.is_set():
            raise Cancelled('Setup stopped. Recheck before retrying; no tools or folders were rolled back.')
        kwargs = {'start_new_session': True} if os.name != 'nt' else {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
        # Frozen Windows DLL search state must not leak into native installers.
        if os.name == 'nt' and getattr(sys, 'frozen', False):
            ctypes.windll.kernel32.SetDllDirectoryW(None)
        process = subprocess.Popen([str(a) for a in argv], cwd=cwd, env=external_environment(),
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding='utf-8', errors='replace', **kwargs)
        self.process = process
        try:
            if self.cancelled.is_set():
                self.stop()
                raise Cancelled('Setup stopped before the new operation could continue.')
            if timeout and not sensitive:
                output, _ = process.communicate(timeout=timeout)
                if process.returncode and output:
                    self.emit(output.rstrip())
            else:
                if sensitive:
                    # Show device codes while auth is pending, without persisting them.
                    process.stdin.write('\n')
                    process.stdin.flush()
                process.stdin.close()
                lines = []
                for line in process.stdout:
                    lines.append(line)
                    self.emit(line.rstrip())
                process.wait()
                output = ''.join(lines)
        except subprocess.TimeoutExpired as error:
            if error.output:
                self.emit(error.output.decode('utf-8', errors='replace') if isinstance(error.output, bytes) else error.output)
            self.stop()
            process.wait()
            raise Handoff('The operation timed out. Recheck its state before retrying.') from None
        finally:
            self.process = None
            for stream in (process.stdin, process.stdout):
                if stream and not stream.closed:
                    stream.close()
        if self.cancelled.is_set():
            raise Cancelled('Setup stopped. Recheck before retrying; current native installations may need to finish.')
        result = subprocess.CompletedProcess(argv, process.returncode, output)
        if check and result.returncode:
            raise Handoff('A setup command failed. Review the output above, complete any native installer prompts, then retry.')
        return result


def find_python(runner):
    env = external_environment()
    for name in ('python3.12', 'python3', 'python'):
        executable = shutil.which(name, path=env['PATH'])
        if executable:
            result = runner.run([executable, '-c', 'import sys,venv; print(sys.executable); sys.exit(0 if sys.version_info >= (3,11) else 1)'], check=False, timeout=15)
            if result.returncode == 0:
                return result.stdout.strip()
    return None


def detect_desktop(agent):
    if platform.system() == 'Darwin':
        names = ('Codex', 'ChatGPT') if agent == 'codex' else ('Claude',)
        for base in (Path('/Applications'), Path.home() / 'Applications'):
            for name in names:
                if (base / (name + '.app')).is_dir():
                    return str(base / (name + '.app'))
    return ''


def probe(runner):
    env = external_environment()
    tools = {name: shutil.which(name, path=env['PATH']) for name in ('git', 'gh', 'brew', 'winget', 'xelatex', 'pdftoppm', 'codex', 'claude')}
    tools['python'] = find_python(runner)
    return tools


def ensure_tools(options, runner):
    tools = probe(runner)
    recipes = {'git': ('git', 'Git.Git'), 'gh': ('gh', 'GitHub.cli'),
               'python': ('python@3.12', 'Python.Python.3.12'), 'pdftoppm': ('poppler', 'oschwartz10612.Poppler'),
               'xelatex': (None, 'MiKTeX.MiKTeX')}
    for name, (formula, package) in recipes.items():
        if tools.get(name):
            continue
        if not options.dependencies:
            raise Handoff('Missing ' + name + '. Allow missing-software installation, or install it and recheck.')
        system = platform.system()
        if system == 'Darwin':
            if not tools['brew']:
                raise Handoff('Install Homebrew using its official installer, then return here and retry.', 'https://brew.sh/')
            if name == 'xelatex':
                raise Handoff('Install BasicTeX using its native package installer, then retry. System authorization stays in that installer.', 'https://tug.org/mactex/morepackages.html')
            runner.emit('Installing ' + name + ' through Homebrew…')
            runner.run([tools['brew'], 'install', formula])
        elif system == 'Windows' and tools['winget']:
            runner.emit('Installing ' + name + ' through WinGet; complete its native prompts…')
            runner.run([tools['winget'], 'install', '--exact', '--id', package, '--source', 'winget', '--interactive'])
        else:
            raise Handoff('Install missing system tools from the platform guide, then retry.', 'https://github.com/BlehMaks/find-me-a-job')
        tools = probe(runner)
        if not tools.get(name):
            raise Handoff(name + ' is still not available. Finish its installer, then retry; custom tool paths may require restarting this wizard.')
    return tools


def checkout(options, tools, runner):
    source, _, _ = options.validate()
    git = tools['git']
    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        # Clone is never retried over an existing destination or reset in place.
        args = [git, '-c', 'credential.helper=', '-c', 'credential.helper=!gh auth git-credential',
                'clone', '--', ORIGIN, str(source)]
        result = runner.run(args, check=False)
        if result.returncode:
            raise Handoff('Clone did not complete. Sign in to GitHub if access is required. If a partial folder remains, inspect it or choose a new source folder; nothing will be overwritten.')
    origin = runner.run([git, '-C', source, 'remote', 'get-url', 'origin'], timeout=15).stdout.strip()
    if origin != ORIGIN:
        raise Handoff('Existing checkout has a different origin. Choose the product checkout; nothing was changed.')
    actual = runner.run([git, '-C', source, 'rev-parse', '--show-toplevel'], timeout=15).stdout.strip()
    if Path(actual).resolve() != source:
        raise Handoff('Select the repository root, not a nested folder.')
    if runner.run([git, '-C', source, 'status', '--porcelain'], timeout=15).stdout.strip():
        raise Handoff('The checkout has uncommitted changes. Save or review them before installation; nothing was reset.')
    script = source / 'install' / ('install.ps1' if os.name == 'nt' else 'install.sh')
    if not script.is_file() or script.is_symlink():
        raise Handoff('The reviewed platform installer is missing.')
    return source


def setup(options, runner):
    source, workspace, environment = options.validate()
    runner.emit('Checking existing software…')
    tools = ensure_tools(options, runner)
    runner.emit('Checking the source checkout…')
    checkout(options, tools, runner)
    args = ['--workspace', str(workspace), '--agent', options.agent, '--interface', options.interface,
            '--python', tools['python'], '--yes', '--feedback', options.feedback, '--upstream', UPSTREAM]
    if options.desktop_app:
        args.extend(['--desktop-app', options.desktop_app])
    app = options.desktop_app or detect_desktop(options.agent)
    if options.interface == 'desktop' and not app and platform.system() == 'Darwin' and options.dependencies:
        runner.run([tools['brew'] or 'brew', 'install', '--cask', '--appdir=' + str(Path.home() / 'Applications'),
                    'codex-app' if options.agent == 'codex' else 'claude'])
    if os.name == 'nt':
        switches = {'--workspace': '-Workspace', '--agent': '-Agent', '--interface': '-Interface', '--python': '-Python',
                    '--yes': '-Yes', '--feedback': '-Feedback', '--upstream': '-Upstream', '--desktop-app': '-DesktopApp'}
        args = [switches.get(value, value) for value in args]
        if options.dependencies:
            args.append('-InstallDependencies')
        command = ['powershell.exe', '-NoProfile', '-File', str(source / 'install/install.ps1'), *args]
        python = environment / 'Scripts/python.exe'
    else:
        if options.interface == 'cli' and not tools.get(options.agent) and options.dependencies:
            args.append('--install-dependencies')
        command = ['/bin/sh', str(source / 'install/install.sh'), *args]
        python = environment / 'bin/python'
    runner.emit('Preparing your private runtime…')
    runner.run(command, cwd=source)
    config = json.loads((workspace / 'workspace.json').read_text(encoding='utf-8'))
    if options.feedback != 'unset':
        # Rerunning init deliberately preserves old consent; this is an explicit UI choice.
        runner.run([python, '-m', 'fmj', 'feedback', 'consent', '--workspace', workspace,
                    '--enabled', 'yes' if options.feedback == 'enabled' else 'no', '--repository', UPSTREAM, '--actor', config['owner']], cwd=workspace)
    feedback_state, feedback_auth = configure_feedback(source, workspace, tools, runner)
    runner.emit('Compiling and inspecting a synthetic PDF…')
    result = runner.run([python, '-m', 'fmj', 'doctor', '--workspace', workspace, '--smoke'], cwd=workspace, timeout=180)
    report = json.loads(result.stdout)
    if report.get('document_smoke', {}).get('status') != 'passed':
        raise Handoff('Runtime exists, but document checks did not pass. Complete the missing document tools and retry.')
    return {'source': str(source), 'workspace': str(workspace), 'python': str(python),
            'starter': str(workspace / 'runtime/start-here.md'), 'documents': 'verified',
            'account_plan': 'unknown', 'browser_mail_permissions': 'not checked',
            'feedback': feedback_state, 'feedback_auth': feedback_auth,
            'revision': runner.run([tools['git'], '-C', source, 'rev-parse', 'HEAD'], timeout=15).stdout.strip()}


def configure_feedback(source, workspace, tools, runner):
    consent = workspace / 'runtime/feedback-consent.json'
    state = json.loads(consent.read_text(encoding='utf-8')).get('state') if consent.exists() else 'unset'
    if state not in {'enabled', 'disabled', 'unset'}:
        raise Handoff('Existing feedback consent needs review before setup can finish.')
    if state != 'enabled':
        return state, 'not requested'
    gh, git = tools['gh'], tools['git']
    if runner.run([gh, 'auth', 'status', '--hostname', 'github.com'], check=False, timeout=20).returncode:
        return state, 'needs sign-in'
    user = json.loads(runner.run([gh, 'api', 'user'], timeout=20).stdout)
    if not re.fullmatch(r'[A-Za-z0-9-]+', user.get('login', '')) or not isinstance(user.get('id'), int):
        raise Handoff('GitHub identity was not recognized. Review the account before configuring contributions.')
    defaults = {'user.name': user['login'],
                'user.email': str(user['id']) + '+' + user['login'] + '@users.noreply.github.com',
                'credential.https://github.com.helper': '!gh auth git-credential',
                'core.hooksPath': '.githooks'}
    for key, value in defaults.items():
        existing = runner.run([git, '-C', source, 'config', '--get', key], check=False, timeout=15)
        if existing.returncode == 1:
            runner.run([git, '-C', source, 'config', '--local', key, value], timeout=15)
        elif existing.returncode:
            raise Handoff('Local Git settings could not be inspected; no global settings were changed.')
    return state, 'authenticated; repository submission checked when needed'


def github_login(runner):
    gh = shutil.which('gh', path=external_environment()['PATH'])
    if not gh:
        raise Handoff('Install GitHub CLI through setup before signing in.')
    if runner.run([gh, 'auth', 'status', '--hostname', 'github.com'], check=False, timeout=20).returncode:
        runner.emit('Complete GitHub authorization in your browser. This does not enable feedback or send proposals.')
        runner.run([gh, 'auth', 'login', '--hostname', 'github.com', '--git-protocol', 'https', '--web'], sensitive=True)
    return runner.run([gh, 'auth', 'status', '--hostname', 'github.com'], check=False, timeout=20).returncode == 0
