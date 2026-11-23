<#
Shows the protected gateway route in action (used for the screenshots / demo video):
  1. banking query without a token  -> 401 from the gateway
  2. login through the gateway       -> token
  3. same request with the token     -> 200

usage:
  powershell -ExecutionPolicy Bypass -File .\deploy\check-gateway.ps1
#>

param(
    [string]$Gateway = "https://tuition-apim-ee7141.azure-api.net/api/v1",
    [string]$Username = "20210001",
    [string]$Password = "student123"
)

function Show-Request($title, $url, $token) {
    Write-Host ""
    Write-Host "=== $title" -ForegroundColor Cyan
    Write-Host "GET $url"
    $curlArgs = @("-s", "-i", $url)
    if ($token) {
        Write-Host "Authorization: Bearer $($token.Substring(0, 20))..."
        $curlArgs += @("-H", "Authorization: Bearer $token")
    }
    $raw = (& curl.exe @curlArgs) -join "`n"
    $parts = $raw -split "`r?`n`r?`n", 2
    Write-Host ""
    foreach ($line in ($parts[0] -split "`r?`n")) {
        if ($line -match "^HTTP/|^x-api-gateway|^content-type|^www-authenticate") {
            Write-Host $line.Trim() -ForegroundColor Yellow
        }
    }
    Write-Host ""
    try {
        $parts[1] | ConvertFrom-Json | ConvertTo-Json -Depth 6 | Write-Host
    } catch {
        Write-Host $parts[1]
    }
}

Write-Host "API Gateway: $Gateway" -ForegroundColor Green
$url = "$Gateway/banking/tuitions/$Username"

Show-Request "1) protected route WITHOUT token" $url $null

Write-Host ""
Write-Host "=== 2) login through the gateway as $Username" -ForegroundColor Cyan
Write-Host "POST $Gateway/auth/token"
$login = Invoke-RestMethod -Method Post -Uri "$Gateway/auth/token" -Body @{ username = $Username; password = $Password }
Write-Host "token_type: $($login.token_type)   role: $($login.role)   expires_in: $($login.expires_in)" -ForegroundColor Yellow

Show-Request "3) protected route WITH token" $url $login.access_token
Write-Host ""
