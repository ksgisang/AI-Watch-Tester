#!/usr/bin/env bash
# Documentation sync checker
# Usage: bash docs/check_sync.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PASS=0
WARN=0

echo "=== Documentation Sync Check ==="
echo ""

# -------------------------------------------------------------------
# 1. i18n key sync: en.json vs ko.json
# -------------------------------------------------------------------
EN="$ROOT/cloud/frontend/messages/en.json"
KO="$ROOT/cloud/frontend/messages/ko.json"

if [[ -f "$EN" && -f "$KO" ]]; then
    # Extract all key paths (e.g. "common.loading", "header.brand")
    en_keys=$(python3 -c "
import json, sys
def flatten(obj, prefix=''):
    keys = []
    for k, v in sorted(obj.items()):
        path = f'{prefix}.{k}' if prefix else k
        if isinstance(v, dict):
            keys.extend(flatten(v, path))
        else:
            keys.append(path)
    return keys
with open('$EN') as f:
    print('\n'.join(flatten(json.load(f))))
")
    ko_keys=$(python3 -c "
import json, sys
def flatten(obj, prefix=''):
    keys = []
    for k, v in sorted(obj.items()):
        path = f'{prefix}.{k}' if prefix else k
        if isinstance(v, dict):
            keys.extend(flatten(v, path))
        else:
            keys.append(path)
    return keys
with open('$KO') as f:
    print('\n'.join(flatten(json.load(f))))
")

    en_only=$(comm -23 <(echo "$en_keys" | sort) <(echo "$ko_keys" | sort))
    ko_only=$(comm -13 <(echo "$en_keys" | sort) <(echo "$ko_keys" | sort))

    if [[ -z "$en_only" && -z "$ko_only" ]]; then
        echo "[PASS] i18n keys: en.json and ko.json are in sync"
        PASS=$((PASS + 1))
    else
        if [[ -n "$en_only" ]]; then
            echo "[WARN] Keys in en.json but missing from ko.json:"
            echo "$en_only" | sed 's/^/  - /'
            WARN=$((WARN + 1))
        fi
        if [[ -n "$ko_only" ]]; then
            echo "[WARN] Keys in ko.json but missing from en.json:"
            echo "$ko_only" | sed 's/^/  - /'
            WARN=$((WARN + 1))
        fi
    fi
else
    echo "[WARN] i18n files not found, skipping key sync check"
    WARN=$((WARN + 1))
fi

echo ""

# -------------------------------------------------------------------
# 2. API endpoint check: API_REFERENCE.md vs actual routers
# -------------------------------------------------------------------
API_DOC="$ROOT/docs/API_REFERENCE.md"
ROUTERS_DIR="$ROOT/cloud/app"

if [[ -f "$API_DOC" && -d "$ROUTERS_DIR" ]]; then
    # Extract documented endpoints (e.g. "GET /health", "POST /api/tests")
    doc_endpoints=$(grep -oE '`(GET|POST|PUT|DELETE|WS) /[^`]+`' "$API_DOC" \
        | sed 's/`//g' \
        | sed 's/{[^}]*}/.*/g' \
        | sort -u)

    missing=0
    while IFS= read -r endpoint; do
        method=$(echo "$endpoint" | awk '{print $1}')
        path=$(echo "$endpoint" | awk '{print $2}')

        # Skip WebSocket — different registration pattern
        [[ "$method" == "WS" ]] && continue

        # Search for the path pattern in router files
        # Convert path like /api/tests/.* to a grep-friendly pattern
        search_path=$(echo "$path" | sed 's|\.\*|{[^}]*}|g' | sed 's|/|\\/|g')
        method_lower=$(echo "$method" | tr '[:upper:]' '[:lower:]')

        if grep -rq "\"$path\"\|'$path'\|@.*\.$method_lower\|\.${method_lower}(" "$ROUTERS_DIR" 2>/dev/null; then
            : # found
        else
            # Try a looser match on just the path tail
            path_tail=$(echo "$path" | sed 's|.*/||')
            if grep -rq "$path_tail" "$ROUTERS_DIR" 2>/dev/null; then
                : # found via tail match
            else
                echo "[WARN] Documented endpoint not found in code: $method $path"
                missing=$((missing + 1))
            fi
        fi
    done <<< "$doc_endpoints"

    if [[ $missing -eq 0 ]]; then
        echo "[PASS] API endpoints: all documented endpoints found in code"
        PASS=$((PASS + 1))
    else
        WARN=$((WARN + missing))
    fi
else
    echo "[WARN] API_REFERENCE.md or routers directory not found, skipping endpoint check"
    WARN=$((WARN + 1))
fi

echo ""

# -------------------------------------------------------------------
# Summary
# -------------------------------------------------------------------
echo "=== Summary ==="
echo "PASS: $PASS  |  WARN: $WARN"

if [[ $WARN -gt 0 ]]; then
    echo ""
    echo "Fix warnings before merging. See docs/MAINTENANCE.md for update rules."
    exit 1
fi

exit 0
