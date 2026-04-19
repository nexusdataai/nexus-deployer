# cleanup-temp.ps1
# Cleans up Totogi Installer temporary files
#
# Usage:
#   .\cleanup-temp.ps1
#   .\cleanup-temp.ps1 -LogFile "C:\temp\uninstall.log"

param(
    [string]$LogFile = "$env:TEMP\totogi-uninstall.log"
)

function Write-UninstallLog {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logEntry = "[$timestamp] [$Level] $Message"
    switch ($Level) {
        "ERROR" { Write-Host $logEntry -ForegroundColor Red }
        "WARN"  { Write-Host $logEntry -ForegroundColor Yellow }
        default { Write-Host $logEntry }
    }
    try { Add-Content -Path $LogFile -Value $logEntry -ErrorAction SilentlyContinue } catch { }
}

function Remove-TempItems {
    param(
        [string]$Pattern,
        [string]$Description
    )
    
    $result = [PSCustomObject]@{
        Pattern = $Pattern
        Description = $Description
        ItemsFound = 0
        ItemsRemoved = 0
        Errors = @()
    }
    
    Write-UninstallLog "Searching for: $Description ($Pattern)"
    
    try {
        $items = Get-ChildItem -Path $env:TEMP -Filter $Pattern -ErrorAction SilentlyContinue
        
        if ($items) {
            $result.ItemsFound = $items.Count
            Write-UninstallLog "Found $($items.Count) items matching $Pattern"
            
            foreach ($item in $items) {
                try {
                    if ($item.PSIsContainer) {
                        Remove-Item -Path $item.FullName -Recurse -Force -ErrorAction Stop
                    } else {
                        Remove-Item -Path $item.FullName -Force -ErrorAction Stop
                    }
                    $result.ItemsRemoved++
                    Write-UninstallLog "Removed: $($item.Name)"
                } catch {
                    $result.Errors += $item.FullName
                    Write-UninstallLog "Could not remove: $($item.Name) - $_" -Level "WARN"
                }
            }
        } else {
            Write-UninstallLog "No items found matching $Pattern"
        }
    } catch {
        Write-UninstallLog "Error searching for $Pattern : $_" -Level "ERROR"
    }
    
    return $result
}

# Main execution
Write-UninstallLog "=========================================="
Write-UninstallLog "Totogi Installer Temp File Cleanup"
Write-UninstallLog "=========================================="
Write-UninstallLog "Temp directory: $env:TEMP"

$results = @()

# Clean totogi-* temp files and directories
$results += Remove-TempItems -Pattern "totogi-*" -Description "Totogi temp files"

# Clean PyInstaller temp directories (_MEI*)
$results += Remove-TempItems -Pattern "_MEI*" -Description "PyInstaller temp directories"

# Clean electron-builder temp files
$results += Remove-TempItems -Pattern "electron-*" -Description "Electron builder temp files"

# Clean crash dumps
$results += Remove-TempItems -Pattern "totogi*.dmp" -Description "Crash dump files"

# Clean error logs
$results += Remove-TempItems -Pattern "totogi*.log" -Description "Error log files"

# Also check LocalAppData\Temp
$localTemp = "$env:LOCALAPPDATA\Temp"
if (Test-Path $localTemp) {
    Write-UninstallLog ""
    Write-UninstallLog "Checking LocalAppData Temp: $localTemp"
    
    try {
        $localItems = Get-ChildItem -Path $localTemp -Filter "totogi-*" -ErrorAction SilentlyContinue
        if ($localItems) {
            foreach ($item in $localItems) {
                try {
                    Remove-Item -Path $item.FullName -Recurse -Force -ErrorAction Stop
                    Write-UninstallLog "Removed from LocalAppData: $($item.Name)"
                } catch {
                    Write-UninstallLog "Could not remove: $($item.Name)" -Level "WARN"
                }
            }
        }
    } catch { }
}

# Summary
Write-UninstallLog ""
Write-UninstallLog "=========================================="
Write-UninstallLog "Cleanup Summary"
Write-UninstallLog "=========================================="

$totalFound = ($results | Measure-Object -Property ItemsFound -Sum).Sum
$totalRemoved = ($results | Measure-Object -Property ItemsRemoved -Sum).Sum
$totalErrors = ($results | ForEach-Object { $_.Errors.Count } | Measure-Object -Sum).Sum

Write-UninstallLog "Items found: $totalFound"
Write-UninstallLog "Items removed: $totalRemoved"
Write-UninstallLog "Errors: $totalErrors"

if ($totalErrors -gt 0) {
    Write-UninstallLog "Temp cleanup completed with some errors" -Level "WARN"
    exit 1
} else {
    Write-UninstallLog "Temp cleanup completed successfully"
    exit 0
}
