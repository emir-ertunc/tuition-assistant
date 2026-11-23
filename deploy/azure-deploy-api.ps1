<#
Deploys the Tuition API code to the web app created by azure-create.ps1.
Can be run again after every code change.

usage (from the repo root):
  .\deploy\azure-deploy-api.ps1           -> zip + deploy
  .\deploy\azure-deploy-api.ps1 -Seed     -> also create the tables + test data on azure postgres
#>

param([switch]$Seed)

# az writes warnings to stderr, exit codes are checked by hand below
$ErrorActionPreference = "Continue"

$SecretsFile = Join-Path $PSScriptRoot "azure-secrets.local.env"
if (-not (Test-Path $SecretsFile)) { throw "run deploy\azure-create.ps1 first" }
$cfg = @{}
Get-Content $SecretsFile | Where-Object { $_ -match "=" -and $_ -notmatch "^#" } | ForEach-Object {
    $k, $v = $_ -split "=", 2; $cfg[$k] = $v
}

$ApiDir = Join-Path $PSScriptRoot "..\tuition-api" | Resolve-Path
$ZipFile = Join-Path $env:TEMP "tuition-api.zip"

# only the code and the requirements, no .venv / .env / tests
Write-Host "==> packing $ApiDir" -ForegroundColor Cyan
if (Test-Path $ZipFile) { Remove-Item $ZipFile }
$staging = Join-Path $env:TEMP "tuition-api-staging"
if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }
New-Item -ItemType Directory $staging | Out-Null
Copy-Item (Join-Path $ApiDir "app") $staging -Recurse
Copy-Item (Join-Path $ApiDir "requirements.txt") $staging
Get-ChildItem $staging -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
# python's zip uses "/" in paths (Compress-Archive on windows powershell 5.1 can use "\",
# which breaks the folders on the linux app service)
$python = Join-Path $ApiDir ".venv\Scripts\python.exe"
& $python -c "import shutil, sys; shutil.make_archive(sys.argv[1][:-4], 'zip', sys.argv[2])" $ZipFile $staging

Write-Host "==> deploying to $($cfg.WEB_APP) (azure installs the requirements, takes 1-3 min)" -ForegroundColor Cyan
az webapp deploy --resource-group $cfg.RESOURCE_GROUP --name $cfg.WEB_APP `
    --src-path $ZipFile --type zip --output none
if ($LASTEXITCODE -ne 0) { throw "deploy failed (exit code $LASTEXITCODE)" }

if ($Seed) {
    # runs on this computer but connects to azure postgres (firewall rule from azure-create.ps1)
    Write-Host "==> creating tables and test data on azure postgres" -ForegroundColor Cyan
    Push-Location $ApiDir
    try {
        $env:DATABASE_URL = $cfg.DATABASE_URL
        & .\.venv\Scripts\python.exe -m app.seed
        if ($LASTEXITCODE -ne 0) { throw "seed failed (exit code $LASTEXITCODE)" }
    } finally {
        Remove-Item Env:\DATABASE_URL -ErrorAction SilentlyContinue
        Pop-Location
    }
}

$url = "https://$($cfg.WEB_APP).azurewebsites.net"
Write-Host "==> checking $url/health" -ForegroundColor Cyan
for ($i = 1; $i -le 10; $i++) {
    try {
        $health = Invoke-RestMethod "$url/health" -TimeoutSec 30
        Write-Host "health: $($health.status)" -ForegroundColor Green
        break
    } catch {
        Write-Host "not up yet ($i/10), waiting..."
        Start-Sleep -Seconds 15
    }
}
Write-Host "swagger: $url/docs"
