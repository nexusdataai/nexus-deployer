# uninstall-logger.ps1
# Logging module for Totogi Installer uninstallation
#
# This module provides logging functions for the uninstall process.
# It can be dot-sourced by other scripts: . .\uninstall-logger.ps1

param(
    [string]$LogFile = "$env:TEMP\totogi-uninstall.log"
)

# Global log file path
$script:UninstallLogFile = $LogFile

# Statistics tracking
$script:UninstallStats = @{
    StartTime = $null
    EndTime = $null
    ActionsPerformed = 0
    ActionsSuccessful = 0
    ActionsFailed = 0
    Warnings = 0
    Errors = 0
}

function Initialize-UninstallLog {
    <#
    .SYNOPSIS
    Initializes the uninstall log file.
    #>
    param(
        [string]$LogPath = $script:UninstallLogFile
    )
    
    $script:UninstallLogFile = $LogPath
    $script:UninstallStats.StartTime = Get-Date
    
    # Create or clear log file
    try {
        $header = @"
========================================
Totogi Installer Uninstall Log
========================================
Started: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
Computer: $env:COMPUTERNAME
User: $env:USERNAME
OS: $([System.Environment]::OSVersion.VersionString)
========================================

"@
        Set-Content -Path $LogPath -Value $header -Force
        return $true
    } catch {
        Write-Host "Warning: Could not initialize log file: $_" -ForegroundColor Yellow
        return $false
    }
}

function Write-UninstallLog {
    <#
    .SYNOPSIS
    Writes a message to the uninstall log.
    
    .PARAMETER Message
    The message to log
    
    .PARAMETER Level
    Log level: INFO, WARN, ERROR, DEBUG
    #>
    param(
        [Parameter(Mandatory=$true)]
        [string]$Message,
        
        [ValidateSet("INFO", "WARN", "ERROR", "DEBUG")]
        [string]$Level = "INFO"
    )
    
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logEntry = "[$timestamp] [$Level] $Message"
    
    # Update statistics
    switch ($Level) {
        "WARN"  { $script:UninstallStats.Warnings++ }
        "ERROR" { $script:UninstallStats.Errors++ }
    }
    
    # Write to console with color
    switch ($Level) {
        "ERROR" { Write-Host $logEntry -ForegroundColor Red }
        "WARN"  { Write-Host $logEntry -ForegroundColor Yellow }
        "DEBUG" { if ($VerbosePreference -eq 'Continue') { Write-Host $logEntry -ForegroundColor Gray } }
        default { Write-Host $logEntry }
    }
    
    # Write to log file
    try {
        Add-Content -Path $script:UninstallLogFile -Value $logEntry -ErrorAction SilentlyContinue
    } catch {
        # Silently ignore logging errors
    }
}

function Write-UninstallAction {
    <#
    .SYNOPSIS
    Logs an uninstall action with its result.
    
    .PARAMETER Action
    Description of the action
    
    .PARAMETER Result
    Result of the action: Success, Failed, Skipped
    
    .PARAMETER Details
    Optional additional details
    #>
    param(
        [Parameter(Mandatory=$true)]
        [string]$Action,
        
        [ValidateSet("Success", "Failed", "Skipped")]
        [string]$Result = "Success",
        
        [string]$Details = ""
    )
    
    $script:UninstallStats.ActionsPerformed++
    
    switch ($Result) {
        "Success" { 
            $script:UninstallStats.ActionsSuccessful++
            $level = "INFO"
            $symbol = "[OK]"
        }
        "Failed" { 
            $script:UninstallStats.ActionsFailed++
            $level = "ERROR"
            $symbol = "[X]"
        }
        "Skipped" { 
            $level = "INFO"
            $symbol = "[--]"
        }
    }
    
    $message = "$symbol $Action"
    if ($Details) {
        $message += " - $Details"
    }
    
    Write-UninstallLog -Message $message -Level $level
}

function Write-UninstallSummary {
    <#
    .SYNOPSIS
    Writes a summary of the uninstall process to the log.
    #>
    
    $script:UninstallStats.EndTime = Get-Date
    $duration = $script:UninstallStats.EndTime - $script:UninstallStats.StartTime
    
    $summary = @"

========================================
Uninstall Summary
========================================
Completed: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
Duration: $($duration.TotalSeconds.ToString("F2")) seconds

Actions Performed: $($script:UninstallStats.ActionsPerformed)
  - Successful: $($script:UninstallStats.ActionsSuccessful)
  - Failed: $($script:UninstallStats.ActionsFailed)

Warnings: $($script:UninstallStats.Warnings)
Errors: $($script:UninstallStats.Errors)

"@
    
    if ($script:UninstallStats.ActionsFailed -eq 0 -and $script:UninstallStats.Errors -eq 0) {
        $summary += "Status: COMPLETED SUCCESSFULLY`n"
        Write-Host $summary -ForegroundColor Green
    } else {
        $summary += "Status: COMPLETED WITH ISSUES`n"
        Write-Host $summary -ForegroundColor Yellow
    }
    
    $summary += "========================================`n"
    $summary += "Log file: $script:UninstallLogFile`n"
    
    try {
        Add-Content -Path $script:UninstallLogFile -Value $summary -ErrorAction SilentlyContinue
    } catch { }
    
    return $script:UninstallStats
}

function Get-UninstallLogPath {
    <#
    .SYNOPSIS
    Returns the current log file path.
    #>
    return $script:UninstallLogFile
}

function Get-UninstallStats {
    <#
    .SYNOPSIS
    Returns the current uninstall statistics.
    #>
    return $script:UninstallStats
}

# Export functions if running as module
Export-ModuleMember -Function @(
    'Initialize-UninstallLog',
    'Write-UninstallLog',
    'Write-UninstallAction',
    'Write-UninstallSummary',
    'Get-UninstallLogPath',
    'Get-UninstallStats'
) -ErrorAction SilentlyContinue
