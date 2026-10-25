"""Public downloads must resolve to versioned release assets, not expiring CI ZIPs."""
from pathlib import Path
import re
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InstallerDownloadLinksTests(unittest.TestCase):
    def test_public_downloads_match_package_version_and_supported_platforms(self):
        version = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']
        expected = {f'FindMeAJob-Setup-{version}-macos-arm64.dmg',
                    f'FindMeAJob-Setup-{version}-windows-x64.exe'}
        for name in ('README.md', 'site/index.html'):
            with self.subTest(document=name):
                content = (ROOT / name).read_text()
                assets = re.findall(
                    r'https://github.com/BlehMaks/find-me-a-job/releases/download/v([^/]+)/([^\s)"<>]+)',
                    content)
                self.assertEqual({asset for _, asset in assets}, expected)
                self.assertEqual({tag for tag, _ in assets}, {version})
                self.assertNotIn('/actions/runs/', content)


if __name__ == '__main__':
    unittest.main()
