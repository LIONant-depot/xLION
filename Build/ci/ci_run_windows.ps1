# xLION CI on Windows (the Jenkins agent "pc-agent"): update the repos, build the editor with MSBuild, run the smoke tests with the window editor (the agent must run in a logged-in desktop session).
#
#   powershell -File Build\ci\ci_run_windows.ps1 -Tier fast|full -Tree D:\xlion-ci\tree -Results <dir> [-Scratch] [-Force] [-Sanitize [-Config auto|Debug|Release]]
#
# -Sanitize: the MSVC AddressSanitizer build (Build/jenkins/Jenkinsfile.windows_sanitize) in its own build folder Build\xLION.vs2022-asan of the same tree: /fsanitize=address /Zi,
# no /RTC1, /INCREMENTAL:NO (Build\ci\msvc_asan.cmake, given to the configure as CMAKE_PROJECT_xLION_INCLUDE), the AddressSanitizer runtime DLLs copied next to the exes. One
# configuration is built and tested (-Config; auto = Release on the Sunday run, from 03:00 Singapore time, Debug otherwise). The verdict is the NEW findings (Build/ci/sanitize_report.py
# against sanitizer_baseline_windows[_release].txt). MSVC has no UBSan and no -fsanitize-recover: the first report ends that process (one asan.<pid> log per process).
#
# Writes the same results as Build/ci/ci_run.sh (status.txt, description.txt, summary.md, suite.xml, stages.tsv, changed.txt), so the job pages look the same.
# No tree lock: the PC has one executor. The known-failure list is shared with Linux only where a test fails on both; Windows has none of its own yet.
param(
    [ValidateSet('fast', 'full')][string]$Tier = 'full',
    [Parameter(Mandatory)][string]$Tree,
    [Parameter(Mandatory)][string]$Results,
    [ValidateSet('auto', 'debug', 'both', 'no')][string]$Tests = 'auto',     # which builds are tested: debug; both (Debug and Release); no (no tests at all: only the builds, no Python needed); auto = debug, and both on the Sunday run that starts at 11:00 or later (Singapore time, the 12:00 job)
    [switch]$Scratch,
    [switch]$Force,
[switch]$Sanitize,
[ValidateSet('auto', 'Debug', 'Release')][string]$Config = 'auto'
)
$ErrorActionPreference = 'Continue'
$GitBase = if ($env:GIT_BASE) { $env:GIT_BASE } else { 'https://github.com/LIONant-depot' }
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Base = Split-Path -Parent $Tree
New-Item -ItemType Directory -Force $Results, $Base | Out-Null
# the results folder is the job's workspace and outlives the run: what an earlier run left there must not be reported as this run's (a run that stopped at the build would
# summarize the suite.xml of the last run that got to the tests). timing.log stays: the test timing keeps the previous one
'suite.xml', 'suite_release.xml', 'summary.md', 'description.txt', 'status.txt', 'new_failures.txt', 'fixed.txt', 'failed_now.txt', 'timing.tsv', 'compile_wait.log', 'compile_editor.log', `
    'compile_editor_err.log', 'build_compilers.log', 'changed.txt', 'manifest.txt', 'smoke_logs.tgz', 'sanitizer.md', 'sanitizer_status.txt', 'sanitizer_all.txt', 'sanitizer_new.txt', 'sanitizer_logs.tgz' |
    ForEach-Object { Remove-Item (Join-Path $Results $_) -Force -ErrorAction SilentlyContinue }
$Stages = Join-Path $Results 'stages.tsv'; '' | Set-Content $Stages
$BDir = if ($Sanitize) { 'xLION.vs2022-asan' } else { 'xLION.vs2022' }          # the build folder under Build\
$sgNow = [System.TimeZoneInfo]::ConvertTime((Get-Date), [System.TimeZoneInfo]::FindSystemTimeZoneById('Singapore Standard Time'))
$SanCfg = if ($Config -ne 'auto') { $Config } elseif ($sgNow.DayOfWeek -eq 'Sunday' -and $sgNow.Hour -ge 3) { 'Release' } else { 'Debug' }
$MSBuild = & "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe" -latest -version '[17.0,18.0)' -requires Microsoft.Component.MSBuild -find 'MSBuild\**\Bin\MSBuild.exe' | Select-Object -First 1
if (-not $MSBuild) { $MSBuild = 'D:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe' }

# The heartbeat and the stall watchdog (Build\ci\watch_windows.ps1): a second process that shares this console, watches everything this script starts, prints a line a minute and, when nothing used CPU and
# no log or result file changed for 5 minutes, prints the process tree and kills what this script started (the stage fails, the run goes on).
Start-Process powershell -NoNewWindow -ArgumentList '-NoProfile', '-File', "`"$Here\watch_windows.ps1`"", '-ParentPid', $PID, '-StallSeconds', '300', '-WatchDirs', "`"$Results;$Tree\source\Editors\LevelEditor\smoke\.logs`"", '-Stamp', "`"$Results\stalled.txt`"" | Out-Null
function Stage([string]$Name, [scriptblock]$Body) {         # runs it, records the time and the result in stages.tsv
    Write-Host "`n=================== $Name ($(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')) ==================="
    $t0 = Get-Date
    $ok = $false
    try { $ok = [bool](& $Body) } catch { Write-Host "error: $_" }
    "{0}`t{1}`t{2}" -f $Name, [int]((Get-Date) - $t0).TotalSeconds, $(if ($ok) { 'ok' } else { 'FAILED' }) | Add-Content $Stages
    return $ok
}
function Write-Manifest {                                 # "<commit> <repo>" for every repo of the tree, as the Linux CI writes it: the history (Build\ci\history.py) bisects with it
    $repos = @($Tree, "$Tree\example.lionprj") + @(Get-ChildItem "$Tree\example.lionprj\Cache\dependencies", "$Tree\example.lionprj\Cache\Plugins" -Directory -ErrorAction SilentlyContinue | ForEach-Object FullName)
    $repos | Where-Object { Test-Path "$_\.git" } | ForEach-Object { "$(git -C $_ rev-parse HEAD 2>$null) $(if ($_ -eq $Tree) { 'xLION' } else { Split-Path -Leaf $_ })" } | Set-Content "$Results\manifest.txt"
}
function Finish {
    Write-Manifest
    $stopped = (Test-Path "$Results\status.txt") -and ((Get-Content "$Results\status.txt" -Raw).Trim() -eq 'FAILED')     # the run stopped before the tests (Fail): that is its verdict, not a test report
    $py = if (Test-Path "$Base\venv\Scripts\python.exe") { "$Base\venv\Scripts\python.exe" } else { 'python' }
    & $py "$Here\summarize.py" --junit "$Results\suite.xml" --out $Results --tier $Tier --known "$Here\known_failures_windows.txt" `
        --changed "$Results\changed.txt" --stages $Stages --title "xLION windows $Tier run $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" *> $null
    if ($stopped) {
        $at = Get-Content $Stages | Where-Object { $_ -match "`t" -and ($_ -split "`t")[2] -ne 'ok' } | Select-Object -First 1 | ForEach-Object { $f = $_ -split "`t"; "$($f[0]) $($f[2])" }
        'FAILED' | Set-Content "$Results\status.txt"
        "The run stopped before the tests: $(if ($at) { $at } else { 'see the console log' })" | Set-Content "$Results\description.txt"
        "# The run stopped before the tests`n`n$(if ($at) { $at } else { 'The reason is in the console log' }). No test ran: see the build logs and the console log." | Set-Content "$Results\summary.md"
    }
    $buildFailed = [bool](Select-String -Path $Stages -Pattern "^(update repos|build)`t.*`tFAILED" -Quiet)
    if ($Sanitize -and -not $buildFailed) {             # the verdict of a sanitizer run is its findings (a run whose update or build FAILED stays FAILED)
        $bl = "$Here\sanitizer_baseline_windows$(if ($SanCfg -eq 'Release') { '_release' }).txt"
        & $py "$Here\sanitize_report.py" --logs "$Results\sanitizer" --out $Results --baseline $bl
        if (Test-Path "$Results\sanitizer_status.txt") {
            Copy-Item "$Results\sanitizer_status.txt" "$Results\status.txt" -Force
            (Get-Content "$Results\sanitizer.md")[2] | Set-Content "$Results\description.txt"
            Copy-Item "$Results\sanitizer.md" "$Results\summary.md" -Force
        }
        if (Test-Path "$Results\sanitizer") { tar -czf "$Results\sanitizer_logs.tgz" -C $Results sanitizer 2>$null }
    }
    Write-Host "`nstatus: $(if (Test-Path "$Results\status.txt") { Get-Content "$Results\status.txt" } else { 'unknown' })"
    if (Test-Path "$Results\summary.md") { Get-Content "$Results\summary.md" }
}
function Fail([string]$Why) { Write-Host $Why; 'FAILED' | Set-Content "$Results\status.txt"; Finish; exit 1 }
if (-not (Test-Path "$Here\known_failures_windows.txt")) { '# failures that are known on Windows (none yet)' | Set-Content "$Here\known_failures_windows.txt" }

# ---------------------------------------------------------------------------------------------------------------- update
$changed = New-Object System.Collections.Generic.List[string]
# the names of the pinned third party libraries (read from the tree's Build\third_party.txt; before the first checkout there is nothing to protect)
$ThirdPartyNames = @(); if (Test-Path "$Tree\Build\third_party.txt") { $ThirdPartyNames = @(Get-Content "$Tree\Build\third_party.txt" | ForEach-Object { ($_ -split '\s+')[0] } | Where-Object { $_ -and -not $_.StartsWith('#') }) }
function Update-Repo([string]$Dir) {                      # a repo that follows a branch (ours: main) is moved to its newest commit; a pinned (detached) one is left alone
    if (-not (Test-Path "$Dir\.git")) { return }
    # a third party library is never moved here, whatever branch it is on: it is pinned (Build\third_party.txt) and the configure patches some of them; a "reset --hard" would undo the patch
    if ($ThirdPartyNames -contains (Split-Path -Leaf $Dir)) { return }
    $branch = git -C $Dir symbolic-ref -q --short HEAD 2>$null
    if (-not $branch) { return }
    $old = git -C $Dir rev-parse HEAD
    git -C $Dir fetch -q --depth 1 origin $branch 2>$null
    if ($LASTEXITCODE -ne 0) { return }
    git -C $Dir reset -q --hard FETCH_HEAD
    $new = git -C $Dir rev-parse HEAD
    if ($old -ne $new) { $changed.Add("$(Split-Path -Leaf $Dir) $($new.Substring(0,9)) $(git -C $Dir log -1 --format=%s)") }
}
$ok = Stage 'update repos' {
    if ($Scratch -and (Test-Path $Tree)) { Remove-Item -Recurse -Force $Tree }
    if (-not (Test-Path "$Tree\.git")) { git clone -q --depth 1 --branch main "$GitBase/xLION.git" $Tree; if ($LASTEXITCODE -ne 0) { return $false } }
    $dirs = @($Tree, "$Tree\example.lionprj") + @(Get-ChildItem "$Tree\example.lionprj\Cache\dependencies", "$Tree\example.lionprj\Cache\Plugins" -Directory -ErrorAction SilentlyContinue | ForEach-Object FullName)
    $dirs += "$Tree\Build\$BDir\_deps\xcmake_tools"        # the CMake helpers: an old copy would not know the pinned commits of Build\third_party.txt
    $dirs | ForEach-Object { Update-Repo $_ }
    # the example project is shared by every run: put it back exactly as GitHub has it (Cache/ is never touched)
    if (Test-Path "$Tree\example.lionprj\.git") { git -C "$Tree\example.lionprj" clean -fdq -- Descriptors Project.config Assets }
    $true
}
if (-not $ok) { Fail 'update failed' }
$changed | Set-Content "$Results\changed.txt"
Write-Host "repos changed since the last run: $($changed.Count)"; $changed | Select-Object -First 20 | ForEach-Object { Write-Host $_ }

# ---------------------------------------------------------------------------------------------------------------- build
$ok = Stage 'build' {
    # configured = the marker that is written when a configure ENDED WELL. A failed configure still leaves xLION.sln and half the projects on the disk (the xLION target without its
    # ImGui sources: the link then fails with hundreds of unresolved ImGui:: symbols), which is not a configured tree.
    $Marker = "$Tree\Build\$BDir\.configured_ok"
    # the marker holds what the configure was made with: the pinned third party commits and the xcmake_tools commit. A change of either means the configure runs again (it fetches the pinned commits and patches them).
    # It also holds the CMake files of our own repos (the blob ids git already has, so nothing is read): xcmake_tools' Common.cmake sets CMAKE_SUPPRESS_REGENERATION, there is
    # no ZERO_CHECK, so a CMakeLists.txt that changed (xLIONRender got the include directory dependencies\xGPU on Oct 13) only reaches the projects by a configure. Without it
    # the projects stayed as the configure of Oct 11 made them: "Cannot open include file: 'source/xGPU.h'".
    function Get-CMakeInputs {
        $repos = @($Tree, "$Tree\example.lionprj") + @(Get-ChildItem "$Tree\example.lionprj\Cache\dependencies", "$Tree\example.lionprj\Cache\Plugins" -Directory -ErrorAction SilentlyContinue | ForEach-Object FullName)
        $list = $repos | Where-Object { Test-Path "$_\.git" } | ForEach-Object { git -C $_ ls-files -s -- '*CMakeLists.txt' '*.cmake' 2>$null }
        $sha = [Security.Cryptography.SHA256]::Create()
        [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes(($list -join "`n")))) -replace '-', ''
    }
    function Get-Stamp { "v4 $((Get-FileHash "$Tree\Build\third_party.txt").Hash) $(git -C "$Tree\Build\$BDir\_deps\xcmake_tools" rev-parse HEAD 2>$null) $(Get-CMakeInputs)$(if ($Sanitize) { ' asan' })" }
    if (-not (Test-Path $Marker) -or (Get-Content $Marker -Raw).Trim() -ne (Get-Stamp)) {            # first run: what Build\CreateProject.bat does, without its admin prompt and pause
        Push-Location "$Tree\Build"; $sanArgs = if ($Sanitize) { @('-DXLION_SANITIZE=ON', "-DCMAKE_PROJECT_xLION_INCLUDE=$($Here -replace '\\', '/')/msvc_asan.cmake") } else { @() }
        $sanArgs += '-DXLION_ECS_LINK_GATE=ON'         # the target xLION_ecs_gate (EXCLUDE_FROM_ALL: only test_ecs_gate.py builds it); without it the link gate test fails with "the target does not exist"
        cmake ../ -G 'Visual Studio 17 2022' -A x64 -B $BDir @sanArgs 2>&1 | Tee-Object -FilePath "$Results\cmake.log" | ForEach-Object { Write-Host $_ }       # live: the console shows the clones and the configure as they happen
        $rc = $LASTEXITCODE; Pop-Location
        if ($rc -ne 0) { Write-Host 'cmake configure failed (see the last lines above; a symbolic link error means Developer Mode is off on the PC)'; return $false }
        Set-Content $Marker (Get-Stamp)
    }
    $buildCfgs = if ($Sanitize) { @($SanCfg) } else { @('Debug', 'Release') }
    foreach ($cfg in $buildCfgs) {                         # both are the standard builds: both are built, the tests run on Debug (the sanitizer run: its one configuration)
        $out = "$Results\build_${cfg}_console.log"
        $p = Start-Process -FilePath $MSBuild -PassThru -NoNewWindow -RedirectStandardOutput $out -ArgumentList "`"$Tree\Build\$BDir\xLION.sln`" /t:xLION;xLION_Headless;xeditorcli /p:Configuration=$cfg /m /nologo /v:m /flp:logfile=$Results\build_$cfg.log;verbosity=minimal"
        $null = $p.Handle                              # without this a process started with -PassThru can report an empty ExitCode (which is not 0: the build would be called failed)
        $n = 0
        while (-not $p.WaitForExit(60000)) {          # a line a minute, so the console shows it is alive: the projects finished so far and the last one (the full output is build_<config>.log)
            $n++; $lines = @(Get-Content $out -ErrorAction SilentlyContinue)
            Write-Host ("{0} build {1}: {2} min, {3} outputs finished, last: {4}" -f (Get-Date -Format 'HH:mm:ss'), $cfg, $n, ($lines | Where-Object { $_ -match ' -> ' }).Count, ($lines | Select-Object -Last 1))
        }
        $p.WaitForExit()
        Get-Content $out -Tail 8 | ForEach-Object { Write-Host $_ }
        Write-Host "build ${cfg}: MSBuild exit code [$($p.ExitCode)]"
        if ($p.ExitCode -ne 0) { Copy-Item "$Results\build_$cfg.log" "$Results\build.log" -Force -ErrorAction SilentlyContinue; return $false }
        if ($Sanitize) {                                # the AddressSanitizer runtime next to the exes (Debug /MDd uses the _dbg_ one): from the bin folder of the cl.exe the configure chose
            $cc = Get-ChildItem "$Tree\Build\$BDir\CMakeFiles\*\CMakeCXXCompiler.cmake" | Select-Object -First 1     # the Visual Studio generator does not cache the compiler path
            $cl = (Select-String -Path $cc.FullName -Pattern 'set\(CMAKE_CXX_COMPILER "([^"]+)"').Matches[0].Groups[1].Value
            $dlls = @(Get-ChildItem "$(Split-Path -Parent $cl)\clang_rt.asan*_dynamic-x86_64.dll")
            if (-not $dlls) { Write-Host "no AddressSanitizer runtime next to $cl (the VS component 'C++ AddressSanitizer' is not installed)"; return $false }
            $dlls | Copy-Item -Destination "$Tree\Build\$BDir\$cfg" -Force
            Write-Host "copied $($dlls.Name -join ', ') to $Tree\Build\$BDir\$cfg"
        }
    }
    # The resource compilers (one exe per plugin, run by the resource pipeline and by the tests) are separate CMake projects that Install.bat only builds when missing:
    # without this a plugin change never reaches them on this tree (the Linux run builds them every time: the target xlion_compilers). Incremental: an unchanged one is not relinked.
    foreach ($dir in Get-ChildItem "$Tree\example.lionprj\Cache\Plugins\*\build\*_compiler.vs2022" -Directory) {
        foreach ($cfg in 'Debug', 'Release') {
            cmake --build $dir.FullName --config $cfg --target $dir.Name.Replace('.vs2022', '') -- /m /nologo /v:m >> "$Results\build_compilers.log" 2>&1
            if ($LASTEXITCODE -ne 0) { Write-Host "build of the $($dir.Name) compiler ($cfg) failed (see build_compilers.log)"; Copy-Item "$Results\build_compilers.log" "$Results\build.log" -Force; return $false }
        }
    }
    Write-Host "resource compilers built: $((Get-ChildItem "$Tree\example.lionprj\Cache\Plugins\*\build\*_compiler.vs2022" -Directory).Count)"
    $true
}
if (-not $ok) { if (Test-Path "$Results\build.log") { Select-String -Path "$Results\build.log" -Pattern ' error ' | Select-Object -First 20 | ForEach-Object { Write-Host $_.Line } }; Fail 'build failed' }

# ---------------------------------------------------------------------------------------------------------------- no tests: the builds are the whole run
if ($Tests -eq 'no') {
    'BUILD-OK' | Set-Content "$Results\status.txt"
    'Debug and Release built; no tests were asked for (Tests=no)' | Set-Content "$Results\description.txt"
    "# Builds only`n`nDebug and Release were built. No tests were run (Tests=no)." | Set-Content "$Results\summary.md"
    Write-Host 'status: BUILD-OK (builds only, no tests)'
    exit 0
}

# ---------------------------------------------------------------------------------------------------------------- python
$ok = Stage 'python (pytest)' {
    if (-not (Test-Path "$Base\venv\Scripts\python.exe")) {
        # a real Python 3: the "py" launcher (python.org) or "python" on the PATH. The Microsoft Store shortcut named python.exe is not one (it prints "Python was not found...").
        $pyCmd = $null                      # (not $base: PowerShell variables ignore case, $base would be $Base, the folder of the CI)
        foreach ($cand in @(@('py', '-3'), @('python'))) {
            $exe = $cand[0]; $extra = @($cand | Select-Object -Skip 1)
            if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
            $v = & $exe @extra --version 2>&1 | Out-String
            if ($v -match '^Python 3\.') { $pyCmd = @($exe) + $extra; break }
        }
        if (-not $pyCmd) { Write-Host 'No Python 3 on this PC. Install it (winget install -e --id Python.Python.3.12), turn off the Microsoft Store shortcuts for python.exe in Settings > Apps > Advanced app settings > App execution aliases, and restart the Jenkins agent.'; return $false }
        Write-Host "python: $($pyCmd -join ' ')"
        & $pyCmd[0] @($pyCmd | Select-Object -Skip 1) -m venv "$Base\venv"
        if ($LASTEXITCODE -ne 0) { return $false }
    }
    & "$Base\venv\Scripts\python.exe" -c 'import pytest, pytest_timeout' 2>$null
    if ($LASTEXITCODE -ne 0) { & "$Base\venv\Scripts\pip.exe" install -q pytest pytest-timeout }
    $LASTEXITCODE -eq 0
}
if (-not $ok) { Fail 'python failed' }

# ---------------------------------------------------------------------------------------------------------------- resources
if ($Sanitize) {        # one log per process (asan.<pid>); the path is quoted: AddressSanitizer splits its options at every colon, the one of D: included
    New-Item -ItemType Directory -Force "$Results\sanitizer" | Out-Null; Remove-Item "$Results\sanitizer\*" -Force -ErrorAction SilentlyContinue
    $env:ASAN_OPTIONS = "log_path='$Results\sanitizer\asan':symbolize=1:print_cmdline=1"
}
# let the resources compile first: an editor on the project until the compile queue is empty, so the tests do not fight over it (a cold cache is the long case, a warm one is seconds)
$null = Stage 'resources compile' {
    $bin = "$Tree\Build\$BDir\$(if ($Sanitize) { $SanCfg } else { 'Debug' })"; $log = "$Results\compile_wait.log"
    $env:XEDITOR_NO_ASSERT_DIALOG = '1'
    $ed = Start-Process -FilePath "$bin\xLION_Headless.exe" -ArgumentList "`"$Tree\example.lionprj`"" -PassThru -RedirectStandardOutput "$Results\compile_editor.log" -RedirectStandardError "$Results\compile_editor_err.log"
    $idle = 0; $polls = 0; $start = Get-Date
    Start-Sleep -Seconds 10
    while (((Get-Date) - $start).TotalMinutes -lt 45 -and -not $ed.HasExited) {          # at most 45 minutes
        $s = (& "$bin\xeditorcli.exe" CompileStatus 2>&1 | Select-Object -First 1) -as [string]
        $polls++; "$(Get-Date -Format 'HH:mm:ss') $s" | Add-Content $log
        if ($polls % 6 -eq 1) { Write-Host "$(Get-Date -Format 'HH:mm:ss') resources: $s" }          # a line a minute on the console too
        if ($s -match '^Compiling=0 Waiting=0') { $idle++ } else { $idle = 0 }
        if ($idle -ge 3) { break }
        Start-Sleep -Seconds 10
    }
    Write-Host "compile queue idle after $([int]((Get-Date) - $start).TotalSeconds) s ($polls polls)"
    & "$bin\xeditorcli.exe" Exit *> $null
    if (-not $ed.WaitForExit(120000)) { $ed.Kill() }
    $idle -ge 3
}

# ---------------------------------------------------------------------------------------------------------------- tests
$sg = [System.TimeZoneInfo]::ConvertTime((Get-Date), [System.TimeZoneInfo]::FindSystemTimeZoneById('Singapore Standard Time'))
$configs = @('Debug')                         # the daily smoke tests run on Debug only (asserts exist only there); Release is built, so a Release-only compile or link error is caught
if ($Tests -eq 'both' -or ($Tests -eq 'auto' -and $sg.DayOfWeek -eq 'Sunday' -and $sg.Hour -ge 11)) { $configs += 'Release' }
if ($Sanitize) { $configs = @($SanCfg) }      # the sanitizer run tests the configuration it built
foreach ($cfg in $configs) {
$Bin = "$Tree\Build\$BDir\$cfg"
$Xml = if ($cfg -eq 'Debug') { "$Results\suite.xml" } else { "$Results\suite_release.xml" }     # the verdict and the summary follow Debug; Release is reported next to it
$null = Stage "tests ($Tier, $cfg)" {
    $smoke = "$Tree\source\Editors\LevelEditor\smoke"
    $files = @('.'); $desel = @()
    if ($Tier -eq 'fast') {
        $files = Get-Content "$Here\fast_files.txt" | ForEach-Object { ($_ -replace '#.*', '').Trim() } | Where-Object { $_ }
        $desel = Get-Content "$Here\fast_deselect.txt" | ForEach-Object { ($_ -replace '#.*', '').Trim() } | Where-Object { $_ } | ForEach-Object { '--deselect'; $_ }
    }
    Remove-Item -Recurse -Force "$smoke\.logs" -ErrorAction SilentlyContinue
    Push-Location $smoke
    $env:XLION_PROJECT = "$Tree\example.lionprj"; $env:XEDITOR_NO_ASSERT_DIALOG = '1'
    & "$Base\venv\Scripts\python.exe" -m pytest @files @desel -p no:cacheprovider --exe "$Bin\xLION.exe" --timeout=300 --timeout-method=thread `
        -o junit_family=xunit2 -o junit_logging=all -o junit_log_passed_tests=false --junitxml="$Xml" -rfE --tb=short -v
    Pop-Location
    $true                                                   # failing tests are the summary's business, not the run's
}
}
if (Test-Path "$Tree\source\Editors\LevelEditor\smoke\.logs") { tar -czf "$Results\smoke_logs.tgz" -C "$Tree\source\Editors\LevelEditor\smoke" .logs 2>$null }
Finish
exit 0
