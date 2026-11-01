# Register the kb-sync task, which runs `kb sync` every 15 minutes for the current user.
#
# Run it in a normal PowerShell window after kb is installed and configured:
#
#   powershell -ExecutionPolicy Bypass -File contrib\windows\register-kb-sync.ps1
#
# Pass -Kb PATH when kb is not on PATH. Running the script again replaces the task.
# Remove the task with: Unregister-ScheduledTask -TaskName kb-sync
#
# The task runs only while you are signed in, so it sees your mapped drives and Git
# credentials. conhost --headless runs kb without opening a console window. A run that
# was missed while the machine was off starts when it is next available, like the
# systemd timer's Persistent=true.

param(
    [string]$Kb = (Get-Command kb -ErrorAction Stop).Source
)

$ErrorActionPreference = "Stop"
$Kb = (Resolve-Path $Kb).Path
& $Kb --version | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "$Kb --version failed"
}

$action = New-ScheduledTaskAction `
    -Execute (Join-Path $env:SystemRoot "System32\conhost.exe") `
    -Argument "--headless `"$Kb`" sync"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 15)
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask -TaskName kb-sync `
    -Description "Synchronize the knowledge base every 15 minutes" `
    -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Force | Out-Null
Write-Output "Registered kb-sync: $Kb sync every 15 minutes"
