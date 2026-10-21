# Support and verification matrix

Evidence date: 2026-10-21. A platform name expresses an intended setup path, not certification of every integration. Provider account/region restrictions, extension versions, browser profiles and permissions can change. Re-run doctor and interactive checks on the actual computer.

| Environment | Bootstrap/core evidence | Agent launch path | Browser/upload/mail evidence |
| --- | --- | --- | --- |
| macOS | POSIX contracts passed with inert command shims; fresh external venv bootstrap and actual paired PDF smoke passed on an existing macOS toolchain (Python 3.14.3, pypdf 6.21.1); clean OS install untested | Codex and Claude CLI command contracts implemented; authenticated clean-machine runs not certified by shim tests | Requires separate installed host integration and actual checks; not supplied by bootstrap |
| Linux native | POSIX implementation; clean Linux machine execution untested | Official native installers selected explicitly; authenticated launch untested | Depends on selected integration; native desktop control not assumed |
| Windows native | PowerShell reviewed and static contract checked; actual execution untested when `pwsh`/Windows unavailable | Native installation/launch path implemented; clean Windows execution untested | Separate native integration/renderer/ACL handoffs; untested |
| WSL | POSIX path intended; real WSL execution untested | Separate Linux environment; do not infer Windows profile access | Separate check required; not equivalent to native Windows |

A skipped PowerShell test is a skip. Inert installer shims validate argument flow, path boundaries, offline flags and preservation of existing state; they do not prove downloads, system packages, provider authentication or native Windows operation. CI can add actual OS results after execution, without changing unknowns into passes.

## Capability states

Use `verified`, `missing`, `unsupported` or `untested` with version, date and evidence. Keep `ready_for_intake`, `ready_for_documents` and outbound eligibility distinct. Missing browser control need not prevent a narrative interview or local document preparation; it does prevent claiming application automation is ready.

- **Documents:** selected TeX engine and template packages/fonts, actual compile, selectable extraction, PDF internal inspection and renderer. Human/agent visual review covers every page; independent content/visual review is separate.
- **Browser:** navigation, intended profile/account, field changes and actual permitted test upload are separate checks.
- **Mailbox:** authorized access and permission to send are separate. No real message is sent by an installation check.
- **Native desktop:** optional, host-specific and never inferred from agent CLI presence.
- **Managed clients:** per-client workspace/browser/channel bindings and permissions. Folder organization is not an OS security sandbox.

## Readiness limits

The repository does not promise universal ATS acceptance, unbounded platform automation, statistical-watermark removal or hiring outcomes. Tool-required human actions remain required. Public readiness also requires rights/history/payload review, an explicit release decision and a consenting real-participant pilot; synthetic tests and this document do not satisfy those gates.

Official capability references: [Codex CLI](https://developers.openai.com/codex/cli), [Codex Chrome extension](https://learn.chatgpt.com/docs/chrome-extension), [Claude setup](https://code.claude.com/docs/en/setup), [Claude Chrome](https://code.claude.com/docs/en/chrome). Check their current availability rather than relying on this date indefinitely.

## Desktop setup coverage

Desktop is the installer's default interface; CLI requires explicit selection. macOS discovery checks Codex/ChatGPT or Claude application bundles; Windows checks known app registrations/paths. A custom app path can be supplied. Desktop presence never proves coding features, login, subscription, quota or permissions. Desktop mode does not install or require the agent CLI. Existing CLI-only integrations remain available with the explicit CLI selection.

Native desktop install routes are implemented for macOS Homebrew and Windows WinGet; actual fresh app installation and an authenticated first GUI session remain untested. Linux/WSL desktop provisioning is a provider-specific manual handoff. Automated fixture checks cover interface separation and state preservation, not provider GUI operation. The landing page and README also offer graphical GitHub Desktop cloning and a copyable desktop-agent setup request.
