"""Generate a private, copyable desktop handoff without changing agent settings."""
import argparse
import json
from pathlib import Path
import sys

from .workspace import load_workspace, workspace_path


def handoff(workspace, source, interface):
    config = load_workspace(workspace)
    root = Path(workspace).resolve()
    source = Path(source).resolve()
    if not (source / 'AGENTS.md').is_file():
        raise ValueError('Source instructions are missing')
    if source == root or source in root.parents or root in source.parents:
        raise ValueError('Source and private workspace must be separate')
    runtime = json.dumps([sys.executable, '-m', 'fmj'])
    prompt = (
        f'Read {json.dumps(str(source / "AGENTS.md"))} and the selected adapter. '
        f'The private workspace is {json.dumps(str(root))}. '
        f'Invoke the installed runtime using this argument list: {runtime}. '
        'First inspect doctor and campaign status; resume the earliest incomplete phase. '
        'Confirm my provider account, plan and available budget; recommend a paid plan for '
        'sustained campaigns if I only have free access. Do not buy anything or switch billing automatically. '
        'Ask for scoped folder/browser/mail permissions as needed. Keep personal data, documents '
        'and logs in the private workspace, never in the source checkout. '
        'Do not start a campaign before intake and campaign approval.'
    )
    if interface == 'cli':
        steps = ('Run the printed fmj run command. It supplies the private working directory, '
                 'runtime PATH and source instructions to the chosen CLI automatically.')
        folders = f'Source instructions: {source}\n\nPrivate workspace: {root}'
    else:
        steps = ('Open Claude, choose the Code tab, select a Local environment, then Open folder.'
                 if config['agent'] == 'claude' else
                 'Open Codex (or Codex mode in the current ChatGPT desktop app); add/open a local project folder.')
        folders = f'Open the source folder: {source}\n\nAlso grant access to this separate private folder when prompted: {root}'
    text = (
        '# Start your career assistant\n\n'
        f'Selected interface: {interface}. Provider: {config["agent"]}.\n\n'
        f'{steps}\n\n{folders}\n\n'
        'Folder access, browser control, uploads and mailbox access are separate permissions. '
        'If the app cannot access both folders, ask it to request the missing folder; '
        'do not move private data into the repository. UI labels vary by app version.\n\n'
        'Sign in yourself. Installed software does not establish account, subscription, remaining '
        'quota or coding-feature access. For ongoing campaigns we recommend a paid plan; '
        'no plan guarantees unlimited usage. CLI/API billing is a separate choice.\n\n'
        f'Paste this into a new local agent chat:\n\n{prompt}\n'
    )
    path = workspace_path(root, 'runtime', 'start-here.md')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    return text, path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('--interface', choices=['desktop', 'cli'], required=True)
    args = parser.parse_args()
    text, path = handoff(args.workspace, args.source, args.interface)
    print(text)
    print(f'Private setup instructions saved to: {path}')


if __name__ == '__main__':
    main()
