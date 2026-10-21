"""Escaped LaTeX bundles with actual PDF checks and hash-bound review evidence.

This helper verifies mechanics, not proprietary ATS scores or authorship. Editorial
and every-page visual judgment remain a separate, named reviewer operation.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import subprocess
import sysconfig
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent


def template_root():
    source = ROOT / "templates"
    installed = Path(sysconfig.get_path("data")) / "share" / "find-me-a-job" / "templates"
    for candidate in (source, installed):
        if (candidate / "industry" / "base.tex").is_file():
            return candidate
    raise RuntimeError("Document templates are not installed")

FAMILIES = {
    "industry": {
        "experience-first": ["summary", "skills", "experience", "projects", "education", "publications"],
        "skills-first": ["summary", "skills", "projects", "experience", "education", "publications"],
    },
    "academic": {
        "research-first": ["summary", "experience", "publications", "projects", "education", "skills"],
        "publications-first": ["summary", "publications", "education", "experience", "projects", "skills"],
    },
    "portfolio": {
        "selected-work": ["summary", "projects", "experience", "skills", "education", "publications"],
        "practice-first": ["summary", "experience", "projects", "education", "skills", "publications"],
    },
}
CARRIERS = {"\u200b": "zero-width space", "\u2060": "word joiner", "\ufeff": "byte-order/zero-width mark"}
UNSUPPORTED_CARRIERS = {"\u200c": "language-sensitive non-joiner", "\u200d": "language-sensitive joiner", "\u00ad": "soft hyphen"}
SECTIONS = {"summary", "skills", "experience", "projects", "education", "publications",
            "teaching", "funding", "service", "awards", "references", "selected_work"}


def _write(path, value):
    path = Path(path)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _external_output(output_dir):
    path = Path(output_dir).expanduser()
    # Follow links before comparison; runtime outputs must never enter the checkout.
    resolved = path.resolve()
    if resolved == ROOT or ROOT in resolved.parents or resolved in ROOT.parents:
        raise ValueError("Document output must be outside and not contain the product checkout")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return resolved


def select_templates(family):
    if family not in FAMILIES:
        raise ValueError("Unknown template family")
    return [{"family": family, "variant": variant, "sections": sections[:], "paper": "a4", "max_pages": None}
            for variant, sections in FAMILIES[family].items()]


def validate_profile(profile):
    if set(profile) - {"family", "variant", "sections", "paper", "max_pages", "approved_by", "approved_at"}:
        raise ValueError("Unsupported document profile constraint")
    options = select_templates(profile.get("family"))
    match = next((option for option in options if option["variant"] == profile.get("variant")), None)
    if not match:
        raise ValueError("Unknown structural variant")
    sections = profile.get("sections", match["sections"])
    if not isinstance(sections, list) or len(set(sections)) != len(sections) or any(s not in SECTIONS for s in sections):
        raise ValueError("Sections must be unique supported section identifiers")
    if profile.get("paper", "a4") not in {"a4", "letter"}:
        raise ValueError("Paper must be a4 or letter")
    limit = profile.get("max_pages")
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("max_pages must be a positive integer or null")
    return {**match, **profile, "sections": sections}


def escape_tex(text):
    if not isinstance(text, str):
        raise ValueError("Visible content must be text")
    mapping = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
    return "".join(mapping.get(char, char) for char in text)


def _rich(value):
    if isinstance(value, str):
        return escape_tex(value)
    if not isinstance(value, dict) or set(value) - {"text", "emphasis"} or not isinstance(value.get("text"), str):
        raise ValueError("Bullet must be text or {text, emphasis}")
    text = value["text"]
    phrases = value.get("emphasis", [])
    if not isinstance(phrases, list) or any(not isinstance(p, str) or not p or text.count(p) != 1 for p in phrases):
        raise ValueError("Emphasis phrases must occur exactly once")
    ranges = sorted((text.index(p), text.index(p) + len(p)) for p in phrases)
    if any(right > following for (_, right), (following, _) in zip(ranges, ranges[1:])):
        raise ValueError("Emphasis phrases overlap")
    result, pos = [], 0
    for start, end in ranges:
        result.extend([escape_tex(text[pos:start]), r"\textbf{" + escape_tex(text[start:end]) + "}"])
        pos = end
    result.append(escape_tex(text[pos:]))
    return "".join(result)


def _visible(value):
    return value if isinstance(value, str) else value["text"]


def _date_key(value):
    if value in {"Present", "Current"}:
        return (9999, 12)
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}(?:-(?:0[1-9]|1[0-2]))?", value):
        raise ValueError("Dates must be YYYY, YYYY-MM, Present or Current")
    year, *month = value.split("-")
    return int(year), int(month[0]) if month else 0


def validate_content(content):
    if not isinstance(content, dict) or not isinstance(content.get("name"), str) or not content["name"].strip():
        raise ValueError("A nonempty display name is required")
    if set(content) - (SECTIONS | {"name", "contact", "section_labels", "dependencies"}):
        raise ValueError("Unsupported visible content field; declare a supported section")
    if set(content.get("section_labels", {})) - SECTIONS:
        raise ValueError("Unknown section label")
    for skill in content.get("skills", []):
        if set(skill) - {"label", "items", "spoken_languages"}:
            raise ValueError("Unsupported visible skill field")
    for section in SECTIONS - {"summary", "skills"}:
        if not isinstance(content.get(section, []), list):
            raise ValueError("Entry sections must be lists")
        for entry in content.get(section, []):
            if not isinstance(entry, dict) or set(entry) - {"title", "organization", "start", "end", "description", "bullets", "url", "links"}:
                raise ValueError("Unsupported visible entry field")
            for link in _entry_links(entry):
                if set(link) - {"label", "url"} or not isinstance(link.get("label"), str):
                    raise ValueError("Proof links require label and URL")
                _url(link["url"])
    forbidden = []
    for key, value in _strings(content):
        if any(ord(c) < 32 and c not in "\n\t" for c in value):
            raise ValueError(f"Control character in {key}")
        if any(c in value for c in CARRIERS):
            forbidden.append(key)
    if forbidden:
        raise ValueError("Invisible carrier inspection requires explicit cleanup before rendering: " + ", ".join(forbidden))
    previous = None
    for entry in content.get("experience", []):
        if len(entry.get("bullets", [])) < 2:
            raise ValueError("Each substantive experience needs at least two supported bullets")
        start, end = _date_key(entry["start"]), _date_key(entry["end"])
        if start > end:
            raise ValueError("Experience starts after it ends")
        current = (end, start)
        if previous is not None and current > previous:
            raise ValueError("Experience must be ordered by descending recency")
        previous = current
    for entry in content.get("education", []):
        if "start" in entry and "end" in entry and _date_key(entry["start"]) > _date_key(entry["end"]):
            raise ValueError("Education starts after it ends")
    for contact in content.get("contact", []):
        if not isinstance(contact, dict) or set(contact) - {"text", "url"} or not isinstance(contact.get("text"), str):
            raise ValueError("Contacts require display text")
        if contact.get("url"):
            _url(contact["url"])
    return True


def _strings(value, path="content"):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _strings(child, f"{path}[{index}]")
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from _strings(child, f"{path}.{key}")


def inspect_unicode(value):
    findings = []
    for field, text in _strings(value):
        for index, char in enumerate(text):
            if char in CARRIERS or char in UNSUPPORTED_CARRIERS or 0xE0000 <= ord(char) <= 0xE007F:
                findings.append({"field": field, "offset": index, "codepoint": f"U+{ord(char):04X}",
                                 "kind": CARRIERS.get(char, UNSUPPORTED_CARRIERS.get(char, "Unicode tag")),
                                 "automatic_removal": char in CARRIERS})
    return findings


def clean_unicode(content, codepoints):
    """Only explicitly selected carriers; language-sensitive joiners are preserved."""
    allowed = {f"U+{ord(c):04X}": c for c in CARRIERS}
    if any(codepoint not in allowed for codepoint in codepoints):
        raise ValueError("Requested removal is not a context-independent carrier")
    chars = {allowed[point] for point in codepoints}
    def clean(value):
        if isinstance(value, str):
            return "".join(c for c in value if c not in chars)
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()}
        return value
    return clean(content)


def _url(value):
    if not isinstance(value, str) or any(c in value for c in "{}\\\r\n\t "):
        raise ValueError("Unsafe contact URL")
    parts = urlsplit(value)
    if parts.username or parts.password:
        raise ValueError("Proof links must not include credentials")
    if parts.scheme not in {"https", "http", "mailto"} or (parts.scheme != "mailto" and not parts.netloc):
        raise ValueError("Contact URL must be http(s) or mailto")
    return value.replace("%", r"\%").replace("#", r"\#")


def _entry_links(entry):
    return entry.get("links", []) + ([{"label":"Work", "url":entry["url"]}] if entry.get("url") else [])


def _proof_text(link):
    return link["label"] + ": " + link["url"]


def _entry(entry, active):
    heading = entry.get("title", "")
    if entry.get("organization"):
        heading += ", " + entry["organization"]
    if entry.get("start") or entry.get("end"):
        dates = " - ".join(str(entry[k]) for k in ("start", "end") if entry.get(k))
        heading += " | " + dates
    lines = [r"\noindent\textbf{" + escape_tex(heading) + r"}\par"] if heading else []
    if entry.get("description"):
        lines.append(_rich(entry["description"]) + r"\par")
    for link in _entry_links(entry):
        visible = escape_tex(_proof_text(link))
        lines.append((r"\href{" + _url(link["url"]) + "}{" + visible + "}" if active else visible) + r"\par")
    if entry.get("bullets"):
        lines.append(r"\begin{itemize}")
        lines.extend(r"\item " + _rich(bullet) for bullet in entry["bullets"])
        lines.append(r"\end{itemize}")
    return "\n".join(lines)


def canonical_visible(content, profile):
    """Expected reading order, excluding presentation-only whitespace."""
    profile = validate_profile(profile)
    items = [content["name"]] + [c["text"] for c in content.get("contact", [])]
    labels = content.get("section_labels", {})
    for section in profile["sections"]:
        value = content.get(section)
        if not value:
            continue
        items.append(labels.get(section, section.replace("_", " ").title()))
        if section == "summary":
            items.append(_visible(value))
        elif section == "skills":
            for skill in value:
                items.append(skill["label"] + ": " + "; ".join(skill["items"]))
        else:
            for entry in value:
                heading = entry.get("title", "")
                if entry.get("organization"):
                    heading += ", " + entry["organization"]
                if entry.get("start") or entry.get("end"):
                    heading += " | " + " - ".join(str(entry[k]) for k in ("start", "end") if entry.get(k))
                if heading:
                    items.append(heading)
                if entry.get("description"):
                    items.append(_visible(entry["description"]))
                items.extend(_proof_text(link) for link in _entry_links(entry))
                items.extend(_visible(bullet) for bullet in entry.get("bullets", []))
    return "\n".join(items)


def _body(content, profile, active):
    contacts = []
    for contact in content.get("contact", []):
        text = escape_tex(contact["text"])
        contacts.append(r"\href{" + _url(contact["url"]) + "}{" + text + "}" if active and contact.get("url") else text)
    # Two intentionally balanced contact lines, never automatic item wrapping.
    midpoint = (len(contacts) + 1) // 2
    contact_lines = [r"\quad ".join(line) for line in (contacts[:midpoint], contacts[midpoint:]) if line]
    out = [r"{\LARGE\bfseries " + escape_tex(content["name"]) + r"}\par", r"\vspace{3pt}"]
    out.extend(line + r"\par" for line in contact_lines)
    labels = content.get("section_labels", {})
    for section in profile["sections"]:
        value = content.get(section)
        if not value:
            continue
        out.append(r"\section*{" + escape_tex(labels.get(section, section.replace("_", " ").title())) + "}")
        if section == "summary":
            out.append(_rich(value) + r"\par")
        elif section == "skills":
            for skill in value:
                phrase = escape_tex(skill["label"]) + ": "
                items = "; ".join(escape_tex(item) for item in skill["items"])
                out.append(r"\noindent " + phrase + (r"\textbf{" + items + "}" if skill.get("spoken_languages") else items) + r"\par")
        else:
            out.extend(_entry(entry, active) for entry in value)
    return "\n".join(out)


def render_sources(content, profile, output_dir):
    validate_content(content)
    profile = validate_profile(profile)
    output = _external_output(output_dir)
    if any(output.iterdir()):
        raise ValueError("Choose an empty bundle directory; existing artifacts are not overwritten")
    template = (template_root() / profile["family"] / "base.tex").read_text(encoding="utf-8")
    files = {}
    for mode in ("standard", "inactive"):
        source = template.replace("@@PAPER@@", profile.get("paper", "a4") + "paper")
        source = source.replace("@@LINKS@@", r"\usepackage[hidelinks,unicode,pdfstartview={}]{hyperref}" if mode == "standard" else "")
        source = source.replace("@@BODY@@", _body(content, profile, mode == "standard"))
        path = output / (mode + ".tex")
        path.write_text(source, encoding="utf-8")
        files[mode] = str(path)
    _write(output / "canonical.json", content)
    _write(output / "template-profile.json", profile)
    return files


def _normalize(text):
    # List markers are PDF layout; normalize compatibility ligatures, not letters.
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text).replace("•", " ")).strip()


def inspect_pdf(path, inactive=False):
    from pypdf import PdfReader
    from pypdf.generic import IndirectObject
    reader = PdfReader(str(path))
    issues, links, seen_refs, seen_objects = [], [], set(), set()
    forbidden = {"/OpenAction", "/AA", "/JS", "/JavaScript", "/EmbeddedFiles", "/EF", "/AF", "/AcroForm", "/XFA", "/RichMediaContent"}
    def walk(obj):
        if isinstance(obj, IndirectObject):
            ref = (obj.idnum, obj.generation)
            if ref in seen_refs:
                return
            seen_refs.add(ref)
            obj = obj.get_object()
        if id(obj) in seen_objects:
            return
        seen_objects.add(id(obj))
        if isinstance(obj, dict):
            for key in forbidden.intersection(obj):
                issues.append("forbidden object " + key)
            if obj.get("/Subtype") == "/Image":
                issues.append("image object")
            if obj.get("/Type") in {"/Filespec", "/EmbeddedFile"}:
                issues.append("file attachment object")
            action_type = obj.get("/S")
            if action_type in {"/GoTo", "/GoToR", "/GoToE", "/Launch", "/Thread", "/URI", "/Sound", "/Movie", "/Hide", "/Named", "/SubmitForm", "/ResetForm", "/ImportData", "/JavaScript", "/SetOCGState", "/Rendition", "/Trans", "/GoTo3DView"}:
                if inactive or action_type != "/URI":
                    issues.append("forbidden action")
            if "/A" in obj:
                action = obj["/A"]
                if inactive or action.get("/S") != "/URI" or any(k != "/S" and k != "/URI" for k in action):
                    issues.append("forbidden action")
            if "/URI" in obj:
                uri = str(obj["/URI"])
                try:
                    _url(uri)
                except ValueError:
                    issues.append("unsafe URI")
                links.append(uri)
            if "/Annots" in obj:
                for ann in obj["/Annots"]:
                    ann = ann.get_object()
                    if inactive or ann.get("/Subtype") != "/Link":
                        issues.append("forbidden annotation")
            for child in obj.values():
                walk(child)
        elif isinstance(obj, (list, tuple)):
            for child in obj:
                walk(child)
    walk(reader.trailer)
    # Include unreferenced objects; a root-only scan misses detached attachments.
    for generation, objects in reader.xref.items():
        for number in objects:
            if number:
                walk(IndirectObject(number, generation, reader))
    for number in reader.xref_objStm:
        walk(IndirectObject(number, 0, reader))
    metadata = {str(k): str(v) for k, v in (reader.metadata or {}).items()}
    metadata_flags = [key for key, value in metadata.items() if re.search(r"c2pa|openai|chatgpt|claude|synthid|generative", key + " " + value, re.I)]
    root = reader.trailer["/Root"]
    if "/Metadata" in root:
        xmp = root["/Metadata"].get_data().decode("utf-8", "replace")
        if re.search(r"c2pa|openai|chatgpt|claude|synthid|generative", xmp, re.I):
            metadata_flags.append("/Metadata")
    return {"pages": len(reader.pages), "sizes":[[float(page.mediabox.width), float(page.mediabox.height)] for page in reader.pages],
            "issues": sorted(set(issues)), "links": sorted(set(links)),
            "metadata_flags": metadata_flags, "metadata": metadata,
            "text": "\n".join(page.extract_text() or "" for page in reader.pages)}


def _run(command, cwd):
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError("Document tool failed: " + command[0] + "\n" + result.stdout[-3000:] + result.stderr[-1000:])
    return result


def _artifact_hashes(output):
    return {str(path.relative_to(output)): _hash(path) for path in sorted(output.rglob("*"))
            if path.is_file() and path.name not in {"manifest.json", "reviews.json", "verification.json", "hygiene.json", "review-pack.json"}
            and path.suffix in {".json", ".tex", ".pdf", ".txt", ".png"}}


def build_bundle(content, profile, output_dir, workspace=None):
    if workspace is not None:
        content = bind_dependencies(workspace, content, profile)
    engine = shutil.which("xelatex")
    renderer = shutil.which("pdftoppm")
    if not engine or not renderer:
        raise RuntimeError("Required tools unavailable: xelatex and pdftoppm")
    try:
        import pypdf
    except ImportError as exc:
        raise RuntimeError("Required PDF inspection unavailable: install pypdf") from exc
    sources = render_sources(content, profile, output_dir)
    output = Path(output_dir).resolve()
    for mode in sources:
        for _ in range(2):
            _run([engine, "-no-shell-escape", "-interaction=batchmode", "-halt-on-error", mode + ".tex"], output)
        log = (output / (mode + ".log")).read_text(errors="replace")
        if re.search(r"Overfull \\[hv]box|Missing character", log):
            raise ValueError("Build contains overflow or missing glyphs: " + mode)
        report = inspect_pdf(output / (mode + ".pdf"), mode == "inactive")
        (output / (mode + ".txt")).write_text(report["text"], encoding="utf-8")
        _run([renderer, "-scale-to", "1400", "-png", mode + ".pdf", mode], output)
    manifest = {"schema_version": 1, "generator": "fmj.documents", "profile": validate_profile(profile),
                "tools": {"xelatex": _run([engine, "--version"], output).stdout.splitlines()[0],
                          "pypdf": pypdf.__version__, "pdftoppm": _run([renderer, "-v"], output).stderr.splitlines()[0]},
                "artifact_hashes": _artifact_hashes(output)}
    if workspace is not None:
        from .workspace import load_workspace
        manifest["workspace_id"] = load_workspace(workspace)["id"]
    _write(output / "manifest.json", manifest)
    if workspace is not None:
        register_document(workspace, output)
    report = verify_bundle(output)
    _write(output / "verification.json", report)
    return {"directory": str(output), "manifest": manifest, "verification": report}


def verify_bundle(bundle_dir):
    output = Path(bundle_dir).resolve()
    manifest = json.loads((output / "manifest.json").read_text())
    content = json.loads((output / "canonical.json").read_text())
    profile = json.loads((output / "template-profile.json").read_text())
    issues = []
    if _artifact_hashes(output) != manifest["artifact_hashes"]:
        issues.append("artifact hashes changed")
    reports = {}
    expected = _normalize(canonical_visible(content, profile))
    for mode in ("standard", "inactive"):
        report = inspect_pdf(output / (mode + ".pdf"), mode == "inactive")
        reports[mode] = report
        if report["issues"]:
            issues.extend(mode + ": " + issue for issue in report["issues"])
        if _normalize(report["text"]) != expected:
            issues.append(mode + ": extraction differs from canonical reading order")
        if report["metadata_flags"]:
            issues.append(mode + ": provenance metadata requires contextual review")
        previews = list(output.glob(mode + "-*.png"))
        if len(previews) != report["pages"]:
            issues.append(mode + ": every-page render missing")
        if profile.get("max_pages") and report["pages"] > profile["max_pages"]:
            issues.append(mode + ": approved page budget exceeded")
        size = (595.28, 841.89) if profile.get("paper", "a4") == "a4" else (612, 792)
        if any(abs(w-size[0]) > 1 or abs(h-size[1]) > 1 for w,h in report["sizes"]):
            issues.append(mode + ": approved paper size mismatch")
    if _normalize(reports["standard"]["text"]) != _normalize(reports["inactive"]["text"]):
        issues.append("paired visible wording mismatch")
    if reports["standard"]["pages"] != reports["inactive"]["pages"]:
        issues.append("paired page count mismatch")
    expected_links = sorted(set(c["url"] for c in content.get("contact", []) if c.get("url")))
    expected_links = sorted(set(expected_links + [link["url"] for section in profile["sections"] if section not in {"summary", "skills"}
        for entry in content.get(section, []) for link in _entry_links(entry)]))
    if reports["standard"]["links"] != expected_links:
        issues.append("standard links differ from canonical contacts")
    if reports["inactive"]["links"]:
        issues.append("inactive PDF has links")
    inactive = (output / "inactive.tex").read_text()
    if re.search(r"\\(?:usepackage(?:\[[^]]*\])?\{hyperref\}|href|url|includegraphics|pdfannot|pdfstartlink)", inactive):
        issues.append("inactive source includes forbidden active content")
    unicode_findings = inspect_unicode(content)
    if any(f["automatic_removal"] for f in unicode_findings):
        issues.append("canonical Unicode carriers require explicit review")
    review_status = "pending_independent_review"
    review_path = output / "reviews.json"
    if review_path.exists():
        review = json.loads(review_path.read_text())
        required_pages = {f"{mode}:{page}" for mode, result in reports.items() for page in range(1, result["pages"] + 1)}
        valid_review = (review.get("independent_assertion") is True and bool(review.get("reviewer"))
                        and review.get("reviewer") != "fmj.documents"
                        and set(review.get("pages", [])) == required_pages
                        and set(review.get("dimensions", [])) == {"factual", "vacancy_fit", "visual"}
                        and isinstance(review.get("findings"), list)
                        and all(isinstance(f, dict) and f.get("severity") in {"material", "optional"}
                                and f.get("description") for f in review.get("findings", [])))
        if not valid_review:
            review_status = "invalid_review_record"
        elif review.get("artifact_hashes") != manifest["artifact_hashes"] or "artifact hashes changed" in issues:
            review_status = "stale_review"
        elif any(f["severity"] == "material" for f in review["findings"]):
            review_status = "material_corrections_required"
        else:
            review_status = "passed"
    return {"mechanical_status": "failed" if issues else "passed", "issues": issues,
            "pages": {m: r["pages"] for m, r in reports.items()}, "unicode_findings": unicode_findings,
            "artifact_hashes": manifest["artifact_hashes"], "editorial_visual_status": review_status,
            "limitations": ["No proprietary ATS scoring", "No universal statistical watermark detector", "Visual and evidence judgments require independent review"]}


def record_review(bundle_dir, reviewer, findings, pages, *, independent=False, reviewed_dimensions=None):
    """Record an explicit review assertion, never infer review from compilation."""
    output = Path(bundle_dir).resolve()
    report = verify_bundle(output)
    if report["mechanical_status"] != "passed":
        raise ValueError("Mechanical gates must pass before independent review")
    required = {f"{mode}:{page}" for mode, count in report["pages"].items() for page in range(1, count + 1)}
    if not reviewer or reviewer == "fmj.documents" or not independent or set(pages) != required:
        raise ValueError("Independent named reviewer must inspect every page in both versions")
    dimensions = set(reviewed_dimensions or [])
    if dimensions != {"factual", "vacancy_fit", "visual"}:
        raise ValueError("Reviewer must explicitly assess factual, vacancy_fit and visual dimensions")
    if any(f.get("severity") not in {"material", "optional"} or not f.get("description") for f in findings):
        raise ValueError("Review findings require severity and description")
    record = {"reviewer": reviewer, "independent_assertion": True, "dimensions": sorted(dimensions),
              "pages": sorted(pages), "findings": findings, "artifact_hashes": report["artifact_hashes"]}
    _write(output / "reviews.json", record)
    return record


def finalize_bundle(bundle_dir, workspace=None):
    """Last workflow step: re-inspect final bytes and bind review/hygiene results."""
    output = Path(bundle_dir).resolve()
    report = verify_bundle(output)
    ready = report["mechanical_status"] == "passed" and report["editorial_visual_status"] == "passed"
    manifest = json.loads((output/"manifest.json").read_text())
    if manifest.get("workspace_id"):
        from .workspace import load_workspace
        if workspace is None or load_workspace(workspace)["id"] != manifest["workspace_id"]:
            ready = False
            report["issues"].append("Select the bound workspace to verify current document evidence")
    if workspace is not None:
        try:
            verify_dependencies(workspace, json.loads((output/"canonical.json").read_text()),
                                json.loads((output/"template-profile.json").read_text()))
        except ValueError:
            ready = False
            report["issues"].append("Document evidence is missing or stale; rebuild from current confirmed facts")
    # No metadata is silently rewritten. Flagged metadata blocks readiness; a
    # deliberate content change must be rebuilt and reviewed as a new bundle.
    hygiene = {"deterministic_unicode": report["unicode_findings"], "pdf_metadata": "inspected",
               "cleanup": "none_required" if report["mechanical_status"] == "passed" else "review_required",
               "statistical_detection": "unavailable; no vendor-key or human-authorship claim",
               "post_check": report, "ready": ready}
    _write(output / "hygiene.json", hygiene)
    return hygiene


def build_previews(content, family, output_dir, workspace=None):
    output = _external_output(output_dir)
    return [build_bundle(copy.deepcopy(content), profile, output / profile["variant"], workspace) for profile in select_templates(family)]


def factual_fields(content, profile):
    """Visible factual units; layout labels and emphasis are presentation metadata."""
    fields = {"/name":content["name"]}
    for i, entry in enumerate(content.get("contact", [])):
        fields[f"/contact/{i}/text"] = entry["text"]
        if entry.get("url"):
            fields[f"/contact/{i}/url"] = entry["url"]
    for section in validate_profile(profile)["sections"]:
        value = content.get(section)
        if not value:
            continue
        if section == "summary":
            fields["/summary"] = _visible(value)
        elif section == "skills":
            for i, skill in enumerate(value):
                for j, item in enumerate(skill["items"]):
                    fields[f"/skills/{i}/items/{j}"] = item
        else:
            for i, entry in enumerate(value):
                for key in ("title", "organization", "start", "end", "description", "url"):
                    if entry.get(key):
                        fields[f"/{section}/{i}/{key}"] = _visible(entry[key])
                for j, bullet in enumerate(entry.get("bullets", [])):
                    fields[f"/{section}/{i}/bullets/{j}"] = _visible(bullet)
                for j, link in enumerate(entry.get("links", [])):
                    fields[f"/{section}/{i}/links/{j}/url"] = link["url"]
    return fields


def _dependency(root, declaration, value):
    from .records import _digest, list_records, load_record, validate_claim
    dep = copy.deepcopy(declaration)
    if dep.get("claim_id"):
        claim = load_record(root, "claim", dep["claim_id"])
        if dep.get("claim_version") != claim["version"]:
            raise ValueError("Document claim version is stale")
        validate_claim(root, claim)
        facts = [{"id":key, "version":version} for key,version in claim["fact_versions"].items()]
    elif dep.get("fact_id"):
        fact = load_record(root, "fact", dep["fact_id"])
        superseded = {item.get("supersedes") for item in list_records(root, "fact")}
        if fact["id"] in superseded or fact["status"] not in {"candidate_confirmed", "document_supported"} or dep.get("fact_version") != fact["version"]:
            raise ValueError("Document fact is stale or unsupported")
        facts = [{"id":fact["id"], "version":fact["version"]}]
    else:
        raise ValueError("Each visible factual unit needs a claim or direct fact reference")
    if "facts" in dep and dep["facts"] != facts:
        raise ValueError("Document supporting fact versions changed")
    if dep.get("value_hash", _digest(value)) != _digest(value):
        raise ValueError("Document wording changed after its evidence selection")
    return {**dep, "facts":facts, "value_hash":_digest(value)}


def bind_dependencies(root, content, profile):
    """Capture selected refs once; exact approved wording needs no extra logging."""
    from .records import list_records
    result = copy.deepcopy(content)
    fields = factual_fields(result, profile)
    supplied = result.get("dependencies", [])
    declarations = {dep["pointer"]:dep for dep in supplied}
    if len(declarations) != len(supplied) or set(declarations) - fields.keys():
        raise ValueError("Dependency pointers must identify unique visible factual units")
    facts, claims = list_records(root, "fact"), list_records(root, "claim")
    dependencies = []
    for pointer, value in fields.items():
        declaration = declarations.get(pointer)
        if declaration is None:
            candidates = [{"claim_id":c["id"], "claim_version":c["version"]} for c in claims if c.get("safe_wording") == value and c.get("status") == "approved"]
            candidates += [{"fact_id":f["id"], "fact_version":f["version"]} for f in facts if f.get("value") == value and f.get("status") in {"candidate_confirmed", "document_supported"}]
            if not candidates:
                raise ValueError("Missing factual provenance at " + pointer)
            declaration = {"pointer":pointer, **candidates[0]}
        dependencies.append(_dependency(root, declaration, value))
    result["dependencies"] = dependencies
    return result


def verify_dependencies(root, content, profile):
    fields = factual_fields(content, profile)
    deps = content.get("dependencies", [])
    if len(deps) != len(fields) or {dep["pointer"] for dep in deps} != set(fields):
        raise ValueError("Production document requires complete field-level provenance")
    for dep in deps:
        if "value_hash" not in dep or "facts" not in dep:
            raise ValueError("Document dependencies were not frozen during preparation")
        _dependency(root, dep, fields[dep["pointer"]])
    return True


def register_document(root, directory):
    from . import store
    from .records import _digest
    from .workspace import contained_path, load_workspace, locked_workspace
    directory = contained_path(root, directory)
    content = json.loads((directory/"canonical.json").read_text())
    profile = json.loads((directory/"template-profile.json").read_text())
    verify_dependencies(root, content, profile)
    manifest = json.loads((directory/"manifest.json").read_text())
    if manifest.get("workspace_id") != load_workspace(root)["id"]:
        raise ValueError("Document manifest is not bound to this workspace")
    value = {"id":_digest(str(directory)), "directory":str(directory), "workspace_id":load_workspace(root)["id"],
             "profile":profile, "dependencies":content["dependencies"], "artifact_hashes":manifest["artifact_hashes"]}
    with locked_workspace(root):
        store.connection(root).execute("INSERT INTO documents VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (value["id"], str(directory), store.encode(value)))
    return value


def review_pack(bundle_dir):
    output = Path(bundle_dir).resolve()
    report = verify_bundle(output)
    value = {"bundle":str(output), "artifact_hashes":report["artifact_hashes"],
        "canonical":json.loads((output/"canonical.json").read_text()),
        "pages":[{"id":f"{mode}:{page}", "render":str(output/f"{mode}-{page}.png")} for mode,count in report["pages"].items() for page in range(1,count+1)],
        "dimensions":["factual", "vacancy_fit", "visual"], "status":"awaiting_independent_human_or_agent_review"}
    _write(output/"review-pack.json", value)
    return value
