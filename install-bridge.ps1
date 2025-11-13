#
# Claude CLI Bridge Installer for Windows
# Downloads and installs the Claude CLI Terminal Bridge Server
#
# Run as Administrator:
#   Set-ExecutionPolicy Bypass -Scope Process -Force
#   $env:SOURCE_SERVER="http://YOUR_SERVER:8890"
#   $env:SERVICE_USER="nentr"  # Optional: Run service as specific user (default: SYSTEM)
#   .\install-bridge.ps1
#

# Requires Administrator privileges
if (-NOT ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) {
    Write-Host "Error: This script must be run as Administrator" -ForegroundColor Red
    Write-Host "Right-click PowerShell and select 'Run as Administrator'" -ForegroundColor Yellow
    exit 1
}

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  Claude CLI Terminal Bridge Installer (Windows)" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# Configuration
$DefaultPort = "8766"
$InstallDir = "$env:ProgramData\claude-bridge"

# Get machine name
if (-not $env:MACHINE_NAME) {
    $MachineName = Read-Host "Enter a name for this machine (default: $env:COMPUTERNAME)"
    if ([string]::IsNullOrWhiteSpace($MachineName)) {
        $MachineName = $env:COMPUTERNAME
    }
} else {
    $MachineName = $env:MACHINE_NAME
}

# Get WebSocket port
if (-not $env:WS_PORT) {
    $PortInput = Read-Host "Enter WebSocket port (default: $DefaultPort)"
    if ([string]::IsNullOrWhiteSpace($PortInput)) {
        $WsPort = $DefaultPort
    } else {
        $WsPort = $PortInput
    }
} else {
    $WsPort = $env:WS_PORT
}

Write-Host ""
Write-Host "Configuration:" -ForegroundColor Yellow
Write-Host "  Install Directory: $InstallDir"
Write-Host "  Machine Name: $MachineName"
Write-Host "  WebSocket Port: $WsPort"
Write-Host ""

$Confirm = Read-Host "Continue with installation? (y/n)"
if ($Confirm -notmatch '^[Yy]$') {
    Write-Host "Installation cancelled." -ForegroundColor Red
    exit 0
}

# Create install directory
Write-Host "Creating installation directory..." -ForegroundColor Green
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

# Get source server
if (-not $env:SOURCE_SERVER) {
    $SourceServer = Read-Host "Enter source server URL (e.g., http://192.168.1.100:8890)"
} else {
    $SourceServer = $env:SOURCE_SERVER
}

Write-Host "Downloading bridge server..." -ForegroundColor Green
try {
    Invoke-WebRequest -Uri "$SourceServer/download/claude-bridge-server-terminal.py" -OutFile "$InstallDir\claude-bridge-server-terminal.py"
} catch {
    Write-Host "Error: Failed to download bridge server from $SourceServer" -ForegroundColor Red
    Write-Host "Make sure the source server is running and accessible." -ForegroundColor Red
    exit 1
}

# Download MCP components (required for conversation logging)
Write-Host "Downloading MCP server components..." -ForegroundColor Green
try {
    Invoke-WebRequest -Uri "$SourceServer/download/conversation-mcp-server.py" -OutFile "$InstallDir\conversation-mcp-server.py"
    Write-Host "  Downloaded conversation-mcp-server.py" -ForegroundColor Green
} catch {
    Write-Host "  Warning: Failed to download conversation-mcp-server.py" -ForegroundColor Yellow
}

try {
    Invoke-WebRequest -Uri "$SourceServer/download/conversation_db.py" -OutFile "$InstallDir\conversation_db.py"
    Write-Host "  Downloaded conversation_db.py" -ForegroundColor Green
} catch {
    Write-Host "  Error: Failed to download conversation_db.py (required for hooks)" -ForegroundColor Red
}

try {
    Invoke-WebRequest -Uri "$SourceServer/download/conversation-hook.py" -OutFile "$InstallDir\conversation-hook.py"
    Write-Host "  Downloaded conversation-hook.py" -ForegroundColor Green
} catch {
    Write-Host "  Error: Failed to download conversation-hook.py (required for hooks)" -ForegroundColor Red
}

# Check Python installation
Write-Host "Checking Python installation..." -ForegroundColor Green
try {
    $PythonVersion = & python --version 2>&1
    $PythonPath = (Get-Command python).Source
    Write-Host "Found: $PythonVersion at $PythonPath" -ForegroundColor Green
} catch {
    Write-Host "Error: Python 3 is not installed" -ForegroundColor Red
    Write-Host "Please install Python 3.8 or higher from https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "Make sure to check 'Add Python to PATH' during installation" -ForegroundColor Yellow
    exit 1
}

# Install Python dependencies
Write-Host "Installing Python dependencies..." -ForegroundColor Green
try {
    & python -m pip install --upgrade pip
    & python -m pip install websockets aiofiles psutil aiohttp mcp pywinpty
    Write-Host "Python dependencies installed successfully" -ForegroundColor Green
} catch {
    Write-Host "Error: Failed to install Python dependencies" -ForegroundColor Red
    Write-Host "Please install manually: pip install websockets aiofiles psutil aiohttp mcp pywinpty" -ForegroundColor Yellow
    exit 1
}

# Check if Claude CLI is installed
Write-Host "Checking Claude CLI installation..." -ForegroundColor Green
try {
    $ClaudeVersion = & claude --version 2>&1
    Write-Host "Found Claude CLI: $ClaudeVersion" -ForegroundColor Green
} catch {
    Write-Host "Warning: Claude CLI is not installed" -ForegroundColor Yellow
    Write-Host "Install it with: irm https://raw.githubusercontent.com/anthropics/claude-cli/main/install.ps1 | iex" -ForegroundColor Yellow
    $Continue = Read-Host "Continue anyway? (y/n)"
    if ($Continue -notmatch '^[Yy]$') {
        exit 1
    }
}

# Create startup script
Write-Host "Creating startup script..." -ForegroundColor Green
$DebugFlag = if ($WsPort -eq "8766") { "--debug" } else { "" }
$ClaudeHomeFlag = if ($env:SERVICE_USER) { "--claude-home `"C:\Users\$env:SERVICE_USER\.claude`"" } else { "" }
$StartupScript = @"
@echo off
cd /d "$InstallDir"
"$PythonPath" claude-bridge-server-terminal.py --machine-name "$MachineName" --port $WsPort $ClaudeHomeFlag $DebugFlag
"@

$StartupScript | Out-File -FilePath "$InstallDir\start-bridge.bat" -Encoding ASCII

# Create Windows Service using NSSM or Task Scheduler
Write-Host "Setting up Windows Service..." -ForegroundColor Green

# Check if NSSM is available
$NssmPath = Get-Command nssm -ErrorAction SilentlyContinue

if ($NssmPath) {
    Write-Host "Using NSSM to create service..." -ForegroundColor Green
    $DebugArg = if ($WsPort -eq "8766") { "--debug" } else { "" }
    $ClaudeHomeNssmArg = if ($env:SERVICE_USER) { "--claude-home `"C:\Users\$env:SERVICE_USER\.claude`"" } else { "" }
    $NssmArgs = "$InstallDir\claude-bridge-server-terminal.py --machine-name `"$MachineName`" --port $WsPort $ClaudeHomeNssmArg $DebugArg"
    & nssm install "ClaudeBridge" "$PythonPath" $NssmArgs
    & nssm set "ClaudeBridge" AppDirectory "$InstallDir"
    & nssm set "ClaudeBridge" DisplayName "Claude CLI Terminal Bridge Server"
    & nssm set "ClaudeBridge" Description "WebSocket bridge server for Claude CLI"
    & nssm set "ClaudeBridge" Start SERVICE_AUTO_START
    & nssm start "ClaudeBridge"
    Write-Host "Service created and started successfully" -ForegroundColor Green
} else {
    Write-Host "NSSM not found. Creating scheduled task instead..." -ForegroundColor Yellow

    # Create a scheduled task that runs at startup
    # Always use SYSTEM account for reliability
    # If SERVICE_USER is specified, set environment variables to point to that user's .claude directory
    $ServiceUser = "SYSTEM"

    if ($env:SERVICE_USER) {
        Write-Host "Service will run as SYSTEM with access to user: $env:SERVICE_USER" -ForegroundColor Cyan
        $UserClaudeDir = "C:\Users\$env:SERVICE_USER\.claude"
        $UserConfigDir = "C:\Users\$env:SERVICE_USER\.config\claude"
        $ClaudeHomeArg = "--claude-home `"$UserClaudeDir`""
    } else {
        Write-Host "Service will run as: SYSTEM" -ForegroundColor Cyan
        $UserClaudeDir = $null
        $UserConfigDir = $null
        $ClaudeHomeArg = ""
    }

    $DebugArg = if ($WsPort -eq "8766") { "--debug" } else { "" }
    $TaskArgs = "$InstallDir\claude-bridge-server-terminal.py --machine-name `"$MachineName`" --port $WsPort $ClaudeHomeArg $DebugArg".Trim()

    $Action = New-ScheduledTaskAction -Execute "`"$PythonPath`"" -Argument $TaskArgs -WorkingDirectory $InstallDir
    $Trigger = New-ScheduledTaskTrigger -AtStartup
    $Principal = New-ScheduledTaskPrincipal -UserId $ServiceUser -LogonType ServiceAccount -RunLevel Highest

    $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

    # Stop any existing bridge processes before creating new task
    Write-Host "Stopping existing bridge processes..." -ForegroundColor Yellow
    Get-Process python -ErrorAction SilentlyContinue | Where-Object {$_.CommandLine -like "*claude-bridge*"} | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2

    # Stop existing task if running
    Stop-ScheduledTask -TaskName "ClaudeBridge" -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1

    Register-ScheduledTask -TaskName "ClaudeBridge" -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Force | Out-Null
    Start-ScheduledTask -TaskName "ClaudeBridge"
    Start-Sleep -Seconds 2
    Write-Host "Scheduled task created and started successfully" -ForegroundColor Green

    # Verify the task is running as the correct user
    $TaskInfo = Get-ScheduledTask -TaskName "ClaudeBridge"
    Write-Host "Task is configured to run as: $($TaskInfo.Principal.UserId)" -ForegroundColor Cyan
}

# Configure MCP if components were downloaded
if (Test-Path "$InstallDir\conversation-mcp-server.py") {
    Write-Host "Configuring MCP server..." -ForegroundColor Green

    # Use the service user's profile for MCP config
    if ($env:SERVICE_USER) {
        $ClaudeConfigDir = "C:\Users\$env:SERVICE_USER\.config\claude"
    } else {
        $ClaudeConfigDir = "$env:USERPROFILE\.config\claude"
    }
    New-Item -ItemType Directory -Force -Path $ClaudeConfigDir | Out-Null

    $McpConfig = @"
{
  "mcpServers": {
    "conversation-history": {
      "command": "python",
      "args": ["$($InstallDir -replace '\\', '\\')\\conversation-mcp-server.py"],
      "env": {
        "CONNECTION_NAME": "$MachineName"
      }
    }
  }
}
"@

    $McpConfig | Out-File -FilePath "$ClaudeConfigDir\mcp_config.json" -Encoding UTF8
    Write-Host "MCP configuration created at $ClaudeConfigDir\mcp_config.json" -ForegroundColor Green

    # Configure conversation hooks
    if (Test-Path "$InstallDir\conversation-hook.py") {
        Write-Host "Configuring conversation hooks..." -ForegroundColor Green

        # Determine the correct .claude directory based on service user
        if ($env:SERVICE_USER) {
            $ClaudeDir = "C:\Users\$env:SERVICE_USER\.claude"
        } else {
            $ClaudeDir = "$env:USERPROFILE\.claude"
        }
        New-Item -ItemType Directory -Force -Path $ClaudeDir | Out-Null

        $SettingsFile = "$ClaudeDir\settings.json"

        # Create or update settings.json with hooks
        $HookConfig = @"
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python $($InstallDir -replace '\\', '\\')\\conversation-hook.py"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python $($InstallDir -replace '\\', '\\')\\conversation-hook.py"
          }
        ]
      }
    ]
  }
}
"@

        $HookConfig | Out-File -FilePath $SettingsFile -Encoding UTF8
        Write-Host "Hooks configuration created at $SettingsFile" -ForegroundColor Green

        # Set environment variables for hooks
        Write-Host "Setting environment variables..." -ForegroundColor Green
        [Environment]::SetEnvironmentVariable("CLAUDE_CENTRAL_SERVER", "http://100.94.187.56:8891", "Machine")
        [Environment]::SetEnvironmentVariable("CLAUDE_CONNECTION_NAME", "$MachineName", "Machine")
        Write-Host "CLAUDE_CENTRAL_SERVER=http://100.94.187.56:8891" -ForegroundColor Cyan
        Write-Host "CLAUDE_CONNECTION_NAME=$MachineName" -ForegroundColor Cyan
    }
}

Write-Host ""
Write-Host "================================================" -ForegroundColor Green
Write-Host "  Installation Complete!" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Bridge server is now running on port $WsPort" -ForegroundColor Cyan
Write-Host "Machine name: $MachineName" -ForegroundColor Cyan
Write-Host "Installation directory: $InstallDir" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "1. Configure firewall to allow port $WsPort (if needed)" -ForegroundColor Yellow
Write-Host "2. Add this connection in your web UI" -ForegroundColor Yellow
Write-Host "3. Check service status:" -ForegroundColor Yellow

if ($NssmPath) {
    Write-Host "   nssm status ClaudeBridge" -ForegroundColor Cyan
} else {
    Write-Host "   Get-ScheduledTask -TaskName ClaudeBridge | Get-ScheduledTaskInfo" -ForegroundColor Cyan
}

Write-Host ""
Write-Host "To view logs:" -ForegroundColor Yellow
Write-Host "   Get-Content $InstallDir\bridge.log -Wait" -ForegroundColor Cyan
Write-Host ""
