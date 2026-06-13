@echo off
REM ============================================================================
REM AWS EKS Context Selector (Windows CMD)
REM
REM After a successful AWS login (via aws-login.bat), this script lists EKS
REM clusters in the active profile + region, lets you pick one, switches
REM kubectl context, and pins a Kubernetes namespace.
REM
REM Default namespace pattern: nexus-ai-%ENVIRONMENT% (ENVIRONMENT defaults to 'dev')
REM Override with --namespace, NAMESPACE=, or --pick-namespace.
REM ============================================================================

setlocal EnableDelayedExpansion

REM -- Directory dance (matches aws-login.bat) --------------------------------
set "ORIGINAL_DIR=%CD%"
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
cd /d "%SCRIPT_DIR%"

set "CACHE_FILE=%SCRIPT_DIR%\.last-eks"

REM -- Source .env.local if present -------------------------------------------
if exist ".env.local" (
    for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env.local") do (
        if not "%%A"=="" (
            set "_K=%%A"
            if "!_K:~0,7!"=="export " set "_K=!_K:~7!"
            set "!_K!=%%~B"
        )
    )
    echo Loaded configuration from .env.local
)

REM -- Defaults ---------------------------------------------------------------
if not defined AWS_PROFILE set "AWS_PROFILE=default"
if not defined AWS_REGION  set "AWS_REGION=us-east-1"

set "PICK_NAMESPACE_FLAG=false"
set "NO_NAMESPACE_FLAG=false"
set "RESET_CACHE=false"
set "NAMESPACE_EXPLICIT=false"

if defined NAMESPACE set "NAMESPACE_EXPLICIT=true"

REM -- Argument parsing -------------------------------------------------------
:argloop
if "%~1"=="" goto :argdone
if /i "%~1"=="--profile" (
    set "AWS_PROFILE=%~2"
    shift
    shift
    goto :argloop
)
if /i "%~1"=="--region" (
    set "AWS_REGION=%~2"
    shift
    shift
    goto :argloop
)
if /i "%~1"=="--cluster" (
    set "EKS_CLUSTER_NAME=%~2"
    shift
    shift
    goto :argloop
)
if /i "%~1"=="--namespace" (
    set "NAMESPACE=%~2"
    set "NAMESPACE_EXPLICIT=true"
    shift
    shift
    goto :argloop
)
if /i "%~1"=="--pick-namespace" (
    set "PICK_NAMESPACE_FLAG=true"
    shift
    goto :argloop
)
if /i "%~1"=="--no-namespace" (
    set "NO_NAMESPACE_FLAG=true"
    shift
    goto :argloop
)
if /i "%~1"=="--reset" (
    set "RESET_CACHE=true"
    shift
    goto :argloop
)
if /i "%~1"=="--help" goto :show_help
if /i "%~1"=="-h"     goto :show_help

echo ERROR: Unknown parameter: %~1
echo    Run '%~nx0 --help' for usage.
goto :error_exit

:show_help
echo Usage: %~nx0 [OPTIONS]
echo.
echo After AWS login, list EKS clusters, pick one, switch kubectl context, pin a namespace.
echo.
echo Options:
echo   --profile NAME       AWS CLI profile to use (default: %%AWS_PROFILE%% or 'default')
echo   --region REGION      AWS region to query (default: %%AWS_REGION%% or 'us-east-1')
echo   --cluster NAME       Non-interactive cluster pick (falls back to menu if not found)
echo   --namespace NS       Pin this namespace onto the kubectl context
echo   --pick-namespace     Show an interactive namespace menu after the cluster picker
echo   --no-namespace       Skip namespace pinning entirely
echo   --reset              Clear the .last-eks cache before resolving
echo   --help               Show this help
echo.
echo Environment variables (also recognized):
echo   AWS_PROFILE, AWS_REGION         Honors values set by aws-login.bat
echo   EKS_CLUSTER_NAME                Same as --cluster
echo   NAMESPACE                       Same as --namespace
echo   ENVIRONMENT                     Used to derive the default namespace: nexus-ai-%%ENVIRONMENT%% (default 'dev')
echo.
echo Examples:
echo   %~nx0                                            # interactive menu, default namespace pattern
echo   %~nx0 --cluster nexus-dev                        # non-interactive cluster pick
echo   set EKS_CLUSTER_NAME=nexus-dev ^&^& %~nx0       # same, via env
echo   %~nx0 --no-namespace --cluster nexus-dev         # cluster only, no namespace pin
echo   set NAMESPACE=nexus-ai-engine-dev ^&^& %~nx0    # nexus-ai-engine namespace
echo   %~nx0 --pick-namespace                           # menu of namespaces after cluster
echo   %~nx0 --reset                                    # clear cache and re-prompt
cd /d "%ORIGINAL_DIR%"
endlocal
exit /b 0

:argdone

REM -- Reset cache if requested -----------------------------------------------
if /i "%RESET_CACHE%"=="true" (
    if exist "%CACHE_FILE%" (
        del /q "%CACHE_FILE%" >nul 2>&1
        echo Cleared .last-eks cache
    )
)

REM -- Prereq checks ----------------------------------------------------------
where aws >nul 2>&1
if errorlevel 1 (
    echo ERROR: aws CLI not found on PATH.
    echo    Install: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html
    goto :error_exit
)

where kubectl >nul 2>&1
if errorlevel 1 (
    echo ERROR: kubectl not found on PATH.
    echo    Install: https://kubernetes.io/docs/tasks/tools/
    goto :error_exit
)

echo Verifying AWS credentials for profile: %AWS_PROFILE%
aws sts get-caller-identity --profile "%AWS_PROFILE%" >nul 2>&1
if errorlevel 1 (
    echo ERROR: AWS credentials are missing or expired for profile '%AWS_PROFILE%'.
    echo.
    echo    Log in first:
    echo      aws-login.bat
    echo.
    echo    Then re-run: %~nx0
    goto :error_exit
)

REM Capture caller identity for the summary block
set "CALLER_ACCOUNT="
set "CALLER_ARN="
for /f "usebackq delims=" %%I in (`aws sts get-caller-identity --profile "%AWS_PROFILE%" --query "Account" --output text 2^>nul`) do set "CALLER_ACCOUNT=%%I"
for /f "usebackq delims=" %%I in (`aws sts get-caller-identity --profile "%AWS_PROFILE%" --query "Arn"     --output text 2^>nul`) do set "CALLER_ARN=%%I"

if not defined CALLER_ACCOUNT set "CALLER_ACCOUNT=?"
if not defined CALLER_ARN     set "CALLER_ARN=?"

echo    Account:  %CALLER_ACCOUNT%
echo    Identity: %CALLER_ARN%
echo    Region:   %AWS_REGION%
echo.

REM -- List clusters ----------------------------------------------------------
echo Listing EKS clusters in %AWS_REGION% ...
set "TMP_LIST=%TEMP%\eks-clusters-%RANDOM%-%RANDOM%.txt"
aws eks list-clusters --region "%AWS_REGION%" --profile "%AWS_PROFILE%" --query "clusters[]" --output text > "%TMP_LIST%" 2>&1
if errorlevel 1 (
    echo ERROR: aws eks list-clusters failed:
    type "%TMP_LIST%"
    del /q "%TMP_LIST%" >nul 2>&1
    goto :error_exit
)

REM AWS returns tab-separated names on one line for --output text on a flat array.
REM Read raw output, then re-tokenize via for-in (splits on space and tab).
set "RAW_CLUSTERS="
for /f "usebackq delims=" %%L in ("%TMP_LIST%") do (
    if defined RAW_CLUSTERS (set "RAW_CLUSTERS=!RAW_CLUSTERS! %%L") else (set "RAW_CLUSTERS=%%L")
)
del /q "%TMP_LIST%" >nul 2>&1

set "CLUSTER_COUNT=0"
for %%X in (!RAW_CLUSTERS!) do (
    set /a CLUSTER_COUNT+=1
    set "CLUSTER_!CLUSTER_COUNT!=%%X"
)

if %CLUSTER_COUNT% EQU 0 (
    echo No EKS clusters found in region '%AWS_REGION%' for profile '%AWS_PROFILE%'.
    echo    Try a different region with --region NAME, or verify the profile permissions.
    cd /d "%ORIGINAL_DIR%"
    endlocal
    exit /b 0
)

echo    Found %CLUSTER_COUNT% cluster(s).
echo.

REM -- Resolve cluster choice -------------------------------------------------
set "SELECTED="

REM 1. Explicit --cluster / EKS_CLUSTER_NAME (validated against the list)
if defined EKS_CLUSTER_NAME (
    for /l %%I in (1,1,%CLUSTER_COUNT%) do (
        if /i "!CLUSTER_%%I!"=="%EKS_CLUSTER_NAME%" set "SELECTED=!CLUSTER_%%I!"
    )
    if defined SELECTED (
        echo Using cluster from --cluster/EKS_CLUSTER_NAME: !SELECTED!
    ) else (
        echo WARNING: Requested cluster '%EKS_CLUSTER_NAME%' not found in %AWS_REGION%.
        echo    Falling back to interactive menu.
    )
)

REM 2. Cached previous selection becomes the menu default
set "DEFAULT_INDEX=1"
if not defined SELECTED (
    if exist "%CACHE_FILE%" (
        set "LAST="
        set /p LAST=<"%CACHE_FILE%"
        if defined LAST (
            for /l %%I in (1,1,%CLUSTER_COUNT%) do (
                if /i "!CLUSTER_%%I!"=="!LAST!" set "DEFAULT_INDEX=%%I"
            )
        )
    )
)

REM 3. Interactive menu
if not defined SELECTED (
    echo Available clusters:
    for /l %%I in (1,1,%CLUSTER_COUNT%) do (
        set "_MARK=  "
        if "%%I"=="!DEFAULT_INDEX!" set "_MARK=* "
        echo   !_MARK!%%I^) !CLUSTER_%%I!
    )
    echo.
    set "CHOICE="
    set /p "CHOICE=Select cluster [!DEFAULT_INDEX!]: "
    if not defined CHOICE set "CHOICE=!DEFAULT_INDEX!"

    set "_VALID=true"
    for /f "delims=0123456789" %%X in ("!CHOICE!") do set "_VALID=false"
    if "!_VALID!"=="false" (
        echo ERROR: Invalid selection: !CHOICE!
        goto :error_exit
    )
    if !CHOICE! LSS 1 (
        echo ERROR: Invalid selection: !CHOICE!
        goto :error_exit
    )
    if !CHOICE! GTR %CLUSTER_COUNT% (
        echo ERROR: Invalid selection: !CHOICE!
        goto :error_exit
    )
    call set "SELECTED=%%CLUSTER_!CHOICE!%%"
)

echo.
echo Selected cluster: %SELECTED%

REM -- update-kubeconfig ------------------------------------------------------
echo Running aws eks update-kubeconfig ...
aws eks update-kubeconfig --name "%SELECTED%" --region "%AWS_REGION%" --profile "%AWS_PROFILE%" --alias "%SELECTED%" >nul 2>&1
if errorlevel 1 (
    echo ERROR: aws eks update-kubeconfig failed for cluster '%SELECTED%'.
    echo    Re-run with --reset, or verify your IAM permissions on this cluster.
    goto :error_exit
)
echo    kubectl context set to: %SELECTED%

kubectl config use-context "%SELECTED%" >nul 2>&1

REM -- Resolve namespace ------------------------------------------------------
set "NAMESPACE_PINNED=false"
set "RESOLVED_NAMESPACE="
set "NAMESPACE_REASON="

if /i "%NO_NAMESPACE_FLAG%"=="true" (
    set "NAMESPACE_REASON=--no-namespace; namespace not pinned"
    goto :verify_namespace
)

if /i "%PICK_NAMESPACE_FLAG%"=="true" goto :pick_namespace

if defined NAMESPACE (
    set "RESOLVED_NAMESPACE=%NAMESPACE%"
    goto :verify_namespace
)

if not defined ENVIRONMENT set "ENVIRONMENT=dev"
set "RESOLVED_NAMESPACE=nexus-ai-%ENVIRONMENT%"
goto :verify_namespace

:pick_namespace
echo.
echo Listing namespaces in %SELECTED% ...
set "NS_COUNT=0"
for /f "usebackq tokens=*" %%N in (`kubectl get ns -o name 2^>nul`) do (
    set "_NS=%%N"
    set "_NS=!_NS:namespace/=!"
    set /a NS_COUNT+=1
    set "NS_!NS_COUNT!=!_NS!"
)
if !NS_COUNT! EQU 0 (
    echo WARNING: Could not list namespaces ^(RBAC?^). Skipping namespace pin.
    set "NAMESPACE_REASON=namespaces not listable; skipped"
    goto :verify_namespace
)
set "NS_DEFAULT_IDX=1"
if defined NAMESPACE (
    for /l %%I in (1,1,!NS_COUNT!) do (
        if /i "!NS_%%I!"=="!NAMESPACE!" set "NS_DEFAULT_IDX=%%I"
    )
)
echo Available namespaces:
for /l %%I in (1,1,!NS_COUNT!) do (
    set "_MARK=  "
    if "%%I"=="!NS_DEFAULT_IDX!" set "_MARK=* "
    echo   !_MARK!%%I^) !NS_%%I!
)
echo.
set "NS_CHOICE="
set /p "NS_CHOICE=Select namespace [!NS_DEFAULT_IDX!]: "
if not defined NS_CHOICE set "NS_CHOICE=!NS_DEFAULT_IDX!"
set "_VALID=true"
for /f "delims=0123456789" %%X in ("!NS_CHOICE!") do set "_VALID=false"
if "!_VALID!"=="false" (
    echo ERROR: Invalid namespace selection: !NS_CHOICE!
    goto :error_exit
)
if !NS_CHOICE! LSS 1 (
    echo ERROR: Invalid namespace selection: !NS_CHOICE!
    goto :error_exit
)
if !NS_CHOICE! GTR !NS_COUNT! (
    echo ERROR: Invalid namespace selection: !NS_CHOICE!
    goto :error_exit
)
call set "RESOLVED_NAMESPACE=%%NS_!NS_CHOICE!%%"

:verify_namespace
if not defined RESOLVED_NAMESPACE goto :smoke_checks

kubectl get ns "!RESOLVED_NAMESPACE!" >nul 2>&1
if not errorlevel 1 (
    kubectl config set-context --current --namespace="!RESOLVED_NAMESPACE!" >nul 2>&1
    if not errorlevel 1 (
        set "NAMESPACE_PINNED=true"
    ) else (
        set "NAMESPACE_REASON=kubectl config set-context failed; not pinned"
    )
    goto :smoke_checks
)

REM Namespace does not exist
if /i "!NAMESPACE_EXPLICIT!"=="true" if /i not "!PICK_NAMESPACE_FLAG!"=="true" goto :offer_create
set "NAMESPACE_REASON=default namespace '!RESOLVED_NAMESPACE!' does not exist; skipped"
goto :smoke_checks

:offer_create
echo.
echo WARNING: Namespace '!RESOLVED_NAMESPACE!' does not exist in %SELECTED%.
set "NS_ACTION="
set /p "NS_ACTION=    (s)kip pinning [default] or (c)reate the namespace now? [s/c] "
if not defined NS_ACTION set "NS_ACTION=s"
if /i not "!NS_ACTION:~0,1!"=="c" (
    set "NAMESPACE_REASON=namespace '!RESOLVED_NAMESPACE!' does not exist; skipped"
    goto :smoke_checks
)
kubectl create namespace "!RESOLVED_NAMESPACE!" >nul 2>&1
if errorlevel 1 (
    set "NAMESPACE_REASON=kubectl create namespace failed; not pinned"
    goto :smoke_checks
)
echo    Created namespace: !RESOLVED_NAMESPACE!
kubectl config set-context --current --namespace="!RESOLVED_NAMESPACE!" >nul 2>&1
if not errorlevel 1 set "NAMESPACE_PINNED=true"

:smoke_checks
REM -- Smoke checks (informational) -------------------------------------------
echo.
echo Smoke checks ...
set "CURRENT_CTX="
for /f "usebackq delims=" %%C in (`kubectl config current-context 2^>nul`) do set "CURRENT_CTX=%%C"
if not defined CURRENT_CTX set "CURRENT_CTX=?"
echo    current-context: !CURRENT_CTX!

if /i "!NAMESPACE_PINNED!"=="true" (
    kubectl get ns "!RESOLVED_NAMESPACE!" >nul 2>&1
    if not errorlevel 1 (
        echo    namespace '!RESOLVED_NAMESPACE!': reachable
    ) else (
        echo    namespace '!RESOLVED_NAMESPACE!': NOT reachable
    )
    set "CAN_I="
    for /f "usebackq delims=" %%R in (`kubectl auth can-i get pods -n "!RESOLVED_NAMESPACE!" 2^>nul`) do set "CAN_I=%%R"
    if not defined CAN_I set "CAN_I=no"
    echo    auth can-i get pods -n !RESOLVED_NAMESPACE!: !CAN_I!
)

REM -- Save cache -------------------------------------------------------------
> "%CACHE_FILE%" echo %SELECTED%

REM -- Cluster metadata for the summary ---------------------------------------
set "CLUSTER_ARN="
set "CLUSTER_ENDPOINT="
for /f "usebackq delims=" %%I in (`aws eks describe-cluster --name "%SELECTED%" --region "%AWS_REGION%" --profile "%AWS_PROFILE%" --query "cluster.arn"      --output text 2^>nul`) do set "CLUSTER_ARN=%%I"
for /f "usebackq delims=" %%I in (`aws eks describe-cluster --name "%SELECTED%" --region "%AWS_REGION%" --profile "%AWS_PROFILE%" --query "cluster.endpoint" --output text 2^>nul`) do set "CLUSTER_ENDPOINT=%%I"

REM -- Summary ----------------------------------------------------------------
echo.
echo EKS context ready
echo =====================================================
echo    Cluster:    %SELECTED%
echo    Region:     %AWS_REGION%
echo    Profile:    %AWS_PROFILE%
echo    Account:    %CALLER_ACCOUNT%
echo    Context:    !CURRENT_CTX!
if /i "!NAMESPACE_PINNED!"=="true" (
    echo    Namespace:  !RESOLVED_NAMESPACE!   ^(pinned^)
) else (
    if defined NAMESPACE_REASON echo    Namespace:  !NAMESPACE_REASON!
)
if defined CLUSTER_ENDPOINT echo    Endpoint:   !CLUSTER_ENDPOINT!
if defined CLUSTER_ARN      echo    ARN:        !CLUSTER_ARN!
echo =====================================================
echo.
echo Next:
echo    kubectl get pods
if /i "!NAMESPACE_PINNED!"=="true" (
    echo    kubectl get pods -n !RESOLVED_NAMESPACE!   ^(already pinned, -n optional^)
)
echo.
echo Done!

cd /d "%ORIGINAL_DIR%"
endlocal
exit /b 0

:error_exit
cd /d "%ORIGINAL_DIR%"
endlocal
exit /b 1
