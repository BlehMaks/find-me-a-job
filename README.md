# Find Me a Job

A local workspace for a career-search agent: turn experience into confirmed knowledge, prepare tailored LaTeX/PDF documents, research opportunities and run an authorized application campaign. Industry, academic and creative careers have different workflows. Start with the person's account of how their profession hires.

The interface is your existing Codex or Claude Code agent. There is no hosted account or web dashboard. An optional operator-managed setup adds bound client questions and pause/resume through Telegram.

## Start from a checkout

You need Git, Python **3.11+** and an installed, authenticated supported agent. Document builds also need **XeLaTeX**, its template packages/fonts and Poppler's `pdftoppm`. GitHub CLI is needed only for optional upstream feedback. Browser, uploads and mailbox access require an available host integration and separate checks.

Clone using the repository's GitHub **Code → Clone** URL, open a terminal inside it, then inspect the bootstrap:

```sh
sh install/install.sh --help
sh install/install.sh --workspace "$HOME/fmj-private" --agent codex --dry-run
sh install/install.sh --workspace "$HOME/fmj-private" --agent codex --yes --smoke
```

Use `--agent claude` for Claude Code. On Windows use `install/install.ps1`; see [installation](docs/install.md) for exact options, dependency installation, offline use and resuming. The default bootstrap only prints a plan. Installing agent software/system dependencies is separately selected; it preserves existing agent configuration and requires provider authentication where applicable.

The default environment is a sibling of the private workspace. Continue with:

```sh
"$HOME/fmj-private.venv/bin/fmj" doctor --workspace "$HOME/fmj-private" --json
"$HOME/fmj-private.venv/bin/fmj" run --workspace "$HOME/fmj-private"
```

Alternatively create an external virtual environment, run `python -m pip install .` there, then `fmj init --workspace /absolute/private-directory --agent codex`. Keep both the environment and workspace outside this checkout. See the [tested platform matrix](docs/support-matrix.md); missing capabilities are precise handoffs.

## Workflow

Read [AGENTS.md](AGENTS.md), or [CLAUDE.md](CLAUDE.md), with the explicitly selected external workspace. The agent resumes the first incomplete phase:

1. Compare historical CVs or start from a narrative. Interview project by project about ownership, methods, results and defensible metrics. Resolve contradictions and confidentiality before approving claims. Unknown and confirmed absent are separate states.
2. Build confirmed facts, evidence, wording variants and question-scoped application answers. Ask for authentic writing examples; use neutral professional wording when none are available.
3. Offer structural previews from industry, academic or portfolio families. Produce general and vacancy-specific CVs. Humanizer is bundled with its license. Standard and inactive `.tex`/PDF versions share visible wording. Compilation, extraction, PDF inspection, every-page visual review and independent review gate readiness.
4. Confirm desired and disliked work, markets, roles, resources and authority. Research official openings, LinkedIn/email alerts, research groups, programs or creative calls. Align the general LinkedIn profile; the person normally chooses Open to Work visibility.
5. Prepare actual form fields and documents, apply through official routes and send authorized correspondence. Keep immutable intent, exact attachments, observations, acknowledgements and outcomes. Reconcile ambiguous delivery before retrying. Prepare sourced interview briefings when invited.

Starter market notes cover Germany, Austria, Switzerland, the UK, the US, Canada and France. Actual employer, institution and call requirements take precedence.

## Commands and outbound bridge

`fmj --help` and each subcommand's `--help` list the interfaces. `record` validates versioned facts, claims, answers and policies. `documents previews/build/check/review/finalize` creates and verifies durable private bundles. Synthetic content examples live under `tests/fixtures/documents/`.

The selected agent uses its actual permitted host tools for browser and mailbox access. After observing a synthetic capability check, record private evidence with `fmj capability`. Before an external action, prepare an operation and call `campaign begin` with the actual form observation. It returns a one-use ticket for that exact intent. Perform the permitted native action once, then `campaign complete` with an observed outcome and evidence. See [the operation contract](docs/operations.md).

One uncertain or in-flight delivery prevents another send in that workspace. `campaign recover` is an explicit restart reconciliation step. Screenshots, receipts and form observations are evidence; a generated CV or queue row is not a submitted application.

Routine sends can be delegated in advance. The person retains appointments, offer decisions, final compensation/terms, withdrawals, paid actions and material commitments. Credential, CAPTCHA and binding-agreement handoffs required by the current tool remain in effect. No hook or credential helper bypasses them.

## Managed use and feedback

Create an external workspace per client with `fmj init --mode managed --operator OPERATOR --owner CLIENT --agent codex ...`. The operator provisions resources and client/browser/channel bindings; see [the operator guide](docs/managed.md).

Bound clients can answer facts, inspect their materials and `/pause` or `/resume` their own pause. Service changes, access, pricing and campaign configuration stay with the operator. Pause changes no billing, cancellation or access rights. Separate folders organize state; operating-system permissions and separate agent/browser contexts must supply required isolation.

Upstream feedback requires an explicit enable/disable choice; unset sends nothing. Only reviewed synthetic issues or hash-bound isolated patches can be submitted through the user's authorized account. The agent cannot merge them. Uncertain content stays private; the maintainer handles deduplication. No background telemetry is included.

## Public source boundary

This repository contains reviewed product source and synthetic examples only.
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

Original-product licensing and public release are owner decisions; the bundled Humanizer license does not grant a license for the original product. See [third-party notices](THIRD_PARTY_NOTICES.md). GitHub Pages deployment is manual, gated and uploads only `site/`. Installation never publishes. There are no guarantees of ATS acceptance, detector results, account availability, interviews or offers. See [pilot and release checks](docs/pilot.md).

## Development checks

```sh
python -m unittest discover -s tests -v
python scripts/check_public_tree.py --history
```

PDF tests need the document tools above and `pypdf`; unavailable dependencies produce explicit skips. Installer shim tests prove argument/path behavior, not provider authentication. Keep private test results, replay cases and development plans outside the source repository.
