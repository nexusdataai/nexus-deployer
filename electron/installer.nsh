; installer.nsh
; Custom NSIS installer hooks for Totogi Capability Installer
; This file is included by electron-builder during NSIS installer creation

!include "LogicLib.nsh"
!include "FileFunc.nsh"

; Variables for user choices
Var DeleteAppData

; ============================================
; Custom Install Hooks
; ============================================

!macro customInstall
  ; Initialize variable to avoid NSIS warning
  StrCpy $DeleteAppData "false"
  
  ; Create scripts directory in installation folder
  CreateDirectory "$INSTDIR\scripts"
  
  ; Copy cleanup scripts to installation directory
  SetOutPath "$INSTDIR\scripts"
  File "${BUILD_RESOURCES_DIR}\scripts\terminate-processes.ps1"
  File "${BUILD_RESOURCES_DIR}\scripts\cleanup-appdata.ps1"
  File "${BUILD_RESOURCES_DIR}\scripts\cleanup-temp.ps1"
  File "${BUILD_RESOURCES_DIR}\scripts\cleanup-registry.ps1"
  File "${BUILD_RESOURCES_DIR}\scripts\uninstall-logger.ps1"
  
  ; Write installation info to registry
  WriteRegStr HKCU "Software\totogi-installer" "InstallPath" "$INSTDIR"
  WriteRegStr HKCU "Software\totogi-installer" "Version" "${VERSION}"
  WriteRegStr HKCU "Software\totogi-installer" "InstallDate" "$INSTDIR"
!macroend

; ============================================
; Custom Uninstall Init
; ============================================

!macro customUnInit
  ; Initialize log file
  FileOpen $0 "$TEMP\totogi-uninstall.log" w
  FileWrite $0 "========================================$\r$\n"
  FileWrite $0 "Totogi Installer Uninstall Log$\r$\n"
  FileWrite $0 "========================================$\r$\n"
  FileClose $0
!macroend

; ============================================
; Custom Uninstall Hooks
; ============================================

!macro customUnInstall
  ; Log uninstall start
  DetailPrint "Starting Totogi Installer cleanup..."
  
  ; ----------------------------------------
  ; Step 1: Terminate running processes
  ; ----------------------------------------
  DetailPrint "Terminating running processes..."
  
  ; Kill backend process
  nsExec::ExecToLog 'taskkill /F /IM totogi-backend.exe /T'
  Pop $0
  
  ; Kill Electron app
  nsExec::ExecToLog 'taskkill /F /IM "Totogi Installer.exe" /T'
  Pop $0
  
  ; Wait for processes to fully terminate
  Sleep 2000
  
  ; ----------------------------------------
  ; Step 2: Run PowerShell cleanup scripts
  ; ----------------------------------------
  
  ; Check if PowerShell is available
  nsExec::ExecToStack 'powershell -Command "exit 0"'
  Pop $0
  
  ${If} $0 == 0
    DetailPrint "Running cleanup scripts..."
    
    ; Run process termination script (in case taskkill missed any)
    ${If} ${FileExists} "$INSTDIR\scripts\terminate-processes.ps1"
      DetailPrint "Running process termination script..."
      nsExec::ExecToLog 'powershell -ExecutionPolicy Bypass -File "$INSTDIR\scripts\terminate-processes.ps1"'
      Pop $0
    ${EndIf}
    
    ; Run temp cleanup script
    ${If} ${FileExists} "$INSTDIR\scripts\cleanup-temp.ps1"
      DetailPrint "Cleaning temporary files..."
      nsExec::ExecToLog 'powershell -ExecutionPolicy Bypass -File "$INSTDIR\scripts\cleanup-temp.ps1"'
      Pop $0
    ${EndIf}
    
    ; Run registry cleanup script
    ${If} ${FileExists} "$INSTDIR\scripts\cleanup-registry.ps1"
      DetailPrint "Cleaning registry entries..."
      nsExec::ExecToLog 'powershell -ExecutionPolicy Bypass -File "$INSTDIR\scripts\cleanup-registry.ps1"'
      Pop $0
    ${EndIf}
  ${Else}
    DetailPrint "PowerShell not available, using fallback cleanup..."
  ${EndIf}
  
  ; ----------------------------------------
  ; Step 3: Clean application data (if user opted in)
  ; ----------------------------------------
  
  ; Check if running in silent mode
  ${IfNot} ${Silent}
    ; Interactive mode - ask user about app data
    MessageBox MB_YESNO|MB_ICONQUESTION "Do you want to remove all application data (settings, logs, cached data)?$\r$\n$\r$\nClick Yes to remove all data.$\r$\nClick No to keep your data for future installations." IDYES deleteData IDNO keepData
    
    deleteData:
      StrCpy $DeleteAppData "true"
      Goto continueUninstall
    
    keepData:
      StrCpy $DeleteAppData "false"
      Goto continueUninstall
  ${Else}
    ; Silent mode - check for /D flag
    ${GetParameters} $R0
    ${GetOptions} $R0 "/D" $R1
    ${If} ${Errors}
      ; No /D flag - preserve data by default
      StrCpy $DeleteAppData "false"
    ${Else}
      ; /D flag present - delete data
      StrCpy $DeleteAppData "true"
    ${EndIf}
  ${EndIf}
  
  continueUninstall:
  
  ${If} $DeleteAppData == "true"
    DetailPrint "Removing application data..."
    
    ; Run app data cleanup script if available
    ${If} ${FileExists} "$INSTDIR\scripts\cleanup-appdata.ps1"
      nsExec::ExecToLog 'powershell -ExecutionPolicy Bypass -File "$INSTDIR\scripts\cleanup-appdata.ps1" -DeleteData'
      Pop $0
    ${Else}
      ; Fallback: manual cleanup
      RMDir /r "$APPDATA\totogi-installer"
      RMDir /r "$LOCALAPPDATA\totogi-installer"
      RMDir /r "$LOCALAPPDATA\Totogi Installer"
    ${EndIf}
  ${Else}
    DetailPrint "Preserving application data..."
  ${EndIf}
  
  ; ----------------------------------------
  ; Step 4: Clean registry (fallback if script failed)
  ; ----------------------------------------
  DetailPrint "Cleaning registry entries..."
  DeleteRegKey HKCU "Software\totogi-installer"
  DeleteRegKey HKCU "Software\Totogi Installer"
  
  ; ----------------------------------------
  ; Step 5: Remove scripts directory
  ; ----------------------------------------
  RMDir /r "$INSTDIR\scripts"
  
  ; ----------------------------------------
  ; Step 6: Final cleanup
  ; ----------------------------------------
  DetailPrint "Cleanup complete!"
  
  ; Log completion
  FileOpen $0 "$TEMP\totogi-uninstall.log" a
  FileWrite $0 "$\r$\n========================================$\r$\n"
  FileWrite $0 "Uninstall completed at: $INSTDIR$\r$\n"
  FileWrite $0 "Application data deleted: $DeleteAppData$\r$\n"
  FileWrite $0 "========================================$\r$\n"
  FileClose $0
!macroend

; ============================================
; Custom Pages (optional)
; ============================================

; You can add custom installer pages here if needed
; !insertmacro MUI_PAGE_CUSTOM customPage customPageLeave
