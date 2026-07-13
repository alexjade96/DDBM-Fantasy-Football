# Launch the sleepermetrics web dashboard on Windows.
#
#   .\tools\run_dashboard.ps1 [-Port 8100] [-League <id>]
#
# R is often not on PATH on Windows, so this locates Rscript.exe itself
# (newest install wins) instead of assuming `Rscript` resolves. Run from the
# repo root.

param(
  [int]$Port = 8100,
  [string]$League = ""
)

$ErrorActionPreference = "Stop"

function Find-Rscript {
  $cmd = Get-Command Rscript -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  $roots = @("$env:ProgramFiles\R", "${env:ProgramFiles(x86)}\R", "$env:LOCALAPPDATA\Programs\R")
  foreach ($r in $roots) {
    if (Test-Path $r) {
      $hit = Get-ChildItem -Path $r -Filter Rscript.exe -Recurse -ErrorAction SilentlyContinue |
             Sort-Object FullName -Descending | Select-Object -First 1
      if ($hit) { return $hit.FullName }
    }
  }
  return $null
}

$rscript = Find-Rscript
if (-not $rscript) {
  Write-Error ("Could not find Rscript.exe. Install R from https://cran.r-project.org/, " +
               "or add its bin\x64 folder to PATH.")
  exit 1
}

Write-Host "Using R: $rscript" -ForegroundColor DarkGray
$args = @("tools/run_dashboard.R", "$Port")
if ($League) { $args += $League }
& $rscript @args
