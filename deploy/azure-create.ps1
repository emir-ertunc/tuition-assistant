<#
Creates the Azure resources for the Tuition API (safe to run again, existing things are skipped):
  - resource group
  - Azure Database for PostgreSQL Flexible Server (Burstable B1ms) + tuition_db
  - App Service plan (Linux) + Web App (Python)
  - app settings (DATABASE_URL, JWT_SECRET ...)

The generated passwords are saved to deploy/azure-secrets.local.env (ignored by git),
the next scripts read them from there.

usage (from the repo root, after `az login`):
  .\deploy\azure-create.ps1 -Suffix ee7139
  .\deploy\azure-create.ps1 -Suffix ee7139 -Location polandcentral -PlanSku B1

note: our Azure for Students subscription only allows some regions (polandcentral,
austriaeast, francecentral, denmarkeast, belgiumcentral). F1 quota and the postgres B1ms
sku were only available together in austriaeast, so that is the default.
#>

param(
    # makes the names unique on azure, e.g. your initials + some digits
    [Parameter(Mandatory = $true)][string]$Suffix,
    [string]$Location = "austriaeast",
    [string]$PlanSku = "F1",          # F1 = free, B1 if F1 has no quota in the region
    [string]$PythonVersion = "3.12",
    [string]$PostgresVersion = "17"
)

# az writes warnings to stderr, so we check the exit code ourselves instead of using "Stop"
$ErrorActionPreference = "Continue"

$ResourceGroup = "tuition-rg"
$PgServer = "tuition-pg-$Suffix"
$PgAdmin = "tuitionadmin"
$Database = "tuition_db"
$Plan = "tuition-plan"
$WebApp = "tuition-api-$Suffix"
$SecretsFile = Join-Path $PSScriptRoot "azure-secrets.local.env"

function Invoke-Az {
    # runs az and stops the script if it fails (powershell 5.1 does not do this for exe files)
    $output = & az @args
    if ($LASTEXITCODE -ne 0) {
        throw "az $($args[0..2] -join ' ') ... failed (exit code $LASTEXITCODE)"
    }
    return $output
}

function New-RandomSecret([int]$Length) {
    # letters + digits only, so it can be used in a url without escaping
    $chars = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789".ToCharArray()
    $body = -join (1..$Length | ForEach-Object { $chars | Get-Random })
    # azure wants upper, lower and digit in the password
    return "Tu7" + $body
}

function Write-Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }

# ---------- secrets ----------
$PgPassword = $null
$JwtSecret = $null
if (Test-Path $SecretsFile) {
    Write-Step "using the passwords in $SecretsFile"
    $saved = @{}
    Get-Content $SecretsFile | Where-Object { $_ -match "=" -and $_ -notmatch "^#" } | ForEach-Object {
        $k, $v = $_ -split "=", 2; $saved[$k] = $v
    }
    $PgPassword = $saved["PG_PASSWORD"]
    $JwtSecret = $saved["JWT_SECRET"]
}
if (-not $PgPassword) { $PgPassword = New-RandomSecret 24 }
if (-not $JwtSecret) { $JwtSecret = New-RandomSecret 48 }

$DatabaseUrl = "postgresql+psycopg://${PgAdmin}:${PgPassword}@${PgServer}.postgres.database.azure.com:5432/${Database}?sslmode=require"

@(
    "# created by deploy/azure-create.ps1 - do not commit"
    "RESOURCE_GROUP=$ResourceGroup"
    "LOCATION=$Location"
    "PG_SERVER=$PgServer"
    "PG_ADMIN=$PgAdmin"
    "PG_PASSWORD=$PgPassword"
    "WEB_APP=$WebApp"
    "JWT_SECRET=$JwtSecret"
    "DATABASE_URL=$DatabaseUrl"
) | Set-Content -Path $SecretsFile -Encoding utf8

# ---------- resource group ----------
Write-Step "resource group $ResourceGroup"
$rgExists = Invoke-Az group exists --name $ResourceGroup
if ($rgExists -eq "false") {
    Invoke-Az group create --name $ResourceGroup --location $Location --output none
}

# ---------- postgres ----------
Write-Step "postgres flexible server $PgServer in $Location (takes 5-10 minutes)"
$exists = Invoke-Az postgres flexible-server list --resource-group $ResourceGroup --query "[?name=='$PgServer'] | length(@)"
if ($exists -eq "0") {
    # 0.0.0.0 = allow connections from azure services (the web app)
    Invoke-Az postgres flexible-server create `
        --resource-group $ResourceGroup `
        --name $PgServer `
        --location $Location `
        --admin-user $PgAdmin `
        --admin-password $PgPassword `
        --tier Burstable `
        --sku-name Standard_B1ms `
        --storage-size 32 `
        --version $PostgresVersion `
        --public-access 0.0.0.0 `
        --yes `
        --output none
} else {
    Write-Host "already exists, skipping"
}

Write-Step "database $Database"
$dbExists = Invoke-Az postgres flexible-server db list --resource-group $ResourceGroup --server-name $PgServer --query "[?name=='$Database'] | length(@)"
if ($dbExists -eq "0") {
    Invoke-Az postgres flexible-server db create --resource-group $ResourceGroup `
        --server-name $PgServer --name $Database --output none
}

Write-Step "firewall rule for this computer (needed to run the seed script from here)"
$myIp = (Invoke-RestMethod -Uri "https://api.ipify.org")
Invoke-Az postgres flexible-server firewall-rule create --resource-group $ResourceGroup `
    --server-name $PgServer --name my-computer `
    --start-ip-address $myIp --end-ip-address $myIp --output none

# ---------- app service ----------
Write-Step "app service plan $Plan ($PlanSku, linux)"
$planExists = Invoke-Az appservice plan list --resource-group $ResourceGroup --query "[?name=='$Plan'] | length(@)"
if ($planExists -eq "0") {
    Invoke-Az appservice plan create --resource-group $ResourceGroup --name $Plan --location $Location `
        --sku $PlanSku --is-linux --output none
} else {
    Write-Host "already exists, skipping"
}

Write-Step "web app $WebApp (python $PythonVersion)"
$exists = Invoke-Az webapp list --resource-group $ResourceGroup --query "[?name=='$WebApp'] | length(@)"
if ($exists -eq "0") {
    Invoke-Az webapp create --resource-group $ResourceGroup --plan $Plan --name $WebApp `
        --runtime "PYTHON:$PythonVersion" --output none
} else {
    Write-Host "already exists, skipping"
}

Write-Step "app settings"
Invoke-Az webapp config appsettings set --resource-group $ResourceGroup --name $WebApp --output none --settings `
    "DATABASE_URL=$DatabaseUrl" `
    "JWT_SECRET=$JwtSecret" `
    "JWT_EXPIRE_MINUTES=60" `
    "SCM_DO_BUILD_DURING_DEPLOYMENT=true"

Write-Step "startup command"
Invoke-Az webapp config set --resource-group $ResourceGroup --name $WebApp --output none `
    --startup-file "python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"

Invoke-Az webapp update --resource-group $ResourceGroup --name $WebApp --https-only true --output none

Write-Host "`ndone. next: .\deploy\azure-deploy-api.ps1 -Seed" -ForegroundColor Green
Write-Host "api url will be: https://$WebApp.azurewebsites.net"
