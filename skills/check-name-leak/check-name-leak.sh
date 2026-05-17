#!/bin/bash
# check-name-leak.sh — v2 (skill-packaged, config-driven).
# Scans customer-facing artifacts for operator identifier leaks.
#
# Usage:
#   bash check-name-leak.sh             # warn-only
#   bash check-name-leak.sh --strict    # exit 1 on any match (CI)
#
# Config: ~/.config/check-name-leak/identifiers.json
# Override path: CHECK_NAME_LEAK_CONFIG=./local-config.json bash check-name-leak.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_PATH="${CHECK_NAME_LEAK_CONFIG:-$HOME/.config/check-name-leak/identifiers.json}"
STRICT=0
[ "${1:-}" = "--strict" ] && STRICT=1

if [ ! -f "$CONFIG_PATH" ]; then
  echo "✗ Config not found at $CONFIG_PATH"
  echo ""
  echo "Setup:"
  echo "  mkdir -p $(dirname "$CONFIG_PATH")"
  echo "  cp $SCRIPT_DIR/identifiers.example.json $CONFIG_PATH"
  echo "  \$EDITOR $CONFIG_PATH    # fill in your real identifiers"
  exit 2
fi

# Parse config via python3 (more portable than jq across mac/linux)
parse_config() {
  python3 -c "
import json, sys, os
c = json.load(open('$CONFIG_PATH'))

def pipe(arr):
    # escape regex metachars in literal identifiers
    import re
    return '|'.join(re.escape(s) for s in arr if s and not s.startswith('_'))

def custom_pipe(arr):
    # custom patterns are already regex, don't re-escape
    return '|'.join(s for s in arr if s)

print('NAMES=' + pipe(c.get('names', [])))
print('SCHOOLS=' + pipe(c.get('schools', [])))
print('EMPLOYERS=' + pipe(c.get('employers', [])))
print('CITIES=' + pipe(c.get('cities', [])))
print('CUSTOM=' + custom_pipe(c.get('custom_patterns', [])))
print('SCAN_DIRS=' + ' '.join(c.get('scan_dirs', [])))
print('EXTENSIONS=' + ' '.join('-o -name \"*.' + e + '\"' for e in c.get('extensions', ['md'])))
print('MAX_SIZE_KB=' + str(c.get('max_file_size_kb', 500)))
"
}

eval "$(parse_config)"

# Strip leading "-o " from extensions pattern (first one shouldn't have it)
EXTENSIONS_PATTERN="${EXTENSIONS:3}"

echo "=== Name-leak scan ==="
echo "Config:    $CONFIG_PATH"
echo "Mode:      $([ $STRICT -eq 1 ] && echo "STRICT (CI)" || echo "warn-only")"
echo ""

FLAGS=0

scan_one() {
  local pattern="$1"
  local label="$2"
  [ -z "$pattern" ] && return 0

  local hits
  hits=$(find $SCAN_DIRS \( -name "*.md" $EXTENSIONS \) -type f -size -${MAX_SIZE_KB}k 2>/dev/null \
    | xargs grep -l -E "$pattern" 2>/dev/null | grep -v "\.bak$" || true)

  if [ -n "$hits" ]; then
    echo "⚠️  $label leak detected:"
    while IFS= read -r f; do
      grep -n -E "$pattern" "$f" 2>/dev/null | head -2 | sed "s|^|    $f: |"
      FLAGS=$((FLAGS+1))
    done <<< "$hits"
    echo ""
  fi
}

scan_one "$NAMES" "operator name"
scan_one "$SCHOOLS" "school"
scan_one "$EMPLOYERS" "employer"
scan_one "$CITIES" "city"
scan_one "$CUSTOM" "custom pattern"

if [ $FLAGS -eq 0 ]; then
  echo "✓ No identifier leaks detected in customer-facing artifacts."
  exit 0
fi

echo "Total leaks: $FLAGS"
echo "Fix: rephrase the flagged lines. Use generic descriptors ('the operator', 'the builder')."

if [ $STRICT -eq 1 ]; then
  echo "STRICT MODE: failing build."
  exit 1
fi
exit 0
