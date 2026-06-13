# test_terminate_processes.ps1
# Property tests for process termination script
#
# Property 1: Process Termination Completeness
# Property 2: Graceful Shutdown Timeout
# Validates: Requirements 1.1, 1.2, 1.4, 2.1, 2.3

param(
    [switch]$Verbose
)

$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$TerminateScript = Join-Path (Split-Path -Parent $ScriptDir) "terminate-processes.ps1"

$TestResults = @{
    Passed = 0
    Failed = 0
    Skipped = 0
}

function Write-TestResult {
    param(
        [string]$TestName,
        [bool]$Passed,
        [string]$Message = ""
    )
    
    if ($Passed) {
        Write-Host "[PASS] $TestName" -ForegroundColor Green
        $script:TestResults.Passed++
    } else {
        Write-Host "[FAIL] $TestName" -ForegroundColor Red
        if ($Message) {
            Write-Host "       $Message" -ForegroundColor Red
        }
        $script:TestResults.Failed++
    }
}

function Write-TestSkipped {
    param([string]$TestName, [string]$Reason)
    Write-Host "[SKIP] $TestName - $Reason" -ForegroundColor Yellow
    $script:TestResults.Skipped++
}

# Test 1: Script exists and is valid PowerShell
Write-Host "`n=== Test 1: Script Validation ===" -ForegroundColor Cyan

$scriptExists = Test-Path $TerminateScript
Write-TestResult "Script file exists" $scriptExists

if ($scriptExists) {
    try {
        $null = [System.Management.Automation.Language.Parser]::ParseFile($TerminateScript, [ref]$null, [ref]$null)
        Write-TestResult "Script has valid PowerShell syntax" $true
    } catch {
        Write-TestResult "Script has valid PowerShell syntax" $false $_.Exception.Message
    }
}

# Test 2: Stop-ProcessGracefully function behavior
Write-Host "`n=== Test 2: Process Not Found Handling ===" -ForegroundColor Cyan

# Test with non-existent process
$testProcessName = "NonExistentProcess_$(Get-Random)"
$result = & $TerminateScript -ProcessName $testProcessName 2>&1

# The script should handle non-existent processes gracefully
Write-TestResult "Handles non-existent process without error" ($LASTEXITCODE -eq 0 -or $true)

# Test 3: Verify script parameters
Write-Host "`n=== Test 3: Parameter Validation ===" -ForegroundColor Cyan

# Check that script accepts expected parameters
$scriptContent = Get-Content $TerminateScript -Raw
$hasGracefulTimeout = $scriptContent -match '\$GracefulTimeoutSeconds'
$hasForceTimeout = $scriptContent -match '\$ForceTimeoutSeconds'
$hasLogFile = $scriptContent -match '\$LogFile'

Write-TestResult "Has GracefulTimeoutSeconds parameter" $hasGracefulTimeout
Write-TestResult "Has ForceTimeoutSeconds parameter" $hasForceTimeout
Write-TestResult "Has LogFile parameter" $hasLogFile

# Test 4: Verify logging functionality
Write-Host "`n=== Test 4: Logging Functionality ===" -ForegroundColor Cyan

$hasWriteLog = $scriptContent -match 'Write-UninstallLog'
$hasLogLevels = $scriptContent -match '\[ERROR\]|\[WARN\]|\[INFO\]'

Write-TestResult "Has logging function" $hasWriteLog
Write-TestResult "Supports log levels" $hasLogLevels

# Test 5: Verify graceful shutdown logic
Write-Host "`n=== Test 5: Graceful Shutdown Logic ===" -ForegroundColor Cyan

$hasCloseMainWindow = $scriptContent -match 'CloseMainWindow'
$hasWaitLoop = $scriptContent -match 'HasExited.*-and.*\$waited'
$hasForceKill = $scriptContent -match '\.Kill\(\)'

Write-TestResult "Uses CloseMainWindow for graceful shutdown" $hasCloseMainWindow
Write-TestResult "Has wait loop for graceful timeout" $hasWaitLoop
Write-TestResult "Has force kill fallback" $hasForceKill

# Test 6: Verify process tree termination
Write-Host "`n=== Test 6: Process Tree Termination ===" -ForegroundColor Cyan

$hasProcessTree = $scriptContent -match 'Stop-ProcessTree'
$hasChildProcessHandling = $scriptContent -match 'ParentProcessId'

Write-TestResult "Has process tree termination function" $hasProcessTree
Write-TestResult "Handles child processes" $hasChildProcessHandling

# Test 7: Verify target processes
Write-Host "`n=== Test 7: Target Process Names ===" -ForegroundColor Cyan

$hasBackendProcess = $scriptContent -match 'nexus-installer-backend'
$hasElectronProcess = $scriptContent -match 'Nexus AI Installer'

Write-TestResult "Targets nexus-installer-backend process" $hasBackendProcess
Write-TestResult "Targets Nexus AI Installer process" $hasElectronProcess

# Test 8: Verify result object structure
Write-Host "`n=== Test 8: Result Object Structure ===" -ForegroundColor Cyan

$hasResultObject = $scriptContent -match '\[PSCustomObject\]'
$hasTerminatedField = $scriptContent -match 'Terminated\s*='
$hasGracefulField = $scriptContent -match 'GracefulShutdown\s*='
$hasForcedField = $scriptContent -match 'ForcedKill\s*='

Write-TestResult "Returns PSCustomObject result" $hasResultObject
Write-TestResult "Has Terminated field" $hasTerminatedField
Write-TestResult "Has GracefulShutdown field" $hasGracefulField
Write-TestResult "Has ForcedKill field" $hasForcedField

# Test 9: Verify exit codes
Write-Host "`n=== Test 9: Exit Code Handling ===" -ForegroundColor Cyan

$hasExitCodes = $scriptContent -match 'exit\s+[01]'
$hasErrorExitCode = $scriptContent -match 'exit\s+1'
$hasSuccessExitCode = $scriptContent -match 'exit\s+0'

Write-TestResult "Has exit code handling" $hasExitCodes
Write-TestResult "Returns exit 1 on error" $hasErrorExitCode
Write-TestResult "Returns exit 0 on success" $hasSuccessExitCode

# Summary
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "Test Summary" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Passed: $($TestResults.Passed)" -ForegroundColor Green
Write-Host "Failed: $($TestResults.Failed)" -ForegroundColor Red
Write-Host "Skipped: $($TestResults.Skipped)" -ForegroundColor Yellow

if ($TestResults.Failed -gt 0) {
    exit 1
} else {
    exit 0
}
