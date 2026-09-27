$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$envPath = Join-Path $projectRoot "backend\.env"

Write-Host "Paste a new key copied directly from Agent Plan API Key Management. Do not share it in chat." -ForegroundColor Cyan
$secureKey = Read-Host "Agent Plan API Key" -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)

try {
  $plainKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
  if ($plainKey.Length -lt 20 -or $plainKey -match "\s") {
    throw "Invalid key. Paste the complete original value from Ark API Key Management."
  }

  $content = @(
    "ARK_API_KEY=$plainKey"
    "ARK_IMAGE_MODEL=doubao-seedream-5.0-lite"
    "ARK_IMAGE_ENDPOINT=https://ark.cn-beijing.volces.com/api/plan/v3/images/generations"
    "FRONTEND_ORIGIN=http://localhost:3000"
  )
  [IO.File]::WriteAllLines($envPath, $content, [Text.UTF8Encoding]::new($false))
  Write-Host "Saved locally to backend/.env. Restart the backend before testing." -ForegroundColor Green
}
finally {
  if ($pointer -ne [IntPtr]::Zero) {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
  }
  $plainKey = $null
}
