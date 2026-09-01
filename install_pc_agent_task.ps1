# Sets up bmo_pc_agent.py to start automatically whenever you log into Windows.
#
# Run this ONCE from PowerShell, from the same folder as bmo_pc_agent.py:
#   .\install_pc_agent_task.ps1 -Token "the pc_agent_token value from config.json on the Pi"
# (or just .\install_pc_agent_task.ps1 and it will prompt you for the token)
#
# If PowerShell blocks it, run this first in an elevated PowerShell window:
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

param(
    [string]$Token
)

$ErrorActionPreference = "Stop"

if (-not $Token) {
    $SecureToken = Read-Host "Paste the 'pc_agent_token' value from config.json on the Pi" -AsSecureString
    $Token = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureToken))
}
if (-not $Token) {
    Write-Host "ERROR: No token provided — the agent needs this to authenticate requests from the Pi." -ForegroundColor Red
    exit 1
}

$ScriptDir  = $PSScriptRoot
$AgentPath  = Join-Path $ScriptDir "bmo_pc_agent.py"
$TaskName   = "BMO PC Agent"

if (-not (Test-Path $AgentPath)) {
    Write-Host "ERROR: bmo_pc_agent.py not found in $ScriptDir" -ForegroundColor Red
    Write-Host "Put this script in the same folder as bmo_pc_agent.py and try again."
    exit 1
}

# 1. Persist BMO_PC_TOKEN as a permanent user environment variable so the
#    agent has it available no matter how it's launched (survives reboots).
[System.Environment]::SetEnvironmentVariable("BMO_PC_TOKEN", $Token, "User")
Write-Host "[1/2] BMO_PC_TOKEN saved to your user environment." -ForegroundColor Green

# 2. Find pythonw.exe (runs with no visible console window). Falls back to
#    python.exe if pythonw isn't found — the agent will still work, you'll
#    just see a console window after login.
$pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $pythonw) {
    $python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
    if (-not $python) {
        Write-Host "ERROR: Python not found on PATH. Install Python and make sure 'python' works from a terminal first." -ForegroundColor Red
        exit 1
    }
    $pythonw = $python
    Write-Host "NOTE: pythonw.exe not found — using python.exe instead (a console window will briefly show at login)." -ForegroundColor Yellow
}

# 3. Register the scheduled task: runs at logon, as the current user,
#    restarts automatically if it crashes. Launched via powershell.exe
#    (hidden window) so all output can be redirected to a log file — pythonw
#    has no console to print to otherwise, making failures invisible.
$LogPath    = Join-Path $ScriptDir "pc_agent_log.txt"
$InnerCmd   = "& '$pythonw' '$AgentPath' *>> '$LogPath'"
$PsArgument = "-NoProfile -WindowStyle Hidden -Command `"$InnerCmd`""
$Action     = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $PsArgument -WorkingDirectory $ScriptDir
$Trigger    = New-ScheduledTaskTrigger -AtLogOn
$Settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger `
    -Settings $Settings -Principal $Principal -Description "Starts BMO's PC control agent at login." | Out-Null

Write-Host "[2/2] Scheduled task '$TaskName' created — it will start at your next login." -ForegroundColor Green
Write-Host ""
Write-Host "To start it right now without rebooting/relogging in:" -ForegroundColor Cyan
Write-Host "    Start-ScheduledTask -TaskName `"$TaskName`""
Write-Host ""
Write-Host "Logs (including 'unauthorized' or missing-token warnings) go to:" -ForegroundColor Cyan
Write-Host "    $LogPath"
Write-Host ""
Write-Host "To check on it later:" -ForegroundColor Cyan
Write-Host "    Get-ScheduledTask -TaskName `"$TaskName`" | Get-ScheduledTaskInfo"
Write-Host ""
Write-Host "To remove it:" -ForegroundColor Cyan
Write-Host "    Unregister-ScheduledTask -TaskName `"$TaskName`""
