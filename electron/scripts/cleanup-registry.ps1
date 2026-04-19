# cleanup-registry.ps1
# Cleans up Totogi Installer registry entries
#
# Usage:
#   .\cleanup-registry.ps1
#   .\cleanup-registry.ps1 -LogFile "C:\temp\uninstall.log"

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

function Remove-RegistryKey {
    param(
        [Parameter(Mandatory=$true)]
        [string]$Path,
        [string]$Description = ""
    )
    
    $result = [PSCustomObject]@{
        Path = $Path
        Description = $Description
        Existed = $false
        Removed = $false
        Error = $null
    }
    
    try {
        if (Test-Path $Path) {
            $result.Existed = $true
            Write-UninstallLog "Found registry key: $Path"
            
            Remove-Item -Path $Path -Recurse -Force -ErrorAction Stop
            $result.Removed = $true
            Write-UninstallLog "Removed registry key: $Path"
        } else {
            Write-UninstallLog "Registry key not found: $Path"
        }
    } catch {
        $result.Error = $_.Exception.Message
        Write-UninstallLog "Error removing registry key $Path : $_" -Level "WARN"
    }
    
    return $result
}

# Main execution
Write-UninstallLog "=========================================="
Write-UninstallLog "Totogi Installer Registry Cleanup"
Write-UninstallLog "=========================================="

$results = @()

# HKCU registry keys (current user - no admin required)
Write-UninstallLog ""
Write-UninstallLog "--- Cleaning HKCU Registry Keys ---"

$hkcuKeys = @(
    @{ Path = "HKCU:\Software\totogi-installer"; Description = "Main application settings" },
    @{ Path = "HKCU:\Software\Totogi Installer"; Description = "Application settings (alternate)" },
    @{ Path = "HKCU:\Software\totogi"; Description = "Totogi parent key" }
)

foreach ($key in $hkcuKeys) {
    $result = Remove-RegistryKey -Path $key.Path -Description $key.Description
    $results += $result
}

# HKLM registry keys (requires admin)
Write-UninstallLog ""
Write-UninstallLog "--- Cleaning HKLM Registry Keys ---"

$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if ($isAdmin) {
    $hklmKeys = @(
        @{ Path = "HKLM:\Software\totogi-installer"; Description = "Machine-wide settings" },
        @{ Path = "HKLM:\Software\Totogi Installer"; Description = "Machine-wide settings (alternate)" }
    )
    
    foreach ($key in $hklmKeys) {
        $result = Remove-RegistryKey -Path $key.Path -Description $key.Description
        $results += $result
    }
} else {
    Write-UninstallLog "Not running as administrator - skipping HKLM cleanup" -Level "WARN"
    Write-UninstallLog "Run as administrator to clean machine-wide registry keys"
}

# Clean Electron/Chromium registry entries
Write-UninstallLog ""
Write-UninstallLog "--- Cleaning Electron Registry Keys ---"

$electronKeys = @(
    @{ Path = "HKCU:\Software\Microsoft\Windows\CurrentVersion\App Paths\Totogi Installer.exe"; Description = "App path registration" }
)

foreach ($key in $electronKeys) {
    $result = Remove-RegistryKey -Path $key.Path -Description $key.Description
    $results += $result
}

# Summary
Write-UninstallLog ""
Write-UninstallLog "=========================================="
Write-UninstallLog "Registry Cleanup Summary"
Write-UninstallLog "=========================================="

$keysExisted = ($results | Where-Object { $_.Existed }).Count
$keysRemoved = ($results | Where-Object { $_.Removed }).Count
$keysErrors = ($results | Where-Object { $_.Error }).Count

Write-UninstallLog "Registry keys found: $keysExisted"
Write-UninstallLog "Registry keys removed: $keysRemoved"
Write-UninstallLog "Errors: $keysErrors"

if ($keysErrors -gt 0) {
    Write-UninstallLog "Registry cleanup completed with some errors" -Level "WARN"
    exit 1
} else {
    Write-UninstallLog "Registry cleanup completed successfully"
    exit 0
}
