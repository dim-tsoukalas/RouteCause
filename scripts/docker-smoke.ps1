# Smoke test (Windows / PowerShell): build the image and verify the pipeline end-to-end.
#   Usage:  .\scripts\docker-smoke.ps1            # tag: routecause
#           .\scripts\docker-smoke.ps1 myimage
param([string]$Image = "routecause")

$script:fail = $false
function Pass($m) { Write-Host "  [PASS] $m" -ForegroundColor Green }
function Bad($m)  { Write-Host "  [FAIL] $m" -ForegroundColor Red; $script:fail = $true }

Write-Host "==> Building $Image"
docker build -t $Image .
if ($LASTEXITCODE -eq 0) { Pass "docker build" }
else { Bad "docker build"; Write-Host "Build failed; aborting." -ForegroundColor Red; exit 1 }

Write-Host "==> Flagship demo (offline, no key)"
$out = docker run --rm $Image 2>&1 | Out-String
if ($out -match "Investigation: pakistan-youtube-2008" -and $out -match "MOAS" -and $out -match "208\.65\.153\.0/24") {
  Pass "default demo produced the MOAS finding"
} else { Bad "default demo output missing expected markers" }

Write-Host "==> Second incident (rostelecom-2020)"
docker run --rm $Image rostelecom-2020 --seek-contradictions | Out-Null
if ($LASTEXITCODE -eq 0) { Pass "rostelecom-2020 ran" } else { Bad "rostelecom-2020 failed" }

Write-Host "==> ask (offline retrieval)"
docker run --rm --entrypoint ask $Image "how is a BGP AS_PATH loop detected?" | Out-Null
if ($LASTEXITCODE -eq 0) { Pass "ask ran" } else { Bad "ask failed" }

Write-Host "==> pytest suite"
docker run --rm --entrypoint pytest $Image -q | Out-Null
if ($LASTEXITCODE -eq 0) { Pass "pytest suite passed" } else { Bad "pytest suite failed" }

Write-Host ""
if (-not $script:fail) { Write-Host "All smoke checks passed." -ForegroundColor Green }
else { Write-Host "Some smoke checks failed." -ForegroundColor Red; exit 1 }
