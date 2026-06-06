#!/bin/sh
# treepaths.sh — resolve a project's env tree path, layout-agnostic.
#
# Supports BOTH layouts so scripts work before and after the
# 2026-06 nesting migration:
#   nested (new):  /opt/projects/<project>/{prod,dev,test}
#   flat   (old):  /opt/projects/<project>            (prod)
#                  /opt/projects/<project>-<role>     (dev|test)
#
# Usage:
#   . "$(dirname "$0")/treepaths.sh"
#   root="$(tree_path storyteller dev)"   # -> absolute path, or non-zero if absent
#
# Resolution prefers the nested layout when present, so a half-migrated
# box (nested dirs created, flat dirs not yet removed) resolves to nested.

tree_path() {
    _tp_project="$1"
    _tp_role="$2"
    _tp_base="${PROJECTS_BASE:-/opt/projects}"

    case "$_tp_role" in
        prod|dev|test) ;;
        *) echo "tree_path: bad role '$_tp_role' (expected prod|dev|test)" >&2; return 2 ;;
    esac

    # 1. nested layout: /opt/projects/<project>/<role>
    if [ -d "$_tp_base/$_tp_project/$_tp_role" ]; then
        printf '%s\n' "$_tp_base/$_tp_project/$_tp_role"
        return 0
    fi
    # 2. flat layout
    if [ "$_tp_role" = prod ]; then
        if [ -d "$_tp_base/$_tp_project" ] && [ ! -d "$_tp_base/$_tp_project/prod" ]; then
            printf '%s\n' "$_tp_base/$_tp_project"
            return 0
        fi
    else
        if [ -d "$_tp_base/$_tp_project-$_tp_role" ]; then
            printf '%s\n' "$_tp_base/$_tp_project-$_tp_role"
            return 0
        fi
    fi
    echo "tree_path: no tree found for $_tp_project/$_tp_role under $_tp_base" >&2
    return 1
}
