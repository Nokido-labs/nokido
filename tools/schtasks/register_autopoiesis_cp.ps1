# Register schtasks LaForge-AutopoiesisDaily + LaForge-CuriosityCPWeekly
# Run as user. Idempotent (delete + recreate).

$pythonExe = "$env:USERPROFILE\miniforge3\python.exe"
$repoRoot = "$env:USERPROFILE\Script python IA\Nokido"

# Task 1 : Autopoiesis daily dry-run (mesure pression, log)
$task1 = "LaForge-AutopoiesisDaily"
schtasks /Delete /TN $task1 /F 2>$null

$action1 = New-ScheduledTaskAction `
  -Execute $pythonExe `
  -Argument "`"$repoRoot\app\forge_semantic_pressure.py`" --window 7 --execute" `
  -WorkingDirectory $repoRoot
$trigger1 = New-ScheduledTaskTrigger -Daily -At 03:00
$settings1 = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 15) -StartWhenAvailable
Register-ScheduledTask -TaskName $task1 -Action $action1 -Trigger $trigger1 -Settings $settings1 `
  -Description "Autopoiese : mesure pression semantique daily 03h" -Force
Write-Host "Registered: $task1"

# Task 2 : Curiosity CP scan weekly Sunday 04h
$task2 = "LaForge-CuriosityCPWeekly"
schtasks /Delete /TN $task2 /F 2>$null

$action2 = New-ScheduledTaskAction `
  -Execute $pythonExe `
  -Argument "`"$repoRoot\app\forge_curiosity_driver.py`" --n-themes 5" `
  -WorkingDirectory $repoRoot
$trigger2 = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 04:00
$settings2 = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -StartWhenAvailable
Register-ScheduledTask -TaskName $task2 -Action $action2 -Trigger $trigger2 -Settings $settings2 `
  -Description "Curiosity CP scan + log domains stagnants weekly" -Force
Write-Host "Registered: $task2"

# Status
Get-ScheduledTask -TaskName "LaForge-Autopoiesis*", "LaForge-Curiosity*" |
  Format-Table TaskName, State, NextRunTime -AutoSize
