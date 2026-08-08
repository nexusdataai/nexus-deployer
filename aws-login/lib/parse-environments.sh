#!/bin/sh
# Parse environments.conf rows for set-context.sh and backup-restore tooling.
#
# Usage:
#   . "${AWS_LOGIN_DIR}/lib/parse-environments.sh"
#   nexus_env_load_row 5 /path/to/environments.conf
#   echo "$NEXUS_ROW_LABEL $NEXUS_ROW_PROFILE"
#
# After nexus_env_load_row succeeds, these are set:
#   NEXUS_ROW_INDEX NEXUS_ROW_LABEL NEXUS_ROW_AUTH NEXUS_ROW_PROFILE
#   NEXUS_ROW_ROLE_IDX NEXUS_ROW_ROLE_ARN NEXUS_ROW_REGION
#   NEXUS_ROW_CLUSTER NEXUS_ROW_NAMESPACE NEXUS_ROW_CONTEXT

nexus_env_normalize_auth() {
    case "$1" in
        keys|key|iam) echo "keys" ;;
        adfs|"")      echo "adfs" ;;
        *)            echo "unknown" ;;
    esac
}

# Split namespace "nexus-ai-prod" -> capability=nexus-ai env=prod
nexus_env_namespace_parts() {
    _ns="$1"
    NEXUS_ROW_ENV="${_ns##*-}"
    NEXUS_ROW_CAPABILITY="${_ns%-*}"
    if [ -z "$NEXUS_ROW_CAPABILITY" ] || [ -z "$NEXUS_ROW_ENV" ]; then
        return 1
    fi
    return 0
}

# Load one registry row by index. Returns 0 on success, 1 if not found.
nexus_env_load_row() {
    _want="$1"
    _config="${2:-}"

    if [ -z "$_want" ]; then
        echo "nexus_env_load_row: index required" >&2
        return 1
    fi
    if [ -z "$_config" ]; then
        echo "nexus_env_load_row: config file required" >&2
        return 1
    fi
    if [ ! -f "$_config" ]; then
        echo "nexus_env_load_row: missing config: $_config" >&2
        return 1
    fi

    _found=0
    while IFS='|' read -r f0 f1 f2 f3 f4 f5 f6 f7 f8 f9; do
        [ -z "${f0:-}" ] && continue
        case "$f0" in
            \#*) continue ;;
        esac

        if [ "$f2" = "adfs" ] || [ "$f2" = "keys" ] || [ "$f2" = "key" ] || [ "$f2" = "iam" ]; then
            _idx="$f0"
            _label="$f1"
            _auth="$(nexus_env_normalize_auth "$f2")"
            _profile="$f3"
            _role_idx="$f4"
            _role_arn="$f5"
            _region="$f6"
            _cluster="$f7"
            _namespace="$f8"
            _ctx="$f9"
        else
            _idx="$f0"
            _label="$f1"
            _auth="adfs"
            _profile="$f2"
            _role_idx="$f3"
            _role_arn="$f4"
            _region="$f5"
            _cluster="$f6"
            _namespace="$f7"
            _ctx="$f8"
        fi

        if [ "$_idx" != "$_want" ]; then
            continue
        fi

        NEXUS_ROW_INDEX="$_idx"
        NEXUS_ROW_LABEL="$_label"
        NEXUS_ROW_AUTH="$_auth"
        NEXUS_ROW_PROFILE="$_profile"
        NEXUS_ROW_ROLE_IDX="$_role_idx"
        NEXUS_ROW_ROLE_ARN="$_role_arn"
        NEXUS_ROW_REGION="$_region"
        NEXUS_ROW_CLUSTER="$_cluster"
        NEXUS_ROW_NAMESPACE="$_namespace"
        NEXUS_ROW_CONTEXT="$_ctx"
        _found=1
        break
    done < "$_config"

    if [ "$_found" -ne 1 ]; then
        echo "nexus_env_load_row: index $_want not found in $_config" >&2
        return 1
    fi
    if [ "$NEXUS_ROW_AUTH" = "unknown" ]; then
        echo "nexus_env_load_row: unsupported auth_type for index $_want" >&2
        return 1
    fi
    return 0
}
