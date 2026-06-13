#!/bin/bash
#
# Bump the semver in the VERSION file of nexus-backend, nexus-ui, and/or
# nexus-docs (plus the in-tree operator and capability). Companion to
# package-images.sh (which consumes the VERSION file) and app-rollout.sh
# (which deploys the resulting image tag).
#
# Usage:
#   ./bump-version.sh <target> <bump> [options]
#
#   <target>  backend | ui | frontend | docs | operator | capability | both | all
#   <bump>    major | minor | patch
#
# Examples:
#   ./bump-version.sh backend patch              # 1.0.0 -> 1.0.1 (backend only)
#   ./bump-version.sh ui minor                   # 1.0.0 -> 1.1.0 (ui only)
#   ./bump-version.sh docs patch                 # 1.0.0 -> 1.0.1 (docs only)
#   ./bump-version.sh operator patch             # 1.0.0 -> 1.0.1 (operator only)
#   ./bump-version.sh capability minor           # 2.5.0 -> 2.6.0 (capability semver only)
#   ./bump-version.sh both major                 # 1.0.0 -> 2.0.0 (backend + ui)
#   ./bump-version.sh all patch                  # 1.0.0 -> 1.0.1 (backend + ui + docs + operator + capability)
#   ./bump-version.sh backend patch --dry-run    # Print plan, do not write
#   ./bump-version.sh ui patch --commit          # Bump + git commit in the ui repo
#   ./bump-version.sh all patch --commit --push  # Bump + commit + push for everything
#
# Options:
#   --dry-run             Show planned change without writing or committing
#   --commit              After bumping, git add <VERSION-file> + git commit in each repo
#   --push                After --commit, also git push origin <current-branch>
#   --backend-dir PATH    Override nexus-backend path (default: ../../nexus-backend)
#   --frontend-dir PATH   Override nexus-ui path (default: ../../nexus-ui)
#   --docs-dir PATH       Override nexus-docs path (default: ../../nexus-docs)
#   --operator-dir PATH   Override kube-operator path (default: this script's directory)
#   --capability-file P   Override capability YAML path (default: examples/nexus-ai-complete.yaml)
#                         The VERSION file is derived by replacing .yaml with .VERSION
#   --help                Show this help

set -eo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
DIM='\033[2m'
BOLD='\033[1m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

TARGET=""
BUMP=""
DRY_RUN=false
DO_COMMIT=false
DO_PUSH=false
BACKEND_DIR=""
FRONTEND_DIR=""
DOCS_DIR=""
OPERATOR_DIR=""
CAPABILITY_FILE=""

show_help() {
    sed -n '2,36p' "$0"
}

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run)        DRY_RUN=true; shift ;;
        --commit)         DO_COMMIT=true; shift ;;
        --push)           DO_PUSH=true; shift ;;
        --backend-dir)    BACKEND_DIR="$2"; shift 2 ;;
        --frontend-dir)   FRONTEND_DIR="$2"; shift 2 ;;
        --docs-dir)       DOCS_DIR="$2"; shift 2 ;;
        --operator-dir)   OPERATOR_DIR="$2"; shift 2 ;;
        --capability-file) CAPABILITY_FILE="$2"; shift 2 ;;
        --help|-h)        show_help; exit 0 ;;
        backend|ui|frontend|docs|operator|capability|both|all)
            if [ -z "$TARGET" ]; then TARGET="$1"; else
                echo "Unexpected positional argument: $1" >&2; exit 1
            fi
            shift
            ;;
        major|minor|patch)
            if [ -z "$BUMP" ]; then BUMP="$1"; else
                echo "Unexpected positional argument: $1" >&2; exit 1
            fi
            shift
            ;;
        *)
            echo "Unknown argument: $1" >&2
            echo "Run with --help for usage." >&2
            exit 1
            ;;
    esac
done

if [ -z "$TARGET" ] || [ -z "$BUMP" ]; then
    echo "Usage: $(basename "$0") <backend|ui|docs|operator|capability|both|all> <major|minor|patch> [options]" >&2
    echo "Run with --help for full usage." >&2
    exit 1
fi

if [ "$DO_PUSH" = "true" ] && [ "$DO_COMMIT" = "false" ]; then
    echo "--push requires --commit (cannot push without committing the bump)" >&2
    exit 1
fi

# Resolve repo paths (mirrors package-images.sh convention)
BACKEND_DIR="${BACKEND_DIR:-$(cd "$SCRIPT_DIR/../../nexus-backend" 2>/dev/null && pwd || echo "")}"
FRONTEND_DIR="${FRONTEND_DIR:-$(cd "$SCRIPT_DIR/../../nexus-ui" 2>/dev/null && pwd || echo "")}"
DOCS_DIR="${DOCS_DIR:-$(cd "$SCRIPT_DIR/../../nexus-docs" 2>/dev/null && pwd || echo "")}"
OPERATOR_DIR="${OPERATOR_DIR:-$SCRIPT_DIR}"
CAPABILITY_FILE="${CAPABILITY_FILE:-${SCRIPT_DIR}/examples/nexus-ai-complete.yaml}"
CAPABILITY_DIR="$(dirname "$CAPABILITY_FILE")"
CAPABILITY_VERSION_FILENAME="$(basename "${CAPABILITY_FILE%.yaml}.VERSION")"

# Build the list of repos to bump.
# Entry format: "name|repo_dir|version_filename"  (3 pipe-separated fields)
REPOS=()
case "$TARGET" in
    backend)        REPOS=("backend|${BACKEND_DIR}|VERSION") ;;
    ui|frontend)    REPOS=("ui|${FRONTEND_DIR}|VERSION") ;;
    docs)           REPOS=("docs|${DOCS_DIR}|VERSION") ;;
    operator)       REPOS=("operator|${OPERATOR_DIR}|VERSION") ;;
    capability)     REPOS=("capability|${CAPABILITY_DIR}|${CAPABILITY_VERSION_FILENAME}") ;;
    both)           REPOS=("backend|${BACKEND_DIR}|VERSION" "ui|${FRONTEND_DIR}|VERSION") ;;
    all)            REPOS=(
                       "backend|${BACKEND_DIR}|VERSION"
                       "ui|${FRONTEND_DIR}|VERSION"
                       "docs|${DOCS_DIR}|VERSION"
                       "operator|${OPERATOR_DIR}|VERSION"
                       "capability|${CAPABILITY_DIR}|${CAPABILITY_VERSION_FILENAME}"
                    ) ;;
esac

bump_semver() {
    _ver="$1"
    _part="$2"
    if ! [[ "$_ver" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
        echo "ERROR: '$_ver' is not a valid X.Y.Z semver" >&2
        return 1
    fi
    _major="${BASH_REMATCH[1]}"
    _minor="${BASH_REMATCH[2]}"
    _patch="${BASH_REMATCH[3]}"
    case "$_part" in
        major)  _major=$((_major + 1)); _minor=0; _patch=0 ;;
        minor)  _minor=$((_minor + 1)); _patch=0 ;;
        patch)  _patch=$((_patch + 1)) ;;
    esac
    echo "${_major}.${_minor}.${_patch}"
}

printf "\n${BOLD}Version Bump${NC}\n"
printf "Target:      ${BOLD}%s${NC}\n" "$TARGET"
printf "Bump:        ${BOLD}%s${NC}\n" "$BUMP"
[ "$DRY_RUN" = "true" ]   && printf "${YELLOW}DRY RUN — no changes will be made${NC}\n"
[ "$DO_COMMIT" = "true" ] && printf "Commit:      ${BOLD}yes${NC}\n"
[ "$DO_PUSH" = "true" ]   && printf "Push:        ${BOLD}yes${NC}\n"
echo ""

EXIT_CODE=0

for entry in "${REPOS[@]}"; do
    IFS='|' read -r name repo version_filename <<< "$entry"

    printf "${CYAN}▶${NC} ${BOLD}%s${NC}  ${DIM}(%s/%s)${NC}\n" "$name" "$repo" "$version_filename"

    if [ -z "$repo" ] || [ ! -d "$repo" ]; then
        printf "  ${RED}✗${NC} repo path not found\n\n"
        EXIT_CODE=1
        continue
    fi

    version_file="${repo}/${version_filename}"
    if [ ! -f "$version_file" ]; then
        printf "  ${RED}✗${NC} VERSION file missing at %s\n\n" "$version_file"
        EXIT_CODE=1
        continue
    fi

    current=$(tr -d '[:space:]' < "$version_file")
    if ! new=$(bump_semver "$current" "$BUMP"); then
        EXIT_CODE=1
        echo ""
        continue
    fi
    printf "  Current:   ${DIM}%s${NC}\n" "$current"
    printf "  New:       ${BOLD}%s${NC}\n" "$new"

    if [ "$DRY_RUN" = "true" ]; then
        printf "  ${YELLOW}(dry-run, not written)${NC}\n\n"
        continue
    fi

    # If committing, refuse to operate on a dirty VERSION/working tree state
    # to avoid mixing the bump with unrelated in-flight changes.
    if [ "$DO_COMMIT" = "true" ]; then
        if ! ( cd "$repo" && git diff --quiet -- "$version_filename" 2>/dev/null && git diff --cached --quiet -- "$version_filename" 2>/dev/null ); then
            printf "  ${RED}✗${NC} %s has uncommitted changes; refusing to bump+commit. Stash or commit first.\n\n" "$version_filename"
            EXIT_CODE=1
            continue
        fi
    fi

    echo "$new" > "$version_file"
    printf "  ${GREEN}✓${NC} %s updated\n" "$version_filename"

    if [ "$DO_COMMIT" = "true" ]; then
        if ( cd "$repo" \
             && git add "$version_filename" \
             && git commit -m "chore(version): bump ${name} to ${new}" >/dev/null ); then
            printf "  ${GREEN}✓${NC} committed: chore(version): bump %s to %s\n" "$name" "$new"
            if [ "$DO_PUSH" = "true" ]; then
                _branch=$(cd "$repo" && git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
                if [ -n "$_branch" ] && (cd "$repo" && git push origin "$_branch" >/dev/null 2>&1); then
                    printf "  ${GREEN}✓${NC} pushed to origin/%s\n" "$_branch"
                else
                    printf "  ${RED}✗${NC} push failed (commit is local only)\n"
                    EXIT_CODE=1
                fi
            fi
        else
            printf "  ${RED}✗${NC} git commit failed\n"
            EXIT_CODE=1
        fi
    fi

    echo ""
done

if [ "$DRY_RUN" = "false" ] && [ "$EXIT_CODE" = "0" ]; then
    printf "${GREEN}✓ Version bump complete${NC}\n"
    printf "Next steps:\n"
    printf "  1. ${DIM}# Build + tag images with the new version${NC}\n"
    printf "     ./package-images.sh\n"
    printf "  2. ${DIM}# Push to ECR${NC}\n"
    printf "     ./create-ecr-images-crane.sh   ${DIM}# (or ./create-ecr-images.sh if Docker available)${NC}\n"
    printf "  3. ${DIM}# Roll out the new tag${NC}\n"
    printf "     ./app-rollout.sh --version <new-tag> all\n"
    echo ""
fi

exit "$EXIT_CODE"
