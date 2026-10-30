#!/usr/bin/env sh
# Inspect first. Writes require --yes; system/agent installs also require
# --install-dependencies. Never changes agent permissions or user configuration.
set -eu
umask 077
SOURCE=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
WORKSPACE='' AGENT='' VENV='' PYTHON='python3' MODE='self-hosted'
OPERATOR='' LANGUAGE='en' TIMEZONE='UTC' FEEDBACK='unset' UPSTREAM=''
INTERFACE='desktop' DESKTOP_APP=''
YES=0 DEPS=0 OFFLINE=0 DRY=0 CHECK=0 SMOKE=0
usage() {
    cat <<'EOF'
Find Me a Job: inspectable local bootstrap
  sh install/install.sh --workspace PATH --agent codex|claude [options]
  --interface desktop|cli   Desktop by default; CLI is an explicit alternative
  --desktop-app PATH        Existing desktop application in a custom location
  --yes                    Create private environment/workspace after reviewing plan
  --install-dependencies   Also install missing official agent/macOS dependencies
  --venv PATH              External Python environment (default: WORKSPACE.venv)
  --python COMMAND         Existing Python 3.11+ executable (default: python3)
  --mode self-hosted|managed --operator ID (required for managed)
  --language CODE --timezone IANA_ZONE
  --feedback enabled|disabled|unset --upstream OWNER/REPO
  --offline                Disable installer downloads and pip indexes
  --dry-run                Print plan only; no network or filesystem writes
  --check                  Read-only dependency report; exit 2 when incomplete
  --smoke                  Run actual synthetic TeX/PDF checks after setup
  --help                   Show help
Without --yes the installer prints a plan and makes no changes.
EOF
}
fail() { printf '%s\n' "$*" >&2; exit 2; }
while [ "$#" -gt 0 ]; do
    case "$1" in
        --workspace|--agent|--venv|--python|--mode|--operator|--language|--timezone|--feedback|--upstream|--interface|--desktop-app)
            [ "$#" -ge 2 ] && [ -n "$2" ] || fail "Missing value for $1"
            case "$1" in
                --workspace) WORKSPACE=$2;; --agent) AGENT=$2;; --venv) VENV=$2;;
                --python) PYTHON=$2;; --mode) MODE=$2;; --operator) OPERATOR=$2;;
                --language) LANGUAGE=$2;; --timezone) TIMEZONE=$2;;
                --feedback) FEEDBACK=$2;; --upstream) UPSTREAM=$2;;
                --interface) INTERFACE=$2;; --desktop-app) DESKTOP_APP=$2;;
            esac
            shift 2;;
        --yes) YES=1; shift;; --install-dependencies) DEPS=1; shift;;
        --offline) OFFLINE=1; shift;; --dry-run) DRY=1; shift;; --check) CHECK=1; shift;;
        --smoke) SMOKE=1; shift;; --help|-h) usage; exit 0;; *) fail "Unknown option: $1";;
    esac
done
case "$AGENT" in ''|codex|claude) ;; *) fail 'Choose --agent codex or claude';; esac
case "$INTERFACE" in desktop|cli) ;; *) fail 'Choose --interface desktop or cli';; esac
case "$MODE" in self-hosted|managed) ;; *) fail 'Invalid mode';; esac
case "$FEEDBACK" in enabled|disabled|unset) ;; *) fail 'Invalid feedback choice';; esac
[ "$FEEDBACK" = unset ] || [ -n "$UPSTREAM" ] || fail 'A feedback choice requires --upstream OWNER/REPO'
[ "$OFFLINE" -eq 0 ] || [ "$DEPS" -eq 0 ] || fail '--offline cannot install external dependencies'
[ -n "$WORKSPACE" ] && VENV=${VENV:-"$WORKSPACE.venv"}
PLATFORM=$(uname -s)
find_desktop() {
    if [ -n "$DESKTOP_APP" ]; then [ -e "$DESKTOP_APP" ]; return; fi
    [ "$PLATFORM" = Darwin ] || return 1
    if [ "$AGENT" = codex ]; then APP_NAMES='Codex ChatGPT'; else APP_NAMES='Claude'; fi
    for app_name in $APP_NAMES; do
        for app_root in /Applications "$HOME/Applications"; do
            if [ -d "$app_root/$app_name.app" ]; then DESKTOP_APP="$app_root/$app_name.app"; return 0; fi
        done
    done
    return 1
}
printf 'Source: %s\nPlatform: %s (WSL and native Windows are separate)\n' "$SOURCE" "$PLATFORM"
printf 'Plan: agent=%s; workspace=%s; environment=%s; feedback=%s\n' "${AGENT:-not selected}" "${WORKSPACE:-not selected}" "${VENV:-not selected}" "$FEEDBACK"
printf 'Interface: %s\n' "$INTERFACE"
printf '%s\n' 'Account/login/plan/quota: unknown. Confirm in the app; installed software does not prove service access.'
printf '%s\n' 'For sustained campaigns, choose a paid agent plan or explicitly budgeted API access. Free allowances are not a reliable campaign budget; paid plans also have limits.'
printf '%s\n' 'Preserve existing agent configuration. Browser/upload/mail require separate interactive checks.'
if [ "$DRY" -eq 1 ]; then exit 0; fi
if [ "$CHECK" -eq 1 ]; then
    MISSING=0
    for tool in "$PYTHON" git xelatex pdftoppm; do
        if command -v "$tool" >/dev/null 2>&1; then printf '%s: present\n' "$tool";
        else printf '%s: missing\n' "$tool"; MISSING=2; fi
    done
    if [ -n "$AGENT" ]; then
        if command -v "$AGENT" >/dev/null 2>&1; then printf '%s: present\n' "$AGENT";
        else printf '%s: missing\n' "$AGENT"; [ "$INTERFACE" != cli ] || MISSING=2; fi
        if find_desktop; then printf 'desktop: present (%s; coding features unverified)\n' "$DESKTOP_APP";
        else printf '%s\n' 'desktop: not detected (use --desktop-app for a custom location)'; [ "$INTERFACE" != desktop ] || MISSING=2; fi
    fi
    if [ "$FEEDBACK" = enabled ]; then
        if command -v gh >/dev/null 2>&1; then printf '%s\n' 'gh: present (feedback enabled)';
        else printf '%s\n' 'gh: missing (feedback enabled)'; MISSING=2; fi
    else printf '%s\n' 'gh: optional (needed only for enabled GitHub feedback)'; fi
    if command -v "$PYTHON" >/dev/null 2>&1; then
        if "$PYTHON" -B -c 'import pypdf' >/dev/null 2>&1; then printf '%s\n' 'pypdf: present in selected Python';
        else printf '%s\n' 'pypdf: installed into private environment during setup'; fi
    fi
    printf '%s\n' 'Presence is not capability verification. Run fmj doctor after setup.' 
    exit "$MISSING"
fi
if [ "$YES" -eq 0 ]; then
    printf '%s\n' 'Review docs/install.md, choose an agent and external workspace, then add --yes.'
    exit 0
fi
[ -n "$WORKSPACE" ] && [ -n "$AGENT" ] || fail '--yes requires --workspace and --agent'
[ "$MODE" != managed ] || [ -n "$OPERATOR" ] || fail 'Managed mode requires --operator'
PATH="$HOME/.local/bin:$PATH"
export PATH
NEED_BREW=0
if [ "$DEPS" -eq 1 ] && [ "$PLATFORM" = Darwin ]; then
    PATH="/Library/TeX/texbin:$PATH"
    for tool in git pdftoppm xelatex; do
        command -v "$tool" >/dev/null 2>&1 || NEED_BREW=1
    done
    if ! command -v "$PYTHON" >/dev/null 2>&1 || ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' >/dev/null 2>&1; then NEED_BREW=1; fi
    if [ "$FEEDBACK" = enabled ] && ! command -v gh >/dev/null 2>&1; then NEED_BREW=1; fi
    if [ "$INTERFACE" = desktop ] && ! find_desktop; then NEED_BREW=1; fi
fi
if [ "$NEED_BREW" -eq 1 ]; then
    if ! command -v brew >/dev/null 2>&1; then
        for brew_prefix in /opt/homebrew /usr/local; do
            if [ -x "$brew_prefix/bin/brew" ]; then PATH="$brew_prefix/bin:$PATH"; break; fi
        done
    fi
    if ! command -v brew >/dev/null 2>&1; then
        printf '%s\n' 'Downloading and running the official Homebrew installer; approve its system prompts.'
        TEMP_INSTALL=$(mktemp)
        trap 'rm -f "$TEMP_INSTALL"' EXIT HUP INT TERM
        curl -fLsS --proto '=https' --proto-redir '=https' https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh -o "$TEMP_INSTALL"
        /bin/bash "$TEMP_INSTALL"
        rm -f "$TEMP_INSTALL"
        trap - EXIT HUP INT TERM
        for brew_prefix in /opt/homebrew /usr/local; do
            if [ -x "$brew_prefix/bin/brew" ]; then PATH="$brew_prefix/bin:$PATH"; break; fi
        done
    fi
    command -v brew >/dev/null 2>&1 || fail 'Homebrew installation did not complete; check its output and retry.'
    eval "$(brew shellenv)"
    export PATH
    if ! command -v "$PYTHON" >/dev/null 2>&1 || ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' >/dev/null 2>&1; then
        printf '%s\n' 'Installing official Homebrew Python formula.'
        brew install python@3.12
        PYTHON="$(brew --prefix python@3.12)/bin/python3.12"
    fi

fi
command -v "$PYTHON" >/dev/null 2>&1 || fail 'Install Python 3.11+ from https://www.python.org/downloads/ (Linux: python3 + python3-venv), then rerun.'
"$PYTHON" -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ required"' || fail 'Select a Python 3.11+ executable with --python'
# Validate all private destinations before any private directory creation.
NORMALIZED_PATHS=$("$PYTHON" - "$SOURCE" "$WORKSPACE" "$VENV" <<'PY'
from pathlib import Path
import json, sys
source = Path(sys.argv[1]).resolve()
paths = [Path(value).expanduser() for value in sys.argv[2:]]
for path in paths:
    if any(part.is_symlink() for part in [path, *path.parents]):
        raise SystemExit('Private destinations must not traverse symbolic links')
roots = [path.resolve() for path in paths]
for root in roots:
    if root == Path(root.anchor) or root == source or root in source.parents or source in root.parents:
        raise SystemExit('Private destinations and source checkout must not overlap')
if roots[0] == roots[1] or roots[0] in roots[1].parents or roots[1] in roots[0].parents:
    raise SystemExit('Workspace and environment must be separate sibling locations')
print(json.dumps([str(root) for root in roots]))
PY
)
WORKSPACE=$("$PYTHON" -c 'import json,sys; print(json.loads(sys.argv[1])[0])' "$NORMALIZED_PATHS")
VENV=$("$PYTHON" -c 'import json,sys; print(json.loads(sys.argv[1])[1])' "$NORMALIZED_PATHS")
"$PYTHON" - "$WORKSPACE" "$AGENT" <<'PY'
from pathlib import Path
import json, sys
config = Path(sys.argv[1]) / 'workspace.json'
if config.exists():
    with config.open(encoding='utf-8') as stream:
        configured = json.load(stream).get('agent')
    if configured not in {'codex', 'claude'}:
        raise SystemExit('Existing workspace has no valid configured agent; inspect it rather than overwriting it')
    if configured != sys.argv[2]:
        raise SystemExit('Requested agent differs from existing workspace configuration; rerun with its configured agent or choose a separate workspace')
PY
if [ "$DEPS" -eq 1 ] && [ "$PLATFORM" = Darwin ]; then
    command -v git >/dev/null 2>&1 || brew install git
    if [ "$FEEDBACK" = enabled ]; then command -v gh >/dev/null 2>&1 || brew install gh; fi
    if ! command -v pdftoppm >/dev/null 2>&1; then brew install poppler; fi
    if ! command -v xelatex >/dev/null 2>&1; then
        printf '%s\n' 'Installing BasicTeX cask; the system installer may request your confirmation.'
        brew install --cask basictex
    fi
fi
if [ "$INTERFACE" = desktop ] && ! find_desktop; then
    if [ "$AGENT" = codex ]; then APP_URL='https://learn.chatgpt.com/docs/app'; CASK='codex-app';
    else APP_URL='https://code.claude.com/docs/en/desktop-quickstart'; CASK='claude'; fi
    if [ "$DEPS" -eq 1 ] && [ "$PLATFORM" = Darwin ]; then
        brew install --cask "$CASK"
        find_desktop || fail "Desktop installation not detected. Follow $APP_URL or set --desktop-app, then rerun."
    else
        fail "Desktop application not detected. Install from $APP_URL and rerun; macOS Homebrew installation is available with --install-dependencies. CLI is separate: --interface cli."
    fi
fi
if [ "$INTERFACE" = cli ] && ! command -v "$AGENT" >/dev/null 2>&1; then
    [ "$DEPS" -eq 1 ] || fail 'Selected agent missing. Install it from its official source or rerun with --install-dependencies.'
    command -v curl >/dev/null 2>&1 || fail 'Install curl, then rerun.'
    TEMP_INSTALL=$(mktemp)
    trap 'rm -f "$TEMP_INSTALL"' EXIT HUP INT TERM
    if [ "$AGENT" = codex ]; then URL='https://chatgpt.com/codex/install.sh'; RUNNER=sh;
    else URL='https://claude.ai/install.sh'; RUNNER=bash; fi
    printf 'Downloading and executing official agent installer: %s\n' "$URL"
    curl -fsSL "$URL" -o "$TEMP_INSTALL"
    "$RUNNER" "$TEMP_INSTALL"
    rm -f "$TEMP_INSTALL"
    trap - EXIT HUP INT TERM
    command -v "$AGENT" >/dev/null 2>&1 || fail 'Agent installed but not on PATH. Open a new terminal, verify the agent, and rerun.'
fi
if [ -d "$VENV" ]; then
    [ -f "$VENV/pyvenv.cfg" ] || fail 'Environment destination exists but is not a Python virtual environment'
else
    "$PYTHON" -m venv "$VENV" || fail 'Could not create environment; install the OS python3-venv package if needed'
fi
ENV_PYTHON="$VENV/bin/python"
[ -x "$ENV_PYTHON" ] || fail 'Environment Python is unavailable'
if [ "$OFFLINE" -eq 1 ]; then
    "$ENV_PYTHON" -m pip install --no-index --no-build-isolation -e "$SOURCE"
else
    "$ENV_PYTHON" -m pip install -e "$SOURCE"
fi
if [ ! -f "$WORKSPACE/workspace.json" ]; then
    set -- "$ENV_PYTHON" -m fmj init --workspace "$WORKSPACE" --mode "$MODE" --agent "$AGENT" --language "$LANGUAGE" --timezone "$TIMEZONE" --feedback "$FEEDBACK"
    [ -z "$OPERATOR" ] || set -- "$@" --operator "$OPERATOR"
    [ -z "$UPSTREAM" ] || set -- "$@" --upstream "$UPSTREAM"
    "$@"
else
    printf '%s\n' 'Resuming existing workspace; existing identity, policy and feedback choice are preserved.'
fi
if [ "$SMOKE" -eq 1 ]; then
    "$ENV_PYTHON" -m fmj doctor --workspace "$WORKSPACE" --smoke
else
    "$ENV_PYTHON" -m fmj doctor --workspace "$WORKSPACE"
fi
"$ENV_PYTHON" -m fmj.setup --workspace "$WORKSPACE" --source "$SOURCE" --interface "$INTERFACE"
if [ "$INTERFACE" = cli ]; then printf 'Next: "%s" -m fmj run --workspace "%s"\n' "$ENV_PYTHON" "$WORKSPACE"; fi
printf '%s\n' 'Sign in yourself. Confirm scoped permissions and browser/upload/mail capabilities with the agent.'
