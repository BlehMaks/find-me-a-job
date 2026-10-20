import json
import tempfile
import unittest
from pathlib import Path
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, TextStringObject, ArrayObject
from fmj.documents import (ROOT, escape_tex, render_sources, select_templates,
                           inspect_pdf, inspect_unicode, clean_unicode, validate_content)


class DocumentGateTests(unittest.TestCase):
    def test_tex_input_is_text_not_code_and_inactive_has_no_active_macros(self):
        content = json.loads((ROOT/'tests/fixtures/documents/industry.json').read_text())
        content['summary'] = r'Handled 20% & R&D; input \input{/etc/passwd} costs $5_{x}.'
        with tempfile.TemporaryDirectory() as temp:
            paths = render_sources(content, select_templates('industry')[0], Path(temp)/'bundle')
            inactive = Path(paths['inactive']).read_text()
            self.assertNotIn(r'\input{/etc/passwd}', inactive)
            self.assertIn(r'\textbackslash{}input\{/etc/passwd\}', inactive)
            for macro in ('hyperref', r'\href', r'\url', r'\includegraphics'):
                self.assertNotIn(macro, inactive)

    def test_all_pdf_objects_checked_including_detached_action(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'unsafe.pdf'
            writer = PdfWriter()
            writer.add_blank_page(100, 100)
            writer._add_object(DictionaryObject({NameObject('/JS'): TextStringObject('app.alert(1)')}))
            writer._add_object(DictionaryObject({NameObject('/S'): NameObject('/Launch')}))
            writer._add_object(DictionaryObject({NameObject('/Type'): NameObject('/EmbeddedFile')}))
            writer.write(path)
            issues = inspect_pdf(path, True)['issues']
            self.assertIn('forbidden object /JS', issues)
            self.assertIn('forbidden action', issues)
            self.assertIn('file attachment object', issues)

    def test_annotations_forms_attachments_and_images_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'unsafe.pdf'
            writer = PdfWriter()
            page = writer.add_blank_page(100, 100)
            annotation = DictionaryObject({NameObject('/Subtype'): NameObject('/Link'), NameObject('/A'): DictionaryObject({NameObject('/S'): NameObject('/URI'), NameObject('/URI'): TextStringObject('https://example.invalid')})})
            page[NameObject('/Annots')] = ArrayObject([writer._add_object(annotation)])
            writer.add_attachment('notes.txt', b'private')
            writer._add_object(DictionaryObject({NameObject('/Subtype'): NameObject('/Image')}))
            writer._root_object[NameObject('/AcroForm')] = DictionaryObject()
            writer.write(path)
            issues = inspect_pdf(path, True)['issues']
            for expected in ('forbidden annotation', 'forbidden action', 'image object', 'forbidden object /AcroForm', 'forbidden object /EmbeddedFiles'):
                self.assertIn(expected, issues)

    def test_hygiene_preserves_language_sensitive_characters(self):
        content = {'text': 'caf\u00e9 Persian\u200cword emoji\u200djoin hidden\u200bmark'}
        findings = inspect_unicode(content)
        self.assertEqual(len(findings), 3)
        cleaned = clean_unicode(content, ['U+200B'])
        self.assertEqual(cleaned['text'], 'café Persian\u200cword emoji\u200djoin hiddenmark')
        with self.assertRaises(ValueError):
            clean_unicode(content, ['U+200C'])

    def test_bad_chronology_and_unsafe_urls_rejected(self):
        content = json.loads((ROOT/'tests/fixtures/documents/industry.json').read_text())
        content['experience'][0]['start'] = '2027-01'
        with self.assertRaises(ValueError):
            validate_content(content)
        content['experience'][0]['start'] = '2020-01'
        content['contact'][0]['url'] = 'javascript:alert(1)'
        with self.assertRaises(ValueError):
            validate_content(content)
