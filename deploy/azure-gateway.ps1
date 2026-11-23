<#
Creates the API Gateway (Azure API Management, Consumption tier) in front of the Tuition API.
Safe to run again: existing things are updated.

  - APIM service tuition-apim-<suffix>
  - named values: jwt-signing-key, gateway-key, swagger-origin
  - api "Tuition API v1" on path /api/v1, imported from the api's openapi.json
  - api policy from gateway/api-policy.xml (jwt check, roles, gateway key, error format)
  - app settings on the web app: GATEWAY_KEY and PUBLIC_BASE_URL

usage (from the repo root, after azure-create.ps1 and azure-deploy-api.ps1):
  .\deploy\azure-gateway.ps1
#>

param(
    [string]$Location = "francecentral",
    [string]$PublisherEmail = "tuition-admin@example.com"
)

$ErrorActionPreference = "Continue"

function Invoke-Az {
    $output = & az @args
    if ($LASTEXITCODE -ne 0) { throw "az $($args[0..2] -join ' ') ... failed (exit code $LASTEXITCODE)" }
    return $output
}
function Write-Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }

$Root = Join-Path $PSScriptRoot ".." | Resolve-Path
$SecretsFile = Join-Path $PSScriptRoot "azure-secrets.local.env"
if (-not (Test-Path $SecretsFile)) { throw "run deploy\azure-create.ps1 first" }
$cfg = [ordered]@{}
Get-Content $SecretsFile | Where-Object { $_ -match "=" -and $_ -notmatch "^#" } | ForEach-Object {
    $k, $v = $_ -split "=", 2; $cfg[$k] = $v
}

$ResourceGroup = $cfg.RESOURCE_GROUP
$WebApp = $cfg.WEB_APP
$Suffix = $WebApp -replace "^tuition-api-", ""
$Apim = "tuition-apim-$Suffix"
$ApiId = "tuition-api-v1"
$BackendUrl = "https://$WebApp.azurewebsites.net"
$GatewayUrl = "https://$Apim.azure-api.net"

if (-not $cfg.GATEWAY_KEY) {
    $chars = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789".ToCharArray()
    $cfg.GATEWAY_KEY = -join (1..40 | ForEach-Object { $chars | Get-Random })
    Add-Content -Path $SecretsFile -Value "GATEWAY_KEY=$($cfg.GATEWAY_KEY)"
}
if (-not $cfg.APIM) { Add-Content -Path $SecretsFile -Value "APIM=$Apim" }

# ---------- apim service ----------
Write-Step "API Management $Apim (Consumption, $Location)"
$exists = Invoke-Az apim list --resource-group $ResourceGroup --query "[?name=='$Apim'] | length(@)"
if ($exists -eq "0") {
    Invoke-Az apim create --resource-group $ResourceGroup --name $Apim --location $Location `
        --publisher-name "Tuition Assistant" --publisher-email $PublisherEmail `
        --sku-name Consumption --output none
} else {
    Write-Host "already exists, skipping"
}

# ---------- web app settings ----------
Write-Step "web app settings (GATEWAY_KEY, PUBLIC_BASE_URL)"
Invoke-Az webapp config appsettings set --resource-group $ResourceGroup --name $WebApp --output none --settings `
    "GATEWAY_KEY=$($cfg.GATEWAY_KEY)" "PUBLIC_BASE_URL=$GatewayUrl"

# ---------- named values ----------
Write-Step "named values"
$jwtKeyBase64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($cfg.JWT_SECRET))
$namedValues = @(
    @{ id = "jwt-signing-key"; value = $jwtKeyBase64; secret = "true" },
    @{ id = "gateway-key"; value = $cfg.GATEWAY_KEY; secret = "true" },
    @{ id = "swagger-origin"; value = $BackendUrl; secret = "false" }
)
foreach ($nv in $namedValues) {
    $found = Invoke-Az apim nv list --resource-group $ResourceGroup --service-name $Apim --query "[?name=='$($nv.id)'] | length(@)"
    if ($found -eq "0") {
        Invoke-Az apim nv create --resource-group $ResourceGroup --service-name $Apim --named-value-id $nv.id `
            --display-name $nv.id --value $nv.value --secret $nv.secret --output none
    } else {
        Invoke-Az apim nv update --resource-group $ResourceGroup --service-name $Apim --named-value-id $nv.id `
            --value $nv.value --secret $nv.secret --output none
    }
    Write-Host "  $($nv.id)"
}

# ---------- api import ----------
Write-Step "importing the api from $BackendUrl/openapi.json"
$python = Join-Path $Root "tuition-api\.venv\Scripts\python.exe"
$specFile = Join-Path $env:TEMP "tuition-openapi-apim.json"
& $python (Join-Path $PSScriptRoot "prepare_openapi.py") $BackendUrl $specFile
if ($LASTEXITCODE -ne 0) { throw "could not read openapi.json from the api" }

Invoke-Az apim api import --resource-group $ResourceGroup --service-name $Apim --api-id $ApiId `
    --path "api/v1" --display-name "Tuition API v1" --protocols https `
    --specification-format OpenApiJson --specification-path $specFile `
    --service-url "$BackendUrl/api/v1" --subscription-required false --output none

# ---------- api policy ----------
Write-Step "api policy (gateway/api-policy.xml)"
$subscriptionId = Invoke-Az account show --query id -o tsv
# ReadAllText gives a plain string. Get-Content adds PSPath/PSDrive... properties to the string
# in powershell 5.1 and ConvertTo-Json would send all of them (policy "too big" error)
$policyXml = [IO.File]::ReadAllText((Join-Path $Root "gateway\api-policy.xml"))
$bodyFile = Join-Path $env:TEMP "tuition-apim-policy.json"
$body = @{ properties = @{ format = "rawxml"; value = $policyXml } } | ConvertTo-Json -Depth 5
# without BOM, az cannot read a json file that starts with one
[IO.File]::WriteAllText($bodyFile, $body, (New-Object Text.UTF8Encoding $false))
$policyUri = "https://management.azure.com/subscriptions/$subscriptionId/resourceGroups/$ResourceGroup" +
    "/providers/Microsoft.ApiManagement/service/$Apim/apis/$ApiId/policies/policy?api-version=2022-08-01"
# Invoke-RestMethod instead of "az rest": the response starts with a BOM and az rest fails on it
$token = Invoke-Az account get-access-token --resource "https://management.azure.com/" --query accessToken -o tsv
Invoke-RestMethod -Method Put -Uri $policyUri -InFile $bodyFile -ContentType "application/json" `
    -Headers @{ Authorization = "Bearer $token" } | Out-Null
Write-Host "  policy applied"

Write-Step "restart web app (new settings)"
Invoke-Az webapp restart --resource-group $ResourceGroup --name $WebApp --output none

Write-Host "`ndone." -ForegroundColor Green
Write-Host "gateway: $GatewayUrl/api/v1"
Write-Host "example: $GatewayUrl/api/v1/mobile/tuitions/20210001"
