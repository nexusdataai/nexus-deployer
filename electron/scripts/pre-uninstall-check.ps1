# pre-uninstall-check.ps1
# Pre-uninstall validation script for Totogi Installer
# Checks for running processes, active deployments, and permissions

param(
    [switch]$Silent,
    [switch]$Force
)

$ErrorActionPreference = "Continue"
$script:ValidationErrors = @()
$script:ValidationWarnings = @()

# ============================================
# Validation Functions
# ============================================

function Test-RunningApplication {
    <#
    .SYNOPSIS
        Check if the Totogi application is currently running
    .OUTPUTS
        Returns $true if application is running, $false otherwise
    #>
    
    $processes = @(
        "totogi-backend",
        "Totogi Installer"
    )
    
    $runningProcesses = @()
    
    foreach ($procName in $processes) {
        $proc = Get-Process -Name $procName -ErrorAction SilentlyContinue
        if ($proc) {
            $runningProcesses += $procName
        }
    }
    
    if ($runningProcesses.Count -gt 0) {
        $script:ValidationWarnings += "Running processes detected: $($runningProcesses -join ', ')"
        return $true
    }
    
    return $false
}

function Test-ActiveDeployments {
    <#
    .SYNOPSIS
        Check if there are any active CloudFormation deployments
    .OUTPUTS
        Returns $true if active deployments found, $false otherwise
    #>
    
    # Check for deployment lock files
    $lockPaths = @(
        "$env:LOCALAPPDATA\totogi-installer\deployment.lock",
        "$env:APPDATA\totogi-installer\deployment.lock"
    )
    
    foreach ($lockPath in $lockPaths) {
        if (Test-Path $lockPath) {
            $lockContent = Get-Content $lockPath -Raw -ErrorAction SilentlyContinue
            if ($lockContent) {
                $script:ValidationWarnings += "Active deployment detected: $lockContent"
                return $true
            }
        }
    }
    
    # Check for in-progress status in state file
    $statePath = "$env:LOCALAPPDATA\totogi-installer\deployment-state.json"
    if (Test-Path $statePath) {
        try {
            $state = Get-Content $statePath -Raw | ConvertFrom-Json
            if ($state.status -eq "IN_PROGRESS" -or $state.status -eq "PENDING") {
                $script:ValidationWarnings += "Deployment in progress: $($state.stackName)"
                return $true
            }
        } catch {
            # Ignore JSON parse errors
        }
    }
    
    return $false
}

function Test-AdminPermissions {
    <#
    .SYNOPSIS
        Check if running with administrator permissions
    .OUTPUTS
        Returns $true if admin, $false otherwise
    #>
    
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-InstallationDirectory {
    <#
    .SYNOPSIS
        Verify the installation directory exists and is accessible
    .PARAMETER InstallPath
        Path to the installation directory
    .OUTPUTS
        Returns $true if valid, $false otherwise
    #>
    param(
        [string]$InstallPath
    )
    
    if (-not $InstallPath) {
        # Try to find from registry
        $InstallPath = Get-ItemProperty -Path "HKCU:\Software\totogi-installer" -Name "InstallPath" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty InstallPath
    }
    
    if (-not $InstallPath -or -not (Test-Path $InstallPath)) {
        $script:ValidationErrors += "Installation directory not found"
        return $false
    }
    
    # Check if we can write to the directory
    try {
        $testFile = Join-Path $InstallPath "uninstall-test.tmp"
        [System.IO.File]::WriteAllText($testFile, "test")
        Remove-Item $testFile -Force
        return $true
    } catch {
        $script:ValidationErrors += "Cannot write to installation directory: $($_.Exception.Message)"
        return $false
    }
}

function Test-LockedFiles {
    <#
    .SYNOPSIS
        Check for locked files in the installation directory
    .PARAMETER InstallPath
        Path to the installation directory
    .OUTPUTS
        Returns list of locked files
    #>
    param(
        [string]$InstallPath
    )
    
    $lockedFiles = @()
    
    if (-not $InstallPath -or -not (Test-Path $InstallPath)) {
        return $lockedFiles
    }
    
    $filesToCheck = @(
        "totogi-backend.exe",
        "Totogi Installer.exe"
    )
    
    foreach ($fileName in $filesToCheck) {
        $filePath = Get-ChildItem -Path $InstallPath -Filter $fileName -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
        
        if ($filePath -and (Test-Path $filePath)) {
            try {
                $stream = [System.IO.File]::Open($filePath, 'Open', 'ReadWrite', 'None')
                $stream.Close()
            } catch {
                $lockedFiles += $filePath
            }
        }
    }
    
    if ($lockedFiles.Count -gt 0) {
        $script:ValidationWarnings += "Locked files detected: $($lockedFiles -join ', ')"
    }
    
    return $lockedFiles
}

# ============================================
# Main Validation
# ============================================

function Invoke-PreUninstallValidation {
    <#
    .SYNOPSIS
        Run all pre-uninstall validation checks
    .PARAMETER InstallPath
        Optional installation path
    .OUTPUTS
        Returns validation result object
    #>
    param(
        [string]$InstallPath
    )
    
    $result = @{
        CanProceed = $true
        IsAdmin = $false
        HasRunningProcesses = $false
        HasActiveDeployments = $false
        HasLockedFiles = $false
        Errors = @()
        Warnings = @()
    }
    
    Write-Host "Running pre-uninstall validation checks..." -ForegroundColor Cyan
    
    # Check 1: Admin permissions
    $result.IsAdmin = Test-AdminPermissions
    if (-not $result.IsAdmin) {
        Write-Host "  [INFO] Running without administrator privileges" -ForegroundColor Yellow
    } else {
        Write-Host "  [OK] Running with administrator privileges" -ForegroundColor Green
    }
    
    # Check 2: Running application
    $result.HasRunningProcesses = Test-RunningApplication
    if ($result.HasRunningProcesses) {
        Write-Host "  [WARN] Application is currently running" -ForegroundColor Yellow
        if (-not $Force) {
            $result.CanProceed = $false
        }
    } else {
        Write-Host "  [OK] No running application processes" -ForegroundColor Green
    }
    
    # Check 3: Active deployments
    $result.HasActiveDeployments = Test-ActiveDeployments
    if ($result.HasActiveDeployments) {
        Write-Host "  [WARN] Active deployments detected" -ForegroundColor Yellow
        if (-not $Force) {
            $result.CanProceed = $false
        }
    } else {
        Write-Host "  [OK] No active deployments" -ForegroundColor Green
    }
    
    # Check 4: Installation directory
    $dirValid = Test-InstallationDirectory -InstallPath $InstallPath
    if (-not $dirValid) {
        Write-Host "  [WARN] Installation directory issues" -ForegroundColor Yellow
    } else {
        Write-Host "  [OK] Installation directory accessible" -ForegroundColor Green
    }
    
    # Check 5: Locked files
    $lockedFiles = Test-LockedFiles -InstallPath $InstallPath
    $result.HasLockedFiles = $lockedFiles.Count -gt 0
    if ($result.HasLockedFiles) {
        Write-Host "  [WARN] Some files are locked" -ForegroundColor Yellow
        if (-not $Force) {
            $result.CanProceed = $false
        }
    } else {
        Write-Host "  [OK] No locked files" -ForegroundColor Green
    }
    
    # Collect errors and warnings
    $result.Errors = $script:ValidationErrors
    $result.Warnings = $script:ValidationWarnings
    
    # Summary
    Write-Host ""
    if ($result.CanProceed) {
        Write-Host "Validation PASSED - Uninstall can proceed" -ForegroundColor Green
    } else {
        Write-Host "Validation FAILED - Issues must be resolved before uninstall" -ForegroundColor Red
        Write-Host "Use -Force to override warnings" -ForegroundColor Yellow
    }
    
    return $result
}

# ============================================
# Script Entry Point
# ============================================

if ($MyInvocation.InvocationName -ne '.') {
    # Script is being run directly, not dot-sourced
    $validationResult = Invoke-PreUninstallValidation
    
    if (-not $Silent) {
        if ($validationResult.Warnings.Count -gt 0) {
            Write-Host "`nWarnings:" -ForegroundColor Yellow
            foreach ($warning in $validationResult.Warnings) {
                Write-Host "  - $warning" -ForegroundColor Yellow
            }
        }
        
        if ($validationResult.Errors.Count -gt 0) {
            Write-Host "`nErrors:" -ForegroundColor Red
            foreach ($error in $validationResult.Errors) {
                Write-Host "  - $error" -ForegroundColor Red
            }
        }
    }
    
    # Exit with appropriate code
    if ($validationResult.CanProceed) {
        exit 0
    } else {
        exit 1
    }
}
