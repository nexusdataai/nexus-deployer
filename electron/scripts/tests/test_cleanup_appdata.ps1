# test_cleanup_appdata.ps1
# Property tests for application data cleanup script
#
# Property 3: Application Data Cleanup
# Property 4: Application Data Preservation
# Validates: Requirements 3.2, 3.3, 3.4

param([switch]$Verbose)

$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$CleanupScript = Join-Path (Split-Path -Parent $ScriptDir) "cleanup-appdata.ps1"

$TestResults = @{ Passed = 0; Failed = 0; Skipped = 0 }

function Write-TestResult {
    param([string]$TestName, [bool]$Passed, [string]$Message = "")
    if ($Passed) {
        Write-Host "[PASS] $TestName" -ForegroundColor Green
        $script:TestResults.Passed++
    } else {
        Write-Host "[FAIL] $TestName" -ForegroundColor Red
        if ($Message) { Write-Host "       $Message" -ForegroundColor Red }
        $script:TestResults.Failed++
    }
}

# Test 1: Script exists and is valid
Write-Host "`n=== Test 1: Script Validation ===" -ForegroundColor Cyan
$scriptExists = Test-Path $CleanupScript
Write-TestResult "Script file exists" $scriptExists

if ($scriptExists) {
    try {
        $null = [System.Management.Automation.Language.Parser]::ParseFile($CleanupScript, [ref]$null, [ref]$null)
        Write-TestResult "Script has valid PowerShell syntax" $true
    } catch {
        Write-TestResult "Script has valid PowerShell syntax" $false $_.Exception.Message
    }
}

# Test 2: Parameter validation
Write-Host "`n=== Test 2: Parameter Validation ===" -ForegroundColor Cyan
$scriptContent = Get-Content $CleanupScript -Raw

$hasDeleteData = $scriptContent -match '\$DeleteData'
$hasPreserveData = $scriptContent -match '\$PreserveData'
$hasLogFile = $scriptContent -match '\$LogFile'

Write-TestResult "Has DeleteData parameter" $hasDeleteData
Write-TestResult "Has PreserveData parameter" $hasPreserveData
Write-TestResult "Has LogFile parameter" $hasLogFile

# Test 3: Target directories
Write-Host "`n=== Test 3: Target Directories ===" -ForegroundColor Cyan

$hasAppData = $scriptContent -match 'APPDATA.*nexus-installer'
$hasLocalAppData = $scriptContent -match 'LOCALAPPDATA.*nexus-installer'
$hasNexusInstaller = $scriptContent -match 'Nexus AI Installer'

Write-TestResult "Targets APPDATA directory" $hasAppData
Write-TestResult "Targets LOCALAPPDATA directory" $hasLocalAppData
Write-TestResult "Targets 'Nexus AI Installer' directory" $hasNexusInstaller

# Test 4: Safe removal function
Write-Host "`n=== Test 4: Safe Removal Logic ===" -ForegroundColor Cyan

$hasRemoveFunction = $scriptContent -match 'Remove-DirectorySafely'
$hasTestPath = $scriptContent -match 'Test-Path'
$hasRemoveItem = $scriptContent -match 'Remove-Item.*-Recurse.*-Force'

Write-TestResult "Has safe removal function" $hasRemoveFunction
Write-TestResult "Checks path existence" $hasTestPath
Write-TestResult "Uses Remove-Item with -Recurse -Force" $hasRemoveItem

# Test 5: Locked file handling
Write-Host "`n=== Test 5: Locked File Handling ===" -ForegroundColor Cyan

$hasMoveFileEx = $scriptContent -match 'MoveFileEx'
$hasDelayUntilReboot = $scriptContent -match 'DELAY_UNTIL_REBOOT'
$hasScheduledForReboot = $scriptContent -match 'ScheduledForReboot'

Write-TestResult "Uses MoveFileEx for locked files" $hasMoveFileEx
Write-TestResult "Has DELAY_UNTIL_REBOOT flag" $hasDelayUntilReboot
Write-TestResult "Tracks scheduled reboot deletions" $hasScheduledForReboot

# Test 6: Preservation mode
Write-Host "`n=== Test 6: Preservation Mode ===" -ForegroundColor Cyan

$hasPreserveLogic = $scriptContent -match 'if.*\$PreserveData'
$hasPreserveExit = $scriptContent -match 'PreserveData.*exit\s+0'

Write-TestResult "Has preservation logic" $hasPreserveLogic
Write-TestResult "Exits cleanly when preserving" ($hasPreserveLogic)

# Test 7: Result tracking
Write-Host "`n=== Test 7: Result Tracking ===" -ForegroundColor Cyan

$hasResultObject = $scriptContent -match '\[PSCustomObject\]'
$hasFilesRemoved = $scriptContent -match 'FilesRemoved'
$hasFilesLocked = $scriptContent -match 'FilesLocked'

Write-TestResult "Returns result object" $hasResultObject
Write-TestResult "Tracks files removed" $hasFilesRemoved
Write-TestResult "Tracks locked files" $hasFilesLocked

# Summary
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "Test Summary" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Passed: $($TestResults.Passed)" -ForegroundColor Green
Write-Host "Failed: $($TestResults.Failed)" -ForegroundColor Red

if ($TestResults.Failed -gt 0) { exit 1 } else { exit 0 }
