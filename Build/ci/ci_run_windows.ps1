# xLION CI on Windows (the Jenkins agent "pc-agent"): update the repos, build the editor with MSBuild, run the smoke tests with the window editor (the agent must run in a logged-in desktop session).
#
#   powershell -File Build\ci\ci_run_windows.ps1 -Tier fast|full -Tree D:\xlion-ci\tree -Results <dir> [-Scratch] [-Force]
#
# Writes the same results as Build/ci/ci_run.sh (status.txt, description.txt, summary.md, suite.xml, stages.tsv, changed.txt), so the job pages look the same.
# No tree lock: the PC has one executor. The known-failure list is shared with Linux only where a test fails on both; Windows has none of its own yet.
param(
    [ValidateSet('fast', 'full')][string]$Tier = 'full',
    [Parameter(Mandatory)][string]$Tree,
    [Parameter(Mandatory)][string]$Results,
    [ValidateSet('auto', 'yes', 'no')][string]$ReleaseTests = 'auto',     # auto: the Sunday run that starts at 11:00 or later (Singapore time, the 12:00 job) also tests the Release build
    [switch]$Scratch,
    [switch]$Force
)
$ErrorActionPreference = 'Continue'
$GitBase = if ($env:GIT_BASE) { $env:GIT_BASE } else { 'https://github.com/LIONant-depot' }
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Base = Split-Path -Parent $Tree
New-Item -ItemType Directory -Force $Results, $Base | Out-Null
$Stages = Join-Path $Results 'stages.tsv'; '' | Set-Content $Stages
$MSBuild = & "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe" -latest -requires Microsoft.Component.MSBuild -find 'MSBuild\**\Bin\MSBuild.exe' | Select-Object -First 1
if (-not $MSBuild) { $MSBuild = 'D:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe' }

function Stage([string]$Name, [scriptblock]$Body) {         # runs it, records the time and the result in stages.tsv
    Write-Host "`n=================== $Name ($(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')) ==================="
    $t0 = Get-Date
    $ok = $false
    try { $ok = [bool](& $Body) } catch { Write-Host "error: $_" }
    "{0}`t{1}`t{2}" -f $Name, [int]((Get-Date) - $t0).TotalSeconds, $(if ($ok) { 'ok' } else { 'FAILED' }) | Add-Content $Stages
    return $ok
}
function Finish {
    $py = if (Test-Path "$Base\venv\Scripts\python.exe") { "$Base\venv\Scripts\python.exe" } else { 'python' }
    & $py "$Here\summarize.py" --junit "$Results\suite.xml" --out $Results --tier $Tier --known "$Here\known_failures_windows.txt" `
        --changed "$Results\changed.txt" --stages $Stages --title "xLION windows $Tier run $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" *> $null
    Write-Host "`nstatus: $(if (Test-Path "$Results\status.txt") { Get-Content "$Results\status.txt" } else { 'unknown' })"
    if (Test-Path "$Results\summary.md") { Get-Content "$Results\summary.md" }
}
function Fail([string]$Why) { Write-Host $Why; 'FAILED' | Set-Content "$Results\status.txt"; Finish; exit 1 }
if (-not (Test-Path "$Here\known_failures_windows.txt")) { '# failures that are known on Windows (none yet)' | Set-Content "$Here\known_failures_windows.txt" }

# ---------------------------------------------------------------------------------------------------------------- update
$changed = New-Object System.Collections.Generic.List[string]
function Update-Repo([string]$Dir) {                      # a repo that follows a branch (ours: main) is moved to its newest commit; a pinned (detached) one is left alone
    if (-not (Test-Path "$Dir\.git")) { return }
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
    if (-not (Test-Path "$Tree\Build\xLION.vs2022\xLION.sln")) {            # first run: what Build\CreateProject.bat does, without its admin prompt and pause
        Push-Location "$Tree\Build"; cmake ../ -G 'Visual Studio 17 2022' -A x64 -B xLION.vs2022 *> "$Results\cmake.log"; $rc = $LASTEXITCODE; Pop-Location
        if ($rc -ne 0) { return $false }
    }
    foreach ($cfg in 'Debug', 'Release') {                  # both are the standard builds: both are built, the tests run on Debug
        & $MSBuild "$Tree\Build\xLION.vs2022\xLION.sln" '/t:xLION;xLION_Headless;xeditorcli' "/p:Configuration=$cfg" /m /nologo /v:m "/flp:logfile=$Results\build_$cfg.log;verbosity=minimal"
        if ($LASTEXITCODE -ne 0) { Copy-Item "$Results\build_$cfg.log" "$Results\build.log" -Force; return $false }
    }
    $true
}
if (-not $ok) { Select-String -Path "$Results\build.log" -Pattern ' error ' -ErrorAction SilentlyContinue | Select-Object -First 20 | ForEach-Object { Write-Host $_.Line }; Fail 'build failed' }

# ---------------------------------------------------------------------------------------------------------------- python
$ok = Stage 'python (pytest)' {
    if (-not (Test-Path "$Base\venv\Scripts\python.exe")) { python -m venv "$Base\venv"; if ($LASTEXITCODE -ne 0) { return $false } }
    & "$Base\venv\Scripts\python.exe" -c 'import pytest, pytest_timeout' 2>$null
    if ($LASTEXITCODE -ne 0) { & "$Base\venv\Scripts\pip.exe" install -q pytest pytest-timeout }
    $LASTEXITCODE -eq 0
}
if (-not $ok) { Fail 'python failed' }

# ---------------------------------------------------------------------------------------------------------------- tests
$sg = [System.TimeZoneInfo]::ConvertTime((Get-Date), [System.TimeZoneInfo]::FindSystemTimeZoneById('Singapore Standard Time'))
$configs = @('Debug')                         # the daily smoke tests run on Debug only (asserts exist only there); Release is built, so a Release-only compile or link error is caught
if ($ReleaseTests -eq 'yes' -or ($ReleaseTests -eq 'auto' -and $sg.DayOfWeek -eq 'Sunday' -and $sg.Hour -ge 11)) { $configs += 'Release' }
foreach ($cfg in $configs) {
$Bin = "$Tree\Build\xLION.vs2022\$cfg"
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
