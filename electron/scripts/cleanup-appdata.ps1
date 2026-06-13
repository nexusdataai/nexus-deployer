# cleanup-appdata.ps1
# Cleans up Nexus AI Installer application data directories
#
# Usage:
#   .\cleanup-appdata.ps1                    # Prompt for confirmation
#   .\cleanup-appdata.ps1 -DeleteData        # Delete without prompting
#   .\cleanup-appdata.ps1 -PreserveData      # Skip deletion (for silent uninstall)

param(
    [switch]$DeleteData,
    [switch]$PreserveData,
    [string]$LogFile = "$env:TEMP\nexus-uninstall.log"
)

function Write-UninstallLog {
    param(
        [string]$Message,
        [string]$Level = "INFO"
    )
    
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logEntry = "[$timestamp] [$Level] $Message"
    
    switch ($Level) {
        "ERROR" { Write-Host $logEntry -ForegroundColor Red }
        "WARN"  { Write-Host $logEntry -ForegroundColor Yellow }
        default { Write-Host $logEntry }
    }
    
    try {
        Add-Content -Path $LogFile -Value $logEntry -ErrorAction SilentlyContinue
    } catch { }
}

function Remove-DirectorySafely {
    <#
    .SYNOPSIS
    Removes a directory with error handling and locked file support.
    
    .PARAMETER Path
    Path to the directory to remove
    
    .OUTPUTS
    PSCustomObject with removal results
    #>
    param(
        [Parameter(Mandatory=$true)]
        [string]$Path
    )
    
    $result = [PSCustomObject]@{
        Path = $Path
        Existed = $false
        Removed = $false
        FilesRemoved = 0
        FilesLocked = 0
        ScheduledForReboot = $false
        Error = $null
    }
    
    if (-not (Test-Path $Path)) {
        Write-UninstallLog "Directory does not exist: $Path"
        return $result
    }
    
    $result.Existed = $true
    Write-UninstallLog "Removing directory: $Path"
    
    try {
        # Count files before removal
        $files = Get-ChildItem -Path $Path -Recurse -File -ErrorAction SilentlyContinue
        $totalFiles = if ($files) { $files.Count } else { 0 }
        
        # Try to remove the directory
        Remove-Item -Path $Path -Recurse -Force -ErrorAction Stop
        
        $result.Removed = $true
        $result.FilesRemoved = $totalFiles
        Write-UninstallLog "Successfully removed directory: $Path ($totalFiles files)"
        
    } catch {
        Write-UninstallLog "Error removing directory: $_" -Level "WARN"
        
        # Try to remove individual files
        $lockedFiles = @()
        
        try {
            $items = Get-ChildItem -Path $Path -Recurse -ErrorAction SilentlyContinue
            
            foreach ($item in $items) {
                try {
                    Remove-Item -Path $item.FullName -Force -ErrorAction Stop
                    $result.FilesRemoved++
                } catch {
                    $lockedFiles += $item.FullName
                    $result.FilesLocked++
                }
            }
            
            # Try to remove empty directories
            try {
                Remove-Item -Path $Path -Recurse -Force -ErrorAction Stop
                $result.Removed = $true
            } catch {
                # Schedule locked files for deletion on reboot
                if ($lockedFiles.Count -gt 0) {
                    Write-UninstallLog "Scheduling $($lockedFiles.Count) locked files for deletion on reboot" -Level "WARN"
                    
                    foreach ($lockedFile in $lockedFiles) {
                        try {
                            # Use MoveFileEx to schedule deletion on reboot
                            $signature = @'
[DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
public static extern bool MoveFileEx(string lpExistingFileName, string lpNewFileName, int dwFlags);
'@
                            $type = Add-Type -MemberDefinition $signature -Name "WinAPI" -Namespace "Kernel32" -PassThru
                            $MOVEFILE_DELAY_UNTIL_REBOOT = 0x4
                            $type::MoveFileEx($lockedFile, $null, $MOVEFILE_DELAY_UNTIL_REBOOT) | Out-Null
                            $result.ScheduledForReboot = $true
                        } catch {
                            Write-UninstallLog "Could not schedule file for reboot deletion: $lockedFile" -Level "WARN"
                        }
                    }
                }
            }
        } catch {
            $result.Error = $_.Exception.Message
        }
    }
    
    return $result
}

# Main execution
Write-UninstallLog "=========================================="
Write-UninstallLog "Nexus AI Installer Application Data Cleanup"
Write-UninstallLog "=========================================="

# Define application data directories
$appDataDirs = @(
    "$env:APPDATA\nexus-installer",
    "$env:LOCALAPPDATA\nexus-installer",
    "$env:LOCALAPPDATA\Nexus AI Installer",
    "$env:LOCALAPPDATA\nexus-installer-updater"
)

# Check if we should delete or preserve
if ($PreserveData) {
    Write-UninstallLog "PreserveData flag set - skipping application data cleanup"
    Write-UninstallLog "The following directories will be preserved:"
    foreach ($dir in $appDataDirs) {
        if (Test-Path $dir) {
            Write-UninstallLog "  - $dir"
        }
    }
    exit 0
}

if (-not $DeleteData) {
    # Interactive mode - prompt user
    Write-Host ""
    Write-Host "The following application data directories were found:" -ForegroundColor Yellow
    
    $existingDirs = @()
    foreach ($dir in $appDataDirs) {
        if (Test-Path $dir) {
            $size = (Get-ChildItem -Path $dir -Recurse -ErrorAction SilentlyContinue | 
                     Measure-Object -Property Length -Sum).Sum
            $sizeMB = [math]::Round($size / 1MB, 2)
            Write-Host "  - $dir ($sizeMB MB)" -ForegroundColor Cyan
            $existingDirs += $dir
        }
    }
    
    if ($existingDirs.Count -eq 0) {
        Write-UninstallLog "No application data directories found"
        exit 0
    }
    
    Write-Host ""
    $response = Read-Host "Do you want to delete these directories? (Y/N)"
    
    if ($response -notmatch '^[Yy]') {
        Write-UninstallLog "User chose to preserve application data"
        exit 0
    }
}

# Perform cleanup
Write-UninstallLog ""
Write-UninstallLog "--- Removing Application Data ---"

$results = @()
$totalRemoved = 0
$totalLocked = 0
$needsReboot = $false

foreach ($dir in $appDataDirs) {
    $result = Remove-DirectorySafely -Path $dir
    $results += $result
    
    if ($result.Existed) {
        $totalRemoved += $result.FilesRemoved
        $totalLocked += $result.FilesLocked
        if ($result.ScheduledForReboot) {
            $needsReboot = $true
        }
    }
}

# Summary
Write-UninstallLog ""
Write-UninstallLog "=========================================="
Write-UninstallLog "Cleanup Summary"
Write-UninstallLog "=========================================="

$dirsExisted = ($results | Where-Object { $_.Existed }).Count
$dirsRemoved = ($results | Where-Object { $_.Removed }).Count

Write-UninstallLog "Directories found: $dirsExisted"
Write-UninstallLog "Directories removed: $dirsRemoved"
Write-UninstallLog "Files removed: $totalRemoved"
Write-UninstallLog "Files locked: $totalLocked"

if ($needsReboot) {
    Write-UninstallLog "Some files are scheduled for deletion on next reboot" -Level "WARN"
    Write-Host ""
    Write-Host "NOTE: Some files could not be deleted and are scheduled for removal on next reboot." -ForegroundColor Yellow
}

if ($totalLocked -gt 0 -and -not $needsReboot) {
    Write-UninstallLog "Some files could not be removed" -Level "WARN"
    exit 1
} else {
    Write-UninstallLog "Application data cleanup completed successfully"
    exit 0
}
