$action = New-ScheduledTaskAction -Execute "wsl.exe" -Argument "-d Debian -- bash /mnt/c/tmp/wasm_start.sh"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "user"
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -StartWhenAvailable
Register-ScheduledTask -TaskName "LaForge\wasmedge_cervelet" -Action $action -Trigger $trigger -Settings $settings -RunLevel Limited -Force
Write-Output "Task created"
Get-ScheduledTask -TaskName "wasmedge_cervelet" -TaskPath "\LaForge\" -ErrorAction SilentlyContinue | Select-Object TaskName, State
