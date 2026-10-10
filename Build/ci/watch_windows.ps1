# The heartbeat and the stall watchdog of the Windows CI (the counterpart of Build/ci/watch.sh): started by ci_run_windows.ps1 as a second process that shares its console, it watches the process
# tree of the script it was started by.
#
#   powershell -NoProfile -File watch_windows.ps1 -ParentPid <pid> [-StallSeconds 300] [-IntervalSeconds 60] [-WatchDirs "<folder>;<folder>"] [-Stamp <file>]
#
# A line every interval: time, how long the script has run, seconds without activity, CPU in use, free memory, the biggest process of the tree. ACTIVITY is any of: the tree (the script and everything it
# started) used CPU (>= 1 s in the interval), or a file in one of -WatchDirs changed in the interval (the build logs, the results, the logs of the tests). No activity for -StallSeconds is a stall:
# the process tree is printed, everything the script started is killed (not the script itself, so the stage fails and the run still writes its report) and the file -Stamp tells why.
param(
    [Parameter(Mandatory)][int]$ParentPid,
    [int]$StallSeconds = 300,
    [int]$IntervalSeconds = 60,
    [string]$WatchDirs = '',                                   # folders, separated by ;
    [string]$Stamp = ''
)
$ErrorActionPreference = 'SilentlyContinue'
$me = $PID

function Get-Tree([int]$Root) {                               # the pids of everything the root started (not the root, not this watchdog)
    $all = Get-CimInstance Win32_Process | Select-Object ProcessId, ParentProcessId, Name
    $found = New-Object System.Collections.Generic.List[int]
    $queue = New-Object System.Collections.Generic.Queue[int]; $queue.Enqueue($Root)
    while ($queue.Count) {
        $p = $queue.Dequeue()
        foreach ($c in $all | Where-Object { $_.ParentProcessId -eq $p -and $_.ProcessId -ne $me }) { $found.Add($c.ProcessId); $queue.Enqueue($c.ProcessId) }
    }
    $found
}
function Get-Cpu([int[]]$Pids) {                              # seconds of CPU used so far by those processes
    $t = 0.0; foreach ($p in $Pids) { $x = (Get-Process -Id $p).TotalProcessorTime; if ($x) { $t += $x.TotalSeconds } }; $t
}
function Newest-File {
    $best = [datetime]::MinValue
    foreach ($d in ($WatchDirs -split ';' | Where-Object { $_ })) { if (Test-Path $d) { $f = Get-ChildItem $d -Recurse -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1; if ($f -and $f.LastWriteTime -gt $best) { $best = $f.LastWriteTime } } }
    $best
}

$start = Get-Date; $lastActive = $start; $lastNewest = Newest-File; $cpu0 = Get-Cpu (Get-Tree $ParentPid)
while (Get-Process -Id $ParentPid -ErrorAction SilentlyContinue) {
    Start-Sleep -Seconds $IntervalSeconds
    if (-not (Get-Process -Id $ParentPid -ErrorAction SilentlyContinue)) { break }
    $tree = @(Get-Tree $ParentPid)
    $cpu1 = Get-Cpu $tree
    if (($cpu1 - $cpu0) -ge 1.0) { $lastActive = Get-Date }                                   # (a process that ended takes its CPU time away: only growth counts)
    $cpu0 = [math]::Max($cpu1, 0)
    $newest = Newest-File; if ($newest -gt $lastNewest) { $lastActive = Get-Date; $lastNewest = $newest }
    $idle = [int]((Get-Date) - $lastActive).TotalSeconds
    $os = Get-CimInstance Win32_OperatingSystem
    $freeMb = [int]($os.FreePhysicalMemory / 1024); $cpuPct = [int](Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average
    $top = $tree | ForEach-Object { Get-Process -Id $_ } | Sort-Object WorkingSet64 -Descending | Select-Object -First 1
    $topText = if ($top) { "$($top.ProcessName) $([int]($top.WorkingSet64 / 1MB))MB" } else { '-' }
    Write-Host ("{0} [heartbeat] ci {1:00}:{2:00} idle {3}s cpu {4}% mem-free {5}MB top {6}" -f (Get-Date -Format 'HH:mm:ss'), [int]((Get-Date) - $start).TotalMinutes, ((Get-Date) - $start).Seconds, $idle, $cpuPct, $freeMb, $topText)
    if ($idle -ge $StallSeconds -and $tree.Count -gt 0) {
        Write-Host "=== STALLED: no CPU use and no file changes for $idle s; the process tree:"
        foreach ($p in $tree) { $x = Get-Process -Id $p; if ($x) { Write-Host ("  {0,6} {1,-28} {2,7:N1}s CPU {3,6}MB" -f $x.Id, $x.ProcessName, $x.TotalProcessorTime.TotalSeconds, [int]($x.WorkingSet64 / 1MB)) } }
        if ($Stamp) { "STALLED after $idle s without CPU or file activity: $(Get-Date -Format o)" | Set-Content $Stamp }
        foreach ($p in ($tree | Sort-Object -Descending)) { Stop-Process -Id $p -Force }       # the newest processes first
        Write-Host "=== killed $($tree.Count) process(es): the stage fails and the run goes on"
        $lastActive = Get-Date
    }
}
