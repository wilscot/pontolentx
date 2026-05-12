param(
    [string]$RepoPath = "C:\apps\pontolentx-main",
    [string]$Remote = "origin",
    [string]$Branch = "main",
    [int]$Port = 5000,
    [switch]$IgnoreMinuteGate
)

$ErrorActionPreference = "Stop"

function Write-DeployLog {
    param([string]$Message)

    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$stamp] $Message"
    Add-Content -LiteralPath $script:LogFile -Value $line -Encoding UTF8
}

function Invoke-Git {
    param([string[]]$Arguments)

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & git @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    if ($exitCode -ne 0) {
        throw "git $($Arguments -join ' ') failed: $($output -join [Environment]::NewLine)"
    }
    return $output
}

function Invoke-Native {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & $FilePath @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    if ($exitCode -ne 0) {
        throw "$FilePath $($Arguments -join ' ') failed with exit code ${exitCode}: $($output -join [Environment]::NewLine)"
    }
    return $output
}

function Stop-Pontolentx {
    $targets = New-Object System.Collections.Generic.HashSet[int]

    try {
        Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            ForEach-Object { [void]$targets.Add([int]$_.OwningProcess) }
    } catch {
        Write-DeployLog "Could not inspect port ${Port}: $($_.Exception.Message)"
    }

    $escapedRepo = [regex]::Escape($RepoPath)
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.ProcessId -ne $PID -and
            $_.CommandLine -and
            $_.CommandLine -match $escapedRepo -and
            ($_.CommandLine -match "tray_launcher\.py" -or $_.CommandLine -match "--service")
        } |
        ForEach-Object { [void]$targets.Add([int]$_.ProcessId) }

    foreach ($pidToStop in $targets) {
        if ($pidToStop -le 0 -or $pidToStop -eq $PID) {
            continue
        }

        try {
            Stop-Process -Id $pidToStop -Force -ErrorAction Stop
            Write-DeployLog "Stopped process PID $pidToStop"
        } catch {
            Write-DeployLog "Could not stop PID ${pidToStop}: $($_.Exception.Message)"
        }
    }

    Start-Sleep -Seconds 2
}

function Start-Pontolentx {
    $startScript = Join-Path $RepoPath "start_pontolentx.cmd"
    if (-not (Test-Path -LiteralPath $startScript)) {
        throw "Start script not found: $startScript"
    }

    $taskName = "Pontolentx Runtime Start"
    $user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $action = New-ScheduledTaskAction -Execute $startScript -WorkingDirectory $RepoPath
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5)
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest

    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null
    Start-ScheduledTask -TaskName $taskName
    Write-DeployLog "Start task issued"
}

function Test-PontolentxPort {
    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $deadline) {
        $ok = Test-NetConnection -ComputerName "127.0.0.1" -Port $Port -InformationLevel Quiet -WarningAction SilentlyContinue
        if ($ok) {
            return $true
        }
        Start-Sleep -Seconds 1
    }
    return $false
}

$repoItem = Get-Item -LiteralPath $RepoPath
$RepoPath = $repoItem.FullName
$dataDir = Join-Path $RepoPath "data"
New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
$script:LogFile = Join-Path $dataDir "deploy.log"
$lockPath = Join-Path $dataDir "deploy.lock"

if (-not $IgnoreMinuteGate -and ((Get-Date).Minute % 2) -ne 0) {
    Write-DeployLog "Skipped: odd minute gate"
    exit 0
}

if (Test-Path -LiteralPath $lockPath) {
    $lock = Get-Item -LiteralPath $lockPath
    if ($lock.LastWriteTime -gt (Get-Date).AddMinutes(-30)) {
        Write-DeployLog "Skipped: deploy already running"
        exit 0
    }
    Remove-Item -LiteralPath $lockPath -Recurse -Force
    Write-DeployLog "Removed stale lock"
}

New-Item -ItemType Directory -Path $lockPath -ErrorAction Stop | Out-Null

$stoppedForUpdate = $false

try {
    Set-Location -LiteralPath $RepoPath
    Write-DeployLog "Checking $Remote/$Branch in $RepoPath"

    if (-not (Test-Path -LiteralPath (Join-Path $RepoPath ".git"))) {
        throw "Repository metadata not found in $RepoPath"
    }

    $dirty = (Invoke-Git @("status", "--porcelain") | Out-String).Trim()
    if ($dirty) {
        Write-DeployLog "Aborted: local worktree has changes"
        Write-DeployLog $dirty
        exit 2
    }

    Invoke-Git @("fetch", $Remote, $Branch) | Out-Null
    $localHead = (Invoke-Git @("rev-parse", "HEAD") | Select-Object -First 1).Trim()
    $remoteHead = (Invoke-Git @("rev-parse", "$Remote/$Branch") | Select-Object -First 1).Trim()

    if ($localHead -eq $remoteHead) {
        Write-DeployLog "No update: HEAD $($localHead.Substring(0, 7))"
        exit 0
    }

    $base = (Invoke-Git @("merge-base", "HEAD", "$Remote/$Branch") | Select-Object -First 1).Trim()
    if ($base -ne $localHead) {
        throw "Local branch is not a fast-forward of $Remote/$Branch"
    }

    Write-DeployLog "Update found: $($localHead.Substring(0, 7)) -> $($remoteHead.Substring(0, 7))"
    Stop-Pontolentx
    $stoppedForUpdate = $true

    Invoke-Git @("pull", "--ff-only", $Remote, $Branch) | ForEach-Object { Write-DeployLog $_ }

    Write-DeployLog "Installing Python dependencies"
    Invoke-Native -FilePath "python" -Arguments @("-m", "pip", "install", "-r", "requirements.txt") |
        ForEach-Object { Write-DeployLog $_ }

    Write-DeployLog "Installing Playwright Chrome"
    Invoke-Native -FilePath "python" -Arguments @("-m", "playwright", "install", "chrome") |
        ForEach-Object { Write-DeployLog $_ }

    Start-Pontolentx
    if (Test-PontolentxPort) {
        Write-DeployLog "Deploy completed: $($remoteHead.Substring(0, 7)) is running"
        exit 0
    }

    throw "Pontolentx did not listen on port $Port after restart"
} catch {
    Write-DeployLog "ERROR: $($_.Exception.Message)"
    if ($stoppedForUpdate) {
        try {
            Start-Pontolentx
        } catch {
            Write-DeployLog "ERROR: fallback start failed: $($_.Exception.Message)"
        }
    }
    exit 1
} finally {
    if (Test-Path -LiteralPath $lockPath) {
        Remove-Item -LiteralPath $lockPath -Recurse -Force
    }
}
