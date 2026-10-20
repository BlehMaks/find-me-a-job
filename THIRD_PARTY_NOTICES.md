# Third-party components and external dependencies

Reviewed 2026-10-20. `dependencies.lock.json` identifies bundled files, exact revisions/hashes, externally installed tools and optional services separately. This inventory is not a choice of license for the original product or a warranty of legal clearance. Check selected versions and distributor notices before a release.

## Bundled Humanizer

`skills/humanizer/SKILL.md` and `skills/humanizer/LICENSE` are unmodified from [blader/humanizer](https://github.com/blader/humanizer), revision `8c307f367c91bd974002f10f2be2965d642c13df`. Copyright (c) 2025 Siqi Chen. MIT permission and warranty notice are retained in the adjacent LICENSE, which must travel with redistributed copies. The upstream skill references Wikipedia's writing-pattern guide; this package does not copy the Wikipedia article itself or claim human-authorship detection. Product-specific fact-preserving editorial orchestration is independently written.

## Installed separately

- **pypdf 6.21.1**: BSD-3-Clause; [upstream license](https://github.com/py-pdf/pypdf/blob/main/LICENSE). Installed into a separate Python environment, not vendored. Its installed distribution carries the copyright, conditions and disclaimer; redistribution of that distribution must preserve them. Extraction/structure inspection is not page rendering.
- **tzdata 2026.5**: Apache-2.0 with upstream IANA data notices; [source](https://github.com/python/tzdata). Separately installed on native Windows for Python's IANA timezone lookup. Preserve the installed distribution's license and component notices if redistributing it; no timezone files are bundled here.
- **Python**: PSF licensing and its component notices. **Git**: GPL-2.0. **GitHub CLI**: MIT. Use official distributions and preserve their notices; these binaries are not bundled here.
- **TeX distribution/packages/fonts**: multiple component licenses; install externally from the chosen distribution, recording actual engine/package versions. No complete TeX bundle or fonts are shipped here.
- **Poppler utilities**: GPL-family project/component terms. External package installation only; no selected binary is redistributed here. Review the chosen distributor's licenses/notices before repackaging.
- **Codex / Claude Code and browser/native integrations**: external provider tools and services. Installation or linking does not sublicense them. Accounts, subscriptions, platform availability and provider/tool permissions remain separate. Use the current official sources in `adapters/`.

## Optional, not bundled

Telegram is a hosted external API used only after managed-mode configuration and disclosure. No Telegram library, hosted operator service, account access or billing system is included by installing the repository. Optional provenance/statistical services require their own commercial-use rights and data-transfer review; none is selected or enabled by default.

Upstream Harness² uses Apache-2.0, but this repository does not bundle its engine, dependencies or local subagent transport. Retrospective study instructions do not imply executable sandboxing or permission to redistribute an adapter. A later optional installation must pin and review all selected components.

Personalized local resume/provenance/browser instructions and proprietary host skills were not copied. The generic experience/document/application workflows are independently authored from product requirements; only rights-cleared Humanizer is vendored. Spec Kit is a development tool, not an end-user dependency or public planning payload.
