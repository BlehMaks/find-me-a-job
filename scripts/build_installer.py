#!/usr/bin/env python3
"""Build private native installer artifacts from a clean, reviewed source export."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import tempfile
import tkinter
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
NAME = 'FindMeAJob-Setup'


def license_file(candidates):
    for path in candidates:
        if path.is_file():
            return path
    raise RuntimeError('Required dependency license not found; do not distribute this build.')


def collect_notices(destination):
    destination.mkdir()
    python = license_file([Path(sysconfig.get_path('stdlib')) / 'LICENSE.txt',
                           Path(sys.base_prefix) / 'LICENSE.txt', Path(sys.base_prefix) / 'LICENSE'])
    shutil.copyfile(python, destination / 'Python-LICENSE.txt')
    root = tkinter.Tk()
    root.withdraw()
    libraries = {'Tcl': Path(root.tk.call('info', 'library')), 'Tk': Path(root.tk.eval('set tk_library'))}
    versions = {'Tcl': root.tk.call('info', 'patchlevel'), 'Tk': root.tk.call('package', 'provide', 'Tk')}
    root.destroy()
    origins = {}
    for name, library in libraries.items():
        candidates = [parent / 'license.terms' for parent in (library, *list(library.parents)[:5])]
        target = destination / (name + '-license.terms')
        local = next((path for path in candidates if path.is_file()), None)
        if local:
            shutil.copyfile(local, target)
        else:
            # Official Windows Python omits separate Tcl/Tk license files.
            version = str(versions[name])
            if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
                raise RuntimeError('Unsupported Tcl/Tk version; provide its reviewed license locally')
            tag = 'core-' + version.replace('.', '-')
            url = 'https://raw.githubusercontent.com/tcltk/' + name.lower() + '/' + tag + '/license.terms'
            with urlopen(url, timeout=30) as response:
                data = response.read(100_001)
            if len(data) > 100_000 or b'permission to use, copy, modify, distribute' not in data:
                raise RuntimeError('Official Tcl/Tk license could not be verified')
            target.write_bytes(data)
            origins[name] = {'version': version, 'url': url, 'sha256': hashlib.sha256(data).hexdigest()}
    (destination / 'sources.json').write_text(json.dumps(origins, indent=2), encoding='utf-8')
    package = importlib.metadata.distribution('pyinstaller')
    copying = next(path for path in package.files if str(path).endswith('licenses/COPYING.txt'))
    shutil.copyfile(package.locate_file(copying), destination / 'PyInstaller-COPYING.txt')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, help='New external directory; source and private workspaces are never bundled')
    args = parser.parse_args()
    output = Path(args.output).expanduser().resolve()
    if output == ROOT or ROOT in output.parents or output in ROOT.parents or output.exists():
        parser.error('Choose a new external output directory; nothing is overwritten')
    if platform.system() not in {'Darwin', 'Windows'}:
        parser.error('Build on native macOS or Windows; no cross-compilation')
    if importlib.metadata.version('pyinstaller') != '6.22.3':
        parser.error('Install the pinned development build dependency: pyinstaller==6.22.3')
    subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--'], cwd=ROOT, check=True)
    subprocess.run([sys.executable, 'scripts/check_public_tree.py', '--history'], cwd=ROOT, check=True)
    approved = set(json.loads((ROOT / '.public-files.json').read_text(encoding='utf-8')))
    tracked = set(subprocess.check_output(['git', 'ls-files'], cwd=ROOT, text=True).splitlines())
    if approved != tracked:
        parser.error('Commit the exact reviewed source allowlist before building')
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    output.mkdir(parents=True, mode=0o700)
    if sys.platform == 'darwin':
        for package, version in (('dmgbuild', '1.6.7'), ('Pillow', '12.1.1')):
            if importlib.metadata.version(package) != version:
                parser.error('Install the pinned Mac build dependency: ' + package + '==' + version)
        from macos_dmg import artwork
        icon = artwork(output / 'artwork')
    with tempfile.TemporaryDirectory(prefix='fmj-native-build-') as temporary:
        build = Path(temporary)
        source = build / 'source'
        source.mkdir()
        archive = build / 'source.tar'
        with archive.open('wb') as stream:
            subprocess.run(['git', 'archive', 'HEAD'], cwd=ROOT, stdout=stream, check=True)
        with tarfile.open(archive) as contents:
            contents.extractall(source, filter='data')
        notices = build / 'licenses'
        collect_notices(notices)
        source_revision = build / 'source-revision.txt'
        source_revision.write_text(revision + '\n', encoding='ascii')
        command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed',
                   '--name', NAME, '--distpath', str(output), '--workpath', str(build / 'work'),
                   '--specpath', str(build), '--paths', str(source), '--add-data', str(notices) + os.pathsep + 'licenses',
                   '--add-data', str(source_revision) + os.pathsep + '.',
                   '--add-data', str(source / 'LICENSE') + os.pathsep + '.',
                   '--add-data', str(source / 'THIRD_PARTY_NOTICES.md') + os.pathsep + '.',
                   '--osx-bundle-identifier', 'org.findmeajob.setup']
        if sys.platform == 'darwin':
            command.extend(['--icon', str(icon)])
        command.append('--onedir' if sys.platform == 'darwin' else '--onefile')
        command.append(str(source / 'install/wizard.py'))
        subprocess.run(command, cwd=source, check=True)
    if sys.platform == 'darwin':
        executable = output / (NAME + '.app/Contents/MacOS/' + NAME)
    else:
        executable = output / (NAME + '.exe')
    report = output / 'bundle-smoke.json'
    environment = os.environ.copy()
    environment['PATH'] = os.defpath  # No system Python is needed to launch the artifact.
    subprocess.run([str(executable), '--self-test', str(report)], env=environment, timeout=60, check=True)
    smoke = json.loads(report.read_text(encoding='utf-8'))
    if smoke.get('status') != 'passed' or not smoke.get('bundled') or smoke.get('installs_executed'):
        raise RuntimeError('Bundled Python/Tk launch did not pass')
    artifact = executable
    dmg_smoke = None
    if sys.platform == 'darwin':
        artifact = output / (NAME + '-macos-' + platform.machine() + '.dmg')
        from macos_dmg import package, verify
        package(artifact, output / (NAME + '.app'), ROOT / 'install/macos-guide.html', output / 'artwork')
        dmg_smoke = verify(artifact)
    manifest = {'revision': revision, 'platform': platform.platform(), 'architecture': platform.machine(),
                'artifact': artifact.name, 'sha256': hashlib.sha256(artifact.read_bytes()).hexdigest(),
                'bundled_python_tk_smoke': smoke, 'dmg_smoke': dmg_smoke, 'signing': 'unsigned pilot; no Developer ID/notarization or Windows publisher certificate',
                'publication': 'not performed'}
    (output / 'installer-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print('Native artifact built and launched with bundled Python/Tk. No publication or account login performed.')


if __name__ == '__main__':
    main()
