# terminate-processes.ps1
# Terminates Nexus AI Installer processes with graceful shutdown support
#
# Usage:
#   .\terminate-processes.ps1
#   .\terminate-processes.ps1 -GracefulTimeoutSeconds 10
#   .\terminate-processes.ps1 -LogFile "C:\temp\uninstall.log"

param(
    [int]$GracefulTimeoutSeconds = 5,
    [int]$ForceTimeoutSeconds = 5,
    [string]$LogFile = "$env:TEMP\nexus-uninstall.log"
)

# Import logging module if available
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$LoggerScript = Join-Path $ScriptDir "uninstall-logger.ps1"
if (Test-Path $LoggerScript) {
    . $LoggerScript
}

function Write-UninstallLog {
    param(
        [string]$Message,
        [string]$Level = "INFO"
    )
    
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logEntry = "[$timestamp] [$Level] $Message"
    
    # Write to console
    switch ($Level) {
        "ERROR" { Write-Host $logEntry -ForegroundColor Red }
        "WARN"  { Write-Host $logEntry -ForegroundColor Yellow }
        default { Write-Host $logEntry }
    }
    
    # Write to log file
    try {
        Add-Content -Path $LogFile -Value $logEntry -ErrorAction SilentlyContinue
    } catch {
        # Ignore logging errors
    }
}

function Stop-ProcessGracefully {
    <#
    .SYNOPSIS
    Stops a process gracefully with timeout, then force-kills if necessary.
    
    .PARAMETER ProcessName
    Name of the process to terminate (without .exe extension)
    
    .PARAMETER GracefulTimeout
    Seconds to wait for graceful shutdown
    
    .PARAMETER ForceTimeout
    Seconds to wait after force-kill before giving up
    
    .OUTPUTS
    PSCustomObject with termination results
    #>
    param(
        [Parameter(Mandatory=$true)]
        [string]$ProcessName,
        
        [int]$GracefulTimeout = 5,
        
        [int]$ForceTimeout = 5
    )
    
    $result = [PSCustomObject]@{
        ProcessName = $ProcessName
        Found = $false
        Terminated = $false
        GracefulShutdown = $false
        ForcedKill = $false
        Error = $null
        ProcessCount = 0
    }
    
    try {
        # Find all processes with the given name
        $processes = Get-Process -Name $ProcessName -ErrorAction SilentlyContinue
        
        if (-not $processes -or $processes.Count -eq 0) {
            Write-UninstallLog "No processes found with name: $ProcessName"
            return $result
        }
        
        $result.Found = $true
        $result.ProcessCount = $processes.Count
        Write-UninstallLog "Found $($processes.Count) process(es) with name: $ProcessName"
        
        foreach ($proc in $processes) {
            Write-UninstallLog "Attempting graceful shutdown of PID $($proc.Id)..."
            
            # Try graceful shutdown first (close main window)
            try {
                $closed = $proc.CloseMainWindow()
                
                if ($closed) {
                    Write-UninstallLog "Sent close signal to PID $($proc.Id), waiting for graceful shutdown..."
                    
                    # Wait for graceful shutdown
                    $waited = 0
                    while (-not $proc.HasExited -and $waited -lt $GracefulTimeout) {
                        Start-Sleep -Seconds 1
                        $waited++
                        $proc.Refresh()
                    }
                    
                    if ($proc.HasExited) {
                        Write-UninstallLog "Process PID $($proc.Id) exited gracefully"
                        $result.GracefulShutdown = $true
                        continue
                    }
                }
            } catch {
                Write-UninstallLog "Could not send close signal to PID $($proc.Id): $_" -Level "WARN"
            }
            
            # Force kill if still running
            try {
                $proc.Refresh()
                if (-not $proc.HasExited) {
                    Write-UninstallLog "Force-killing PID $($proc.Id)..." -Level "WARN"
                    $proc.Kill()
                    
                    # Wait for force kill to complete
                    $waited = 0
                    while (-not $proc.HasExited -and $waited -lt $ForceTimeout) {
                        Start-Sleep -Milliseconds 500
                        $waited++
                        $proc.Refresh()
                    }
                    
                    if ($proc.HasExited) {
                        Write-UninstallLog "Process PID $($proc.Id) force-killed successfully"
                        $result.ForcedKill = $true
                    } else {
                        Write-UninstallLog "Failed to kill PID $($proc.Id) after $ForceTimeout seconds" -Level "ERROR"
                    }
                }
            } catch {
                Write-UninstallLog "Error killing PID $($proc.Id): $_" -Level "ERROR"
                $result.Error = $_.Exception.Message
            }
        }
        
        # Verify all processes are terminated
        Start-Sleep -Milliseconds 500
        $remaining = Get-Process -Name $ProcessName -ErrorAction SilentlyContinue
        
        if (-not $remaining -or $remaining.Count -eq 0) {
            $result.Terminated = $true
            Write-UninstallLog "All $ProcessName processes terminated successfully"
        } else {
            Write-UninstallLog "$($remaining.Count) $ProcessName process(es) still running" -Level "WARN"
        }
        
    } catch {
        Write-UninstallLog "Error terminating $ProcessName : $_" -Level "ERROR"
        $result.Error = $_.Exception.Message
    }
    
    return $result
}

function Stop-ProcessTree {
    <#
    .SYNOPSIS
    Stops a process and all its child processes.
    
    .PARAMETER ProcessId
    PID of the parent process
    #>
    param(
        [Parameter(Mandatory=$true)]
        [int]$ProcessId
    )
    
    try {
        # Get child processes
        $children = Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $ProcessId }
        
        foreach ($child in $children) {
            Write-UninstallLog "Terminating child process PID $($child.ProcessId) ($($child.Name))"
            Stop-ProcessTree -ProcessId $child.ProcessId
        }
        
        # Kill the parent process
        $proc = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
        if ($proc -and -not $proc.HasExited) {
            $proc.Kill()
            Write-UninstallLog "Terminated process PID $ProcessId"
        }
    } catch {
        Write-UninstallLog "Error in process tree termination: $_" -Level "WARN"
    }
}

# Main execution
Write-UninstallLog "=========================================="
Write-UninstallLog "Nexus AI Installer Process Termination"
Write-UninstallLog "=========================================="
Write-UninstallLog "Graceful timeout: $GracefulTimeoutSeconds seconds"
Write-UninstallLog "Force timeout: $ForceTimeoutSeconds seconds"

$results = @()

# Terminate backend process
Write-UninstallLog ""
Write-UninstallLog "--- Terminating Backend Process ---"
$backendResult = Stop-ProcessGracefully -ProcessName "nexus-installer-backend" `
    -GracefulTimeout $GracefulTimeoutSeconds `
    -ForceTimeout $ForceTimeoutSeconds
$results += $backendResult

# Terminate Electron app
Write-UninstallLog ""
Write-UninstallLog "--- Terminating Electron App ---"
$electronResult = Stop-ProcessGracefully -ProcessName "Nexus AI Installer" `
    -GracefulTimeout $GracefulTimeoutSeconds `
    -ForceTimeout $ForceTimeoutSeconds
$results += $electronResult

# Also try alternative process names
$altNames = @("nexus-installer", "NexusInstaller")
foreach ($name in $altNames) {
    $altResult = Stop-ProcessGracefully -ProcessName $name `
        -GracefulTimeout $GracefulTimeoutSeconds `
        -ForceTimeout $ForceTimeoutSeconds
    if ($altResult.Found) {
        $results += $altResult
    }
}

# Summary
Write-UninstallLog ""
Write-UninstallLog "=========================================="
Write-UninstallLog "Termination Summary"
Write-UninstallLog "=========================================="

$totalFound = ($results | Where-Object { $_.Found }).Count
$totalTerminated = ($results | Where-Object { $_.Terminated }).Count
$totalGraceful = ($results | Where-Object { $_.GracefulShutdown }).Count
$totalForced = ($results | Where-Object { $_.ForcedKill }).Count
$totalErrors = ($results | Where-Object { $_.Error }).Count

Write-UninstallLog "Processes found: $totalFound"
Write-UninstallLog "Processes terminated: $totalTerminated"
Write-UninstallLog "Graceful shutdowns: $totalGraceful"
Write-UninstallLog "Forced kills: $totalForced"
Write-UninstallLog "Errors: $totalErrors"

# Return exit code
if ($totalErrors -gt 0) {
    Write-UninstallLog "Process termination completed with errors" -Level "WARN"
    exit 1
} else {
    Write-UninstallLog "Process termination completed successfully"
    exit 0
}
