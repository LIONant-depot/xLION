# Self-check of watch_windows.ps1 (about 30 seconds): a tree that does nothing is killed after the stall time, a tree that computes is left alone.
#   powershell -NoProfile -File Build\ci\test_watch_windows.ps1
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$fail = 0
function Check([string]$what, [bool]$ok) { if ($ok) { "ok   $what" } else { "FAIL $what"; $script:fail = 1 } }

# 1. a parent that starts an idle child (ping: waits, no CPU) and waits for it
$idleParent = Start-Process powershell -PassThru -WindowStyle Hidden -ArgumentList '-NoProfile', '-Command', 'ping -n 300 127.0.0.1 | Out-Null'
Start-Sleep -Seconds 3
$dog = Start-Process powershell -PassThru -WindowStyle Hidden -ArgumentList '-NoProfile', '-File', "$here\watch_windows.ps1", '-ParentPid', $idleParent.Id, '-StallSeconds', '6', '-IntervalSeconds', '2'
$idleParent.WaitForExit(40000) | Out-Null
Check 'a tree that sleeps is stalled and killed (its parent ends)' $idleParent.HasExited
Check 'the idle child is gone' (-not (Get-Process ping -ErrorAction SilentlyContinue | Where-Object { $_.StartTime -gt (Get-Date).AddMinutes(-2) }))
Stop-Process -Id $dog.Id -Force -ErrorAction SilentlyContinue

# 2. a parent whose child computes for 15 seconds: not touched
$busyParent = Start-Process powershell -PassThru -WindowStyle Hidden -ArgumentList '-NoProfile', '-Command', 'powershell -NoProfile -Command "$e=(Get-Date).AddSeconds(15); while((Get-Date) -lt $e){ 1..2000 | % { [math]::Sqrt($_) } | Out-Null }"'
Start-Sleep -Seconds 3
$dog2 = Start-Process powershell -PassThru -WindowStyle Hidden -ArgumentList '-NoProfile', '-File', "$here\watch_windows.ps1", '-ParentPid', $busyParent.Id, '-StallSeconds', '6', '-IntervalSeconds', '2'
$busyParent.WaitForExit(60000) | Out-Null
Check 'a tree that computes is left alone (it ends by itself, exit 0)' ($busyParent.HasExited -and $busyParent.ExitCode -eq 0)
Stop-Process -Id $dog2.Id -Force -ErrorAction SilentlyContinue
exit $fail
