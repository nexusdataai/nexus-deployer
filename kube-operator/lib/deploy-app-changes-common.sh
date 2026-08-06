#!/bin/bash
# Shared helpers for deploy-app-changes.sh (sourced, not executed directly).

dac_bump_semver() {
    local ver="$1" part="$2"
    if ! [[ "$ver" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
        dac_log_fail "'$ver' is not valid X.Y.Z semver" >&2
        return 1
    fi
    local major="${BASH_REMATCH[1]}" minor="${BASH_REMATCH[2]}" patch="${BASH_REMATCH[3]}"
    case "$part" in
        major) major=$((major + 1)); minor=0; patch=0 ;;
        minor) minor=$((minor + 1)); patch=0 ;;
        patch) patch=$((patch + 1)) ;;
        *) dac_log_fail "Invalid bump type: $part"; return 1 ;;
    esac
    echo "${major}.${minor}.${patch}"
}

dac_repo_git_sha() {
    (cd "$1" && git rev-parse --short HEAD 2>/dev/null) || echo "unknown"
}

dac_repo_is_dirty() {
    local dir="$1"
    ! (cd "$dir" && git diff --quiet && git diff --cached --quiet) 2>/dev/null
}

dac_read_version() {
    local dir="$1" ver_file="$2"
    tr -d '[:space:]' < "${dir}/${ver_file}"
}

dac_deployed_image_tag() {
    local k8s_name="$1" kind="${2:-deployment}"
    local img
    img=$(kubectl get "${kind}/${k8s_name}" -n "$DAC_NAMESPACE" \
        -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null || true)
    [ -z "$img" ] && return 0
    echo "${img##*:}"
}

dac_deployed_git_sha_from_tag() {
    local tag="$1"
    [ -z "$tag" ] && return 0
    echo "${tag##*-}"
}

dac_component_needs_deploy() {
    local comp_id="$1" dir="$2" k8s_name="$3" kind="$4" force="$5"

    [ "$force" = true ] && return 0
    dac_repo_is_dirty "$dir" && return 0
    [ "$DRY_RUN" = true ] && return 1

    local deployed_tag deployed_sha head_sha
    deployed_tag=$(dac_deployed_image_tag "$k8s_name" "$kind")
    deployed_sha=$(dac_deployed_git_sha_from_tag "$deployed_tag")
    head_sha=$(dac_repo_git_sha "$dir")

    if [ -z "$deployed_tag" ]; then
        dac_log_warn "${comp_id}: no ${kind}/${k8s_name} in ${DAC_NAMESPACE}; will deploy"
        return 0
    fi
    [ "$head_sha" != "$deployed_sha" ] && return 0
    return 1
}

dac_summarize_changed_files() {
    local dir="$1"
    (cd "$dir" && git status --porcelain 2>/dev/null | awk '{print $2}' | head -8) || true
}

dac_auto_commit_message() {
    local component="$1" new_ver="$2" dir="$3"
    local summary
    summary=$(dac_summarize_changed_files "$dir" | tr '\n' ', ' | sed 's/,$//')
    if [ -n "$summary" ]; then
        printf "chore(%s): deploy changes\n\nChanged: %s\n\nBump %s to %s" \
            "$component" "$summary" "$component" "$new_ver"
    else
        printf "chore(%s): deploy changes\n\nBump %s to %s" \
            "$component" "$component" "$new_ver"
    fi
}

dac_git_commit_repo() {
    local dir="$1" component="$2" new_ver="$3" msg="$4"

    [ "$COMMIT" != true ] && return 0
    if ! (cd "$dir" && git rev-parse --git-dir >/dev/null 2>&1); then
        dac_log_warn "${component}: not a git repo — skipping commit"
        return 0
    fi
    if (cd "$dir" && git diff --quiet && git diff --cached --quiet); then
        dac_log_info "${component}: working tree clean — nothing to commit"
        return 0
    fi

    local final_msg="$msg"
    if [ -z "$final_msg" ]; then
        final_msg=$(dac_auto_commit_message "$component" "$new_ver" "$dir")
    elif ! grep -qi "bump.*${new_ver}" <<< "$final_msg"; then
        final_msg="${final_msg}

Bump ${component} to ${new_ver}"
    fi

    if [ "$DRY_RUN" = true ]; then
        dac_log_info "[dry-run] would commit in ${dir}:"
        (cd "$dir" && git status --short | sed 's/^/    /')
        dac_log_info "[dry-run] message: ${final_msg}"
        return 0
    fi

    (cd "$dir" && git add -A && git commit -m "$final_msg")
    dac_log_ok "${component}: committed"

    if [ "$DO_PUSH" = true ]; then
        local branch
        branch=$(cd "$dir" && git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
        if [ -n "$branch" ] && (cd "$dir" && git push origin "$branch"); then
            dac_log_ok "${component}: pushed to origin/${branch}"
        else
            dac_log_fail "${component}: push failed"
            return 1
        fi
    fi
}

dac_bump_version_file() {
    local dir="$1" ver_file="$2" new_ver="$3"
    if [ "$DRY_RUN" = true ]; then
        dac_log_info "[dry-run] would write ${ver_file}=${new_ver} in ${dir}"
        return 0
    fi
    echo "$new_ver" > "${dir}/${ver_file}"
}

dac_ecr_login() {
    local account_id="$1"
    if [ "$DRY_RUN" = true ]; then
        dac_log_info "[dry-run] would ECR login to ${account_id}.dkr.ecr.${REGION}.amazonaws.com"
        return 0
    fi
    aws_cli ecr get-login-password --region "$REGION" \
        | docker login --username AWS --password-stdin \
            "${account_id}.dkr.ecr.${REGION}.amazonaws.com" >/dev/null
    dac_log_ok "ECR login"
}

dac_ensure_ecr_repo() {
    local repo="$1"
    [ "$DRY_RUN" = true ] && return 0
    if ! aws_cli ecr describe-repositories --repository-names "$repo" --region "$REGION" >/dev/null 2>&1; then
        dac_log_info "Creating ECR repository: ${repo}"
        aws_cli ecr create-repository --repository-name "$repo" --region "$REGION" >/dev/null
    fi
}

dac_push_image() {
    local local_repo="$1" ecr_registry="$2" tag="$3"
    if [ "$DRY_RUN" = true ]; then
        dac_log_info "[dry-run] would push ${ecr_registry}/${local_repo}:latest"
        dac_log_info "[dry-run] would push ${ecr_registry}/${local_repo}:${tag}"
        return 0
    fi
    dac_ensure_ecr_repo "$local_repo"
    docker tag "${local_repo}:latest" "${ecr_registry}/${local_repo}:latest"
    docker tag "${local_repo}:latest" "${ecr_registry}/${local_repo}:${tag}"
    for full in "${ecr_registry}/${local_repo}:latest" "${ecr_registry}/${local_repo}:${tag}"; do
        docker push "$full" >/dev/null
        dac_log_ok "pushed ${full}"
    done
}

dac_build_component() {
    local local_image="$1" tag="$2" sha="$3" build_flags="$4" dir="$5" pre_build="$6"
    dac_log_info "Building ${local_image}:${tag} ..."
    if [ "$DRY_RUN" = true ]; then
        dac_log_info "[dry-run] docker build ${build_flags} -t ${local_image}:latest ${dir}"
        return 0
    fi
    if [ "$pre_build" = docs ]; then
        bash "${SCRIPT_DIR}/build-docs-site.sh" "$dir"
    fi
    if [ -n "$sha" ]; then
        docker build ${build_flags} -t "${local_image}:latest" \
            --build-arg VERSION="${tag}" \
            --build-arg BUILD_SHA="${sha}" \
            "$dir"
    else
        docker build ${build_flags} -t "${local_image}:latest" \
            --build-arg VERSION="${tag}" \
            "$dir"
    fi
    docker tag "${local_image}:latest" "${local_image}:${tag}"
    dac_log_ok "${local_image} image built"
}

dac_build_and_push() {
    local local_image="$1" ecr_repo="$2" tag="$3" sha="$4" build_flags="$5" dir="$6" pre_build="$7"
    dac_build_component "$local_image" "$tag" "$sha" "$build_flags" "$dir" "$pre_build"
    dac_push_image "$ecr_repo" "$ECR_REGISTRY" "$tag"
}

dac_optimize_rollout_strategy() {
    local k8s_name="$1" kind="${2:-deployment}"
    [ "$FAST_ROLLOUT" != true ] && return 0
    if ! kubectl get "${kind}/${k8s_name}" -n "$DAC_NAMESPACE" >/dev/null 2>&1; then
        dac_log_warn "${k8s_name}: ${kind} not found — skipping strategy patch"
        return 0
    fi
    if kubectl patch "${kind}/${k8s_name}" -n "$DAC_NAMESPACE" --type=strategic -p '{
        "spec": {
            "strategy": {
                "type": "RollingUpdate",
                "rollingUpdate": {"maxSurge": "100%", "maxUnavailable": 0}
            }
        }
    }' >/dev/null 2>&1; then
        dac_log_ok "${k8s_name}: rollout strategy → maxSurge 100%, maxUnavailable 0"
    else
        dac_log_warn "${k8s_name}: could not patch rollout strategy (continuing)"
    fi
}

dac_rollout_component() {
    local rollout_comp="$1" version_flag="$2" tag="$3" k8s_name="$4" kind="$5"
    local log_file="${TMPDIR:-/tmp}/deploy-rollout-${rollout_comp}-$$.log"

    if [ "$DRY_RUN" = true ]; then
        dac_log_info "[dry-run] optimize rollout for ${k8s_name}"
        dac_log_info "[dry-run] app-rollout.sh ${DAC_ROLLOUT_ARGS[*]} --skip-diagnostics --skip-ecr-verify ${version_flag} ${tag} ${rollout_comp}"
        return 0
    fi

    dac_optimize_rollout_strategy "$k8s_name" "$kind"

    dac_log_info "Starting rollout: ${rollout_comp} → ${tag}"
    local -a _rollout_cmd=("${DAC_ROLLOUT_ARGS[@]}" --env "$DEPLOY_ENV" --skip-diagnostics)
    [ "$SKIP_BUILD" = false ] && _rollout_cmd+=(--skip-ecr-verify)
    _rollout_cmd+=("${version_flag}" "$tag" "$rollout_comp")

    if ECR_REGISTRY="$ECR_REGISTRY" ACCOUNT_ID="$ACCOUNT_ID" \
        bash "${SCRIPT_DIR}/app-rollout.sh" "${_rollout_cmd[@]}" \
        > "$log_file" 2>&1; then
        sed "s/^/  [${rollout_comp}] /" "$log_file"
        dac_log_ok "${rollout_comp} rollout complete"
        rm -f "$log_file"
        return 0
    fi
    sed "s/^/  [${rollout_comp}] /" "$log_file"
    dac_log_fail "${rollout_comp} rollout failed (see log above)"
    rm -f "$log_file"
    return 1
}

dac_run_parallel_jobs() {
    local label="$1"
    shift
    local -a pids=() names=()

    [ "$#" -eq 0 ] && return 0

    if [ "$PARALLEL" = false ] || [ "$#" -eq 1 ]; then
        for job in "$@"; do
            IFS='|' read -r name cmd <<< "$job"
            dac_log_info "${label}: ${name} (sequential)"
            # shellcheck disable=SC2086
            eval "$cmd" || return 1
        done
        return 0
    fi

    dac_log_info "${label}: running ${#} jobs in parallel"
    for job in "$@"; do
        IFS='|' read -r name cmd <<< "$job"
        names+=("$name")
        ( eval "$cmd" ) &
        pids+=($!)
    done

    local failed=false
    for i in "${!pids[@]}"; do
        if ! wait "${pids[$i]}"; then
            dac_log_fail "${label} failed: ${names[$i]}"
            failed=true
        fi
    done
    [ "$failed" = false ]
}

dac_write_versions_env() {
    [ "$DRY_RUN" = true ] && return 0
    mkdir -p "$DAC_IMAGES_DIR"
    : > "${DAC_IMAGES_DIR}/versions.env"
    local entry
    for entry in "${DAC_VERSION_ENTRIES[@]}"; do
        echo "$entry" >> "${DAC_IMAGES_DIR}/versions.env"
    done
    echo "PACKAGED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "${DAC_IMAGES_DIR}/versions.env"
}

dac_load_tags_from_versions_env() {
    local key="$1"
    grep "^${key}=" "${DAC_IMAGES_DIR}/versions.env" 2>/dev/null | cut -d= -f2- | tr -d '[:space:]' || true
}

dac_resolve_persisted_tag() {
    local tag_key="$1" dir="$2" fallback_ver="$3" k8s_name="$4" kind="$5"
    local tag
    tag=$(dac_load_tags_from_versions_env "$tag_key")
    [ -z "$tag" ] && tag=$(dac_deployed_image_tag "$k8s_name" "$kind")
    if [ -z "$tag" ]; then
        tag="${fallback_ver}-$(dac_repo_git_sha "$dir")"
    fi
    echo "$tag"
}

# Parse pipe field from component spec (see dac_load_product).
dac_comp_field() {
    local spec="$1" idx="$2"
    echo "$spec" | cut -d'|' -f"$idx"
}
