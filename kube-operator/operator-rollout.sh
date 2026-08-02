#!/bin/sh
# Operator Rollout Update + Diagnostics
#
# Performs versioned rolling upgrade of the nexus-operator Deployment in
# the nexus-system namespace, waits for full readiness, then runs minimal
# operator-side diagnostics (pod status, recent log tail, managed CRs).
# Supports rollback on failure (automatic or manual).
#
# Mirrors the patterns in app-rollout.sh (app rollout) but trimmed for the
# single-component, single-replica operator Deployment.
#
# Usage:
#   sh operator-rollout.sh                            # Restart in place, then diagnose
#   sh operator-rollout.sh --version 1.3.0-a7f2bc1   # Upgrade to specific version
#   sh operator-rollout.sh --rollback                 # Rollback to previous version
#   sh operator-rollout.sh --rollback-to 1.2.0       # Rollback to explicit version
#   sh operator-rollout.sh --list-versions            # List available ECR tags
#   sh operator-rollout.sh --skip-diagnostics         # Rollout + wait only
#   sh operator-rollout.sh --diagnostics-only         # Just run diagnostics
#   sh operator-rollout.sh --dry-run --version TAG    # Show plan without executing

set -e

# ── Colors ─────────────────────────────────────────────────────────
GREEN="\033[32m"
RED="\033[31m"
YELLOW="\033[33m"
CYAN="\033[36m"
BOLD="\033[1m"
DIM="\033[2m"
RESET="\033[0m"

# ── Defaults ───────────────────────────────────────────────────────
NAMESPACE="nexus-system"
DEPLOYMENT="nexus-operator"
CONTAINER="operator"
ECR_REPO="nexus-operator"
TIMEOUT=300
REGION="us-east-1"
AWS_PROFILE="${AWS_PROFILE:-external-access}"
LOG_TAIL=50

SKIP_DIAGNOSTICS=0
DIAGNOSTICS_ONLY=0
DRY_RUN=0

# Version control
TARGET_VERSION=""
ROLLBACK_MODE=0
ROLLBACK_TO_VERSION=""
LIST_VERSIONS=0
AUTO_ROLLBACK=1

# ── Load .env.local (overrides defaults; CLI args override these) ─
_script_dir="$(cd "$(dirname "$0")" && pwd)"
SCRIPT_DIR="$_script_dir"
. "${SCRIPT_DIR}/lib/init-kube-env.sh"
_env_local="${_script_dir}/.env.local"
[ -f "$_env_local" ] && . "$_env_local"
unset _script_dir _env_local

# ── Argument parsing ──────────────────────────────────────────────
while [ $# -gt 0 ]; do
    case "$1" in
        --namespace|-n)     NAMESPACE="$2"; shift 2 ;;
        --deployment)       DEPLOYMENT="$2"; shift 2 ;;
        --timeout)          TIMEOUT="$2"; shift 2 ;;
        --log-tail)         LOG_TAIL="$2"; shift 2 ;;
        --skip-diagnostics) SKIP_DIAGNOSTICS=1; shift ;;
        --diagnostics-only) DIAGNOSTICS_ONLY=1; shift ;;
        --dry-run)          DRY_RUN=1; shift ;;
        --version)          TARGET_VERSION="$2"; shift 2 ;;
        --rollback)         ROLLBACK_MODE=1; shift ;;
        --rollback-to)      ROLLBACK_MODE=1; ROLLBACK_TO_VERSION="$2"; shift 2 ;;
        --list-versions)    LIST_VERSIONS=1; shift ;;
        --no-auto-rollback) AUTO_ROLLBACK=0; shift ;;
        --region)           REGION="$2"; shift 2 ;;
        --profile)          AWS_PROFILE="$2"; shift 2 ;;
        --help|-h)
            cat <<'EOF'
Operator Rollout Update + Diagnostics

Usage: sh operator-rollout.sh [OPTIONS]

Version Options:
  --version TAG           Target version tag (e.g. 1.3.0-a7f2bc1)
  --rollback              Rollback to previous version (from annotation)
  --rollback-to TAG       Rollback to explicit version tag
  --list-versions         List available image tags in ECR
  --no-auto-rollback      Disable automatic rollback on failure

Options:
  --namespace NS      Override namespace (default: nexus-system)
  --deployment NAME   Override deployment name (default: nexus-operator)
  --timeout SECS      Rollout timeout (default: 300)
  --log-tail N        Lines of operator log to tail in diagnostics (default: 50)
  --skip-diagnostics  Only rollout + wait, skip diagnostics
  --diagnostics-only  Skip rollout, just run diagnostics
  --dry-run           Show what would be done without executing
  --region REGION     AWS region (default: us-east-1)
  --profile PROFILE   AWS profile (default: external-access)
  --help              Show this help

Phases:
  0.  Pre-flight (verify image in ECR, record current version)
  1.  Image update (or restart) and wait for readiness
  2.  Operator diagnostics (pod status, log tail, managed CRs)

On failure: auto-rollback via kubectl rollout undo (disable with --no-auto-rollback)
EOF
            exit 0
            ;;
        *)
            echo "Unknown option: $1"; exit 1 ;;
    esac
done

# ── Utility ────────────────────────────────────────────────────────
log_info()  { printf "${CYAN}▶${RESET} %s\n" "$1"; }
log_ok()    { printf "${GREEN}✓${RESET} %s\n" "$1"; }
log_fail()  { printf "${RED}✗${RESET} %s\n" "$1"; }
log_warn()  { printf "${YELLOW}⚠${RESET} %s\n" "$1"; }
log_phase() { printf "\n${BOLD}── %s ──${RESET}\n" "$1"; }

run_cmd() {
    if [ "$DRY_RUN" = "1" ]; then
        printf "  ${DIM}[dry-run] %s${RESET}\n" "$*"
        return 0
    fi
    eval "$@"
}

# Pod-template-hash of the newest ReplicaSet, used to scope selectors to
# the new generation during/after a rollout (excludes terminating pods).
latest_rs_hash() {
    kubectl get rs -l "app.kubernetes.io/name=${DEPLOYMENT}" -n "$NAMESPACE" \
        --sort-by=.metadata.creationTimestamp \
        -o jsonpath='{.items[-1:].metadata.labels.pod-template-hash}' 2>/dev/null
}

get_pod() {
    _hash=$(latest_rs_hash)
    _selector="app.kubernetes.io/name=${DEPLOYMENT}"
    [ -n "$_hash" ] && _selector="${_selector},pod-template-hash=${_hash}"
    kubectl get pods -l "$_selector" -n "$NAMESPACE" \
        --field-selector=status.phase=Running \
        --sort-by=.metadata.creationTimestamp \
        -o jsonpath='{.items[-1:].metadata.name}' 2>/dev/null
}

get_current_image() {
    kubectl get "deployment/${DEPLOYMENT}" -n "$NAMESPACE" \
        -o jsonpath="{.spec.template.spec.containers[?(@.name==\"${CONTAINER}\")].image}" 2>/dev/null || echo ""
}

get_current_version_annotation() {
    kubectl get "deployment/${DEPLOYMENT}" -n "$NAMESPACE" \
        -o jsonpath='{.metadata.annotations.nexus\.com/app-version}' 2>/dev/null || echo ""
}

get_previous_version_annotation() {
    kubectl get "deployment/${DEPLOYMENT}" -n "$NAMESPACE" \
        -o jsonpath='{.metadata.annotations.nexus\.com/previous-version}' 2>/dev/null || echo ""
}

get_ecr_registry() {
    ACCOUNT_ID=$(aws sts get-caller-identity --profile "${AWS_PROFILE}" --query Account --output text \
        --cli-connect-timeout 5 --cli-read-timeout 10 2>/dev/null || echo "")
    if [ -z "$ACCOUNT_ID" ]; then
        ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text \
            --cli-connect-timeout 5 --cli-read-timeout 10 2>/dev/null || echo "")
    fi
    echo "${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
}

verify_image_exists() {
    _tag="$1"
    aws ecr describe-images --repository-name "${ECR_REPO}" --image-ids "imageTag=${_tag}" \
        --region "${REGION}" --profile "${AWS_PROFILE}" \
        --cli-connect-timeout 5 --cli-read-timeout 10 > /dev/null 2>&1
}

# Given a tag (e.g. "latest"), find a sibling semver-style tag (X.Y.Z[-SUFFIX])
# sharing the same ECR image digest. Returns the original tag unchanged if it
# already looks like semver, or if no semver alias can be found.
resolve_tag_to_semver() {
    _tag="$1"
    [ -z "$_tag" ] && return 0
    case "$_tag" in
        [0-9]*.[0-9]*.[0-9]*) echo "$_tag"; return 0 ;;
    esac
    # Capture stderr too so we can surface a visible warning if AWS fails
    # (e.g. SSO token expired, profile not configured, ECR throttling). The
    # || branch keeps the script alive under `set -e` and falls back to the
    # original tag so the caller sees something sensible.
    _digest=$(aws ecr describe-images --repository-name "${ECR_REPO}" \
        --image-ids "imageTag=${_tag}" \
        --region "${REGION}" --profile "${AWS_PROFILE}" \
        --cli-connect-timeout 5 --cli-read-timeout 10 \
        --query 'imageDetails[0].imageDigest' --output text 2>&1) || {
        printf >&2 '\033[33m⚠ resolve_tag_to_semver: aws ecr describe-images failed for tag=%s — %s\033[0m\n' \
            "$_tag" "$(printf '%s' "$_digest" | awk 'NF{print; exit}')"
        echo "$_tag"; return 0
    }
    if [ -z "$_digest" ] || [ "$_digest" = "None" ]; then
        echo "$_tag"; return 0
    fi
    _siblings=$(aws ecr describe-images --repository-name "${ECR_REPO}" \
        --image-ids "imageDigest=${_digest}" \
        --region "${REGION}" --profile "${AWS_PROFILE}" \
        --cli-connect-timeout 5 --cli-read-timeout 10 \
        --query 'imageDetails[0].imageTags[]' --output text 2>&1) || {
        printf >&2 '\033[33m⚠ resolve_tag_to_semver: aws ecr (siblings) failed for digest=%s — %s\033[0m\n' \
            "${_digest:0:24}…" "$(printf '%s' "$_siblings" | awk 'NF{print; exit}')"
        echo "$_tag"; return 0
    }
    for _sib in $_siblings; do
        case "$_sib" in
            [0-9]*.[0-9]*.[0-9]*) echo "$_sib"; return 0 ;;
        esac
    done
    echo "$_tag"
}

# Return the semver version actually running inside the operator pod, derived
# from the pod's containerStatuses[].imageID digest mapped back to ECR tags.
# This reflects what the kubelet pulled, which can differ from the
# deployment's image-tag string (e.g. when :latest has been rotated since
# the pod started). Returns empty string if it cannot be resolved.
get_running_pod_version() {
    _rp_pod=$(get_pod)
    [ -z "$_rp_pod" ] && { echo ""; return 0; }
    _image_id=$(kubectl get pod "$_rp_pod" -n "$NAMESPACE" \
        -o jsonpath="{.status.containerStatuses[?(@.name==\"${CONTAINER}\")].imageID}" 2>/dev/null)
    case "$_image_id" in
        *@sha256:*) _digest="${_image_id##*@}" ;;
        *)          echo ""; return 0 ;;
    esac
    _tags=$(aws ecr describe-images --repository-name "${ECR_REPO}" \
        --image-ids "imageDigest=${_digest}" \
        --region "${REGION}" --profile "${AWS_PROFILE}" \
        --cli-connect-timeout 5 --cli-read-timeout 10 \
        --query 'imageDetails[0].imageTags[]' --output text 2>&1) || {
        printf >&2 '\033[33m⚠ get_running_pod_version: aws ecr describe-images failed for digest=%s — %s\033[0m\n' \
            "${_digest:0:24}…" "$(printf '%s' "$_tags" | awk 'NF{print; exit}')"
        echo ""; return 0
    }
    for _t in $_tags; do
        case "$_t" in
            [0-9]*.[0-9]*.[0-9]*) echo "$_t"; return 0 ;;
        esac
    done
    for _t in $_tags; do
        [ -n "$_t" ] && [ "$_t" != "latest" ] && [ "$_t" != "None" ] && { echo "$_t"; return 0; }
    done
    echo ""
}

annotate_version() {
    _version="$1"
    _prev_version="$2"
    _now=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    kubectl annotate "deployment/${DEPLOYMENT}" -n "$NAMESPACE" --overwrite \
        "nexus.ai/app-version=${_version}" \
        "nexus.ai/previous-version=${_prev_version}" \
        "nexus.ai/deployed-at=${_now}" \
        "nexus.ai/deployed-by=operator-rollout.sh" 2>/dev/null || true
}

OVERALL_EXIT=0

# ── Pre-flight: AWS credential check ───────────────────────────────
# Every code path below issues at least one `aws ecr describe-images` or
# similar AWS API call. Without an upfront probe, expired credentials cause
# each call to retry-with-backoff for ~30-180s before the (silenced) error
# surfaces — to the operator the script appears to hang at the next print.
# Probe sts:GetCallerIdentity with short timeouts; bail out fast on failure.
_preflight_err=$(aws sts get-caller-identity \
    --profile "${AWS_PROFILE}" \
    --cli-connect-timeout 5 --cli-read-timeout 10 \
    --output text 2>&1 >/dev/null) || {
    log_fail "AWS credentials are expired or unreachable (profile: ${AWS_PROFILE})"
    printf "      ${DIM}%s${RESET}\n" "$(echo "$_preflight_err" | head -n1)"
    log_info "Refresh credentials, e.g.:"
    printf "        ${BOLD}cd ~/trilogy/nexus-backend && bash aws-login.sh${RESET}\n"
    exit 1
}

# ── List Versions Mode ─────────────────────────────────────────────
if [ "$LIST_VERSIONS" = "1" ]; then
    printf "\n${BOLD}Available Image Tags in ECR${RESET}\n\n"
    printf "${BOLD}${ECR_REPO}${RESET}:\n"
    aws ecr describe-images --repository-name "${ECR_REPO}" \
        --region "${REGION}" --profile "${AWS_PROFILE}" \
        --cli-connect-timeout 5 --cli-read-timeout 10 \
        --query 'sort_by(imageDetails,& imagePushedAt)[*].{tags:imageTags,pushed:imagePushedAt,size:imageSizeInBytes}' \
        --output json 2>/dev/null | python3 -c "
import sys, json
data = json.load(sys.stdin)
for img in reversed(data[-20:]):
    tags = img.get('tags') or ['<untagged>']
    pushed = img.get('pushed','?')[:19]
    size_mb = round((img.get('size',0) or 0) / 1048576, 1)
    print(f'  {pushed}  {size_mb:>6.1f}MB  {\" | \".join(tags)}')
" 2>/dev/null || echo "  (failed to query ECR)"
    echo ""
    exit 0
fi

# ── Pre-flight: operator deployment must exist ─────────────────────
# This script performs ROLLOUTS — it requires an existing Deployment to act
# on. Detect the "operator never deployed" and "cluster unreachable" cases
# upfront with clear messages, instead of letting later `kubectl rollout
# restart` / `kubectl set image` fail with cryptic NotFound / Unauthorized.
_op_check_err=$(kubectl get "deployment/${DEPLOYMENT}" -n "$NAMESPACE" 2>&1 >/dev/null) || {
    if echo "$_op_check_err" | grep -qi "not found"; then
        log_fail "Operator deployment '${DEPLOYMENT}' does not exist in namespace '${NAMESPACE}'."
        log_info "This script performs rollout updates against an EXISTING deployment."
        log_info "To deploy the operator for the first time, run:"
        printf "        ${BOLD}cd %s && ./operator.sh deploy${RESET}\n" \
               "$(cd "$(dirname "$0")" && pwd)"
    elif echo "$_op_check_err" | grep -qiE 'unauthorized|forbidden'; then
        log_fail "kubectl cannot access cluster (authorization failed)."
        printf "      ${DIM}%s${RESET}\n" "$(echo "$_op_check_err" | head -n1)"
        log_info "Refresh kubectl credentials, e.g.:"
        printf "        ${BOLD}aws eks update-kubeconfig --name <cluster> --region <region> --profile %s${RESET}\n" "$AWS_PROFILE"
    else
        log_fail "kubectl cannot reach the cluster or describe the deployment."
        printf "      ${DIM}%s${RESET}\n" "$(echo "$_op_check_err" | head -n1)"
        printf "${CYAN}▶${RESET} Verify cluster connectivity:  ${BOLD}kubectl get nodes${RESET}\n"
    fi
    exit 1
}

# ── Header ─────────────────────────────────────────────────────────
ECR_REGISTRY=$(get_ecr_registry)

printf "\n${BOLD}Operator Rollout Update + Diagnostics${RESET}\n"
printf "Namespace:   ${BOLD}${NAMESPACE}${RESET}\n"
printf "Deployment:  ${BOLD}${DEPLOYMENT}${RESET}\n"
printf "Container:   ${BOLD}${CONTAINER}${RESET}\n"
printf "Timeout:     ${TIMEOUT}s\n"
printf "ECR:         ${ECR_REGISTRY}/${ECR_REPO}\n"
[ -n "$TARGET_VERSION" ] && printf "Version:     ${BOLD}${TARGET_VERSION}${RESET}\n"
[ "$ROLLBACK_MODE" = "1" ] && printf "Mode:        ${YELLOW}ROLLBACK${RESET}\n"
[ "$DRY_RUN" = "1" ] && printf "${YELLOW}DRY RUN — no changes will be made${RESET}\n"
echo ""

# ── Planned Deployment ────────────────────────────────────────────
if [ "$DIAGNOSTICS_ONLY" = "0" ]; then
    printf "${BOLD}Planned Deployment:${RESET}\n"
    _pd_current_ann=$(get_current_version_annotation)
    _pd_current_img=$(get_current_image)
    _pd_current_tag=$(echo "$_pd_current_img" | grep -o ':[^:]*$' | tr -d ':')
    _pd_current="${_pd_current_ann:-${_pd_current_tag:-(none)}}"

    # Actual semver running in the pod (digest-based, may differ from spec tag)
    _pd_running_ver=$(get_running_pod_version)
    if [ -n "$_pd_running_ver" ]; then
        if [ -n "$_pd_current_tag" ] && [ "$_pd_running_ver" != "$_pd_current_tag" ]; then
            printf "  ${DIM}Running in pod:${RESET} ${BOLD}%s${RESET} ${DIM}(deployed as :%s)${RESET}\n" \
                   "$_pd_running_ver" "$_pd_current_tag"
        else
            printf "  ${DIM}Running in pod:${RESET} ${BOLD}%s${RESET}\n" "$_pd_running_ver"
        fi
    fi

    if [ "$ROLLBACK_MODE" = "1" ]; then
        if [ -n "$ROLLBACK_TO_VERSION" ]; then
            _pd_planned="$ROLLBACK_TO_VERSION"
        else
            _pd_planned=$(get_previous_version_annotation)
        fi
    elif [ -n "$TARGET_VERSION" ]; then
        _pd_planned="$TARGET_VERSION"
    else
        _pd_planned="$_pd_current"
    fi

    # Resolve "latest" / non-semver tags to their underlying semver for display.
    # Use parens for the "current" annotation so it doesn't visually clash with
    # the "current → planned" arrow used between two distinct versions.
    _pd_current_disp="$_pd_current"
    _pd_current_resolved=$(resolve_tag_to_semver "$_pd_current")
    [ -n "$_pd_current_resolved" ] && [ "$_pd_current_resolved" != "$_pd_current" ] \
        && _pd_current_disp="${_pd_current} (${_pd_current_resolved})"

    _pd_planned_disp="$_pd_planned"
    _pd_planned_resolved=$(resolve_tag_to_semver "$_pd_planned")
    [ -n "$_pd_planned_resolved" ] && [ "$_pd_planned_resolved" != "$_pd_planned" ] \
        && _pd_planned_disp="${_pd_planned} → ${_pd_planned_resolved}"

    if [ -z "$_pd_planned" ]; then
        printf "  ${DIM}%s${RESET} → ${YELLOW}(unresolved)${RESET}\n" "${_pd_current_disp}"
    elif [ "$ROLLBACK_MODE" != "1" ] && [ -z "$TARGET_VERSION" ] && [ "$_pd_planned" = "$_pd_current" ]; then
        printf "  ${BOLD}%s${RESET}  ${DIM}(restart, same image)${RESET}\n" "${_pd_planned_disp}"
    else
        printf "  ${DIM}%s${RESET} → ${BOLD}%s${RESET}\n" "${_pd_current_disp}" "${_pd_planned_disp}"
    fi
    echo ""
fi

# ── Phase 0 + 1: Pre-flight, Image Update / Restart, Wait ─────────
if [ "$DIAGNOSTICS_ONLY" = "0" ]; then
    # Determine target version
    if [ "$ROLLBACK_MODE" = "1" ]; then
        if [ -n "$ROLLBACK_TO_VERSION" ]; then
            comp_version="$ROLLBACK_TO_VERSION"
        else
            comp_version=$(get_previous_version_annotation)
            if [ -z "$comp_version" ]; then
                log_fail "No previous version annotation found — cannot rollback"
                log_info "Use --rollback-to TAG to specify an explicit version"
                exit 1
            fi
        fi
    else
        comp_version="$TARGET_VERSION"
    fi

    # ── Phase 0: Pre-flight ──
    if [ -n "$comp_version" ]; then
        log_phase "Phase 0: Pre-flight for operator → ${comp_version}"

        current_image=$(get_current_image)
        current_version=$(get_current_version_annotation)
        [ -z "$current_version" ] && current_version=$(echo "$current_image" | grep -o ':[^:]*$' | tr -d ':')
        [ -z "$current_version" ] && current_version="unknown"

        printf "  Current:  ${DIM}%s${RESET}\n" "${current_version}"
        printf "  Target:   ${BOLD}%s${RESET}\n" "${comp_version}"

        if [ "$DRY_RUN" = "0" ]; then
            log_info "Verifying image ${ECR_REPO}:${comp_version} exists in ECR..."
            if ! verify_image_exists "$comp_version"; then
                log_fail "Image ${ECR_REPO}:${comp_version} NOT FOUND in ECR"
                log_info "Available tags: sh operator-rollout.sh --list-versions"
                exit 1
            fi
            log_ok "Image verified in ECR"
        fi

        full_image="${ECR_REGISTRY}/${ECR_REPO}:${comp_version}"

        # Save current version for rollback
        if [ "$DRY_RUN" = "0" ] && [ "$ROLLBACK_MODE" != "1" ]; then
            annotate_version "$comp_version" "$current_version"
        fi

        # ── Phase 1: Image Update ──
        log_phase "Phase 1: Update image for operator (deployment/${DEPLOYMENT})"

        if ! run_cmd "kubectl set image deployment/${DEPLOYMENT} ${CONTAINER}=${full_image} -n ${NAMESPACE}" && [ "$DRY_RUN" = "0" ]; then
            log_fail "Failed to set image for deployment/${DEPLOYMENT}"
            exit 1
        fi
        [ "$DRY_RUN" = "0" ] && log_ok "Image updated to ${comp_version}"
    else
        # No version specified — plain restart (legacy behavior)
        log_phase "Phase 1: Rollout restart operator (deployment/${DEPLOYMENT})"

        current_image=$(get_current_image)
        current_version=$(get_current_version_annotation)
        _existing_ann="$current_version"
        [ -z "$current_version" ] && current_version=$(echo "$current_image" | grep -o ':[^:]*$' | tr -d ':')

        # Prefer the actual semver running in the pod, then resolve a non-semver
        # tag (e.g. "latest") to its underlying semver via ECR digest lookup.
        # This gives the Summary block a meaningful version to display.
        _annot_version="$current_version"
        _running_for_annot=$(get_running_pod_version)
        if [ -n "$_running_for_annot" ]; then
            _annot_version="$_running_for_annot"
        else
            _resolved_for_annot=$(resolve_tag_to_semver "$current_version")
            [ -n "$_resolved_for_annot" ] && _annot_version="$_resolved_for_annot"
        fi

        if ! run_cmd "kubectl rollout restart deployment/${DEPLOYMENT} -n ${NAMESPACE}" && [ "$DRY_RUN" = "0" ]; then
            log_fail "Failed to restart deployment/${DEPLOYMENT}"
            exit 1
        fi
        [ "$DRY_RUN" = "0" ] && log_ok "Rollout restart triggered for deployment/${DEPLOYMENT}"

        # Backfill nexus.ai/app-version annotation if missing, so the
        # Summary block (and the operator's own About-style introspection)
        # show the real image tag instead of "(unknown)".
        if [ "$DRY_RUN" = "0" ] && [ -z "$_existing_ann" ] && [ -n "$_annot_version" ]; then
            annotate_version "$_annot_version" "$_annot_version"
            log_ok "Backfilled version annotation: ${_annot_version}"
        fi
    fi

    # ── Phase 2: Wait for readiness ──
    log_phase "Phase 2: Wait for operator readiness"

    log_info "Waiting for rollout to complete (timeout: ${TIMEOUT}s)..."
    if ! run_cmd "kubectl rollout status deployment/${DEPLOYMENT} -n ${NAMESPACE} --timeout=${TIMEOUT}s" && [ "$DRY_RUN" = "0" ]; then
        log_fail "Rollout did not complete within ${TIMEOUT}s"

        log_phase "Crash diagnostics"
        printf "  ${DIM}Pod status:${RESET}\n"
        kubectl get pods -l "app.kubernetes.io/name=${DEPLOYMENT}" -n "$NAMESPACE" -o wide 2>/dev/null | sed 's/^/    /'

        _fail_pod=$(kubectl get pods -l "app.kubernetes.io/name=${DEPLOYMENT}" -n "$NAMESPACE" \
            --sort-by=.metadata.creationTimestamp \
            -o jsonpath='{.items[?(@.status.phase!="Running")].metadata.name}' 2>/dev/null | awk '{print $NF}')
        if [ -z "$_fail_pod" ]; then
            _fail_pod=$(kubectl get pods -l "app.kubernetes.io/name=${DEPLOYMENT}" -n "$NAMESPACE" \
                --sort-by=.metadata.creationTimestamp \
                -o jsonpath='{.items[-1:].metadata.name}' 2>/dev/null)
        fi

        if [ -n "$_fail_pod" ]; then
            printf "\n  ${DIM}Crash logs (${_fail_pod}):${RESET}\n"
            kubectl logs "$_fail_pod" -n "$NAMESPACE" --tail=40 2>/dev/null | sed 's/^/    /' || true
            _prev_logs=$(kubectl logs "$_fail_pod" -n "$NAMESPACE" --previous --tail=40 2>/dev/null)
            if [ -n "$_prev_logs" ]; then
                printf "\n  ${DIM}Previous crash logs (${_fail_pod}):${RESET}\n"
                echo "$_prev_logs" | sed 's/^/    /'
            fi
            printf "\n  ${DIM}Pod events:${RESET}\n"
            kubectl describe pod "$_fail_pod" -n "$NAMESPACE" 2>/dev/null \
                | sed -n '/Events:/,$ p' | head -25 | sed 's/^/    /'
        fi
        echo ""

        # Auto-rollback on failure
        if [ "$AUTO_ROLLBACK" = "1" ] && [ -n "$comp_version" ]; then
            log_phase "Auto-rollback"
            log_info "Rolling back deployment/${DEPLOYMENT}..."
            if kubectl rollout undo "deployment/${DEPLOYMENT}" -n "$NAMESPACE" 2>/dev/null; then
                log_ok "Rollback triggered"
                kubectl rollout status "deployment/${DEPLOYMENT}" -n "$NAMESPACE" --timeout=120s 2>/dev/null || true
                if [ -n "$current_version" ] && [ "$current_version" != "unknown" ]; then
                    annotate_version "$current_version" "$comp_version"
                fi
                log_warn "Rolled back to previous revision"
            else
                log_fail "Auto-rollback failed"
            fi
        fi

        OVERALL_EXIT=1
    else
        [ "$DRY_RUN" = "0" ] && log_ok "Rollout complete"

        # Update annotation after successful rollback
        if [ "$ROLLBACK_MODE" = "1" ] && [ "$DRY_RUN" = "0" ] && [ -n "$comp_version" ]; then
            annotate_version "$comp_version" "$current_version"
            log_ok "Version annotation updated (rolled back to ${comp_version})"
        fi

        # Verify pod readiness scoped to new generation only
        log_info "Verifying pod readiness (readinessProbe → /readyz)..."
        _hash=$(latest_rs_hash)
        _wait_selector="app.kubernetes.io/name=${DEPLOYMENT}"
        [ -n "$_hash" ] && _wait_selector="${_wait_selector},pod-template-hash=${_hash}"
        if ! run_cmd "kubectl wait --for=condition=ready pod -l ${_wait_selector} -n ${NAMESPACE} --timeout=120s" && [ "$DRY_RUN" = "0" ]; then
            log_warn "Pod readiness wait timed out"
            OVERALL_EXIT=1
        else
            [ "$DRY_RUN" = "0" ] && log_ok "Operator pod ready"
        fi

        printf "  ${DIM}Pod status:${RESET}\n"
        run_cmd "kubectl get pods -l app.kubernetes.io/name=${DEPLOYMENT} -n ${NAMESPACE} -o wide 2>/dev/null | sed 's/^/    /'"
        echo ""
    fi
fi

# ── Phase 3: Operator diagnostics ─────────────────────────────────
if [ "$SKIP_DIAGNOSTICS" = "0" ] && [ "$DRY_RUN" = "0" ]; then
    log_phase "Phase 3: Operator diagnostics"

    op_pod=$(get_pod)

    if [ -z "$op_pod" ]; then
        log_fail "No running operator pod found — cannot run diagnostics"
        OVERALL_EXIT=1
    else
        printf "  Operator pod: ${BOLD}%s${RESET}\n" "$op_pod"

        # Restart count
        _restarts=$(kubectl get pod "$op_pod" -n "$NAMESPACE" \
            -o jsonpath='{.status.containerStatuses[?(@.name=="'"${CONTAINER}"'")].restartCount}' 2>/dev/null)
        if [ -n "$_restarts" ] && [ "$_restarts" -gt 0 ]; then
            log_warn "Container has restarted ${_restarts} time(s)"
            [ "$OVERALL_EXIT" = "0" ] && OVERALL_EXIT=2
        else
            log_ok "Container has not restarted"
        fi

        # Recent logs (last LOG_TAIL lines, plus error scan)
        printf "\n  ${DIM}Last %s log lines:${RESET}\n" "$LOG_TAIL"
        kubectl logs "$op_pod" -n "$NAMESPACE" --tail="$LOG_TAIL" 2>/dev/null | sed 's/^/    /' | head -"$LOG_TAIL" || true

        _err_count=$(kubectl logs "$op_pod" -n "$NAMESPACE" --tail="$LOG_TAIL" 2>/dev/null \
            | grep -ciE '\b(error|exception|traceback|critical|fatal)\b' || echo 0)
        if [ "$_err_count" -gt 0 ]; then
            log_warn "Found ${_err_count} error/exception line(s) in last ${LOG_TAIL} lines"
            [ "$OVERALL_EXIT" = "0" ] && OVERALL_EXIT=2
        else
            log_ok "No error/exception keywords in recent logs"
        fi

        # Managed Capability CRs (operator's primary workload)
        printf "\n  ${DIM}Managed Capability CRs:${RESET}\n"
        _cr_out=$(kubectl get capabilities.nexus.ai -A 2>/dev/null | sed 's/^/    /')
        if [ -n "$_cr_out" ]; then
            echo "$_cr_out"
        else
            printf "    ${DIM}(no Capability CRs found, or CRD not installed)${RESET}\n"
        fi
        echo ""
    fi
fi

# ── Summary ────────────────────────────────────────────────────────
log_phase "Summary"

# Resolve the deployed version. Priority:
#   1. Actual semver running in the pod (digest-based, most authoritative)
#   2. Annotation, but resolve non-semver tags (e.g. "latest") via ECR digest
#   3. Annotation as-is
#   4. "(unknown)"
_summary_running=$(get_running_pod_version)
_summary_ann=$(get_current_version_annotation)
if [ -n "$_summary_running" ]; then
    if [ -n "$_summary_ann" ] && [ "$_summary_ann" != "$_summary_running" ]; then
        _summary_ver="${_summary_running} (image tag: ${_summary_ann})"
    else
        _summary_ver="$_summary_running"
    fi
elif [ -n "$_summary_ann" ]; then
    _summary_resolved=$(resolve_tag_to_semver "$_summary_ann")
    if [ -n "$_summary_resolved" ] && [ "$_summary_resolved" != "$_summary_ann" ]; then
        _summary_ver="${_summary_resolved} (image tag: ${_summary_ann})"
    else
        _summary_ver="$_summary_ann"
    fi
else
    _summary_ver="(unknown)"
fi
printf "  ${BOLD}Deployed Version:${RESET}  %s\n\n" "$_summary_ver"

run_cmd "kubectl get pods -l app.kubernetes.io/name=${DEPLOYMENT} -n ${NAMESPACE} -o wide 2>/dev/null | sed 's/^/  /'"

echo ""
if [ "$OVERALL_EXIT" = "0" ]; then
    log_ok "All phases completed successfully"
elif [ "$OVERALL_EXIT" = "1" ]; then
    log_fail "Rollout or readiness failure (exit code 1)"
else
    log_warn "Diagnostics surfaced warnings (exit code ${OVERALL_EXIT})"
fi
echo ""

exit $OVERALL_EXIT
