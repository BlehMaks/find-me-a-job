"""Check the exact static payload, local resources and manual publication gate."""
from html.parser import HTMLParser
from pathlib import Path
import re
import unittest
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree
from fmj.documents import FAMILIES

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
ALLOWED = {"index.html", "styles.css", "assets/mark.svg", "assets/structures.svg"}


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.references = []
        self.reference_context = []
        self.ids = set()
        self.tags = []
        self.images = []
        self.preview_labels = []
        self.template_variants = []

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        self.tags.append(tag)
        if "id" in attributes:
            self.ids.add(attributes["id"])
        for attribute in ("src", "href"):
            if attribute in attributes:
                self.references.append(attributes[attribute])
                self.reference_context.append((tag, attribute, attributes[attribute]))
        if tag == "article" and attributes.get("class") == "template-card":
            self.template_variants.append((attributes.get("data-family"), attributes.get("data-variant")))
        if tag == "img":
            self.images.append(attributes)
        if tag == "svg" and attributes.get("role") == "img":
            self.preview_labels.append(attributes.get("aria-label"))


class SiteArtifactTests(unittest.TestCase):
    def setUp(self):
        self.source = (SITE / "index.html").read_text()
        self.page = Page()
        self.page.feed(self.source)

    def test_exact_site_only_textual_payload(self):
        files = set()
        for path in SITE.rglob("*"):
            self.assertFalse(path.is_symlink(), "No linked/private files in Pages payload")
            if path.is_file():
                files.add(path.relative_to(SITE).as_posix())
                self.assertNotIn(b"\x00", path.read_bytes())
        self.assertEqual(files, ALLOWED)

    def test_relative_resources_fragments_and_six_preview_symbols(self):
        symbols = ElementTree.parse(SITE / "assets/structures.svg")
        identifiers = {element.attrib["id"] for element in symbols.iter() if "id" in element.attrib}
        self.assertEqual(len(identifiers), 6)
        references = set()
        for tag, attribute, value in self.page.reference_context:
            parsed = urlsplit(value)
            if parsed.scheme:
                self.assertIn(value, {"https://github.com/BlehMaks/find-me-a-job", "https://learn.chatgpt.com/docs/app", "https://code.claude.com/docs/en/desktop-quickstart", "https://desktop.github.com/download/", "https://github.com/BlehMaks/find-me-a-job/actions/workflows/installer.yml"})
                self.assertEqual((tag, attribute), ("a", "href"))
                continue
            self.assertFalse(parsed.scheme, "Site resources must be relative; no external tracking/font scripts")
            self.assertFalse(parsed.netloc)
            self.assertFalse(parsed.path.startswith("/"), "Pages project subpaths must work")
            target = (SITE / unquote(parsed.path)).resolve() if parsed.path else SITE / "index.html"
            self.assertTrue(target == SITE or SITE in target.parents)
            self.assertTrue(target.exists(), value)
            if parsed.fragment:
                available = identifiers if target.name == "structures.svg" else self.page.ids
                self.assertIn(parsed.fragment, available)
                if target.name == "structures.svg":
                    references.add(parsed.fragment)
        self.assertEqual(references, identifiers)
        self.assertEqual(len(self.page.preview_labels), 6)
        self.assertTrue(all(self.page.preview_labels))

    def test_preview_variants_and_visible_section_order_match_runtime(self):
        expected = {(family, variant): sections for family, variants in FAMILIES.items() for variant, sections in variants.items()}
        self.assertEqual(set(self.page.template_variants), set(expected))
        symbols = ElementTree.parse(SITE / "assets/structures.svg")
        for (family, variant), sections in expected.items():
            symbol = next(item for item in symbols.iter() if item.attrib.get("id") == family + "-" + variant)
            visible_sections = [item.attrib["data-section"] for item in symbol.iter() if "data-section" in item.attrib]
            self.assertEqual(visible_sections, sections)
            visible_labels = [item.text for item in symbol.iter() if "data-section" in item.attrib]
            self.assertEqual(visible_labels, [section.upper() for section in sections])
        self.assertIn("Publication-led", self.source)
        self.assertNotIn("Teaching-led", self.source)

    def test_accessible_no_collection_or_unreviewed_active_content(self):
        self.assertIn('<html lang="en">', self.source)
        self.assertIn('name="viewport"', self.source)
        self.assertEqual(self.page.tags.count("h1"), 1)
        self.assertIn('href="#main"', self.source)
        self.assertFalse(set(self.page.tags) & {"script", "iframe", "form", "input"})
        self.assertTrue(all("alt" in image for image in self.page.images))
        css = (SITE / "styles.css").read_text()
        self.assertIn("prefers-reduced-motion", css)
        self.assertIn(":focus-visible", css)
        self.assertNotIn("\n+@", css)
        self.assertFalse(re.search(r"url\s*\(\s*[\"']?(?:https?:|/|\.\.)", css))

    def test_manual_review_gate_and_site_only_upload(self):
        workflow = (ROOT / ".github/workflows/pages.yml").read_text()
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("release_review_complete == true", workflow)
        self.assertIn("default: false", workflow)
        self.assertIn("path: site\n", workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertNotIn("push:", workflow)
        self.assertNotIn("path: .\n", workflow)
        self.assertNotIn("path: ..", workflow)


if __name__ == "__main__":
    unittest.main()
