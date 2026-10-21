# Installation and first result

This is a repository used by an agent, not a hosted application. Start from an inspected clone obtained with Git or GitHub CLI. Choose an agent account/subscription and a **private directory outside the source checkout**. Personal files must not be placed in source, even when ignored by Git.

## Inspect the plan

Run from the checkout on macOS or Linux:

```sh
sh install/install.sh --dry-run
sh install/install.sh --check --agent codex
```

On native Windows, use PowerShell:

```powershell
.\install\install.ps1 -DryRun
.\install\install.ps1 -Check -Agent claude
```

The default invocation only prints a plan. `--dry-run` / `-DryRun` does not call Python, download or write files. `--check` / `-Check` is a read-only command-presence report; exit 2 means incomplete. Presence is not a successful build, account login, browser upload or mailbox capability.

## Create the environment

After reviewing the source, choose a local private workspace:

```sh
sh install/install.sh \
  --workspace "$HOME/career-workspace" \
  --agent codex --yes --smoke
```

```powershell
.\install\install.ps1 `
  -Workspace "$env:USERPROFILE\career-workspace" `
  -Agent claude -Yes -Smoke
```

Choose `codex` or `claude`; existing installations/configuration are preserved. A separate Python environment defaults to the workspace path with `.venv` appended. Override with `--venv` / `-Venv` and select existing Python 3.11+ using `--python` / `-Python`. Workspace, environment and source must not overlap or traverse symbolic links/junctions. Existing non-environment directories are not overwritten. Re-running preserves an initialized workspace and its policy/feedback choice.

Resume with the workspace's configured agent. A conflicting agent choice stops setup before environment changes; use a separate workspace when choosing a different agent.

The installer installs this checkout into the private environment with its pinned Python dependencies, including pypdf for extraction/inspection. XeLaTeX compiles the templates and Poppler's `pdftoppm` renders them; `pdftotext` is not required. GitHub CLI is optional unless upstream GitHub feedback is enabled. This step uses package indexes unless `--offline` / `-Offline` is selected. Offline mode disables indexes, build isolation and installer downloads; the environment must already have the required build backend/dependencies from a trusted offline source. It is not a promise that a fresh machine can install without prepared packages.

`--smoke` / `-Smoke` asks doctor to actually compile a synthetic paired CV, extract/compare text and render pages. Basic doctor reports capability discovery. Neither can perform the person's every-page visual and independent review on their behalf. Missing required tools/checks remain handoffs rather than a false ready result.

## Clean-machine dependencies

`--install-dependencies` / `-InstallDependencies` is an **additional explicit permission** to install missing dependencies, used together with `--yes` / `-Yes`. It cannot be combined with offline mode. The bootstrap does not set agent permissions, alter global agent settings, sign in, change execution policy or silently escalate to administrator privileges.

- **macOS:** with user-installed Homebrew, missing Python, Git and Poppler can be installed from its formulas; missing XeLaTeX uses the BasicTeX cask (GitHub CLI is installed only for enabled feedback). The system installer may request confirmation. Reopen the terminal if PATH changes. BasicTeX may need template packages through its normal package manager; doctor/smoke exposes missing packages. Homebrew itself is not silently installed.
- **Linux:** supply Python 3.11+, its `venv` support, Git, a XeLaTeX-capable TeX distribution and Poppler through the machine's package manager. On Debian/Ubuntu typical packages are `python3 python3-venv git texlive-xetex texlive-latex-recommended texlive-fonts-recommended poppler-utils`; verify package names for your distribution. The script does not run `sudo` or modify package repositories. Missing system tools become explicit installation handoffs.
- **Native Windows:** the PowerShell path can install missing Python and Git (plus GitHub CLI for enabled feedback) through WinGet when explicitly permitted, using interactive package prompts. Install [official TeX Live](https://tug.org/texlive/windows.html). A reviewed Windows Poppler binary source is a separate handoff; the bootstrap does not fetch an unreviewed binary. Review private-directory Windows ACLs. This native path remains untested until run on a real Windows machine.
- **WSL:** use the POSIX installer inside the chosen distribution. Its Python/TeX environment and Windows browser integrations are separate capabilities. Do not report native Windows tests as WSL tests or assume Chrome/native desktop integration works across the boundary.

Missing chosen agents can be installed through the official native installers, downloaded then executed only under the explicit dependency flag. Review the provider's current installer and sign in yourself: [Codex](https://developers.openai.com/codex/cli), [Claude Code](https://code.claude.com/docs/en/setup). These installer channels can change; record the installed version. No bundled agent binary, account or subscription is included.

If a new binary is not on PATH, reopen the terminal and rerun. Do not overwrite existing configuration or enable unrestricted execution to make a capability check pass.

## Start the agent and complete onboarding

The bootstrap prints the exact private-environment Python path and `fmj run` command. Use it to launch the selected agent bound to the workspace. Or start the agent in this checkout and explicitly identify the workspace; it reads `AGENTS.md` / `CLAUDE.md`.

First confirm provider/service data processing, language/timezone and scoped capabilities. Browser navigation, upload, mailbox read/send and optional native computer control require separate real checks. A CLI installation does not provide them. Tool-required credential, CAPTCHA and agreement handoffs stay with the person. No helper bypasses them.

Feedback is unset initially: onboarding asks whether inspected generic issues/isolated PRs may be sent from your GitHub identity to the selected upstream. No sending on silence. Set a deliberate initial choice only with an explicit upstream:

```sh
sh install/install.sh --workspace "$HOME/career-workspace" \
  --agent codex --yes --feedback disabled --upstream example/product
```

`example/product` illustrates the argument format; select the actual repository before enabling feedback. It is not a published package or a configured destination. Existing workspace consent is preserved on rerun.

Bring several historical CV versions if available; otherwise tell the agent your story. Work through the project interview, confirm claims/recurring answers and choose from two or three relevant LaTeX structures. The first result is an inspectable evidence base and general CV. Only then approve roles, resources, filters, outreach and schedule for a campaign.

Choose an independent human or separate-agent review route before document work. `documents review-pack` supplies exact private content, hashes and pages; doctor reports an unconfigured reviewer. Missing browser/upload leaves a manual-submission package available. Agent launch uses the private workspace and installed runtime without parent-shell activation. Version-1 workspaces need `storage migrate` inspection and explicit `--apply`; see [tracking and recovery](tracking.md).

## Managed setup

The operator provisions separate private workspaces/browser sessions and initial resources. Use `--mode managed --operator ID` (PowerShell: `-Mode managed -Operator ID`). The operator configures paid-client Telegram binding separately; self-hosted operation does not require Telegram. Never put bot tokens, passwords or client material in source or chat. A client pause stops new outbound actions; resume removes only their own pause, with no billing/access change.

## Acceptance on another computer

1. Use a clean clone and a new private workspace; do not transfer real candidate data for a tooling smoke test.
2. Record OS/architecture, native vs WSL, agent/version and dependency versions. Run plan/check, then the chosen setup with smoke.
3. Verify source remains free of generated/private data and existing agent configuration is unchanged.
4. Complete synthetic intake, compare two structural previews and inspect both generated PDFs on every page. Missing fonts/packages/renderers must appear as blockers.
5. Check browser navigation and a permitted synthetic upload separately, then mailbox access if authorized. Do not send applications, emails or feedback as part of an unapproved smoke test.
6. Record actual passes, failures and untested capabilities privately. A consenting real-person intake/document review is a separate release gate; synthetic fixtures cannot replace it.

See [support matrix](support-matrix.md) for the current evidence boundary. Installation performs no publication, Pages deployment, paid action or real campaign activation by itself.
