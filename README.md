# Find Me a Job

**Let your agent do the application work.**

Find Me a Job turns Codex or Claude Code into a job-search assistant that learns your experience, finds suitable roles, prepares tailored CVs and helps submit applications. It keeps track of what was sent and what came back, so the next session can pick up where you left off.

**[See the product page](https://blehmaks.github.io/find-me-a-job/) · [Run it yourself](#start-with-the-desktop-installer-recommended) · [Have me run it for you](#want-me-to-run-your-search)**

## I built it for my own search

I'm Maksim. I was working as an **IT Consultant in Germany** and looking for my next job. I built Find Me a Job during that search to help prepare and submit applications across different sites.

The search led to **around 25 first-round interviews and an offer for an AI Solutions Developer position**.

Now I'm sharing the workflow. You can run it with Codex or Claude Code, or have me run the application campaign for you.

## What it takes off your plate

- **Explaining your career again.** Start with old CVs, project notes or a conversation. The agent builds a reusable experience bank and asks you to resolve gaps and contradictions.
- **Rewriting every application.** Get a CV tailored to the actual role, plus a cover letter when needed. The workflow checks the compiled PDF's text and layout and asks an independent reviewer to critique it.
- **Repeating the same search on different sites.** Use employer career pages, job boards, LinkedIn and email alerts within the access available to your agent. The search is not limited to one job site; applications go through official employer routes where available.
- **Losing track of what happened.** Keep documents, submissions, acknowledgements and replies separate. Resume blocked forms and prepare for interviews with the history at hand.

Use **Codex or Claude Code**, on your computer or in an operator-managed setup. Industry, academic and creative careers have different workflows and CV structures. Your personal records live in a separate private workspace; the chosen model provider and connected services process the data they need.

## Want me to run your search?

**Email [findmeajobai@gmail.com](mailto:findmeajobai@gmail.com).** I can set up and operate the workflow on your behalf, with an agreed search scope and permissions.

For this managed service, you'll need:

- **An active paid subscription that includes Claude Code or Codex**, with enough quota for the campaign.
- **A mailbox** you authorise me to use for job applications and replies.
- **A LinkedIn account linked to that mailbox.**

We'll arrange access together and agree on the service terms before starting. You confirm your experience and answer personal questions; I handle the campaign work within the agreed scope. Interviews, offers and final commitments stay with you. Managed mode supports questions and pause/resume through Telegram.

## Technical setup

The interface is your existing Codex or Claude Code agent. There is no hosted account or web dashboard. The sections below explain installation and the runtime; you can also read the [operator guide](docs/managed.md).

## Start with the desktop installer (recommended)

1. Download **FindMeAJob-Setup** for [macOS (.dmg)](https://github.com/BlehMaks/find-me-a-job/actions/runs/39633618699/artifacts/12360688210) or [Windows (.exe)](https://github.com/BlehMaks/find-me-a-job/actions/runs/39630554386/artifacts/12359196363), then extract the downloaded ZIP. These links update automatically after successful builds on the default branch, separately for each operating system. Sign in to GitHub to download these unsigned pilot builds. They are early test builds, not a signed stable release. If an artifact has expired, request a new [installer build](https://github.com/BlehMaks/find-me-a-job/actions/workflows/installer.yml).
2. On macOS open the `.dmg`, drag **Find Me a Job Setup** into **Applications**, then open it from Applications; on Windows launch the `.exe`. The wizard includes Python and Tk: no terminal, GitHub Desktop or preinstalled Python is needed to open it.
3. Select Codex or Claude, keep **desktop**, and choose separate source/private folders. Review the detected tools and setup plan. Allow missing software installation if wanted; native package managers may request your confirmation. GitHub authorization is a separate button. Existing folders and settings are checked before reuse.
4. After runtime and PDF checks pass, use **Copy first message**. Open the displayed source folder in your agent: add/open the local project in Codex, or choose **Code → Local → Open folder…** in Claude. Paste the message and grant access to the separate private folder when requested.

The wizard can install Git, GitHub CLI, Python and document tools, clone the repository and prepare the private runtime. GitHub Desktop is optional and does not supply GitHub CLI. Feedback is a separate explicit choice; enabling it prepares missing local contribution settings but does not send any issue or PR. Sign-in alone does not enable feedback.

For sustained application campaigns we recommend a paid agent plan. Free allowances may be useful for exploration but are not a reliable campaign budget; paid plans also have limits. Installing an app proves neither subscription nor available quota. Confirm these in your account. Nothing buys a subscription, signs in to the agent or changes billing automatically. Folder access, browser control and mailbox permissions need separate checks.

For a manual graphical fallback, install [Codex / ChatGPT desktop](https://learn.chatgpt.com/docs/app) or [Claude Desktop](https://code.claude.com/docs/en/desktop-quickstart), then clone with [GitHub Desktop](https://desktop.github.com/download/), **File → Clone repository → URL**. Open that folder in the agent and ask it to read `AGENTS.md`, inspect the installer and prepare a separate private workspace after reviewing its plan. Begin experience intake before any campaign actions. See [installation](docs/install.md) for complete instructions and native build limitations.

## Installer and optional CLI route

From a reviewed checkout, you or your desktop agent can run:

```sh
sh install/install.sh --workspace "$HOME/fmj-private" --agent codex --dry-run
sh install/install.sh --workspace "$HOME/fmj-private" --agent codex --yes --smoke
```

Desktop is the default. Add `--install-dependencies` to permit missing desktop/system software installation through available package managers. Use `--desktop-app PATH` for a custom app location. The installer prints exact folder paths and a starter prompt, also saved privately as `runtime/start-here.md`.

For the CLI alternative, select it explicitly:

```sh
sh install/install.sh --interface cli --workspace "$HOME/fmj-private" --agent codex --yes
"$HOME/fmj-private.venv/bin/fmj" run --workspace "$HOME/fmj-private"
```

The CLI route automatically prepares the runtime and workspace; `run` binds the agent to the correct private directory and source instructions. Existing global agent settings remain unchanged. Provider sign-in, service access and browser/mail permissions still require their own checks.

Use `--agent claude` for Claude Code. On Windows use `install/install.ps1 -Interface desktop` or `-Interface cli`. Git and Python **3.11+** are required for runtime setup; PDF work needs **XeLaTeX** and Poppler's `pdftoppm`. GitHub CLI is optional unless upstream feedback is enabled. See [installation](docs/install.md) for platform paths, offline use, partial setup and resuming, and the [tested platform matrix](docs/support-matrix.md).

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

Operational memory uses local SQLite with linked companies, opportunities, applications, documents and next actions. Normal commands record effects automatically; no duplicate narrative ledger or reporting model is required. Use `track list/report` for bounded queries, and inspect employer-interest tasks before new discovery. Existing workspaces require validated migration. See [tracking and recovery](docs/tracking.md).

For suitable opportunities seek referrals before submitting, contacting a few relevant people in parallel with a finite wait. Prepare documents and continue other opportunities meanwhile. Preserve broad matching; every 50 unique observed new applications creates a short, nonblocking direction review.

The selected agent uses its actual permitted host tools for browser and mailbox access. After observing a synthetic capability check, record private evidence with `fmj capability`. Before an external action, prepare an operation and call `campaign begin` with the actual form observation. It returns a one-use ticket for that exact intent. Perform the permitted native action once, then `campaign complete` with an observed outcome and evidence. See [the operation contract](docs/operations.md).

One uncertain or in-flight delivery prevents another send in that workspace. `campaign recover` is an explicit restart reconciliation step. Screenshots, receipts and form observations are evidence; a generated CV or queue row is not a submitted application.

Routine sends can be delegated in advance. The person retains appointments, offer decisions, final compensation/terms, withdrawals, paid actions and material commitments. Credential, CAPTCHA and binding-agreement handoffs required by the current tool remain in effect. No hook or credential helper bypasses them.

## Managed use and feedback

Create an external workspace per client with `fmj init --mode managed --operator OPERATOR --owner CLIENT --agent codex ...`. The operator provisions resources and client/browser/channel bindings; see [the operator guide](docs/managed.md).

Bound clients can answer facts, inspect their materials and `/pause` or `/resume` their own pause. Service changes, access, pricing and campaign configuration stay with the operator. Pause changes no billing, cancellation or access rights. Separate folders organize state; operating-system permissions and separate agent/browser contexts must supply required isolation.

Upstream feedback requires an explicit enable/disable choice; unset sends nothing. Only reviewed synthetic issues or hash-bound isolated patches can be submitted through the user's authorized account. The agent cannot merge them. Uncertain content stays private; the maintainer handles deduplication. No background telemetry is included.

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

The source is published for inspection. No license has been granted for the original product yet; the bundled Humanizer has its own license. See [third-party notices](THIRD_PARTY_NOTICES.md). GitHub Pages deployment is manual, gated and uploads only `site/`. Installation never publishes. There are no guarantees of ATS acceptance, detector results, account availability, interviews or offers. See [pilot and release checks](docs/pilot.md).

## Development checks

```sh
python -m unittest discover -s tests -v
python scripts/check_public_tree.py --history
```

PDF tests need the document tools above and `pypdf`; unavailable dependencies produce explicit skips. Installer shim tests prove argument/path behavior, not provider authentication. Keep private test results, replay cases and development plans outside the source repository.

For local distribution checks, install the development tool `build` in an external environment and run `python scripts/build_release.py --output /absolute/new-package-directory` from a clean committed checkout. It builds wheel/sdist, neutralizes source-archive ownership metadata and checks exact approved paths, content and required notices. This does not choose a license or publish a package.
