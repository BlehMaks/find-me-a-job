import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from fmj.documents import ROOT, select_templates, validate_profile, render_sources, template_root


class TemplateSelectionTests(unittest.TestCase):
    def test_each_family_offers_distinct_section_orders(self):
        for family in ('industry', 'academic', 'portfolio'):
            options = select_templates(family)
            self.assertIn(len(options), (2, 3))
            self.assertNotEqual(options[0]['sections'], options[1]['sections'])
            self.assertEqual(json.loads((ROOT/'templates'/family/'variants.json').read_text())['variants'],
                             {p['variant']: p['sections'] for p in options})

    def test_actual_call_can_select_paper_and_omit_sections(self):
        profile = {**select_templates('academic')[0], 'sections': ['publications', 'experience'], 'paper': 'letter', 'max_pages': 8}
        self.assertEqual(validate_profile(profile)['paper'], 'letter')
        with self.assertRaises(ValueError):
            validate_profile({**profile, 'sections': ['publications', 'publications']})

    def test_cannot_write_into_source_or_overwrite_bundle(self):
        content = json.loads((ROOT/'tests/fixtures/documents/industry.json').read_text())
        with self.assertRaises(ValueError):
            render_sources(content, select_templates('industry')[0], ROOT/'danger-test')
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)/'bundle'
            render_sources(content, select_templates('industry')[0], out)
            with self.assertRaises(ValueError):
                render_sources(content, select_templates('industry')[0], out)

    def test_wheel_installed_template_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp)
            installed = data/'share/find-me-a-job/templates/industry'
            installed.mkdir(parents=True)
            (installed/'base.tex').write_text('synthetic template')
            with patch('fmj.documents.ROOT', data/'site-packages'), patch('fmj.documents.sysconfig.get_path', return_value=str(data)):
                self.assertEqual(template_root(), installed.parent)
