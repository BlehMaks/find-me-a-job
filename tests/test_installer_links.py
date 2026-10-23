"""Execute the workflow's README update against an in-memory GitHub API."""
import base64
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node unavailable; GitHub script execution untested')
class InstallerDownloadLinksTests(unittest.TestCase):
    def setUp(self):
        self.original = (ROOT / 'README.md').read_text()
        self.links = dict(re.findall(
            r'\[(macOS|Windows) \(\.[a-z]+\)\]\(https://github.com/BlehMaks/find-me-a-job/actions/runs/(\d+/artifacts/\d+)\)',
            self.original))
        self.assertEqual(set(self.links), {'macOS', 'Windows'})
        self.run_id = max(int(link.split('/')[0]) for link in self.links.values()) + 1

    def update(self, artifacts, run_id=None, source=None):
        workflow = (ROOT / '.github/workflows/installer.yml').read_text()
        script = workflow.split('          script: |\n', 1)[1]
        script = '\n'.join(line[12:] for line in script.splitlines())
        readme = source if source is not None else (ROOT / 'README.md').read_text()
        harness = r"""
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const context = {repo: {owner: 'BlehMaks', repo: 'find-me-a-job'},
  runId: input.run_id, payload: {repository: {default_branch: 'main'}}};
let update = null;
const github = {rest: {
  actions: {listWorkflowRunArtifacts: async () => ({data: {artifacts: input.artifacts}})},
  repos: {
    getContent: async () => ({data: {sha: 'current-readme',
      content: Buffer.from(input.readme).toString('base64')}}),
    createOrUpdateFileContents: async args => {update = args;}
  }
}};
const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
new AsyncFunction('github', 'context', 'Buffer', input.script)(github, context, Buffer)
  .then(() => process.stdout.write(JSON.stringify(update)))
  .catch(error => {console.error(error.message); process.exitCode = 1;});
"""
        result = subprocess.run(['node', '-e', harness], input=json.dumps({
            'script': script, 'readme': readme, 'run_id': self.run_id if run_id is None else run_id,
            'artifacts': artifacts,
        }), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        update = json.loads(result.stdout)
        if update:
            self.assertEqual((update['branch'], update['path'], update['sha']),
                             ('main', 'README.md', 'current-readme'))
            return base64.b64decode(update['content']).decode()
        return readme

    def test_single_platform_build_preserves_other_download_and_wording(self):
        for platform, label in [('macos', 'macOS'), ('windows', 'Windows')]:
            with self.subTest(platform=platform):
                updated = self.update([{'name': f'installer-{platform}-latest',
                                        'id': 123, 'expired': False}])
                self.assertEqual(updated, self.original.replace(self.links[label], f'{self.run_id}/artifacts/123'))

    def test_both_platforms_and_repeated_run(self):
        artifacts = [{'name': f'installer-{platform}-latest', 'id': number, 'expired': False}
                     for platform, number in [('macos', 123), ('windows', 456)]]
        updated = self.update(artifacts)
        for number in (123, 456):
            self.assertIn(f'/runs/{self.run_id}/artifacts/{number})', updated)
        self.assertEqual(self.update(artifacts, source=updated), updated)

    def test_expired_unknown_or_older_build_does_not_replace_downloads(self):
        original = (ROOT / 'README.md').read_text()
        for artifacts, run_id in [([], self.run_id),
                ([{'name': 'installer-macos-latest', 'id': 1, 'expired': True}], self.run_id),
                ([{'name': 'unrelated', 'id': 1, 'expired': False}], self.run_id),
                ([{'name': 'installer-macos-latest', 'id': 1, 'expired': False}], 1)]:
            with self.subTest(artifacts=artifacts, run_id=run_id):
                self.assertEqual(self.update(artifacts, run_id), original)


if __name__ == '__main__':
    unittest.main()
