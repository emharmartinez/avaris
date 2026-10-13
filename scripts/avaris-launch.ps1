# Opens the Avaris desktop app (the installed Chrome PWA), first starting `avaris serve` in WSL
# when the server is not answering. Run from Windows:
#   powershell -ExecutionPolicy Bypass -File \\wsl.localhost\Ubuntu\home\<you>\avaris\scripts\avaris-launch.ps1
#   ... -Install  adds "Avaris Launcher" to the Start menu (pin it to the taskbar from there)
#   ... -Stop     stops a server this launcher started
# The distro and repo default to where this script lives; data/serve.log holds the latest
# server run
param(
  [string]$Distro,
  [string]$Repo,
  [int]$Port = 8000,
  [int]$TimeoutSec = 120,
  [switch]$Install,
  [switch]$Stop
)
$ErrorActionPreference = "Stop"

if ($PSScriptRoot -match '^\\\\wsl(?:\.localhost|\$)\\([^\\]+)\\(.+)\\scripts$') {
  if (-not $Distro) { $Distro = $Matches[1] }
  if (-not $Repo) { $Repo = "/" + ($Matches[2] -replace '\\', '/') }
}
if (-not $Distro) { $Distro = "Ubuntu" }
if (-not $Repo) { $Repo = "~/avaris" }

$Url = "http://127.0.0.1:$Port/"
$Programs = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$AppShortcut = Join-Path $Programs "Chrome Apps\Avaris.lnk"  # created by Chrome's install
$Shell = New-Object -ComObject WScript.Shell

function Show-Error([string]$Message) {
  [void]$Shell.Popup($Message, 0, "Avaris", 16)
  exit 1
}

function Test-Server {
  try {
    (Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 "${Url}api/health").StatusCode -eq 200
  } catch {
    $false
  }
}

function Invoke-Wsl([string]$Command) {
  # One bash -lc argument: the login shell puts uv (~/.local/bin) on PATH
  & wsl.exe -d $Distro --exec bash -lc "cd $Repo && $Command"
}

if ($Install) {
  $link = $Shell.CreateShortcut((Join-Path $Programs "Avaris Launcher.lnk"))
  $link.TargetPath = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
  $link.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$PSCommandPath`""
  $link.WindowStyle = 7  # minimized, so the console barely flashes
  if (Test-Path $AppShortcut) { $link.IconLocation = $Shell.CreateShortcut($AppShortcut).IconLocation }
  $link.Description = "Start the Avaris server if needed, then open the app"
  $link.Save()
  Write-Output "Added 'Avaris Launcher' to the Start menu. Right-click it there to pin it."
  exit 0
}

if ($Stop) {
  Invoke-Wsl 'test -f data/serve.pid && kill $(cat data/serve.pid) && rm -f data/serve.pid'
  exit $LASTEXITCODE
}

if (-not (Test-Server)) {
  # exec keeps the pid for -Stop; the hidden wsl.exe lives as long as the server, which also
  # keeps WSL running
  $serve = "cd $Repo && mkdir -p data && echo `$`$ > data/serve.pid && exec uv run avaris serve --port $Port > data/serve.log 2>&1"
  $proc = Start-Process wsl.exe -WindowStyle Hidden -PassThru `
    -ArgumentList "-d $Distro --exec bash -lc `"$serve`""
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while (-not (Test-Server)) {
    if ($proc.HasExited) {
      Show-Error "The Avaris server stopped while starting. See data/serve.log in $Repo."
    }
    if ((Get-Date) -gt $deadline) {
      Show-Error "The Avaris server did not answer within $TimeoutSec s. See data/serve.log in $Repo."
    }
    Start-Sleep -Milliseconds 500
  }
}

if (Test-Path $AppShortcut) {
  Start-Process $AppShortcut
} else {
  Start-Process $Url  # app not installed: the default browser
}
