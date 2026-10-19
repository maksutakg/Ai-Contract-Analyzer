# Starts everything needed to use the app: Yargı MCP, the web interface build, and the API.
# Usage: double-click start.cmd, or run .\start.ps1 [-NoBrowser]
param([switch]$NoBrowser)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

function Read-DotEnv {
    $values = @{}
    if (Test-Path "$root\.env") {
        foreach ($line in Get-Content "$root\.env") {
            if ($line -match '^\s*([A-Z_]+)\s*=\s*(.*?)\s*$') { $values[$Matches[1]] = $Matches[2] }
        }
    }
    return $values
}

# Process environment wins over .env, matching how the backend's settings resolve.
function Get-Setting([hashtable]$dotEnv, [string]$name, [string]$default) {
    $fromEnv = [Environment]::GetEnvironmentVariable($name)
    if ($fromEnv) { return $fromEnv }
    if ($dotEnv.ContainsKey($name) -and $dotEnv[$name]) { return $dotEnv[$name] }
    return $default
}

function Test-Listening([int]$port) {
    return [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

function Wait-Listening([int]$port, [int]$seconds, [System.Diagnostics.Process]$process) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Listening $port) { return $true }
        if ($process -and $process.HasExited) { return $false }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

# uv was installed with "pip install --user", whose Scripts folder may not be on PATH.
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
$env:Path = "$machinePath;$userPath"
if (Get-Command uv -ErrorAction SilentlyContinue) {
    $uvExe = (Get-Command uv).Source
    $uvPrefix = @()
} else {
    $uvExe = (Get-Command python).Source
    $uvPrefix = @("-m", "uv")
}

$dotEnv = Read-DotEnv
if (-not (Test-Path "$root\.env")) {
    Write-Warning ".env bulunamadı. .env.example dosyasını .env olarak kopyalayıp GEMINI_API_KEY değerini girin; şimdilik varsayılan ayarlarla devam ediliyor."
}
$appPort = [int](Get-Setting $dotEnv "APP_PORT" "8000")
$mcpUri = [Uri](Get-Setting $dotEnv "YARGI_MCP_URL" "http://127.0.0.1:8001/mcp/")
$appUrl = "http://localhost:$appPort/"

if (Test-Listening $appPort) {
    Write-Host "Uygulama zaten $appUrl adresinde çalışıyor."
    if (-not $NoBrowser) { Start-Process $appUrl }
    exit 0
}

# 1. Web interface: build when missing or when its sources are newer than the build.
$dist = "$root\frontend\dist\index.html"
$needsBuild = -not (Test-Path $dist)
if (-not $needsBuild) {
    $builtAt = (Get-Item $dist).LastWriteTime
    $needsBuild = [bool](Get-ChildItem "$root\frontend\src", "$root\frontend\index.html" -Recurse -File |
        Where-Object { $_.LastWriteTime -gt $builtAt } | Select-Object -First 1)
}
if ($needsBuild) {
    if (Get-Command npm -ErrorAction SilentlyContinue) {
        Write-Host "Arayüz derleniyor..."
        Push-Location "$root\frontend"
        try {
            if (-not (Test-Path "node_modules")) { npm install --no-fund --no-audit | Out-Host }
            npm run build | Out-Host
            if ($LASTEXITCODE -ne 0) { throw "Arayüz derlenemedi (npm run build)." }
        } finally { Pop-Location }
    } else {
        Write-Warning "npm bulunamadı; arayüz derlenmeden yalnız API başlatılıyor. Node.js kurun."
    }
}

# 2. Yargı MCP, unless something already listens on its port.
New-Item -ItemType Directory -Force "$root\logs" | Out-Null
$mcp = $null
if (Test-Listening $mcpUri.Port) {
    Write-Host "Yargı MCP zaten $($mcpUri.Port) portunda çalışıyor."
} else {
    Write-Host "Yargı MCP başlatılıyor (ilk çalıştırmada bağımlılıklar iner, birkaç dakika sürebilir)..."
    # Dependencies are pinned to yargi-mcp's release date; newer mcp releases break it (README).
    $mcpArgs = $uvPrefix + @(
        "tool", "run", "--python", "3.11", "--exclude-newer", "2026-07-15",
        "--from", "yargi-mcp[asgi]==0.2.2",
        "uvicorn", "asgi_app:app", "--host", $mcpUri.Host, "--port", "$($mcpUri.Port)"
    )
    $mcp = Start-Process -FilePath $uvExe -ArgumentList $mcpArgs -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput "$root\logs\yargi-mcp.log" -RedirectStandardError "$root\logs\yargi-mcp.err.log"
    if (-not (Wait-Listening $mcpUri.Port 300 $mcp)) {
        if (-not $mcp.HasExited) { taskkill /PID $mcp.Id /T /F | Out-Null }
        Write-Error "Yargı MCP başlamadı. Ayrıntı: logs\yargi-mcp.err.log"
    }
    Write-Host "Yargı MCP hazır."
}

# 3. The API (also serves the interface). Opens the browser once it answers.
if (-not $NoBrowser) {
    Start-Job -ArgumentList $appUrl -ScriptBlock {
        param($url)
        for ($i = 0; $i -lt 120; $i++) {
            try { Invoke-WebRequest "$($url)health" -UseBasicParsing -TimeoutSec 2 | Out-Null; Start-Process $url; return } catch { Start-Sleep 1 }
        }
    } | Out-Null
}
Write-Host "Uygulama başlatılıyor: $appUrl  (durdurmak için Ctrl+C)"
try {
    & $uvExe @($uvPrefix + @("run", "python", "main.py"))
} finally {
    # Only stop the MCP server this script started; one started elsewhere keeps running.
    if ($mcp -and -not $mcp.HasExited) {
        taskkill /PID $mcp.Id /T /F | Out-Null
        Write-Host "Yargı MCP durduruldu."
    }
}
