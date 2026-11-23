<#
Creates (first time) and deploys the MCP server as a second web app on the same
App Service plan as the Tuition API. Safe to run again after code changes.

The MCP server is not behind the API gateway; the agent calls it directly at
https://tuition-mcp-<suffix>.azurewebsites.net/mcp

usage (from the repo root, after azure-create.ps1):
  .\deploy\azure-deploy-mcp.ps1
#>

param([string]$PythonVersion = "3.12")

$ErrorActionPreference = "Continue"

function Invoke-Az {
    $output = & az @args
    if ($LASTEXITCODE -ne 0) { throw "az $($args[0..2] -join ' ') ... failed (exit code $LASTEXITCODE)" }
    return $output
}
function Write-Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }

$SecretsFile = Join-Path $PSScriptRoot "azure-secrets.local.env"
if (-not (Test-Path $SecretsFile)) { throw "run deploy\azure-create.ps1 first" }
$cfg = @{}
Get-Content $SecretsFile | Where-Object { $_ -match "=" -and $_ -notmatch "^#" } | ForEach-Object {
    $k, $v = $_ -split "=", 2; $cfg[$k] = $v
}

$ResourceGroup = $cfg.RESOURCE_GROUP
$Suffix = $cfg.WEB_APP -replace "^tuition-api-", ""
$McpApp = "tuition-mcp-$Suffix"
$Plan = "tuition-plan"
$HostName = "$McpApp.azurewebsites.net"
$McpDir = Join-Path $PSScriptRoot "..\mcp-server" | Resolve-Path

Write-Step "web app $McpApp"
$exists = Invoke-Az webapp list --resource-group $ResourceGroup --query "[?name=='$McpApp'] | length(@)"
if ($exists -eq "0") {
    Invoke-Az webapp create --resource-group $ResourceGroup --plan $Plan --name $McpApp `
        --runtime "PYTHON:$PythonVersion" --output none
} else {
    Write-Host "already exists, skipping"
}

Write-Step "app settings + startup command"
# the sdk checks the Host header, so the public name has to be allowed
Invoke-Az webapp config appsettings set --resource-group $ResourceGroup --name $McpApp --output none --settings `
    "MCP_HOST=0.0.0.0" "MCP_PORT=8000" "MCP_ALLOWED_HOSTS=$HostName" "MCP_STATELESS=true" `
    "SCM_DO_BUILD_DURING_DEPLOYMENT=true"
Invoke-Az webapp config set --resource-group $ResourceGroup --name $McpApp --output none `
    --startup-file "python server.py"
Invoke-Az webapp update --resource-group $ResourceGroup --name $McpApp --https-only true --output none

Write-Step "packing $McpDir"
$staging = Join-Path $env:TEMP "tuition-mcp-staging"
$ZipFile = Join-Path $env:TEMP "tuition-mcp.zip"
if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }
if (Test-Path $ZipFile) { Remove-Item $ZipFile }
New-Item -ItemType Directory $staging | Out-Null
foreach ($item in "server.py", "indexer.py", "requirements.txt", "data") {
    Copy-Item (Join-Path $McpDir $item) $staging -Recurse
}
$python = Join-Path $McpDir ".venv\Scripts\python.exe"
& $python -c "import shutil, sys; shutil.make_archive(sys.argv[1][:-4], 'zip', sys.argv[2])" $ZipFile $staging

Write-Step "deploying (azure installs the requirements, takes 1-3 min)"
az webapp deploy --resource-group $ResourceGroup --name $McpApp --src-path $ZipFile --type zip --output none
if ($LASTEXITCODE -ne 0) { throw "deploy failed (exit code $LASTEXITCODE)" }

if (-not $cfg.MCP_APP) { Add-Content -Path $SecretsFile -Value "MCP_APP=$McpApp" }

Write-Step "checking https://$HostName/health"
for ($i = 1; $i -le 10; $i++) {
    try {
        $health = Invoke-RestMethod "https://$HostName/health" -TimeoutSec 30
        Write-Host "health: $($health.status), sections: $($health.sections)" -ForegroundColor Green
        break
    } catch {
        Write-Host "not up yet ($i/10), waiting..."
        Start-Sleep -Seconds 15
    }
}
Write-Host "MCP endpoint: https://$HostName/mcp"
