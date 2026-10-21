# Installation and first result

This is a repository used by an agent, not a hosted application. Use the native setup wizard, or start from an inspected clone. Choose an agent account/subscription and a **private directory outside the source checkout**. Personal files must not be placed in source, even when ignored by Git.

## Native graphical installer

The primary route is **FindMeAJob-Setup**, a standalone setup application for macOS and Windows. It bundles the interpreter and Tk UI, so opening it does not require Python, a terminal or an installed agent. It provisions a separate system Python/venv for the actual workspace; the frozen setup interpreter is not used as a long-lived runtime.

During the private pilot, downloads are [GitHub Actions artifacts](https://github.com/BlehMaks/find-me-a-job/actions/workflows/installer.yml), not public Releases. An authorized GitHub account can open a successful run and download the artifact for its OS/architecture. Extract the artifact ZIP. On macOS open the DMG, drag **Find Me a Job Setup** into **Applications**, then open the copied app from Applications; on Windows launch the EXE. Builds are currently unsigned/unnotarized, so OS trust checks may block or warn. Verify provenance with the maintainer; do not disable system protections globally. Public distribution and signing require a separate release decision.

1. Choose **codex** or **claude**, and **desktop** (default) or **cli**. Existing installations are detected rather than reinstalled. Pick separate dedicated source and private folders; the environment will be `<private folder>.venv`.
2. Choose **Ask later**, **Allow generic improvements**, or **Keep improvements local**. Silence sends nothing. The latter two deliberately update the choice even when resuming an existing workspace; Ask later preserves an earlier choice.
3. Use **Check & review plan**. No setup is performed. Allow missing software installation only if wanted, then select **Install / retry** and confirm the displayed plan.
4. Complete any native package prompt. If setup needs a manual prerequisite, use **Open required step**, complete it and retry. For private repository access use **Sign in to GitHub** after GitHub CLI is installed; authorization appears in the browser and the wizard. Codes/output are displayed transiently, not saved as an installer journal.
5. Success requires actual synthetic LaTeX compilation, PDF extraction/inspection and rendering. It does not certify an agent subscription, browser integration or mailbox. Open the displayed source folder in your chosen app, use **Copy first message**, then grant the separate private folder access through the host app. Confirm account/plan/budget and supported permissions before intake.

The wizard uses a fixed HTTPS product origin. It refuses unrelated/nonempty destinations, dirty checkouts, wrong-origin checkouts, overlapping paths and symbolic links/junctions; it never resets, pulls over local changes or deletes partial installs. A failed clone may leave a partial folder: inspect it or choose a new source folder. Existing initialized workspaces must match the selected agent and be self-hosted; managed setup remains operator-controlled.

**Stop** cancels the wizard's owned operation and prevents later steps. It does not roll back packages or files; elevated/native installers may still need their own completion or cancellation. Recheck state before retrying. Raw command output remains in the current window only.

Dependency sources differ from the source scripts below. On macOS the wizard uses existing Homebrew for Git, GitHub CLI, Python and Poppler; missing Homebrew is an explicit handoff. Missing XeLaTeX opens the official BasicTeX installer instructions because that installation may require administrator confirmation. A missing agent app uses the selected Homebrew cask. On Windows it uses interactive WinGet packages **Git.Git**, **GitHub.cli**, **Python.Python.3.12**, **MiKTeX.MiKTeX** and **oschwartz10612.Poppler** (a community Windows distribution), followed by the existing reviewed PowerShell agent setup. Missing template packages remain explicit PDF-check failures. Linux/WSL retain the source installer; native graphical bundles are built only for macOS and Windows.

Enabled feedback checks GitHub CLI authorization and reports a missing login separately. Once authenticated, only missing effective Git settings receive repository-local defaults: GitHub login/noreply identity, GitHub CLI credential helper and the product commit hook. Existing identity/global settings remain. No fork, proposal, issue or PR is created by setup; submission access is checked when a reviewed contribution is actually requested. Sign-in can be completed later and **Install / retry** repairs this state without replacing workspace data.

### Build a private native artifact

Use a clean committed checkout on the target OS, Python with working Tk, and `pyinstaller==6.22.3`. Mac builds also require `dmgbuild==1.6.7` and `Pillow==12.1.1` for the Finder layout and rendered artwork. Run `python scripts/build_installer.py --output /absolute/new/external-directory`. It archives only approved committed source, bundles required interpreter/Tk licenses (fetching version-matched licenses from the official Tcl/Tk source tags if omitted by the Python distribution), builds on that OS, launches the bundled UI without system Python on PATH, and records its revision/hash in `installer-manifest.json`. It creates a macOS DMG or Windows EXE. Outputs must remain outside source; existing output directories are refused. Cross-compilation, signing, notarization and publication are not performed. The manual `installer.yml` workflow runs the same build on native OS runners; choose macOS, Windows or both when dispatching. Bundled UI smoke is narrower than a fresh computer installing every dependency: see [actual evidence and limits](support-matrix.md).

## Manual desktop fallback without an agent CLI

Clone with [GitHub Desktop](https://desktop.github.com/download/) using **File → Clone repository → URL** and `https://github.com/BlehMaks/find-me-a-job.git`. Choose a new local folder. While source is private, sign in with an authorized GitHub account. Alternatively, `git clone https://github.com/BlehMaks/find-me-a-job.git` does the same from a terminal. Never clone into a client-data folder or overwrite an existing directory.

Install an app from its official source, or let the reviewed bootstrap install missing software with its explicit dependency flag:

- **Codex / current ChatGPT desktop:** [official app instructions](https://learn.chatgpt.com/docs/app); add/open the local cloned folder, select Codex and start a local chat.
- **Claude Desktop:** [official Code setup](https://code.claude.com/docs/en/desktop-quickstart); sign in, open **Code**, choose a **Local** environment and **Open folder…**, then select the clone. The Code tab does not need the separate `claude` CLI.

Paste the starter request from [README](../README.md#start-with-the-desktop-installer-recommended). The agent inspects the installer, establishes your preferred external workspace and prepares the runtime with permission. It must request access to the external private directory separately if the app's folder scope excludes it. App labels vary by version. Filesystem access does not imply browser, upload, mailbox or full computer control.

On macOS with existing Homebrew, `--yes --install-dependencies` installs a missing desktop app via cask **codex-app** or **claude**. The **codex** cask is the CLI and is not used for desktop setup. Native Windows uses interactive WinGet: OpenAI Store ID **9PLM9XGG6VKS**, or **Anthropic.Claude** for desktop. Existing apps are preserved; no reinstall is requested when detected. Linux/WSL desktop installation remains a provider-specific manual handoff; use the provider's official guide or explicitly choose CLI. Custom app locations use `--desktop-app PATH` / `-DesktopApp PATH`. Detection means presence, not a working Code tab.

### Optional clone-and-setup launcher

The repository also contains small reviewed `install/clone.sh` and `install/clone.ps1` launchers. They clone the fixed project URL into a **new** directory and invoke the installer from that clone. Review both launcher and repository before permitting execution. Downloading a script does not grant permission to run it. While this repository is private, Git must already have authorized GitHub access; no token is embedded in a download command.

```sh
sh install/clone.sh "$HOME/find-me-a-job" --agent codex \
  --workspace "$HOME/career-workspace" --yes
```

```powershell
.\install\clone.ps1 -Checkout "$env:USERPROFILE\find-me-a-job" `
  -Workspace "$env:USERPROFILE\career-workspace" -Agent claude -Yes
```

Without `--yes` / `-Yes`, or with dry-run, no clone is made. An existing destination is refused; resume its `install/install` script instead. The launchers do not reset/pull existing repositories, install Git or log you in. GitHub Desktop is an optional manual graphical cloning route.

### Partially configured computers

| Existing setup | Next step |
| --- | --- |
| Desktop app, no agent CLI | Continue in desktop mode; the CLI is optional |
| CLI only, desktop selected | Install the desktop app; do not silently switch interfaces |
| Paid account, app missing | Install the chosen app, then sign in to the existing account |
| App installed, free/unknown account | Check the plan in the app; recommend paid access for sustained campaigns |
| Both installed | Use the selected interface and preserve the other installation |
| Setup interrupted | Rerun with the same workspace/provider; existing policy/data remain |

Account, login, subscription and quota are reported **unknown**, never inferred from software or cached credentials. Ask the person to confirm access in the selected app. Recommend a paid plan for ongoing campaign work; free limits are not a reliable budget, and paid plans are also limited. API funding is separate from a consumer subscription; never switch to API billing automatically. Provider references checked 21 October 2026: [OpenAI plans/limits](https://learn.chatgpt.com/docs/pricing), [Claude desktop requirements](https://code.claude.com/docs/en/desktop-quickstart). No credentials or payment are collected by this repository.


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
  --agent codex --interface desktop --yes --smoke
```

```powershell
.\install\install.ps1 `
  -Workspace "$env:USERPROFILE\career-workspace" `
  -Agent claude -Interface desktop -Yes -Smoke
```

Choose `codex` or `claude` independently of `desktop` or `cli`; desktop is the default. Existing installations/configuration are preserved. Desktop setup never requires the agent CLI; select `--interface cli` / `-Interface cli` for the previous command-line launch path. A separate Python environment defaults to the workspace path with `.venv` appended. Override with `--venv` / `-Venv` and select existing Python 3.11+ using `--python` / `-Python`. Workspace, environment and source must not overlap or traverse symbolic links/junctions. Existing non-environment directories are not overwritten. Re-running preserves an initialized workspace and its policy/feedback choice.

Resume with the workspace's configured agent. A conflicting agent choice stops setup before environment changes; use a separate workspace when choosing a different agent.

The installer installs this checkout into the private environment with its pinned Python dependencies, including pypdf for extraction/inspection. XeLaTeX compiles the templates and Poppler's `pdftoppm` renders them; `pdftotext` is not required. GitHub CLI is optional unless upstream GitHub feedback is enabled. This step uses package indexes unless `--offline` / `-Offline` is selected. Offline mode disables indexes, build isolation and installer downloads; the environment must already have the required build backend/dependencies from a trusted offline source. It is not a promise that a fresh machine can install without prepared packages.

`--smoke` / `-Smoke` asks doctor to actually compile a synthetic paired CV, extract/compare text and render pages. Basic doctor reports capability discovery. Neither can perform the person's every-page visual and independent review on their behalf. Missing required tools/checks remain handoffs rather than a false ready result.

## Clean-machine dependencies

`--install-dependencies` / `-InstallDependencies` is an **additional explicit permission** to install missing dependencies, used together with `--yes` / `-Yes`. It cannot be combined with offline mode. The bootstrap does not set agent permissions, alter global agent settings, sign in, change execution policy or silently escalate to administrator privileges.

- **macOS:** with user-installed Homebrew, missing Python, Git and Poppler can be installed from its formulas; missing XeLaTeX uses the BasicTeX cask (GitHub CLI is installed only for enabled feedback). The system installer may request confirmation. Reopen the terminal if PATH changes. BasicTeX may need template packages through its normal package manager; doctor/smoke exposes missing packages. Homebrew itself is not silently installed.
- **Linux:** supply Python 3.11+, its `venv` support, Git, a XeLaTeX-capable TeX distribution and Poppler through the machine's package manager. On Debian/Ubuntu typical packages are `python3 python3-venv git texlive-xetex texlive-latex-recommended texlive-fonts-recommended poppler-utils`; verify package names for your distribution. The script does not run `sudo` or modify package repositories. Missing system tools become explicit installation handoffs.
- **Native Windows:** the PowerShell path can install missing Python and Git (plus GitHub CLI for enabled feedback) through WinGet when explicitly permitted, using interactive package prompts. Install [official TeX Live](https://tug.org/texlive/windows.html). A reviewed Windows Poppler binary source is a separate handoff; the bootstrap does not fetch an unreviewed binary. Review private-directory Windows ACLs. This native path remains untested until run on a real Windows machine.
- **WSL:** use the POSIX installer inside the chosen distribution. Its Python/TeX environment and Windows browser integrations are separate capabilities. Do not report native Windows tests as WSL tests or assume Chrome/native desktop integration works across the boundary.

In CLI mode, missing chosen agents can be installed through the official native installers, downloaded then executed only under the explicit dependency flag. Review the provider's current installer and sign in yourself: [Codex](https://developers.openai.com/codex/cli), [Claude Code](https://code.claude.com/docs/en/setup). These installer channels can change; record the installed version. No bundled agent binary, account or subscription is included.

If a new binary is not on PATH, reopen the terminal and rerun. Do not overwrite existing configuration or enable unrestricted execution to make a capability check pass.

## Start the agent and complete onboarding

Desktop setup prints exact source/private-workspace/runtime paths and a copyable starter prompt, saved in the private workspace at `runtime/start-here.md`. Open the cloned source folder in the desktop app, paste that prompt, and grant the separate private-folder access through the app when requested. In CLI mode the bootstrap also prints `fmj run`; it launches the agent with private cwd, runtime PATH and explicit source/workspace context automatically. No global agent configuration is overwritten.

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
