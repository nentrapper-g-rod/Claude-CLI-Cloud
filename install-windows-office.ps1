#
# Quick installer for My Office Desktop Windows
# Run this as Administrator in PowerShell
#

# Check if running as Administrator
if (-NOT ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) {
    Write-Host "Error: This script must be run as Administrator" -ForegroundColor Red
    Write-Host "Right-click PowerShell and select 'Run as Administrator'" -ForegroundColor Yellow
    exit 1
}

Write-Host "Installing Claude Bridge for My Office Desktop Windows..." -ForegroundColor Cyan
Write-Host ""

# Set configuration
$env:SOURCE_SERVER = "http://100.94.187.56:8888"
$env:MACHINE_NAME = "My Office Desktop Windows"
$env:WS_PORT = "8766"
$env:SERVICE_USER = "nentr"

# Download and run installer
Write-Host "Downloading installer from $env:SOURCE_SERVER..." -ForegroundColor Green
try {
    Invoke-WebRequest -Uri "$env:SOURCE_SERVER/install-bridge.ps1" -OutFile "$env:TEMP\install-bridge.ps1"
    Write-Host "Running installer..." -ForegroundColor Green
    & "$env:TEMP\install-bridge.ps1"
} catch {
    Write-Host "Error: Failed to download or run installer" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
