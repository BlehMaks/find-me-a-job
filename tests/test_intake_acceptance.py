import json
import unittest
from pathlib import Path
from fmj.documents import ROOT, validate_content, canonical_visible, select_templates


class IntakeAcceptanceTests(unittest.TestCase):
    def test_three_professions_preserve_supported_results_and_languages(self):
        for family in ('industry','academic','portfolio'):
            content=json.loads((ROOT/'tests/fixtures/documents'/f'{family}.json').read_text())
            self.assertTrue(validate_content(content))
            text=canonical_visible(content,select_templates(family)[0])
            self.assertIn('20%',text)
            self.assertIn('English C1',text)
            self.assertGreaterEqual(len(content['experience'][0]['bullets']),2)

    def test_conflicting_sources_and_unquantified_narrative_have_ground_truth(self):
        fixture=json.loads((ROOT/'tests/fixtures/intake/conflicting-cvs.json').read_text())
        self.assertNotEqual(fixture['sources'][0]['claims'],fixture['sources'][1]['claims'])
        self.assertEqual(set(fixture['ground_truth'].values()),{'needs_confirmation'})
        narrative=json.loads((ROOT/'tests/fixtures/intake/narrative.json').read_text())
        self.assertNotIn('%',narrative['acceptable_claim'])
        self.assertEqual(narrative['ground_truth']['numeric_impact'],'unknown')
