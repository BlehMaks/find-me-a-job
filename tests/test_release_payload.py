import io
import gzip
import warnings
import json
from pathlib import Path
import stat
import tarfile
import tempfile
import unittest
import zipfile

from scripts.check_release_payload import inspect_archive, load_manifest


class ReleasePayloadTests(unittest.TestCase):
    def test_source_manifest_includes_exact_reviewed_product_paths(self):
        root=Path(__file__).resolve().parents[1]
        approved=load_manifest(root/'.public-files.json')
        lines=(root/'MANIFEST.in').read_text().splitlines()
        self.assertTrue(all(line.startswith('#') or line.startswith('include ') for line in lines))
        included={line[len('include '):] for line in lines if line.startswith('include ')}
        self.assertEqual(included,approved)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.approved = {'AGENTS.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'skills/humanizer/SKILL.md',
                         'skills/humanizer/LICENSE', 'schemas/fact.json', 'templates/industry/base.tex',
                         'fmj/__init__.py', 'fmj/__main__.py'}
        self.distribution = 'find_me_a_job-0.1.0'

    def wheel_entries(self):
        data = self.distribution + '.data/data/share/find-me-a-job/'
        return {path if path.startswith('fmj/') else data + path: b'synthetic public source\n' for path in self.approved}

    def wheel(self, entries=None, *, symlink=None, comment=b'', metadata=None, extras=None):
        path = self.root/(self.distribution + '-py3-none-any.whl')
        entries = self.wheel_entries() if entries is None else entries.copy()
        for name in ('METADATA','WHEEL','entry_points.txt','top_level.txt','RECORD'):
            entries[self.distribution+'.dist-info/'+name] = b'generic generated metadata\n'
        entries.update(metadata or {})
        with zipfile.ZipFile(path, 'w') as archive:
            archive.comment = comment
            for name, content in entries.items():
                info=zipfile.ZipInfo(name)
                info.external_attr = (stat.S_IFLNK|0o777 if name == symlink else stat.S_IFREG|0o644) << 16
                if extras and name in extras:info.extra=extras[name]
                archive.writestr(info, content)
        return path

    def sdist(self, *, extra=None, special=None, owner=None, pax=None):
        path=self.root/(self.distribution+'.tar.gz')
        entries={self.distribution+'/'+name:b'synthetic public source\n' for name in self.approved}
        for name in ('PKG-INFO','setup.cfg', 'find_me_a_job.egg-info/SOURCES.txt', 'find_me_a_job.egg-info/requires.txt'):
            entries[self.distribution+'/'+name]=b'generic generated metadata\n'
        entries.update(extra or {})
        with tarfile.open(path,'w:gz',format=tarfile.PAX_FORMAT) as archive:
            for name,content in entries.items():
                info=tarfile.TarInfo(name);info.size=len(content)
                if owner:info.uid=501;info.uname=owner
                if pax:info.pax_headers=pax
                if special and name==special:info.type=tarfile.SYMTYPE;info.linkname='outside';info.size=0
                archive.addfile(info,io.BytesIO(content))
        return path

    def assert_blocked(self, archive):
        self.assertTrue(inspect_archive(archive,self.approved))

    def test_valid_product_wheel_and_sdist(self):
        self.assertEqual(inspect_archive(self.wheel(),self.approved),[])
        self.assertEqual(inspect_archive(self.sdist(),self.approved),[])

    def test_wheel_license_metadata_is_reviewed_required_payload(self):
        entries = self.wheel_entries()
        license_text = entries.pop(self.distribution + '.data/data/share/find-me-a-job/LICENSE')
        license_path = self.distribution + '.dist-info/licenses/LICENSE'
        self.assertEqual(inspect_archive(self.wheel(entries, metadata={license_path: license_text}), self.approved), [])
        self.assert_blocked(self.wheel(entries))
        self.assert_blocked(self.wheel(entries, metadata={license_path: b'client' + b'@' + b'private.test'}))
        self.assert_blocked(self.wheel(entries, metadata={license_path + '.unknown': license_text}))

    def test_private_unapproved_member_and_path_traversal(self):
        for name in ('private/client.json','../escaped.txt','/absolute.txt','fmj/../client.txt','fmj\\client.txt'):
            with self.subTest(name=name):
                self.assert_blocked(self.wheel(metadata={name:b'synthetic'}))
        for name in (self.distribution+'/private/client.json',self.distribution+'/../escaped.txt'):
            self.assert_blocked(self.sdist(extra={name:b'synthetic'}))

    def test_link_and_binary_members_are_blocked(self):
        self.assert_blocked(self.wheel(symlink='fmj/__main__.py'))
        self.assert_blocked(self.sdist(special=self.distribution+'/fmj/__main__.py'))
        entries=self.wheel_entries();entries['fmj/__main__.py']=b'\x00binary'
        self.assert_blocked(self.wheel(entries))

    def test_generated_metadata_is_not_a_privacy_exception(self):
        sensitive=b'Contact: client' + b'@' + b'private.test\n'
        metadata=self.distribution+'.dist-info/METADATA'
        self.assert_blocked(self.wheel(metadata={metadata:sensitive}))
        self.assert_blocked(self.sdist(extra={self.distribution+'/PKG-INFO':sensitive}))
        self.assert_blocked(self.sdist(extra={self.distribution+'/find_me_a_job.egg-info/SOURCES.txt':sensitive}))
        self.assert_blocked(self.wheel(metadata={self.distribution+'.dist-info/private-client.json':b'private'}))

    def test_comments_pax_and_owner_metadata_do_not_leak(self):
        self.assert_blocked(self.wheel(comment=b'client' + b'@' + b'private.test'))
        self.assert_blocked(self.sdist(owner='private-person'))
        self.assert_blocked(self.sdist(pax={'comment':'client'+'@'+'private.test'}))
        self.assert_blocked(self.sdist(pax={'SCHILY.xattr.private':'synthetic secret'}))
        self.assertEqual(inspect_archive(self.sdist(pax={'mtime':'123.5'}),self.approved),[])

    def test_mandatory_workflows_licenses_schemas_and_templates_present(self):
        for required in ('AGENTS.md','LICENSE','skills/humanizer/LICENSE','schemas/fact.json','templates/industry/base.tex'):
            entries=self.wheel_entries();entries.pop(self.distribution+'.data/data/share/find-me-a-job/'+required)
            self.assert_blocked(self.wheel(entries))

    def test_duplicate_member_and_hidden_directory_payload_are_blocked(self):
        path=self.wheel()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(path,'a') as archive:
                archive.writestr('fmj/__main__.py',b'another version')
        self.assert_blocked(path)
        path=self.wheel()
        with zipfile.ZipFile(path,'a') as archive:
            archive.writestr('fmj/',b'client' + b'@' + b'private.test')
        self.assert_blocked(path)

    def test_unknown_directory_and_dependency_wheel_rejected(self):
        self.assert_blocked(self.wheel(metadata={self.distribution+'.data/private/':b''}))
        product=self.wheel();dependency=self.root/'other_package-0.1-py3-none-any.whl';product.rename(dependency)
        self.assert_blocked(dependency)

    def test_manifest_paths_and_corrupt_archives_fail_closed(self):
        manifest=self.root/'manifest.json';manifest.write_text(json.dumps(['../private']))
        with self.assertRaises(ValueError):load_manifest(manifest)
        archive=self.root/(self.distribution+'-py3-none-any.whl');archive.write_bytes(b'not a zip')
        self.assert_blocked(archive)

    def test_gzip_original_filename_is_checked(self):
        path=self.sdist()
        tar_bytes=gzip.decompress(path.read_bytes())
        with path.open('wb') as raw:
            with gzip.GzipFile(filename='private-original-name.tar',mode='wb',fileobj=raw) as packed:
                packed.write(tar_bytes)
        self.assert_blocked(path)
