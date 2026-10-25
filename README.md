<p align="center"><img src="site/assets/mark.svg" alt="Find Me a Job" width="72"></p>

# Find Me a Job

[![Source checks](https://github.com/BlehMaks/find-me-a-job/actions/workflows/check.yml/badge.svg)](https://github.com/BlehMaks/find-me-a-job/actions/workflows/check.yml) [![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Let your agent do the application work.**

Turn Codex or Claude Code into a job-search assistant that knows your experience, prepares tailored CVs and helps you apply across different sites. Keep applications and replies in one private workspace, so you can pick up where you left off.

[Explore the website](https://blehmaks.github.io/find-me-a-job/) · [Quick start](#quick-start-without-installers) · [Have me run it for you](#want-me-to-run-your-search)

## What it does

- **Learn your experience once.** Start with old CVs, project notes or a conversation. Confirm what you built, owned and achieved.
- **Prepare each application.** Get a tailored CV and a cover letter when needed, with checks on the PDF's text and layout.
- **Search across sites.** Use employer career pages, job boards, LinkedIn and email alerts. Apply through official employer routes where available.
- **Keep the search moving.** Track submissions and replies, resume blocked steps and prepare for interviews.

There are CV structures for industry, academic and creative careers. You work through your existing agent; no separate hosted account or dashboard is required.

## I built it for my own search

I'm Maksim. I was working as an **IT Consultant in Germany** and looking for my next job. I built Find Me a Job during that search to help prepare and submit applications across different sites.

The search led to **around 25 first-round interviews and an offer for an AI Solutions Developer position**.

## Before you start

- **Codex or Claude Code**, with access to your local project folder. Use a paid plan with enough quota for a sustained search.
- **Your experience:** an existing CV, project notes, or time to talk through your work.
- **A separate private folder** for your documents and applications. Keep personal data outside this repository.
- Browser and mailbox access for submitting applications and following up. Your agent's available integrations determine which steps it can perform.

## Quick start without installers

### 1. Get the source

Clone the first release with Git:

```sh
git clone --branch v0.1.0 https://github.com/BlehMaks/find-me-a-job.git
cd find-me-a-job
```

Or download the **Source code (zip)** from [Releases](https://github.com/BlehMaks/find-me-a-job/releases/tag/v0.1.0) and extract it. No setup application is required.

### 2. Open the folder in your agent

Open the cloned or extracted folder in Codex or Claude Code. Paste this to get started:

> Read AGENTS.md and the installation guide. Review the setup scripts and help me prepare a private workspace outside this checkout. Show me the setup plan before installing dependencies. Then help me turn my experience into a CV and agree on the roles and locations for my search.

The agent can walk you through the source setup. Python 3.11+, Git, XeLaTeX and Poppler are needed for the full document workflow; the [installation guide](docs/install.md) covers each platform. Grant the agent access to your private folder when prompted.

### 3. Start with your experience

Add your existing CV and notes to the private folder, or describe your work in the chat. Confirm the facts, review your first CV, then agree on a campaign. The same workspace keeps your applications, replies and next steps together.

<details>
<summary><strong>Terminal setup: macOS, Linux and Windows</strong></summary>

From the cloned folder, with the [prerequisites](docs/install.md) installed:

**macOS / Linux**

```sh
sh install/install.sh --interface cli --agent codex \
  --workspace "$HOME/fmj-private" --yes
"$HOME/fmj-private.venv/bin/fmj" run --workspace "$HOME/fmj-private"
```

**Windows PowerShell**

```powershell
.\install\install.ps1 -Interface cli -Agent codex `
  -Workspace "$env:USERPROFILE\fmj-private" -Yes
& "$env:USERPROFILE\fmj-private.venv\Scripts\fmj.exe" run `
  --workspace "$env:USERPROFILE\fmj-private"
```

Use `claude` instead of `codex` for Claude Code. The CLI must already be installed and authenticated. For desktop use, select `--interface desktop` / `-Interface desktop` and open the source folder in your app. See the guide for dependency installation, offline use and resuming setup.

</details>

## Optional desktop setup app

| Platform | Download | Open it |
| --- | --- | --- |
| macOS · Apple Silicon (arm64) | [macOS (.dmg)](https://github.com/BlehMaks/find-me-a-job/releases/download/v0.1.0/FindMeAJob-Setup-0.1.0-macos-arm64.dmg) | Open the DMG, drag **Find Me a Job Setup** into **Applications**, then open it there. |
| Windows · x64 | [Windows (.exe)](https://github.com/BlehMaks/find-me-a-job/releases/download/v0.1.0/FindMeAJob-Setup-0.1.0-windows-x64.exe) | Launch the EXE. |

These are **unsigned builds**; macOS builds are not notarized. Your OS may warn or block them. You can use the source route above. [Release notes and SHA-256 checksums](https://github.com/BlehMaks/find-me-a-job/releases/tag/v0.1.0) identify the published files; a checksum is not a publisher signature.

The app bundles Python and its interface. Choose your agent and separate source/private folders, review the plan, then start setup. When checks pass, use **Copy first message** and open the displayed source folder in your agent. Account, quota, browser and mailbox access are checked separately. See the [support matrix](docs/support-matrix.md) for tested platforms and limitations.

## Want me to run your search?

**Email [findmeajobai@gmail.com](mailto:findmeajobai@gmail.com)** with your target roles and locations. I can set up the workflow and run the application campaign for you.

You'll need:

- **A paid subscription that includes Claude Code or Codex**, with enough quota for the campaign.
- **A mailbox** you authorise me to use for applications and replies.
- **A LinkedIn account linked to that mailbox.**

We'll agree on access, scope and service terms before starting. You confirm your experience and answer personal questions; I handle the campaign work. You attend interviews and make the final decisions. Managed mode supports questions and pause/resume through Telegram.

## Find what you need

| Guide | What's inside |
| --- | --- |
| [Installation](docs/install.md) | Desktop, manual and CLI setup; dependencies and troubleshooting |
| [Platform support](docs/support-matrix.md) | Tested platforms and current limitations |
| [Tracking and recovery](docs/tracking.md) | Applications, receipts, next steps and recovery |
| [Agent operations](docs/operations.md) | Browser/mail access, submission checks and delivery reconciliation |
| [Managed workspaces](docs/managed.md) | Separate client setups and Telegram questions |
| [Development and release](docs/pilot.md) | Tests, public-source checks, package builds and pilot verification |
| [Agent entry points](AGENTS.md) / [Claude instructions](CLAUDE.md) | How the agent runs the workflow |

Keep personal documents outside this checkout. Your chosen model provider and connected services process the data they need. Feedback is optional and nothing is sent upstream by default.

Released under the [MIT license](LICENSE). See [third-party notices](THIRD_PARTY_NOTICES.md) for bundled components. Interviews and offers are not guaranteed.
