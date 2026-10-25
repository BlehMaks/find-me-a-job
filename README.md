# Find Me a Job

**Let your agent do the application work.**

Turn Codex or Claude Code into a job-search assistant that knows your experience, prepares tailored CVs and helps you apply across different sites. Keep applications and replies in one private workspace, so you can pick up where you left off.

[Explore the website](https://blehmaks.github.io/find-me-a-job/) · [Run it yourself](#start-with-the-desktop-installer-recommended) · [Have me run it for you](#want-me-to-run-your-search)

## What it does

- **Learn your experience once.** Start with old CVs, project notes or a conversation. Confirm what you built, owned and achieved.
- **Prepare each application.** Get a tailored CV and a cover letter when needed, with checks on the PDF's text and layout.
- **Search across sites.** Use employer career pages, job boards, LinkedIn and email alerts. Apply through official employer routes where available.
- **Keep the search moving.** Track submissions and replies, resume blocked steps and prepare for interviews.

There are CV structures for industry, academic and creative careers. You work through your existing agent; no separate hosted account or dashboard is required.

## I built it for my own search

I'm Maksim. I was working as an **IT Consultant in Germany** and looking for my next job. I built Find Me a Job during that search to help prepare and submit applications across different sites.

The search led to **around 25 first-round interviews and an offer for an AI Solutions Developer position**.

## Start with the desktop installer (recommended)

### 1. Download and open the setup app

| Download | Open it |
| --- | --- |
| [macOS (.dmg)](https://github.com/BlehMaks/find-me-a-job/actions/runs/39633618699/artifacts/12360688210) | Extract the ZIP, open the DMG, drag **Find Me a Job Setup** into **Applications**, then open it there. |
| [Windows (.exe)](https://github.com/BlehMaks/find-me-a-job/actions/runs/39630554386/artifacts/12359196363) | Extract the ZIP and launch the EXE. |

GitHub sign-in is required for downloads. These are unsigned pilot builds. If a download has expired, open the [installer builds](https://github.com/BlehMaks/find-me-a-job/actions/workflows/installer.yml).

### 2. Choose your agent and folders

Select **Codex** or **Claude**, keep **desktop**, and choose separate source and private-workspace folders. Review the setup plan, then let the wizard prepare the tools you approve. The setup app includes its own Python and interface.

### 3. Open the project and start talking

After the checks pass, select **Copy first message**. Open the displayed source folder in your agent, paste the message and grant access to the private folder. Start with your experience; agree on the search scope before applications begin.

Your agent account, available quota, browser and mailbox access are checked separately. Paid access is recommended for sustained campaigns.

<details>
<summary>Manual setup, CLI or Linux</summary>

From a reviewed clone, the CLI route is:

```sh
sh install/install.sh --interface cli --agent codex \
  --workspace "$HOME/fmj-private" --yes
"$HOME/fmj-private.venv/bin/fmj" run --workspace "$HOME/fmj-private"
```

Use `--agent claude` for Claude Code. See the [installation guide](docs/install.md) for manual desktop setup, Windows PowerShell, dependencies, offline use and resuming an interrupted setup. The [support matrix](docs/support-matrix.md) records what has actually been tested.

</details>

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

The source is available for inspection; an original-product license has not yet been specified. See [third-party notices](THIRD_PARTY_NOTICES.md). Interviews and offers are not guaranteed.
