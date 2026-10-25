# Private pilot and release checks

Use a separate computer or clean OS account and synthetic examples first. Consent, personal intake, results and development notes belong in an external private directory.

1. Inspect the bootstrap plan. Verify preservation of existing agent settings. Run doctor and its synthetic document smoke check; record actual agent, Python, TeX, renderer and OS versions.
2. Give the agent the explicit workspace. Test narrative-only intake and conflicting CVs. Confirm facts, open questions, defensible wording and scoped answers. Unknown metrics stay unknown.
3. Compare two structures and select one. Review paired LaTeX/PDF output, extraction, every rendered page and independent content/visual findings. Correct material defects and finalize unchanged hashes. A smoke build with review pending is a draft.
4. Approve campaign roles, resources, filters and permissions. Try a synthetic form, permitted test upload and mailbox read. Save precise handoffs for unavailable capabilities. No employer send is needed for this pilot.
5. Use controlled fixtures for duplicates, changed attachments, interrupted delivery and pause/resume. Managed-mode checks use two synthetic clients. Never test with another client's live data.
6. Ask the participant about factual accuracy, interview burden, useful formulations, template fit and handoff clarity. Record defects privately and repeat affected checks after corrections.

A real-person usability gate requires a consenting participant other than the source candidate. A second computer proves an installation path, not that participant gate. Report synthetic journeys, contract tests, PDF builds, authenticated browser operation and real submissions separately.

Before release, review the public tree, reachable history, identities, tags, notices, wheel/sdist and site-only payload. Choose an explicit original-product license and obtain the owner's publication decision. Never publish private plans, records, traces or experiment cases. The Pages workflow requires a deliberate release-review input; installation does not trigger it.

## Public source boundary

This repository contains reviewed product source, synthetic examples and the founder's explicitly published story and service contact. Candidate records stay private.
Keep candidate documents, account details, correspondence, browser state,
application records, interview notes, experiments and development plans outside
this checkout. An ignored file is still a local file; ignoring it does not make
it safe to share, upload or include in an archive.

Enable the local commit check after cloning:

```sh
git config --local core.hooksPath .githooks
python3 scripts/check_public_tree.py --history
```

The check inspects the entire staged tree, including files added with force.
Unknown paths, links, binary content and common sensitive-data markers fail
closed. Extend the explicit path list and ignore rules only for reviewed product
files. Use reserved example domains for synthetic email addresses.

This is an accidental-disclosure guard, not a complete anonymization detector.
Names, work histories and other personal facts still require human review.
Hooks are local and bypassable; run the check separately before publication.
The history option also checks reachable commits and author/committer email
metadata. Review names, tags, configuration and release payloads manually.
Start with clean history and choose a deliberate public commit identity.
Private data may be sent to a chosen model provider during agent use; local file
storage does not imply local model inference.

The source is published for inspection. No license has been granted for the original product yet; the bundled Humanizer has its own license. See [third-party notices](../THIRD_PARTY_NOTICES.md). GitHub Pages deployment is manual, gated and uploads only `site/`. Installation never publishes. There are no guarantees of ATS acceptance, detector results, account availability, interviews or offers. See [pilot and release checks](#private-pilot-and-release-checks).

## Development checks

```sh
python -m unittest discover -s tests -v
python scripts/check_public_tree.py --history
```

PDF tests need the document tools above and `pypdf`; unavailable dependencies produce explicit skips. Installer shim tests prove argument/path behavior, not provider authentication. Keep private test results, replay cases and development plans outside the source repository.

For local distribution checks, install the development tool `build` in an external environment and run `python scripts/build_release.py --output /absolute/new-package-directory` from a clean committed checkout. It builds wheel/sdist, neutralizes source-archive ownership metadata and checks exact approved paths, content and required notices. This does not choose a license or publish a package.
