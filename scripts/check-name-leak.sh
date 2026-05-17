#!/bin/bash
# check-name-leak.sh — Scan customer-facing artifacts for operator-name leaks.
# The operator's legal name + identifiers never appear in PDFs, landing pages,
# launch posts, or any artifact published outside the repo.
#
# Usage: bash scripts/check-name-leak.sh [--strict]
#   --strict: exit 1 if any leak found (CI / pre-deploy fail-closed)
#
# Lesson: 2026-05-14 — anonymity hardening rule added to PRIME_DIRECTIVE.md.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STRICT=0
[ "${1:-}" = "--strict" ] && STRICT=1

# Operator identifiers to scrub from customer-facing artifacts.
# Stored as regex pieces — keep in sync with USER.md but only the EXTERNAL-leak-relevant ones.
NAMES='Vedant Yadav|Vedant|Yadav'
SCHOOL='NYU Tandon|NYU|Tandon|tandon'
EMPLOYER='Lightbeam'
CITY='New York City|NYC'   # generic; matches "in NYC" style

# Customer-facing artifact directories (deployed or about-to-be deployed).
SCAN_DIRS=(
  "$ROOT/products/felixops-site"     # the deployed site
  "$ROOT/felixops-site"              # secondary site dir (root-level)
  "$ROOT/products/*/launch"          # launch post drafts
  "$ROOT/products/*/site"            # per-product landing source
  "$ROOT/products/*/pdf"             # PDF source markdown
  "$ROOT/products/*/blog"            # blog content
  "$ROOT/products/*/twitter"         # twitter/X drafts
  "$ROOT/LAUNCH_TONIGHT.md"          # consolidated launch doc
)

echo "=== Name-leak scan ==="
echo "Names:     $NAMES"
echo "School:    $SCHOOL"
echo "Employer:  $EMPLOYER"
echo ""

FLAGS=0
declare -a LEAKED

scan_one() {
  local pattern="$1"
  local label="$2"
  local hits
  hits=$(find ${SCAN_DIRS[@]} \( -name "*.md" -o -name "*.html" -o -name "*.txt" -o -name "*.json" \) -type f -size -500k 2>/dev/null \
    | xargs grep -l -E "$pattern" 2>/dev/null | grep -v "\.bak$" || true)
  if [ -n "$hits" ]; then
    echo "⚠️  $label leak detected:"
    while IFS= read -r f; do
      LEAKED+=("$f|$label")
      # Show first 2 matching lines
      grep -n -E "$pattern" "$f" 2>/dev/null | head -2 | sed "s|^|    $f: |"
      FLAGS=$((FLAGS+1))
    done <<< "$hits"
    echo ""
  fi
}

scan_one "$NAMES" "operator name"
scan_one "$SCHOOL" "school"
scan_one "$EMPLOYER" "prior employer"

if [ $FLAGS -eq 0 ]; then
  echo "✓ No operator-name leaks detected in customer-facing artifacts."
  exit 0
fi

echo "Total leaks: $FLAGS"
echo ""
echo "Fix: rephrase the flagged lines. Use 'my operator' / 'the principal' / generic descriptors."
echo "Internal docs (USER.md, IDENTITY.md, AUDIT_LOG.md, memory/) can keep the name — they're not scanned."

if [ $STRICT -eq 1 ]; then
  echo "STRICT MODE: failing."
  exit 1
fi
echo "Rerun with --strict in CI to fail-closed."
exit 0
