# Optional reviewed clone-and-setup entry point. Never overwrites a destination.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Checkout,
    [string]$Workspace = '',
    [ValidateSet('codex','claude')][string]$Agent,
    [ValidateSet('desktop','cli')][string]$Interface = 'desktop',
    [switch]$Yes, [switch]$DryRun, [switch]$InstallDependencies
)
$ErrorActionPreference = 'Stop'
Write-Output "Clone https://github.com/BlehMaks/find-me-a-job.git into $Checkout, then run its reviewed installer."
if ($DryRun -or -not $Yes) { exit 0 }
if (Test-Path -LiteralPath $Checkout) { throw 'Checkout already exists; resume install/install.ps1 there. Nothing overwritten.' }
if (-not $Workspace -or -not $Agent) { throw 'Choose -Workspace and -Agent before cloning.' }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Install Git or clone with GitHub Desktop first.' }
& git clone -- 'https://github.com/BlehMaks/find-me-a-job.git' $Checkout
if ($LASTEXITCODE -ne 0) { throw 'Clone failed; check GitHub access/network. No installer was run.' }
$Arguments = @{ Workspace = $Workspace; Agent = $Agent; Interface = $Interface; Yes = $true; InstallDependencies = $InstallDependencies }
& (Join-Path $Checkout 'install/install.ps1') @Arguments
if ($LASTEXITCODE) { exit $LASTEXITCODE }
