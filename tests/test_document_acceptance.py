import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from fmj.documents import (ROOT, build_bundle, verify_bundle, select_templates, record_review,
                           finalize_bundle, canonical_visible)


@unittest.skipUnless(shutil.which('xelatex') and shutil.which('pdftoppm'), 'real TeX/renderer unavailable')
class DocumentAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.bundle = Path(cls.temp.name)/'base'
        cls.content = json.loads((ROOT/'tests/fixtures/documents/academic.json').read_text())
        cls.result = build_bundle(cls.content, select_templates('academic')[0], cls.bundle)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def copied_bundle(self, name):
        target = Path(self.temp.name)/name
        shutil.copytree(self.bundle, target)
        return target

    def test_real_build_matches_and_does_not_self_approve(self):
        report = verify_bundle(self.bundle)
        self.assertEqual(report['mechanical_status'], 'passed', report['issues'])
        self.assertFalse(finalize_bundle(self.bundle)['ready'])
        parsed = (self.bundle/'inactive.txt').read_text()
        self.assertIn('French B2', parsed)
        self.assertIn('20%.', parsed)
        self.assertIn('Accepted; publication pending.', parsed)

    def test_hash_bound_independent_review_and_changed_artifact(self):
        output = self.copied_bundle('reviewed')
        with self.assertRaises(ValueError):
            record_review(output, 'generator', [], ['standard:1', 'inactive:1'])
        record_review(output, 'independent-test-fixture-reviewer', [], ['standard:1', 'inactive:1'], independent=True,
                      reviewed_dimensions=['factual', 'vacancy_fit', 'visual'])
        self.assertTrue(finalize_bundle(output)['ready'])
        with (output/'inactive.tex').open('a') as stream:
            stream.write('\n% changed source\n')
        self.assertFalse(finalize_bundle(output)['ready'])

    def test_material_finding_blocks_until_corrected_bundle(self):
        output = self.copied_bundle('material')
        record_review(output, 'independent-test-fixture-reviewer', [{'severity':'material','description':'A confirmed source is missing.'}],
                      ['standard:1', 'inactive:1'], independent=True, reviewed_dimensions=['factual','vacancy_fit','visual'])
        self.assertFalse(finalize_bundle(output)['ready'])

    def test_missing_render_and_paired_pdf_mismatch_fail(self):
        output = self.copied_bundle('missing-render')
        (output/'inactive-1.png').unlink()
        self.assertIn('inactive: every-page render missing', verify_bundle(output)['issues'])
        other = json.loads((ROOT/'tests/fixtures/documents/portfolio.json').read_text())
        second = Path(self.temp.name)/'other'
        build_bundle(other, select_templates('portfolio')[0], second)
        shutil.copyfile(second/'inactive.pdf', output/'inactive.pdf')
        issues = verify_bundle(output)['issues']
        self.assertIn('paired visible wording mismatch', issues)
        self.assertIn('inactive: extraction differs from canonical reading order', issues)

    def test_natural_multipage_breaks_and_anonymous_call(self):
        content = copy.deepcopy(self.content)
        content['name'] = 'Applicant reference 001'
        content['contact'] = []
        content['experience'][0]['bullets'] *= 14
        output = Path(self.temp.name)/'long'
        result = build_bundle(content, select_templates('academic')[1], output)
        self.assertEqual(result['verification']['mechanical_status'], 'passed', result['verification']['issues'])
        self.assertGreater(result['verification']['pages']['inactive'], 1)
        self.assertNotIn('\\newpage', (output/'inactive.tex').read_text())
        self.assertNotIn('alex@example.invalid', (output/'inactive.txt').read_text())

    def test_placeholder_review_cannot_approve_bundle(self):
        output = self.copied_bundle('placeholder')
        manifest = json.loads((output/'manifest.json').read_text())
        (output/'reviews.json').write_text(json.dumps({'artifact_hashes':manifest['artifact_hashes'],'findings':[]}))
        result = finalize_bundle(output)
        self.assertFalse(result['ready'])
        self.assertEqual(result['post_check']['editorial_visual_status'], 'invalid_review_record')

    def test_cli_profile_letter_extra_sections_and_proof_link_survive(self):
        import contextlib
        import io
        from fmj.__main__ import main
        content={'name':'Synthetic Example','contact':[],
            'teaching':[{'title':'Teaching practice','bullets':['Taught a verified methods course.']}],
            'funding':[{'title':'Research award','bullets':['Awarded funding for a documented research project.']}],
            'selected_work':[{'title':'Selected work','links':[{'label':'Case study','url':'https://example.invalid/work'}],
                              'bullets':['Created the credited work sample.']}]}
        profile={**select_templates('academic')[0],'sections':['teaching','funding','selected_work'],
                 'paper':'letter','max_pages':1,'approved_by':'synthetic-candidate','approved_at':'2026-01-01T00:00:00Z'}
        folder=Path(self.temp.name)/'profile-cli';folder.mkdir()
        (folder/'content.json').write_text(json.dumps(content));(folder/'profile.json').write_text(json.dumps(profile))
        with contextlib.redirect_stdout(io.StringIO()):
            code=main(['documents','build','--content',str(folder/'content.json'),
                      '--profile',str(folder/'profile.json'),'--output',str(folder/'output')])
        self.assertEqual(0,code)
        report=verify_bundle(folder/'output')
        self.assertEqual('passed',report['mechanical_status'],report['issues'])
        self.assertEqual({'standard':1,'inactive':1},report['pages'])
        text=(folder/'output'/'inactive.txt').read_text()
        for term in ('Teaching','Funding','Selected Work','https://example.invalid/work'):
            self.assertIn(term,text)
        self.assertEqual('letter',json.loads((folder/'output'/'template-profile.json').read_text())['paper'])

    def test_unknown_content_or_profile_constraint_never_disappears(self):
        from fmj.documents import validate_content,validate_profile
        for change in ({'unrecognized_section':[]},{'experience':[{'title':'Synthetic','unexpected_visible_field':'Lost work'}]}):
            with self.assertRaises(ValueError):validate_content({**self.content,**change})
        with self.assertRaises(ValueError):validate_profile({**select_templates('industry')[0],'columns':2})
