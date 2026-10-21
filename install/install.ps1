# Review first. No profile, agent settings or execution-policy changes are made.
[CmdletBinding()]
param(
    [string]$Workspace = '',
    [ValidateSet('codex','claude')][string]$Agent,
    [ValidateSet('desktop','cli')][string]$Interface = 'desktop',
    [string]$DesktopApp = '',
    [string]$Venv = '',
    [string]$Python = 'python',
    [ValidateSet('self-hosted','managed')][string]$Mode = 'self-hosted',
    [string]$Operator = '',
    [string]$Language = 'en',
    [string]$Timezone = 'UTC',
    [ValidateSet('enabled','disabled','unset')][string]$Feedback = 'unset',
    [string]$Upstream = '',
    [switch]$Yes, [switch]$InstallDependencies, [switch]$Offline,
    [switch]$DryRun, [switch]$Check, [switch]$Smoke
)
$ErrorActionPreference = 'Stop'
$Source = Split-Path -Parent $PSScriptRoot
function Invoke-Checked([string]$Command, [string[]]$Arguments) {
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed: $Command (exit $LASTEXITCODE). Correct the reported blocker and rerun." }
}
function Refresh-Path {
    $env:PATH = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User') + ';' + $env:PATH
}
function Find-Desktop {
    if ($DesktopApp) {
        if (Test-Path -LiteralPath $DesktopApp) { return $DesktopApp }; return $null
    }
    $PackageNames = if ($Agent -eq 'codex') { @('OpenAI.Codex','OpenAI.ChatGPT-Desktop') } else { @('Anthropic.Claude') }
    if (Get-Command Get-AppxPackage -ErrorAction SilentlyContinue) {
        foreach ($Name in $PackageNames) {
            $Package = Get-AppxPackage -Name $Name | Select-Object -First 1
            if ($Package) { return $Package.InstallLocation }
        }
    }
    if ($Agent -eq 'claude') {
        foreach ($Candidate in @("$env:LOCALAPPDATA\AnthropicClaude\claude.exe", "$env:LOCALAPPDATA\Programs\Claude\Claude.exe")) {
            if (Test-Path -LiteralPath $Candidate) { return $Candidate }
        }
    }
    return $null
}
if ($Offline -and $InstallDependencies) { throw 'Offline cannot install external dependencies.' }
if ($Feedback -ne 'unset' -and -not $Upstream) { throw 'A feedback choice requires -Upstream OWNER/REPO.' }
if ($Workspace -and -not $Venv) { $Venv = "$Workspace.venv" }
Write-Output "Source: $Source"
Write-Output "Plan: agent=$Agent; workspace=$Workspace; environment=$Venv; feedback=$Feedback"
Write-Output "Interface: $Interface"
Write-Output 'Account/login/plan/quota: unknown. Confirm in the app; installation does not prove service access.'
Write-Output 'For sustained campaigns choose a paid agent plan or explicitly budgeted API access. Free allowances are not a reliable campaign budget; paid plans also have limits.'
Write-Output 'Native Windows and WSL are separate targets. Existing configuration is preserved.'
if ($DryRun) { exit 0 }
if ($Check) {
    $Missing = $false
    foreach ($Tool in @($Python,'git','xelatex','pdftoppm')) {
        if (Get-Command $Tool -ErrorAction SilentlyContinue) { Write-Output "${Tool}: present" }
        else { Write-Output "${Tool}: missing"; $Missing = $true }
    }
    if ($Agent) {
        if (Get-Command $Agent -ErrorAction SilentlyContinue) { Write-Output "${Agent}: present" }
        else { Write-Output "${Agent}: missing"; if ($Interface -eq 'cli') { $Missing = $true } }
        $DetectedDesktop = Find-Desktop
        if ($DetectedDesktop) { Write-Output "desktop: present ($DetectedDesktop; coding features unverified)" }
        else { Write-Output 'desktop: not detected (use -DesktopApp for a custom location)'; if ($Interface -eq 'desktop') { $Missing = $true } }
    }
    if ($Feedback -eq 'enabled' -and -not (Get-Command gh -ErrorAction SilentlyContinue)) {
        Write-Output 'gh: missing (feedback enabled)'; $Missing = $true
    } else { Write-Output 'gh: optional unless GitHub feedback is enabled' }
    Write-Output 'pypdf: installed into the private Python environment during setup'
    Write-Output 'Presence is not capability verification. Browser/upload/mail need interactive checks.' 
    if ($Missing) { exit 2 }; exit 0
}
if (-not $Yes) {
    Write-Output 'Review docs/install.md, choose an agent and external workspace, then add -Yes.'
    exit 0
}
if (-not $Workspace -or -not $Agent) { throw '-Yes requires -Workspace and -Agent.' }
if ($Mode -eq 'managed' -and -not $Operator) { throw 'Managed mode requires -Operator.' }
if (-not (Get-Command $Python -ErrorAction SilentlyContinue)) {
    if (-not $InstallDependencies -or -not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw 'Install Python 3.11+ from https://www.python.org/downloads/windows/ and select it with -Python; then rerun.'
    }
    Write-Output 'Installing official Python through WinGet; review its package prompts.'
    Invoke-Checked 'winget' @('install','--exact','--id','Python.Python.3.12','--interactive')
    Refresh-Path
    if (-not (Get-Command $Python -ErrorAction SilentlyContinue)) { throw 'Open a new PowerShell after Python installation and rerun.' }
}
Invoke-Checked $Python @('-c','import sys; assert sys.version_info >= (3,11), "Python 3.11+ required"')
$PathCheck = @'
from pathlib import Path
import json, sys
source = Path(sys.argv[1]).resolve()
paths = [Path(value).expanduser() for value in sys.argv[2:]]
for path in paths:
    for part in [path, *path.parents]:
        if part.is_symlink() or (part.exists() and getattr(part.lstat(), "st_file_attributes", 0) & 0x400):
            raise SystemExit("Private destinations must not traverse links or junctions")
roots = [path.resolve() for path in paths]
for root in roots:
    if root == Path(root.anchor) or root == source or root in source.parents or source in root.parents:
        raise SystemExit("Private destinations and source checkout must not overlap")
if roots[0] == roots[1] or roots[0] in roots[1].parents or roots[1] in roots[0].parents:
    raise SystemExit("Workspace and environment must be separate sibling locations")
print(json.dumps([str(root) for root in roots]))
'@
$NormalizedPaths = Invoke-Checked $Python @('-c',$PathCheck,$Source,$Workspace,$Venv) | ConvertFrom-Json
$Workspace = $NormalizedPaths[0]
$Venv = $NormalizedPaths[1]
$ExistingConfiguration = Join-Path $Workspace 'workspace.json'
if (Test-Path $ExistingConfiguration) {
    $ConfiguredAgent = (Get-Content -LiteralPath $ExistingConfiguration -Raw | ConvertFrom-Json).agent
    if ($ConfiguredAgent -notin @('codex','claude')) { throw 'Existing workspace has no valid configured agent; inspect it rather than overwriting it.' }
    if ($ConfiguredAgent -ne $Agent) { throw 'Requested agent differs from existing workspace configuration; rerun with its configured agent or choose a separate workspace.' }
}
if ($InstallDependencies) {
    $Packages = @(@{ Command = 'git'; Id = 'Git.Git' })
    if ($Feedback -eq 'enabled') { $Packages += @{ Command = 'gh'; Id = 'GitHub.cli' } }
    foreach ($Package in $Packages) {
        if (-not (Get-Command $Package.Command -ErrorAction SilentlyContinue)) {
            if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { throw "Install $($Package.Command) from its official source and rerun." }
            Invoke-Checked 'winget' @('install','--exact','--id',$Package.Id,'--interactive')
        }
    }
    Refresh-Path
}
$Temporary = $null
try {
    if ($Interface -eq 'desktop' -and -not (Find-Desktop)) {
        $AppUrl = if ($Agent -eq 'codex') { 'https://learn.chatgpt.com/docs/windows/windows-app' } else { 'https://code.claude.com/docs/en/desktop-quickstart' }
        if (-not $InstallDependencies -or -not (Get-Command winget -ErrorAction SilentlyContinue)) {
            throw "Desktop application not detected. Install from $AppUrl and rerun, or use -InstallDependencies with WinGet. CLI is separate: -Interface cli."
        }
        if ($Agent -eq 'codex') {
            Invoke-Checked 'winget' @('install','--exact','--id','9PLM9XGG6VKS','--source','msstore','--interactive')
        } else {
            Invoke-Checked 'winget' @('install','--exact','--id','Anthropic.Claude','--source','winget','--interactive')
        }
        if (-not (Find-Desktop)) { throw "App installation not detected. Open the official app, or supply -DesktopApp, then rerun: $AppUrl" }
    }
    if ($Interface -eq 'cli' -and -not (Get-Command $Agent -ErrorAction SilentlyContinue)) {
        if (-not $InstallDependencies) { throw 'Selected agent missing. Install officially or rerun with -InstallDependencies.' }
        $Temporary = Join-Path ([IO.Path]::GetTempPath()) ('fmj-bootstrap-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $Temporary | Out-Null
        $Url = if ($Agent -eq 'codex') { 'https://chatgpt.com/codex/install.ps1' } else { 'https://claude.ai/install.ps1' }
        $Installer = Join-Path $Temporary 'official-agent.ps1'
        Write-Output "Downloading and running official agent installer: $Url"
        Invoke-WebRequest -Uri $Url -OutFile $Installer
        & $Installer
        if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw 'Official agent installer failed.' }
        Refresh-Path
        if (-not (Get-Command $Agent -ErrorAction SilentlyContinue)) { throw 'Open a new PowerShell, verify the agent on PATH and rerun.' }
    }
    if (Test-Path $Venv) {
        if (-not (Test-Path (Join-Path $Venv 'pyvenv.cfg'))) { throw 'Environment destination exists but is not a Python virtual environment.' }
    } else { Invoke-Checked $Python @('-m','venv',$Venv) }
    $EnvPython = Join-Path $Venv 'Scripts/python.exe'
    if (-not (Test-Path $EnvPython)) { throw 'Environment Python unavailable; select a native Windows environment.' }
    $PipArguments = @('-m','pip','install')
    if ($Offline) { $PipArguments += @('--no-index','--no-build-isolation') }
    Invoke-Checked $EnvPython ($PipArguments + @('-e',$Source))
    if (-not (Test-Path (Join-Path $Workspace 'workspace.json'))) {
        $InitArguments = @('-m','fmj','init','--workspace',$Workspace,'--mode',$Mode,'--agent',$Agent,'--language',$Language,'--timezone',$Timezone,'--feedback',$Feedback)
        if ($Operator) { $InitArguments += @('--operator',$Operator) }
        if ($Upstream) { $InitArguments += @('--upstream',$Upstream) }
        Invoke-Checked $EnvPython $InitArguments
    } else { Write-Output 'Resuming existing workspace; identity, policy and feedback choice are preserved.' }
    $DoctorArguments = @('-m','fmj','doctor','--workspace',$Workspace)
    if ($Smoke) { $DoctorArguments += '--smoke' }
    Invoke-Checked $EnvPython $DoctorArguments
    Invoke-Checked $EnvPython @('-m','fmj.setup','--workspace',$Workspace,'--source',$Source,'--interface',$Interface)
    if ($Interface -eq 'cli') { Write-Output "Next: & '$EnvPython' -m fmj run --workspace '$Workspace'" }
    Write-Output 'Sign in yourself. Review Windows ACLs, scoped permissions and browser/upload/mail capabilities.'
    if (-not (Get-Command xelatex -ErrorAction SilentlyContinue)) {
        Write-Output 'TeX handoff: install official TeX Live from https://tug.org/texlive/windows.html and rerun doctor.'
    }
    if (-not (Get-Command pdftoppm -ErrorAction SilentlyContinue)) {
        Write-Output 'PDF renderer handoff: choose a reviewed Windows Poppler distribution; no unreviewed binary is installed automatically.'
    }
} finally {
    if ($Temporary -and (Test-Path $Temporary)) { Remove-Item -LiteralPath $Temporary -Recurse -Force }
}
