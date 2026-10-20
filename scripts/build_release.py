#!/usr/bin/env python3
"""Build reviewed product packages outside source, with neutral tar ownership."""
import argparse
import gzip
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def neutral_tar(source, target, epoch):
    with tarfile.open(source, 'r:gz') as original, Path(target).open('wb') as raw:
        with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=epoch) as compressed:
            with tarfile.open(fileobj=compressed, mode='w', format=tarfile.PAX_FORMAT) as output:
                for member in original.getmembers():
                    if not (member.isfile() or member.isdir()):
                        raise ValueError('Release source archive cannot contain links or special files')
                    member.uid = member.gid = 0
                    member.uname = member.gname = ''
                    member.mtime = epoch
                    member.pax_headers = {}
                    member.mode = 0o755 if member.isdir() or member.mode & 0o111 else 0o644
                    output.addfile(member, original.extractfile(member) if member.isfile() else None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, help='New empty external output directory')
    args = parser.parse_args()
    destination = Path(args.output).expanduser().resolve()
    if destination == ROOT or ROOT in destination.parents or destination in ROOT.parents:
        parser.error('Release output must be outside and not contain source')
    if destination.exists() and any(destination.iterdir()):
        parser.error('Release output must be empty; preserve earlier packages separately')
    subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--'], cwd=ROOT, check=True)
    subprocess.run([sys.executable, 'scripts/check_public_tree.py', '--history'], cwd=ROOT, check=True)
    approved = set(json.loads((ROOT / '.public-files.json').read_text()))
    tracked = set(subprocess.check_output(['git', 'ls-files'], cwd=ROOT, text=True).splitlines())
    if approved != tracked:
        parser.error('Commit all reviewed manifest files before packaging')
    epoch = int(subprocess.check_output(['git', 'show', '-s', '--format=%ct', 'HEAD'], cwd=ROOT, text=True))
    with tempfile.TemporaryDirectory(prefix='fmj-build-') as temporary:
        built = Path(temporary)
        subprocess.run([sys.executable, '-m', 'build', '--outdir', str(built)], cwd=ROOT, check=True)
        destination.mkdir(parents=True, exist_ok=True, mode=0o700)
        for source in built.iterdir():
            target = destination / source.name
            if source.name.endswith('.tar.gz'):
                neutral_tar(source, target, epoch)
            elif source.suffix == '.whl':
                shutil.copyfile(source, target)
            else:
                raise ValueError('Unexpected build output')
            subprocess.run([sys.executable, 'scripts/check_release_payload.py', str(target)], cwd=ROOT, check=True)
    print('Reviewed packages built locally. No upload or publication performed.')


if __name__ == '__main__':
    main()
