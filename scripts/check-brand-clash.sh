#!/bin/bash
# check-brand-clash.sh — Scan product copy for false-attribution claims.
# Restricted to text source files (.md/.html/.txt/.json) — PDFs are derived;
# their source .md files are what we should be auditing.
#
# Usage: bash scripts/check-brand-clash.sh [--strict]
#   --strict: exit 1 if any high-confidence flag found (use in CI / pre-deploy)
#
# Lesson: 2026-05-14 — Teagan invented "Antigravity" as Vedant's fictional CLI,
# colliding with Google's actual Antigravity product.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STRICT=0
[ "${1:-}" = "--strict" ] && STRICT=1

# Pipe of known commercial-software brands. Add as new products launch.
BRANDS='Antigravity|Sourcegraph|Tabnine|Codeium|Replit|Lovable|Cognition|Aider'
# Note: Cursor, Cline, Continue, Devin, Linear, Notion, Vercel, Anthropic, OpenAI, Stripe
# are deliberately EXCLUDED because they have legitimate non-attribution uses in our docs
# (referring to tools we use or integrate with). Add high-risk targeted regex per brand below
# if needed.

# Single combined regex for false-attribution
PATTERN="(I (built|wrote|created|made|developed|invented) (the )?(${BRANDS})\b|Author of (the )?(${BRANDS})\b|I'?m the (creator|author|founder|maker) of (${BRANDS})\b|called (${BRANDS})\b|\b(${BRANDS}) \\((Python|JavaScript|Rust|Go|TypeScript) (CLI|library|tool|framework)\\))"

echo "=== Brand-clash scan ==="
echo "Root: $ROOT/products/"
echo "Files: *.md / *.html / *.txt / *.json"
echo ""

FLAGS=$(find "$ROOT/products" \( -name "*.md" -o -name "*.html" -o -name "*.txt" -o -name "*.json" \) -type f 2>/dev/null \
  | xargs grep -l -i -E "$PATTERN" 2>/dev/null | grep -v "\.bak$" || true)

if [ -z "$FLAGS" ]; then
  echo "✓ No false-attribution patterns detected."
  exit 0
fi

echo "⚠️  Files with brand-collision risk:"
echo "$FLAGS" | while IFS= read -r f; do
  echo ""
  echo "  $f"
  grep -n -i -E "$PATTERN" "$f" 2>/dev/null | head -3 | sed 's/^/    /'
done

FLAG_COUNT=$(echo "$FLAGS" | wc -l | tr -d ' ')
echo ""
echo "Total flagged files: $FLAG_COUNT"

if [ $STRICT -eq 1 ]; then
  echo "STRICT MODE: failing."
  exit 1
fi
echo "Review each flag. Add brand to PATTERN above and re-fix as needed."
echo "Rerun with --strict in CI to fail-closed."
exit 0
